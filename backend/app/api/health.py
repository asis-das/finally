"""Health check endpoint used by Docker, deployment platforms and the E2E suite."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from app.api.deps import get_market_source
from app.db import get_connection
from app.market import MarketDataSource
from app.market.massive_client import MassiveDataSource

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["system"])


def _db_status() -> str:
    try:
        with get_connection() as conn:
            conn.execute("SELECT 1").fetchone()
        return "ok"
    except Exception:
        logger.exception("Health check: database is unreachable")
        return "error"


@router.get("/health")
def health(source: MarketDataSource = Depends(get_market_source)) -> dict:
    db = _db_status()
    return {
        "status": "ok" if db == "ok" else "degraded",
        "market_source": "massive" if isinstance(source, MassiveDataSource) else "simulator",
        "tickers": len(source.get_tickers()),
        "db": db,
    }
