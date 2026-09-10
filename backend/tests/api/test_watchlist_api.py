"""Tests for the /api/watchlist endpoints."""

from __future__ import annotations

import pytest

from app.db import list_watchlist, upsert_position


def test_get_watchlist_returns_seeded_tickers_in_order(client):
    body = client.get("/api/watchlist").json()
    tickers = [row["ticker"] for row in body["tickers"]]
    assert tickers == list_watchlist()
    assert tickers[0] == "AAPL"
    assert len(tickers) == 10


def test_priced_row_shape(client, price_cache):
    price_cache.update("AAPL", 192.5)

    row = next(r for r in client.get("/api/watchlist").json()["tickers"] if r["ticker"] == "AAPL")
    assert set(row) == {
        "ticker",
        "price",
        "previous_price",
        "change",
        "change_percent",
        "direction",
        "previous_close",
        "day_change",
        "day_change_percent",
    }
    assert row["price"] == 192.5
    assert row["previous_price"] == 190.0
    assert row["change"] == 2.5
    assert row["change_percent"] == 1.32
    assert row["direction"] == "up"


def test_day_change_is_measured_against_the_seed_price(client, price_cache):
    """A seeded ticker's "day" reference is its SEED_PRICES entry (AAPL 190.00)."""
    price_cache.update("AAPL", 199.50)

    row = next(r for r in client.get("/api/watchlist").json()["tickers"] if r["ticker"] == "AAPL")
    assert row["previous_close"] == 190.0
    assert row["day_change"] == 9.5
    assert row["day_change_percent"] == 5.0


def test_day_change_survives_further_ticks(client, price_cache):
    """The reference is the seed price, not the previous tick - so it accumulates."""
    price_cache.update("AAPL", 195.00)
    price_cache.update("AAPL", 199.50)

    row = next(r for r in client.get("/api/watchlist").json()["tickers"] if r["ticker"] == "AAPL")
    # Tick-over-tick stays small; the day move is the whole distance from 190.
    assert row["change"] == 4.5
    assert row["previous_close"] == 190.0
    assert row["day_change"] == 9.5


def test_unseeded_ticker_uses_its_first_observed_price(client, price_cache):
    """A ticker the user adds has no seed price, so first sight becomes the reference."""
    client.post("/api/watchlist", json={"ticker": "PYPL"})
    price_cache.update("PYPL", 60.00)

    rows = client.get("/api/watchlist").json()["tickers"]
    row = next(r for r in rows if r["ticker"] == "PYPL")
    assert row["previous_close"] == 60.0
    assert row["day_change"] == 0.0

    price_cache.update("PYPL", 63.00)
    row = next(r for r in client.get("/api/watchlist").json()["tickers"] if r["ticker"] == "PYPL")
    assert row["previous_close"] == 60.0, "reference must not drift with the price"
    assert row["day_change"] == 3.0
    assert row["day_change_percent"] == 5.0


def test_unpriced_ticker_has_zero_day_change(client):
    row = next(r for r in client.get("/api/watchlist").json()["tickers"] if r["ticker"] == "NFLX")
    assert row["price"] is None
    assert row["day_change"] == 0.0
    assert row["day_change_percent"] == 0.0


def test_unpriced_row_is_flat_with_null_price(client):
    row = next(r for r in client.get("/api/watchlist").json()["tickers"] if r["ticker"] == "NFLX")
    assert row["price"] is None
    assert row["previous_price"] is None
    assert row["direction"] == "flat"


def test_add_ticker_normalises_and_tracks_it(client, market_source):
    response = client.post("/api/watchlist", json={"ticker": "pypl"})
    assert response.status_code == 201
    assert response.json() == {"ticker": "PYPL", "added": True}
    assert market_source.added == ["PYPL"]
    assert "PYPL" in list_watchlist()


def test_add_duplicate_is_409(client, market_source):
    response = client.post("/api/watchlist", json={"ticker": "AAPL"})
    assert response.status_code == 409
    assert response.json() == {"detail": "Ticker AAPL is already on the watchlist"}
    assert market_source.added == []


@pytest.mark.parametrize("ticker", ["", "TOOLONGTICKER", "AA PL", "123", "AA$PL"])
def test_invalid_tickers_are_400(client, ticker):
    response = client.post("/api/watchlist", json={"ticker": ticker})
    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid ticker"}


def test_dotted_and_hyphenated_tickers_are_allowed(client):
    assert client.post("/api/watchlist", json={"ticker": "brk.b"}).status_code == 201
    assert client.post("/api/watchlist", json={"ticker": "BF-B"}).status_code == 201


def test_remove_ticker_stops_tracking_it(client, market_source):
    response = client.delete("/api/watchlist/AAPL")
    assert response.status_code == 200
    assert response.json() == {"ticker": "AAPL", "removed": True}
    assert market_source.removed == ["AAPL"]
    assert "AAPL" not in list_watchlist()


def test_remove_is_case_insensitive(client):
    assert client.delete("/api/watchlist/aapl").status_code == 200
    assert "AAPL" not in list_watchlist()


def test_remove_unknown_ticker_is_404(client, market_source):
    response = client.delete("/api/watchlist/PYPL")
    assert response.status_code == 404
    assert response.json() == {"detail": "Ticker PYPL is not on the watchlist"}
    assert market_source.removed == []


def test_held_ticker_keeps_streaming_after_removal(client, market_source):
    upsert_position("AAPL", 5.0, 180.0)

    assert client.delete("/api/watchlist/AAPL").status_code == 200
    assert "AAPL" not in list_watchlist()
    # Still owned, so the price must keep flowing for portfolio valuation.
    assert market_source.removed == []
    assert client.get("/api/portfolio").json()["positions"][0]["current_price"] == 190.0
