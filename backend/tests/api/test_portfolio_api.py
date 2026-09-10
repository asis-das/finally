"""Tests for the /api/portfolio endpoints."""

from __future__ import annotations

import pytest

from app.db import upsert_position


def test_get_portfolio_fresh_account(client):
    body = client.get("/api/portfolio").json()
    assert body["cash_balance"] == 10000.0
    assert body["positions"] == []
    assert body["total_value"] == 10000.0


def test_get_portfolio_position_shape(client, price_cache):
    upsert_position("AAPL", 10.0, 180.0)
    price_cache.update("AAPL", 190.0)

    body = client.get("/api/portfolio").json()
    assert set(body) == {
        "cash_balance",
        "positions",
        "positions_value",
        "total_value",
        "total_cost_basis",
        "total_unrealized_pnl",
        "total_unrealized_pnl_percent",
    }
    position = body["positions"][0]
    assert set(position) == {
        "ticker",
        "quantity",
        "avg_cost",
        "current_price",
        "market_value",
        "unrealized_pnl",
        "unrealized_pnl_percent",
        "weight",
    }
    assert position["market_value"] == 1900.0
    assert position["unrealized_pnl"] == 100.0


def test_buy_returns_full_payload(client):
    response = client.post(
        "/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 10, "side": "buy"}
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"trade", "cash_balance", "position", "total_value"}
    assert body["trade"]["ticker"] == "AAPL"
    assert body["trade"]["price"] == 190.0
    assert body["cash_balance"] == 8100.0
    assert body["position"] == {"ticker": "AAPL", "quantity": 10.0, "avg_cost": 190.0}

    portfolio = client.get("/api/portfolio").json()
    assert portfolio["cash_balance"] == 8100.0
    assert portfolio["positions"][0]["ticker"] == "AAPL"


def test_sell_can_close_a_position(client):
    client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 5, "side": "buy"})
    response = client.post(
        "/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 5, "side": "sell"}
    )
    assert response.status_code == 200
    assert response.json()["position"] is None
    assert client.get("/api/portfolio").json()["positions"] == []


def test_lowercase_ticker_is_accepted(client):
    response = client.post(
        "/api/portfolio/trade", json={"ticker": "aapl", "quantity": 1, "side": "buy"}
    )
    assert response.status_code == 200
    assert response.json()["trade"]["ticker"] == "AAPL"


def test_insufficient_cash_is_400(client):
    response = client.post(
        "/api/portfolio/trade", json={"ticker": "NVDA", "quantity": 100, "side": "buy"}
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "Insufficient cash: need $90000.00, have $10000.00"}


def test_insufficient_shares_is_400(client):
    upsert_position("AAPL", 3.0, 100.0)
    response = client.post(
        "/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 10, "side": "sell"}
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "Insufficient shares: tried to sell 10 AAPL, hold 3"}


def test_unpriced_ticker_is_404(client):
    response = client.post(
        "/api/portfolio/trade", json={"ticker": "NFLX", "quantity": 1, "side": "buy"}
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "No price available for NFLX"}


@pytest.mark.parametrize(
    "payload",
    [
        {"ticker": "AAPL", "quantity": 0, "side": "buy"},
        {"ticker": "AAPL", "quantity": -3, "side": "buy"},
        {"ticker": "AAPL", "quantity": 1, "side": "short"},
        {"ticker": "AAPL", "side": "buy"},
    ],
)
def test_invalid_trade_requests_are_422(client, payload):
    assert client.post("/api/portfolio/trade", json=payload).status_code == 422


def test_history_seeds_a_synthetic_point_when_empty(client):
    body = client.get("/api/portfolio/history").json()
    assert len(body["snapshots"]) == 1
    assert body["snapshots"][0]["total_value"] == 10000.0
    assert body["snapshots"][0]["recorded_at"]


def test_history_returns_snapshots_after_a_trade(client):
    client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 1, "side": "buy"})
    client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 1, "side": "buy"})

    snapshots = client.get("/api/portfolio/history").json()["snapshots"]
    assert len(snapshots) == 2
    assert set(snapshots[0]) == {"total_value", "recorded_at"}
    assert snapshots == sorted(snapshots, key=lambda s: s["recorded_at"])


def test_history_respects_limit(client):
    for _ in range(3):
        client.post("/api/portfolio/trade", json={"ticker": "AAPL", "quantity": 1, "side": "buy"})
    assert len(client.get("/api/portfolio/history?limit=2").json()["snapshots"]) == 2
    assert client.get("/api/portfolio/history?limit=0").status_code == 422
