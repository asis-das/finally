"""Execution of assistant actions against the real portfolio service and db."""

from __future__ import annotations

import pytest

from app.db import (
    add_watchlist_ticker,
    get_cash_balance,
    get_position,
    list_positions,
    list_trades,
    list_watchlist,
)
from app.llm.actions import apply_actions, apply_trade, apply_watchlist_change
from app.llm.schemas import ChatResponse, Trade, WatchlistChange

pytestmark = pytest.mark.usefixtures("temp_db")


class TestTrades:
    def test_successful_buy(self, price_cache):
        action = apply_trade(Trade(ticker="aapl", side="buy", quantity=10), price_cache)

        assert action == {
            "type": "trade",
            "status": "executed",
            "ticker": "AAPL",
            "side": "buy",
            "quantity": 10.0,
            "price": 190.0,
            "detail": "Bought 10 AAPL @ $190.00",
        }
        assert get_position("AAPL")["quantity"] == 10.0

    def test_successful_sell(self, price_cache):
        apply_trade(Trade(ticker="AAPL", side="buy", quantity=10), price_cache)
        action = apply_trade(Trade(ticker="AAPL", side="sell", quantity=4), price_cache)

        assert action["status"] == "executed"
        assert action["detail"] == "Sold 4 AAPL @ $190.00"
        assert get_position("AAPL")["quantity"] == pytest.approx(6.0)

    def test_insufficient_cash_is_reported_not_raised(self, price_cache):
        action = apply_trade(Trade(ticker="AAPL", side="buy", quantity=1000), price_cache)

        assert action["status"] == "failed"
        assert action["price"] is None
        assert action["detail"].startswith("Insufficient cash:")
        assert get_position("AAPL") is None

    def test_insufficient_shares_is_reported(self, price_cache):
        action = apply_trade(Trade(ticker="AAPL", side="sell", quantity=3), price_cache)

        assert action["status"] == "failed"
        assert action["detail"] == "Insufficient shares: tried to sell 3 AAPL, hold 0"

    def test_unpriced_ticker_is_reported(self, price_cache):
        action = apply_trade(Trade(ticker="ZZZZ", side="buy", quantity=1), price_cache)

        assert action["status"] == "failed"
        assert action["detail"] == "No price available for ZZZZ"

    def test_zero_quantity_is_reported(self, price_cache):
        action = apply_trade(Trade(ticker="AAPL", side="buy", quantity=0), price_cache)

        assert action["status"] == "failed"
        assert action["detail"] == "Quantity must be greater than zero"

    def test_buying_does_not_touch_the_watchlist(self, price_cache):
        before = list_watchlist()
        apply_trade(Trade(ticker="AAPL", side="buy", quantity=1), price_cache)
        assert list_watchlist() == before


class TestHostileModelOutput:
    """The schema constrains shape, not sanity.

    Two of six benchmarked free models emitted structurally-valid nonsense: a
    fabricated ``sell 1925 CASH``, and ``{"ticker": "AAPL", "side": "sell",
    "quantity": -4}``. Trades auto-execute with no confirmation dialog, so the
    executor must be hostile to its own model's output. Every case here has to
    come back as a reported failure with nothing written.
    """

    def _ledger(self) -> tuple:
        return (get_cash_balance(), list_positions(), list_trades())

    def test_negative_quantity_is_rejected_not_coerced(self, price_cache):
        before = self._ledger()

        action = apply_trade(Trade(ticker="AAPL", side="sell", quantity=-4), price_cache)

        assert action["status"] == "failed"
        assert action["detail"] == "Quantity must be greater than zero"
        assert action["quantity"] == -4.0, "the bad value is reported verbatim, never abs()'d"
        assert action["price"] is None
        # Nothing written: no phantom sale, and no accidental buy from abs(-4).
        assert self._ledger() == before
        assert get_position("AAPL") is None

    def test_negative_buy_quantity_is_rejected(self, price_cache):
        before = self._ledger()

        action = apply_trade(Trade(ticker="AAPL", side="buy", quantity=-10), price_cache)

        assert action["status"] == "failed"
        assert action["detail"] == "Quantity must be greater than zero"
        assert self._ledger() == before

    def test_fabricated_ticker_is_rejected(self, price_cache):
        before = self._ledger()

        action = apply_trade(Trade(ticker="CASH", side="sell", quantity=1925), price_cache)

        assert action["status"] == "failed"
        assert action["detail"] == "No price available for CASH"
        assert action["price"] is None
        assert self._ledger() == before
        assert get_position("CASH") is None

    async def test_the_observed_liquid_hallucination(self, price_cache, market_source):
        """"buy me 10 Apple shares" -> the right trade PLUS an invented sell."""
        reply = ChatResponse(
            message="Bought 10 AAPL.",
            trades=[
                Trade(ticker="AAPL", side="buy", quantity=10),
                Trade(ticker="CASH", side="sell", quantity=1925),
            ],
        )

        actions = await apply_actions(reply, price_cache, market_source)

        assert [a["status"] for a in actions] == ["executed", "failed"]
        assert actions[1]["detail"] == "No price available for CASH"
        # The good half still happened; the ledger holds only the real trade.
        assert get_position("AAPL")["quantity"] == 10.0
        assert [t["ticker"] for t in list_trades()] == ["AAPL"]

    async def test_the_observed_dots_hallucination(self, price_cache, market_source):
        """"Sell 4 of my Apple shares" -> quantity: -4."""
        apply_trade(Trade(ticker="AAPL", side="buy", quantity=10), price_cache)
        cash_after_buy = get_cash_balance()

        reply = ChatResponse(
            message="Sold 4 AAPL.",
            trades=[Trade(ticker="AAPL", side="sell", quantity=-4)],
        )
        actions = await apply_actions(reply, price_cache, market_source)

        assert actions[0]["status"] == "failed"
        assert actions[0]["detail"] == "Quantity must be greater than zero"
        # The position is untouched: not sold, and not bought via abs(-4).
        assert get_position("AAPL")["quantity"] == 10.0
        assert get_cash_balance() == cash_after_buy
        assert len(list_trades()) == 1

    async def test_a_bad_trade_does_not_block_a_later_good_one(
        self, price_cache, market_source
    ):
        reply = ChatResponse(
            message="Two trades.",
            trades=[
                Trade(ticker="AAPL", side="sell", quantity=-4),
                Trade(ticker="MSFT", side="buy", quantity=2),
            ],
        )

        actions = await apply_actions(reply, price_cache, market_source)

        assert [a["status"] for a in actions] == ["failed", "executed"]
        assert get_position("MSFT")["quantity"] == 2.0
        assert [t["ticker"] for t in list_trades()] == ["MSFT"]

    async def test_a_bad_watchlist_change_does_not_block_the_trade(
        self, price_cache, market_source
    ):
        reply = ChatResponse(
            message="Adding and buying.",
            trades=[Trade(ticker="AAPL", side="buy", quantity=1)],
            watchlist_changes=[WatchlistChange(ticker="NOT A TICKER", action="add")],
        )

        actions = await apply_actions(reply, price_cache, market_source)

        assert [a["status"] for a in actions] == ["failed", "executed"]
        assert "Invalid ticker" in actions[0]["detail"]
        assert get_position("AAPL")["quantity"] == 1.0


class TestWatchlistChanges:
    async def test_add(self, market_source):
        action = await apply_watchlist_change(
            WatchlistChange(ticker="pypl", action="add"), market_source
        )

        assert action == {
            "type": "watchlist",
            "status": "executed",
            "ticker": "PYPL",
            "action": "add",
            "detail": "Added PYPL to the watchlist",
        }
        assert "PYPL" in list_watchlist()
        assert market_source.added == ["PYPL"]

    async def test_add_duplicate_fails(self, market_source):
        add_watchlist_ticker("PYPL")
        action = await apply_watchlist_change(
            WatchlistChange(ticker="PYPL", action="add"), market_source
        )

        assert action["status"] == "failed"
        assert action["detail"] == "Ticker PYPL is already on the watchlist"
        assert market_source.added == []

    async def test_remove(self, market_source):
        action = await apply_watchlist_change(
            WatchlistChange(ticker="AAPL", action="remove"), market_source
        )

        assert action["status"] == "executed"
        assert action["detail"] == "Removed AAPL from the watchlist"
        assert "AAPL" not in list_watchlist()
        assert market_source.removed == ["AAPL"]

    async def test_remove_missing_fails(self, market_source):
        action = await apply_watchlist_change(
            WatchlistChange(ticker="PYPL", action="remove"), market_source
        )

        assert action["status"] == "failed"
        assert action["detail"] == "Ticker PYPL is not on the watchlist"
        assert market_source.removed == []

    async def test_remove_keeps_pricing_a_held_ticker(self, market_source, price_cache):
        apply_trade(Trade(ticker="AAPL", side="buy", quantity=1), price_cache)

        action = await apply_watchlist_change(
            WatchlistChange(ticker="AAPL", action="remove"), market_source
        )

        assert action["status"] == "executed"
        assert "AAPL" not in list_watchlist()
        assert market_source.removed == []

    async def test_invalid_ticker_is_reported(self, market_source):
        action = await apply_watchlist_change(
            WatchlistChange(ticker="not a ticker!", action="add"), market_source
        )

        assert action["status"] == "failed"
        assert "Invalid ticker" in action["detail"]
        assert market_source.added == []


class TestOrdering:
    async def test_watchlist_changes_run_before_trades(self, price_cache, market_source):
        # PYPL is priced but not watched: the add must land before the buy.
        price_cache.update("PYPL", 60.0)
        reply = ChatResponse(
            message="Adding and buying.",
            trades=[Trade(ticker="PYPL", side="buy", quantity=2)],
            watchlist_changes=[WatchlistChange(ticker="PYPL", action="add")],
        )

        actions = await apply_actions(reply, price_cache, market_source)

        assert [a["type"] for a in actions] == ["watchlist", "trade"]
        assert all(a["status"] == "executed" for a in actions)
        assert get_position("PYPL")["quantity"] == 2.0

    async def test_a_failed_action_does_not_stop_the_others(self, price_cache, market_source):
        reply = ChatResponse(
            message="Two trades.",
            trades=[
                Trade(ticker="AAPL", side="buy", quantity=100000),
                Trade(ticker="MSFT", side="buy", quantity=1),
            ],
        )

        actions = await apply_actions(reply, price_cache, market_source)

        assert [a["status"] for a in actions] == ["failed", "executed"]
        assert get_position("MSFT")["quantity"] == 1.0

    async def test_no_actions_yields_an_empty_list(self, price_cache, market_source):
        assert await apply_actions(ChatResponse(message="Hi."), price_cache, market_source) == []


class TestQuantityIsNeverSubstituted:
    """The assistant must never silently resize a quantity the user stated.

    Observed with the free model before the prompt was tightened: asked to
    "Buy 5000 shares of TSLA" with $10,000 of cash, it bought 20 instead and
    mentioned the change in prose. That is worse than a hallucination — the
    trade is plausible, it auto-executes with no confirmation dialog, and the
    only record of the substitution is a sentence the user may never read.

    The prompt now forbids it (see app/llm/prompt.py). These tests pin the
    behaviour the executor must guarantee regardless of what the model does:
    an unaffordable quantity is reported as failed, at the quantity asked for,
    and nothing reaches the database.
    """

    def test_unaffordable_buy_fails_at_the_requested_quantity(self, price_cache):
        action = apply_trade(Trade(ticker="TSLA", side="buy", quantity=5000), price_cache)

        assert action["status"] == "failed"
        # The full requested size is echoed back, not a size that would have fit.
        assert action["quantity"] == 5000.0
        assert "Insufficient cash" in action["detail"]

    def test_unaffordable_buy_writes_nothing(self, price_cache):
        cash_before = get_cash_balance()

        apply_trade(Trade(ticker="TSLA", side="buy", quantity=5000), price_cache)

        assert get_cash_balance() == cash_before
        assert get_position("TSLA") is None
        assert list_positions() == []
        assert list_trades() == []

    def test_oversized_sell_fails_rather_than_selling_what_is_held(self, price_cache):
        apply_trade(Trade(ticker="AAPL", side="buy", quantity=10), price_cache)

        action = apply_trade(Trade(ticker="AAPL", side="sell", quantity=999), price_cache)

        assert action["status"] == "failed"
        assert action["quantity"] == 999.0
        assert "Insufficient shares" in action["detail"]
        # The holding is untouched — not partially liquidated down to zero.
        assert get_position("AAPL")["quantity"] == 10.0

    async def test_a_valid_trade_still_runs_when_another_is_unaffordable(
        self, price_cache, market_source
    ):
        """One bad trade in a response must not suppress the good one."""
        response = ChatResponse(
            message="Doing both.",
            trades=[
                Trade(ticker="AAPL", side="buy", quantity=2),
                Trade(ticker="TSLA", side="buy", quantity=5000),
            ],
        )

        actions = await apply_actions(response, price_cache, market_source)

        statuses = [(a["ticker"], a["status"]) for a in actions if a["type"] == "trade"]
        assert statuses == [("AAPL", "executed"), ("TSLA", "failed")]
        assert get_position("AAPL")["quantity"] == 2.0
        assert get_position("TSLA") is None
