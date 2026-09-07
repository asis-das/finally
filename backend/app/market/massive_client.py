"""Massive (Polygon.io) API client for real market data."""

from __future__ import annotations

import asyncio
import logging
import threading

from massive import RESTClient
from massive.rest.models import SnapshotMarketType

from .cache import PriceCache
from .interface import MarketDataSource

logger = logging.getLogger(__name__)


class MassiveDataSource(MarketDataSource):
    """MarketDataSource backed by the Massive (Polygon.io) REST API.

    Polls GET /v2/snapshot/locale/us/markets/stocks/tickers for all watched
    tickers in a single API call, then writes results to the PriceCache.

    Rate limits:
      - Free tier: 5 req/min → poll every 15s (default)
      - Paid tiers: higher limits → poll every 2-5s
    """

    def __init__(
        self,
        api_key: str,
        price_cache: PriceCache,
        poll_interval: float = 15.0,
    ) -> None:
        self._api_key = api_key
        self._cache = price_cache
        self._interval = poll_interval
        self._tickers: list[str] = []
        # Guards _tickers: mutated from the event-loop thread (add/remove_ticker),
        # read from a worker thread inside asyncio.to_thread (_fetch_snapshots).
        self._tickers_lock = threading.Lock()
        self._task: asyncio.Task | None = None
        self._client: RESTClient | None = None

    async def start(self, tickers: list[str]) -> None:
        self._client = RESTClient(api_key=self._api_key)
        with self._tickers_lock:
            self._tickers = list(tickers)

        # Do an immediate first poll so the cache has data right away
        await self._poll_once()

        self._task = asyncio.create_task(self._poll_loop(), name="massive-poller")
        logger.info(
            "Massive poller started: %d tickers, %.1fs interval",
            len(tickers),
            self._interval,
        )

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._client = None
        logger.info("Massive poller stopped")

    async def add_ticker(self, ticker: str) -> None:
        ticker = ticker.upper().strip()
        with self._tickers_lock:
            if ticker in self._tickers:
                return
            self._tickers = [*self._tickers, ticker]

        if self._client:
            # Seed the cache now with a targeted single-ticker fetch instead of
            # waiting up to `poll_interval` seconds for the next full poll cycle.
            # Fire-and-forget so add_ticker stays non-blocking.
            asyncio.create_task(  # noqa: RUF006
                self._refresh_ticker(ticker), name=f"massive-refresh-{ticker}"
            )
            logger.info("Massive: added ticker %s (fetching now)", ticker)
        else:
            logger.info("Massive: added ticker %s (will appear on next poll)", ticker)

    async def remove_ticker(self, ticker: str) -> None:
        ticker = ticker.upper().strip()
        with self._tickers_lock:
            self._tickers = [t for t in self._tickers if t != ticker]
        self._cache.remove(ticker)
        logger.info("Massive: removed ticker %s", ticker)

    def get_tickers(self) -> list[str]:
        with self._tickers_lock:
            return list(self._tickers)

    # --- Internal ---

    async def _poll_loop(self) -> None:
        """Poll on interval. First poll already happened in start()."""
        while True:
            await asyncio.sleep(self._interval)
            await self._poll_once()

    async def _poll_once(self) -> None:
        """Execute one poll cycle: fetch snapshots for all tickers, update cache."""
        tickers = self.get_tickers()
        if not tickers or not self._client:
            return

        try:
            # The Massive RESTClient is synchronous — run in a thread to
            # avoid blocking the event loop.
            snapshots = await asyncio.to_thread(self._fetch_snapshots, tickers)
            processed = self._apply_snapshots(snapshots)
            logger.debug("Massive poll: updated %d/%d tickers", processed, len(tickers))
        except Exception as e:
            logger.error("Massive poll failed: %s", e)
            # Don't re-raise — the loop will retry on the next interval.
            # Common failures: 401 (bad key), 429 (rate limit), network errors.

    async def _refresh_ticker(self, ticker: str) -> None:
        """Fetch a single ticker immediately (used right after add_ticker)."""
        if not self._client:
            return
        try:
            snapshots = await asyncio.to_thread(self._fetch_snapshots, [ticker])
            self._apply_snapshots(snapshots)
        except Exception as e:
            logger.error("Massive refresh of %s failed: %s", ticker, e)

    def _apply_snapshots(self, snapshots: list) -> int:
        """Write snapshot data to the cache. Returns the count applied."""
        processed = 0
        for snap in snapshots:
            try:
                price = snap.last_trade.price
                # Massive timestamps are Unix milliseconds → convert to seconds
                timestamp = snap.last_trade.timestamp / 1000.0
                self._cache.update(ticker=snap.ticker, price=price, timestamp=timestamp)
                processed += 1
            except (AttributeError, TypeError) as e:
                logger.warning(
                    "Skipping snapshot for %s: %s",
                    getattr(snap, "ticker", "???"),
                    e,
                )
        return processed

    def _fetch_snapshots(self, tickers: list[str]) -> list:
        """Synchronous call to the Massive REST API. Runs in a thread."""
        return self._client.get_snapshot_all(
            market_type=SnapshotMarketType.STOCKS,
            tickers=tickers,
        )
