"""The chat routes through FastAPI's TestClient."""

from __future__ import annotations

import json
from types import SimpleNamespace

from app.db import get_position
from app.llm import client as llm_client
from app.llm import service


class TestPostChat:
    def test_summary_turn(self, client):
        response = client.post("/api/chat", json={"message": "how am I doing?"})

        assert response.status_code == 200
        body = response.json()
        assert body["message"].startswith("You have $10,000.00 in cash")
        assert body["actions"] == []
        assert body["created_at"]

    def test_buy_turn_executes_and_reports(self, client):
        response = client.post("/api/chat", json={"message": "buy 10 AAPL"})

        body = response.json()
        assert body["message"] == "Bought 10 AAPL."
        assert body["actions"] == [
            {
                "type": "trade",
                "status": "executed",
                "ticker": "AAPL",
                "side": "buy",
                "quantity": 10.0,
                "price": 190.0,
                "detail": "Bought 10 AAPL @ $190.00",
            }
        ]
        assert get_position("AAPL")["quantity"] == 10.0
        assert client.get("/api/portfolio").json()["cash_balance"] == 8100.0

    def test_watchlist_turn_reaches_the_rest_endpoint(self, client):
        client.post("/api/chat", json={"message": "add PYPL"})

        tickers = [row["ticker"] for row in client.get("/api/watchlist").json()["tickers"]]
        assert "PYPL" in tickers

    def test_missing_message_is_a_422(self, client):
        assert client.post("/api/chat", json={}).status_code == 422

    def test_llm_failure_is_never_a_500(self, client, monkeypatch, live_env):
        def boom(**kwargs):
            raise RuntimeError("provider down")

        monkeypatch.setattr(llm_client, "completion", boom)

        response = client.post("/api/chat", json={"message": "buy 10 AAPL"})

        assert response.status_code == 200
        body = response.json()
        assert body["message"] == service.UNAVAILABLE_MESSAGE
        assert body["actions"] == []
        assert get_position("AAPL") is None

    def test_unexpected_internal_failure_is_never_a_500(self, client, monkeypatch):
        async def boom(*args, **kwargs):
            raise RuntimeError("database on fire")

        monkeypatch.setattr("app.api.chat.handle_chat", boom)

        response = client.post("/api/chat", json={"message": "hello"})

        assert response.status_code == 200
        body = response.json()
        assert body["actions"] == []
        assert "unavailable" in body["message"].lower()
        assert body["created_at"]

    def test_live_mode_round_trip(self, client, monkeypatch, live_env):
        payload = {
            "message": "Added PYPL and bought 1 share.",
            "trades": [{"ticker": "AAPL", "side": "buy", "quantity": 1}],
            "watchlist_changes": [{"ticker": "PYPL", "action": "add"}],
        }
        monkeypatch.setattr(
            llm_client,
            "completion",
            lambda **kwargs: SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
            ),
        )

        body = client.post("/api/chat", json={"message": "do it"}).json()

        assert body["message"] == "Added PYPL and bought 1 share."
        assert [a["type"] for a in body["actions"]] == ["watchlist", "trade"]
        assert all(a["status"] == "executed" for a in body["actions"])


class TestChatHistory:
    def test_empty_history(self, client):
        assert client.get("/api/chat/history").json() == {"messages": []}

    def test_history_is_oldest_first(self, client):
        client.post("/api/chat", json={"message": "buy 10 AAPL"})
        client.post("/api/chat", json={"message": "how am I doing?"})

        messages = client.get("/api/chat/history").json()["messages"]

        assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
        assert messages[0]["content"] == "buy 10 AAPL"
        assert messages[1]["actions"][0]["detail"] == "Bought 10 AAPL @ $190.00"
        assert messages[2]["actions"] is None

    def test_limit_is_validated(self, client):
        assert client.get("/api/chat/history?limit=0").status_code == 422
        assert client.get("/api/chat/history?limit=501").status_code == 422
        assert client.get("/api/chat/history?limit=1").status_code == 200
