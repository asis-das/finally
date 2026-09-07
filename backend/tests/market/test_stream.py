"""Tests for the SSE streaming endpoint.

The SSE response body is an infinite generator, so it is exercised directly
rather than through an ASGI test client (httpx's ASGITransport buffers the
whole response and would never return for a stream that does not end).
"""

import json

import pytest
from fastapi.responses import StreamingResponse

from app.market.cache import PriceCache
from app.market.stream import _generate_events, create_stream_router

TICK = 0.01  # Fast interval so tests don't wait on the 500ms production cadence


class StubRequest:
    """Minimal stand-in for starlette's Request.

    `disconnect_after` controls how many is_disconnected() polls return False
    before the client is reported gone, which is what ends the generator.
    """

    def __init__(self, disconnect_after: int = 1, client_host: str | None = "1.2.3.4"):
        self._remaining = disconnect_after
        self.client = type("Client", (), {"host": client_host})() if client_host else None
        self.poll_count = 0

    async def is_disconnected(self) -> bool:
        self.poll_count += 1
        if self._remaining <= 0:
            return True
        self._remaining -= 1
        return False


async def collect(cache: PriceCache, request: StubRequest) -> list[str]:
    """Drain the SSE generator into a list of raw chunks."""
    return [chunk async for chunk in _generate_events(cache, request, interval=TICK)]


def data_frames(chunks: list[str]) -> list[dict]:
    """Parse the JSON payload out of each `data:` chunk."""
    return [
        json.loads(chunk.removeprefix("data:").strip())
        for chunk in chunks
        if chunk.startswith("data:")
    ]


class TestStreamRouter:
    """The router factory itself."""

    def test_registers_prices_route(self):
        router = create_stream_router(PriceCache())
        assert [route.path for route in router.routes] == ["/api/stream/prices"]

    def test_each_call_builds_a_fresh_router(self):
        """No shared module-level router — two apps never double-register the route."""
        first = create_stream_router(PriceCache())
        second = create_stream_router(PriceCache())
        assert first is not second
        assert len(first.routes) == 1
        assert len(second.routes) == 1

    async def test_endpoint_returns_sse_response_with_headers(self):
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        endpoint = create_stream_router(cache).routes[0].endpoint

        response = await endpoint(StubRequest())

        assert isinstance(response, StreamingResponse)
        assert response.media_type == "text/event-stream"
        assert response.headers["cache-control"] == "no-cache"
        assert response.headers["x-accel-buffering"] == "no"


@pytest.mark.asyncio
class TestGenerateEvents:
    """Behavior of the SSE event generator."""

    async def test_first_chunk_is_retry_directive(self):
        """Sets EventSource's reconnect backoff before anything else."""
        chunks = await collect(PriceCache(), StubRequest(disconnect_after=1))
        assert chunks[0] == "retry: 1000\n\n"

    async def test_emits_all_cached_tickers(self):
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        cache.update("GOOGL", 175.00)

        frames = data_frames(await collect(cache, StubRequest(disconnect_after=1)))

        assert len(frames) == 1
        assert set(frames[0]) == {"AAPL", "GOOGL"}
        assert frames[0]["AAPL"]["price"] == 190.00
        assert frames[0]["GOOGL"]["previous_price"] == 175.00

    async def test_frame_matches_price_update_schema(self):
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        cache.update("AAPL", 191.50)

        entry = data_frames(await collect(cache, StubRequest(disconnect_after=1)))[0]["AAPL"]

        assert set(entry) == {
            "ticker",
            "price",
            "previous_price",
            "timestamp",
            "change",
            "change_percent",
            "direction",
        }
        assert entry["direction"] == "up"
        assert entry["change"] == 1.50

    async def test_chunks_are_sse_framed(self):
        """Every data chunk must terminate with a blank line."""
        cache = PriceCache()
        cache.update("AAPL", 190.00)

        chunks = await collect(cache, StubRequest(disconnect_after=1))

        assert all(chunk.endswith("\n\n") for chunk in chunks)

    async def test_unchanged_prices_produce_no_further_frames(self):
        """Version-based change detection: no writes, no repeat payloads."""
        cache = PriceCache()
        cache.update("AAPL", 190.00)

        frames = data_frames(await collect(cache, StubRequest(disconnect_after=5)))

        assert len(frames) == 1

    async def test_new_write_produces_a_new_frame(self):
        cache = PriceCache()
        cache.update("AAPL", 190.00)

        class WritingRequest(StubRequest):
            """Writes a new price after the first frame has been emitted."""

            async def is_disconnected(self) -> bool:
                if self.poll_count == 1:
                    cache.update("AAPL", 195.00)
                return await super().is_disconnected()

        frames = data_frames(await collect(cache, WritingRequest(disconnect_after=3)))

        assert [f["AAPL"]["price"] for f in frames] == [190.00, 195.00]
        assert frames[1]["AAPL"]["direction"] == "up"

    async def test_empty_cache_sends_no_data_frames(self):
        """Retry directive only — an empty cache must not emit `data: {}`."""
        chunks = await collect(PriceCache(), StubRequest(disconnect_after=3))

        assert chunks == ["retry: 1000\n\n"]

    async def test_stops_when_client_disconnects(self):
        cache = PriceCache()
        cache.update("AAPL", 190.00)
        request = StubRequest(disconnect_after=2)

        await collect(cache, request)

        # Two polls returned False, the third reported the disconnect and ended it
        assert request.poll_count == 3

    async def test_handles_request_without_client(self):
        """request.client is None behind some proxies — must not raise."""
        cache = PriceCache()
        cache.update("AAPL", 190.00)

        frames = data_frames(await collect(cache, StubRequest(disconnect_after=1, client_host=None)))

        assert len(frames) == 1
