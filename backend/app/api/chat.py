"""Chat endpoints. A thin adapter over ``app.llm.service``.

Built by a factory rather than a module-level ``router`` so that ``main`` can
mount it per application instance, and so the price cache and market source are
resolved from ``request.app.state`` at request time (importing them from
``main`` would be circular).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_market_source, get_price_cache
from app.llm import ChatRequest, chat_history, handle_chat
from app.llm import config as llm_config
from app.llm.service import UNAVAILABLE_MESSAGE
from app.market import MarketDataSource, PriceCache

logger = logging.getLogger(__name__)


def create_chat_router() -> APIRouter:
    """Mounts ``POST /api/chat`` and ``GET /api/chat/history`` under ``/api``."""
    router = APIRouter(prefix="/api/chat", tags=["chat"])

    @router.post("")
    async def post_chat(
        payload: ChatRequest,
        cache: PriceCache = Depends(get_price_cache),
        source: MarketDataSource = Depends(get_market_source),
    ) -> dict:
        try:
            return await handle_chat(payload.message, cache, source)
        except Exception:  # noqa: BLE001 - the assistant must never 500 the user
            logger.exception("Chat request failed")
            return {
                "message": UNAVAILABLE_MESSAGE,
                "actions": [],
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

    @router.get("/history")
    def get_history(limit: int = Query(default=50, ge=1, le=500)) -> dict:
        return chat_history(limit=limit)

    logger.info(
        "Chat router mounted (mode: %s)",
        llm_config.mock_reason() or f"live via {llm_config.litellm_model()}",
    )
    return router
