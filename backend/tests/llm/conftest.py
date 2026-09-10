"""Fixtures for the LLM tests.

Nothing here may reach the network: the autouse ``isolated_llm_env`` fixture
pins every LLM variable so a real ``.env`` on the developer's machine can never
leak into a test, and live-mode tests patch ``app.llm.client.completion``.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import database
from app.llm import service
from app.main import create_app
from app.market import MarketDataSource, PriceCache

SEEDED_PRICES = {
    "AAPL": 190.00,
    "GOOGL": 175.00,
    "MSFT": 420.00,
    "TSLA": 250.00,
    "NVDA": 900.00,
}

LLM_ENV_VARS = (
    "LLM_MOCK",
    "OPENROUTER_API_KEY",
    "OPENROUTER_MODEL",
    "OPENROUTER_FREE_ONLY",
    "OPENROUTER_TIMEOUT",
    "OPENROUTER_PROVIDER_ORDER",
    "OPENROUTER_REASONING_EFFORT",
)


@pytest.fixture(autouse=True)
def isolated_llm_env(monkeypatch):
    """Deterministic mock mode unless a test opts into live mode."""
    for name in LLM_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("LLM_MOCK", "true")
    monkeypatch.setattr(service, "_free_only_warned", False, raising=False)


@pytest.fixture
def live_env(monkeypatch):
    """Switch the layer into live mode (the call itself is always patched)."""
    monkeypatch.setenv("LLM_MOCK", "false")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "vendor/test-model:free")


class FakeMarketSource(MarketDataSource):
    """Records lifecycle calls instead of producing prices."""

    def __init__(self, tickers: list[str] | None = None) -> None:
        self._tickers = list(tickers or [])
        self.added: list[str] = []
        self.removed: list[str] = []

    async def start(self, tickers: list[str]) -> None:
        self._tickers = list(tickers)

    async def stop(self) -> None:
        pass

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
    """A TestClient with state injected directly, so no lifespan runs."""
    monkeypatch.delenv("FINALLY_STATIC_DIR", raising=False)
    monkeypatch.setenv("DEV_CORS", "false")
    app = create_app()
    app.state.price_cache = price_cache
    app.state.market_source = market_source
    return TestClient(app)
