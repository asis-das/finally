"""The chat flow: persistence, context, action execution, graceful degradation."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.db import (
    add_chat_message,
    get_cash_balance,
    get_position,
    list_chat_messages,
    list_trades,
    list_watchlist,
)
from app.llm import client, service
from app.llm.prompt import build_context, build_messages
from app.llm.schemas import ChatResponse

pytestmark = pytest.mark.usefixtures("temp_db")


def fake_reply(payload: dict):
    content = json.dumps(payload)
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


class TestMockFlow:
    async def test_persists_both_turns(self, price_cache, market_source):
        result = await service.handle_chat("how am I doing?", price_cache, market_source)

        assert result["actions"] == []
        assert result["created_at"]
        messages = list_chat_messages()
        assert [m["role"] for m in messages] == ["user", "assistant"]
        assert messages[0]["content"] == "how am I doing?"
        assert messages[0]["actions"] is None
        assert messages[1]["content"] == result["message"]
        assert messages[1]["actions"] == []

    async def test_summary_reflects_the_real_portfolio(self, price_cache, market_source):
        result = await service.handle_chat("status please", price_cache, market_source)
        assert result["message"] == (
            "You have $10,000.00 in cash across 0 positions, total value $10,000.00."
        )

    async def test_buy_executes_a_real_trade(self, price_cache, market_source):
        result = await service.handle_chat("buy 10 AAPL", price_cache, market_source)

        assert result["message"] == "Bought 10 AAPL."
        assert len(result["actions"]) == 1
        action = result["actions"][0]
        assert action["type"] == "trade"
        assert action["status"] == "executed"
        assert action["detail"] == "Bought 10 AAPL @ $190.00"
        assert get_position("AAPL")["quantity"] == 10.0
        assert list_chat_messages()[-1]["actions"] == result["actions"]

    async def test_rejected_trade_is_reported_in_the_actions(self, price_cache, market_source):
        result = await service.handle_chat("buy 100000 AAPL", price_cache, market_source)

        assert result["actions"][0]["status"] == "failed"
        assert "Insufficient cash" in result["actions"][0]["detail"]
        assert get_position("AAPL") is None

    async def test_watchlist_add_flows_through_to_the_market_source(
        self, price_cache, market_source
    ):
        result = await service.handle_chat("add PYPL", price_cache, market_source)

        assert result["actions"][0]["status"] == "executed"
        assert "PYPL" in list_watchlist()
        assert market_source.added == ["PYPL"]


class TestLiveFlow:
    async def test_uses_the_model_reply_and_executes_its_actions(
        self, monkeypatch, live_env, price_cache, market_source
    ):
        monkeypatch.setattr(
            client,
            "completion",
            lambda **kwargs: fake_reply(
                {
                    "message": "Bought some Apple for you.",
                    "trades": [{"ticker": "AAPL", "side": "buy", "quantity": 2}],
                    "watchlist_changes": [],
                }
            ),
        )

        result = await service.handle_chat("buy me some apple", price_cache, market_source)

        assert result["message"] == "Bought some Apple for you."
        assert result["actions"][0]["status"] == "executed"
        assert get_position("AAPL")["quantity"] == 2.0

    async def test_history_excludes_the_message_being_answered(
        self, monkeypatch, live_env, price_cache, market_source
    ):
        add_chat_message("user", "earlier question")
        add_chat_message("assistant", "earlier answer")
        captured = {}

        def capture(**kwargs):
            captured["messages"] = kwargs["messages"]
            return fake_reply({"message": "ok"})

        monkeypatch.setattr(client, "completion", capture)
        await service.handle_chat("new question", price_cache, market_source)

        messages = captured["messages"]
        assert messages[0]["role"] == "system"
        assert [m["content"] for m in messages[1:]] == [
            "earlier question",
            "earlier answer",
            "new question",
        ]
        assert sum(1 for m in messages if m["content"] == "new question") == 1

    async def test_timeout_degrades_gracefully_without_acting(
        self, monkeypatch, live_env, price_cache, market_source
    ):
        class APITimeoutError(Exception):
            pass

        def boom(**kwargs):
            raise APITimeoutError("queued too long")

        monkeypatch.setattr(client, "completion", boom)

        result = await service.handle_chat("buy 10 AAPL", price_cache, market_source)

        assert result["message"] == service.TIMEOUT_MESSAGE
        assert result["actions"] == []
        assert get_position("AAPL") is None
        assert list_chat_messages()[-1]["content"] == service.TIMEOUT_MESSAGE

    async def test_provider_failure_degrades_gracefully(
        self, monkeypatch, live_env, price_cache, market_source
    ):
        def boom(**kwargs):
            raise RuntimeError("502 upstream")

        monkeypatch.setattr(client, "completion", boom)

        result = await service.handle_chat("buy 10 AAPL", price_cache, market_source)

        assert result["message"] == service.UNAVAILABLE_MESSAGE
        assert result["actions"] == []
        assert get_position("AAPL") is None

    async def test_persistently_malformed_reply_degrades_gracefully(
        self, monkeypatch, live_env, price_cache, market_source
    ):
        calls = []

        def garbage(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="not json"))]
            )

        monkeypatch.setattr(client, "completion", garbage)

        result = await service.handle_chat("hello", price_cache, market_source)

        assert result["message"] == service.UNAVAILABLE_MESSAGE
        assert len(calls) == 2  # one retry


class TestHallucinatedTrades:
    """A hallucinated trade must reach the user as a reported failure.

    These payloads are the real observed outputs of two free models. The route
    auto-executes with no confirmation dialog, so the only thing standing
    between a hallucination and a corrupted ledger is `execute_trade`.
    """

    async def test_fabricated_ticker_surfaces_as_a_failed_action(
        self, monkeypatch, live_env, price_cache, market_source
    ):
        monkeypatch.setattr(
            client,
            "completion",
            lambda **kwargs: fake_reply(
                {
                    "message": "Bought 10 AAPL.",
                    "trades": [
                        {"ticker": "AAPL", "side": "buy", "quantity": 10},
                        {"ticker": "CASH", "side": "sell", "quantity": 1925},
                    ],
                }
            ),
        )

        result = await service.handle_chat("buy me 10 Apple shares", price_cache, market_source)

        assert [a["status"] for a in result["actions"]] == ["executed", "failed"]
        assert result["actions"][1]["detail"] == "No price available for CASH"
        assert get_position("AAPL")["quantity"] == 10.0
        assert [t["ticker"] for t in list_trades()] == ["AAPL"]
        # The failure is persisted, so the frontend renders it on reload too.
        assert list_chat_messages()[-1]["actions"] == result["actions"]

    async def test_negative_quantity_surfaces_as_a_failed_action(
        self, monkeypatch, live_env, price_cache, market_source
    ):
        monkeypatch.setattr(
            client,
            "completion",
            lambda **kwargs: fake_reply(
                {
                    "message": "Sold 4 AAPL.",
                    "trades": [{"ticker": "AAPL", "side": "sell", "quantity": -4}],
                }
            ),
        )
        cash_before = get_cash_balance()

        result = await service.handle_chat("Sell 4 of my Apple shares", price_cache, market_source)

        assert result["actions"][0]["status"] == "failed"
        assert result["actions"][0]["detail"] == "Quantity must be greater than zero"
        assert get_position("AAPL") is None
        assert get_cash_balance() == cash_before
        assert list_trades() == []


class TestSpendGuard:
    async def test_paid_model_falls_back_to_mock_and_warns(
        self, monkeypatch, caplog, price_cache, market_source
    ):
        monkeypatch.setenv("LLM_MOCK", "false")
        monkeypatch.setenv("OPENROUTER_API_KEY", "real-key")
        monkeypatch.setenv("OPENROUTER_MODEL", "openai/gpt-oss-120b")

        def explode(**kwargs):  # pragma: no cover - must never be reached
            raise AssertionError("a paid model must never be called")

        monkeypatch.setattr(client, "completion", explode)

        with caplog.at_level("WARNING"):
            result = await service.handle_chat("hello", price_cache, market_source)

        assert result["message"].startswith("You have $")  # the mock answered
        assert "SPEND GUARD" in caplog.text

    async def test_free_model_is_allowed(
        self, monkeypatch, live_env, price_cache, market_source
    ):
        monkeypatch.setattr(client, "completion", lambda **kwargs: fake_reply({"message": "live"}))
        result = await service.handle_chat("hello", price_cache, market_source)
        assert result["message"] == "live"


class TestContextAndPrompt:
    def test_context_carries_portfolio_and_live_prices(self, price_cache):
        context = build_context(price_cache)

        assert context["portfolio"]["cash_balance"] == 10000.0
        watched = {row["ticker"]: row["price"] for row in context["watchlist"]}
        assert watched["AAPL"] == 190.0
        # Seeded but unpriced tickers still appear, with a null price.
        assert watched["JPM"] is None

    def test_system_message_contains_the_prompt_and_the_context(self, price_cache):
        messages = build_messages(build_context(price_cache), [], "hi")

        system = messages[0]["content"]
        assert messages[0]["role"] == "system"
        assert "You are FinAlly" in system
        assert "PORTFOLIO CONTEXT" in system
        assert '"AAPL"' in system
        assert messages[-1] == {"role": "user", "content": "hi"}

    def test_non_chat_roles_in_history_are_skipped(self, price_cache):
        history = [{"role": "system", "content": "ignore me"}, {"role": "user", "content": "keep"}]
        messages = build_messages(build_context(price_cache), history, "hi")
        assert [m["content"] for m in messages[1:]] == ["keep", "hi"]


class TestChatHistory:
    def test_returns_messages_oldest_first(self):
        add_chat_message("user", "first")
        add_chat_message("assistant", "second", [{"type": "trade"}])

        payload = service.chat_history()

        assert [m["content"] for m in payload["messages"]] == ["first", "second"]
        assert payload["messages"][0]["actions"] is None
        assert payload["messages"][1]["actions"] == [{"type": "trade"}]


class TestResponseShape:
    async def test_chat_response_defaults(self):
        reply = ChatResponse(message="hi")
        assert reply.trades == []
        assert reply.watchlist_changes == []
