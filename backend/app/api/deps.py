"""FastAPI dependencies exposing per-app shared state.

The price cache and market data source are created in the lifespan handler and
stored on ``app.state`` — never at module level — because the test suite builds
several app instances in one process.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from app.market import MarketDataSource, PriceCache
from app.services.reference_prices import ReferencePrices


def get_price_cache(request: Request) -> PriceCache:
    cache = getattr(request.app.state, "price_cache", None)
    if cache is None:  # pragma: no cover - only reachable if lifespan was skipped
        raise HTTPException(status_code=503, detail="Market data is not ready")
    return cache


def get_market_source(request: Request) -> MarketDataSource:
    source = getattr(request.app.state, "market_source", None)
    if source is None:  # pragma: no cover - only reachable if lifespan was skipped
        raise HTTPException(status_code=503, detail="Market data is not ready")
    return source


def get_reference_prices(request: Request) -> ReferencePrices:
    refs = getattr(request.app.state, "reference_prices", None)
    if refs is None:  # pragma: no cover - only reachable if create_app was bypassed
        raise HTTPException(status_code=503, detail="Market data is not ready")
    return refs
