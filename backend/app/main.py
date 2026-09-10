"""FastAPI application for FinAlly.

Wiring lives here and nowhere else: the price cache and market data source are
created per application instance and published on ``app.state``, so building a
second app (as the tests do) never touches the first one's state.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import config
from app.api import health_router, portfolio_router, watchlist_router
from app.db import init_db, list_watchlist, record_snapshot
from app.market import PriceCache, create_market_data_source, create_stream_router
from app.services.portfolio import total_portfolio_value
from app.services.reference_prices import ReferencePrices

logger = logging.getLogger(__name__)

SNAPSHOT_INTERVAL_SECONDS = 30.0


def _record_snapshot(price_cache: PriceCache) -> None:
    record_snapshot(total_portfolio_value(price_cache))


async def _snapshot_loop(
    price_cache: PriceCache, interval: float = SNAPSHOT_INTERVAL_SECONDS
) -> None:
    """Record total portfolio value every `interval` seconds, forever."""
    while True:
        try:
            # SQLite writes are blocking; keep them off the event loop.
            await asyncio.to_thread(_record_snapshot, price_cache)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Portfolio snapshot failed")
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db(config.db_path())

    price_cache: PriceCache = app.state.price_cache
    source = create_market_data_source(price_cache)
    await source.start(list_watchlist())
    app.state.market_source = source

    snapshot_task = asyncio.create_task(_snapshot_loop(price_cache), name="portfolio-snapshots")
    app.state.snapshot_task = snapshot_task
    logger.info("FinAlly backend ready (market source: %s)", config.market_source_name())

    try:
        yield
    finally:
        snapshot_task.cancel()
        with suppress(asyncio.CancelledError):
            await snapshot_task
        app.state.snapshot_task = None
        await source.stop()
        app.state.market_source = None


class SPAStaticFiles(StaticFiles):
    """StaticFiles that serves index.html for unknown non-API paths."""

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404 and not path.startswith("api"):
                return await super().get_response("index.html", scope)
            raise


def _mount_static(app: FastAPI) -> None:
    static_dir = config.static_dir()
    if not static_dir.is_dir():
        logger.info("No static directory at %s; serving API only", static_dir)
        return
    # Mounted last so that every /api/* route is matched first.
    app.mount("/", SPAStaticFiles(directory=static_dir, html=True), name="static")
    logger.info("Serving frontend from %s", static_dir)


def create_app() -> FastAPI:
    config.load_env()

    app = FastAPI(title="FinAlly", lifespan=lifespan)
    # Created here rather than in the lifespan so the SSE router can capture it.
    price_cache = PriceCache()
    app.state.price_cache = price_cache
    app.state.reference_prices = ReferencePrices()
    app.state.market_source = None
    app.state.snapshot_task = None

    if config.dev_cors_enabled():
        logger.info("DEV_CORS enabled for %s", config.DEV_CORS_ORIGINS)
        app.add_middleware(
            CORSMiddleware,
            allow_origins=config.DEV_CORS_ORIGINS,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    app.include_router(create_stream_router(price_cache))
    app.include_router(health_router)
    app.include_router(portfolio_router)
    app.include_router(watchlist_router)

    try:
        from app.api.chat import create_chat_router
    except ImportError:
        logger.warning("app.api.chat is not importable yet; /api/chat is disabled")
    else:
        app.include_router(create_chat_router())

    _mount_static(app)
    return app


app = create_app()
