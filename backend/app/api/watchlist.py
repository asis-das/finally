"""Watchlist endpoints. Mutations keep the market data source in step."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import get_market_source, get_price_cache, get_reference_prices
from app.db import (
    add_watchlist_ticker,
    get_position,
    list_watchlist,
    remove_watchlist_ticker,
)
from app.market import MarketDataSource, PriceCache
from app.services.reference_prices import ReferencePrices

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])

TICKER_PATTERN = re.compile(r"^[A-Z.\-]{1,10}$")


class WatchlistRequest(BaseModel):
    ticker: str


def _normalize(ticker: str) -> str:
    normalized = ticker.strip().upper()
    if not TICKER_PATTERN.match(normalized):
        raise HTTPException(status_code=400, detail="Invalid ticker")
    return normalized


@router.get("")
def get_watchlist(
    cache: PriceCache = Depends(get_price_cache),
    references: ReferencePrices = Depends(get_reference_prices),
) -> dict:
    """Watchlist with live prices.

    `change`/`change_percent` are tick-over-tick (the frontend drives its flash
    animation from them). `day_change`/`day_change_percent` are measured against
    `previous_close` — see `app.services.reference_prices` for what "day" means
    when the prices come from a simulator.
    """
    tickers = []
    for ticker in list_watchlist():
        update = cache.get(ticker)
        price = None if update is None else round(update.price, 2)
        reference, day_change, day_change_percent = references.day_move(ticker, price)
        entry = {
            "ticker": ticker,
            "price": price,
            "previous_price": None if update is None else round(update.previous_price, 2),
            "change": 0.0 if update is None else round(update.change, 2),
            "change_percent": 0.0 if update is None else round(update.change_percent, 2),
            "direction": "flat" if update is None else update.direction,
            "previous_close": None if reference is None else round(reference, 2),
            "day_change": day_change,
            "day_change_percent": day_change_percent,
        }
        tickers.append(entry)
    return {"tickers": tickers}


@router.post("", status_code=201)
async def post_watchlist(
    payload: WatchlistRequest,
    source: MarketDataSource = Depends(get_market_source),
) -> dict:
    ticker = _normalize(payload.ticker)
    if not add_watchlist_ticker(ticker):
        raise HTTPException(status_code=409, detail=f"Ticker {ticker} is already on the watchlist")
    await source.add_ticker(ticker)
    return {"ticker": ticker, "added": True}


@router.delete("/{ticker}")
async def delete_watchlist(
    ticker: str,
    source: MarketDataSource = Depends(get_market_source),
) -> dict:
    normalized = _normalize(ticker)
    if not remove_watchlist_ticker(normalized):
        raise HTTPException(
            status_code=404, detail=f"Ticker {normalized} is not on the watchlist"
        )
    # Keep pricing anything we still hold, even once it leaves the watchlist.
    if get_position(normalized) is None:
        await source.remove_ticker(normalized)
    return {"ticker": normalized, "removed": True}
