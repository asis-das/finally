"""Portfolio endpoints: holdings, trade execution and value history."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.deps import get_price_cache
from app.db import list_snapshots
from app.market import PriceCache
from app.services.portfolio import (
    PriceUnavailableError,
    TradeError,
    build_portfolio,
    execute_trade,
    total_portfolio_value,
)

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


class TradeRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=10)
    quantity: float = Field(gt=0)
    side: Literal["buy", "sell"]


@router.get("")
def get_portfolio(cache: PriceCache = Depends(get_price_cache)) -> dict:
    return build_portfolio(cache)


@router.post("/trade")
def post_trade(payload: TradeRequest, cache: PriceCache = Depends(get_price_cache)) -> dict:
    try:
        return execute_trade(cache, payload.ticker, payload.side, payload.quantity)
    except PriceUnavailableError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TradeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/history")
def get_history(
    limit: int = Query(default=500, ge=1, le=5000),
    cache: PriceCache = Depends(get_price_cache),
) -> dict:
    snapshots = [
        {"total_value": round(row["total_value"], 2), "recorded_at": row["recorded_at"]}
        for row in list_snapshots(limit=limit)
    ]
    if not snapshots:
        # Never hand the chart an empty series — seed it with "now".
        snapshots.append(
            {
                "total_value": total_portfolio_value(cache),
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    return {"snapshots": snapshots}
