"""Fixtures for the portfolio service tests."""

from __future__ import annotations

import pytest

from app.db import database
from app.market import PriceCache

SEEDED_PRICES = {"AAPL": 190.00, "GOOGL": 175.00, "MSFT": 420.00}


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    path = str(tmp_path / "finally.db")
    monkeypatch.setenv("FINALLY_DB_PATH", path)
    monkeypatch.setattr(database, "_db_path", None, raising=False)
    database.init_db(path)
    return path


@pytest.fixture
def cache(temp_db) -> PriceCache:
    price_cache = PriceCache()
    for ticker, price in SEEDED_PRICES.items():
        price_cache.update(ticker, price)
    return price_cache
