"""Tests for GET /api/health."""

from __future__ import annotations

from unittest.mock import patch

from app.market.massive_client import MassiveDataSource


def test_health_reports_ok(client, market_source):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "market_source": "simulator",
        "tickers": len(market_source.get_tickers()),
        "db": "ok",
    }


def test_health_tracks_ticker_count(client, market_source):
    market_source._tickers = ["AAPL", "MSFT"]
    assert client.get("/api/health").json()["tickers"] == 2


def test_health_reports_massive_source(client, price_cache):
    client.app.state.market_source = MassiveDataSource(api_key="test", price_cache=price_cache)
    assert client.get("/api/health").json()["market_source"] == "massive"


def test_health_degrades_when_db_is_unreachable(client):
    with patch("app.api.health.get_connection", side_effect=RuntimeError("boom")):
        body = client.get("/api/health").json()
    assert body["status"] == "degraded"
    assert body["db"] == "error"
