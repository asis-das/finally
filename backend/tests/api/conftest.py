"""Fixtures for the API tests: a temp database, a primed cache, a fake source."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import database
from app.main import create_app
from app.market import MarketDataSource, PriceCache

SEEDED_PRICES = {
    "AAPL": 190.00,
    "GOOGL": 175.00,
    "MSFT": 420.00,
    "AMZN": 185.00,
    "TSLA": 250.00,
    "NVDA": 900.00,
    "META": 500.00,
    "JPM": 200.00,
    "V": 280.00,
    # NFLX is deliberately left unpriced so the "no price yet" paths are covered.
}


class FakeMarketSource(MarketDataSource):
    """Records lifecycle calls instead of producing prices."""

    def __init__(self, tickers: list[str] | None = None) -> None:
        self._tickers = list(tickers or [])
        self.added: list[str] = []
        self.removed: list[str] = []
        self.started = False
        self.stopped = False

    async def start(self, tickers: list[str]) -> None:
        self._tickers = list(tickers)
        self.started = True

    async def stop(self) -> None:
        self.stopped = True

    async def add_ticker(self, ticker: str) -> None:
        self.added.append(ticker)
        if ticker not in self._tickers:
            self._tickers.append(ticker)

    async def remove_ticker(self, ticker: str) -> None:
        self.removed.append(ticker)
        if ticker in self._tickers:
            self._tickers.remove(ticker)

    def get_tickers(self) -> list[str]:
        return list(self._tickers)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    """Point the whole db layer at a throwaway SQLite file."""
    path = str(tmp_path / "finally.db")
    monkeypatch.setenv("FINALLY_DB_PATH", path)
    monkeypatch.setattr(database, "_db_path", None, raising=False)
    database.init_db(path)
    return path


@pytest.fixture
def price_cache() -> PriceCache:
    cache = PriceCache()
    for ticker, price in SEEDED_PRICES.items():
        cache.update(ticker, price)
    return cache


@pytest.fixture
def market_source(price_cache) -> FakeMarketSource:
    return FakeMarketSource(sorted(SEEDED_PRICES))


@pytest.fixture
def client(temp_db, price_cache, market_source, monkeypatch):
    """A TestClient with state injected directly, so no lifespan runs.

    The market simulator would otherwise move prices under the assertions.
    """
    monkeypatch.delenv("FINALLY_STATIC_DIR", raising=False)
    monkeypatch.setenv("DEV_CORS", "false")
    app = create_app()
    app.state.price_cache = price_cache
    app.state.market_source = market_source
    return TestClient(app)
