# Market Data Backend — Summary

**Status:** Complete, tested, reviewed, all issues resolved.

## What Was Built

A complete market data subsystem in `backend/app/market/` (8 modules, ~500 lines) providing live price simulation and real market data via a unified interface.

Design reference: `planning/MARKET_DATA_DESIGN.md`.

### Architecture

```
MarketDataSource (ABC)
├── SimulatorDataSource  →  GBM simulator (default, no API key needed)
└── MassiveDataSource    →  Polygon.io REST poller (when MASSIVE_API_KEY set)
        │
        ▼
   PriceCache (thread-safe, in-memory)
        │
        ├──→ SSE stream endpoint (/api/stream/prices)
        ├──→ Portfolio valuation
        └──→ Trade execution
```

### Modules

| File | Purpose |
|------|---------|
| `models.py` | `PriceUpdate` — immutable frozen dataclass (ticker, price, previous_price, timestamp, change, direction) |
| `interface.py` | `MarketDataSource` — abstract base class defining `start/stop/add_ticker/remove_ticker/get_tickers` |
| `cache.py` | `PriceCache` — thread-safe price store with version counter for SSE change detection |
| `seed_prices.py` | Realistic seed prices, per-ticker GBM params (drift/volatility), correlation groups |
| `simulator.py` | `GBMSimulator` (Geometric Brownian Motion with Cholesky-correlated moves) + `SimulatorDataSource` |
| `massive_client.py` | `MassiveDataSource` — REST polling client for Polygon.io via the `massive` package |
| `factory.py` | `create_market_data_source()` — selects simulator or Massive based on `MASSIVE_API_KEY` env var |
| `stream.py` | `create_stream_router()` — FastAPI SSE endpoint factory using version-based change detection |

### Key Design Decisions

- **Strategy pattern** — both data sources implement the same ABC; downstream code is source-agnostic
- **PriceCache as single point of truth** — producers write, consumers read; no direct coupling
- **GBM with correlated moves** — Cholesky decomposition of sector-based correlation matrix; tech stocks correlate at 0.6, finance at 0.5, cross-sector at 0.3
- **Random shock events** — ~0.1% chance per tick per ticker of a 2-5% move for visual drama
- **SSE over WebSockets** — simpler, one-way push, universal browser support

## Test Suite

**95 tests, all passing.** 7 test modules in `backend/tests/market/`.

| Module | Tests | Coverage |
|--------|-------|----------|
| test_models.py | 11 | models.py: 100% |
| test_cache.py | 15 | cache.py: 100% |
| test_simulator.py | 20 | simulator.py: 98% |
| test_simulator_source.py | 10 | (integration tests) |
| test_factory.py | 7 | factory.py: 100% |
| test_massive.py | 18 | massive_client.py: 94% (API transport mocked) |
| test_stream.py | 12 | stream.py: 94% |

Overall coverage: 97%.

## Code Review & Fixes Applied

A comprehensive code review identified 7 issues. All were resolved:

1. **pyproject.toml build config** — added `[tool.hatch.build.targets.wheel] packages = ["app"]`
2. **Lazy imports removed** — `massive` is a core dependency; imports moved to top level
3. **SSE return type fixed** — `_generate_events` annotated as `AsyncGenerator[str, None]`
4. **Public `get_tickers()`** — added to `GBMSimulator` to avoid private attribute access
5. **Correlation constants cleaned up** — removed unused `DEFAULT_CORR`, consolidated into `CROSS_GROUP_CORR`
6. **Unused test imports removed** — `pytest`, `math`, `asyncio` cleaned from 4 test files
7. **Massive test mocks fixed** — `source._client` set in tests, patches target correct names

A follow-up pass closed the review's remaining "nice to have" items:

8. **SSE endpoint tested** — `test_stream.py` drives `_generate_events` directly with a stub
   request (httpx's `ASGITransport` buffers the whole response, so it cannot test an
   endless stream). `stream.py` coverage 33% → 94%
9. **`stream.py` router built per call** — was a module-level `APIRouter`, which
   double-registered `/prices` if the factory ran twice and made the endpoint untestable
10. **`PriceCache.version` reads under the lock** — consistent with every other accessor,
    and correct on free-threaded Python (PEP 703)
11. **Thread-safety and full-watchlist tests added** — concurrent writers against the cache,
    and a check that the 10-ticker correlation matrix stays positive definite

A second independent re-review (`planning/MARKET_DATA_REVIEW.md`, 2026-09-07) verified
all of the above and raised two low-severity observations, both now resolved:

12. **`MassiveDataSource.add_ticker` seeds the cache immediately** — when the poller is
    running, `add_ticker` now fires a targeted single-ticker snapshot fetch instead of
    leaving the new ticker priceless for up to a full `poll_interval` (15s on the free
    tier). Behaviour now matches `SimulatorDataSource.add_ticker`.
13. **`MassiveDataSource._tickers` no longer shared across the thread boundary** — a
    `threading.Lock` guards every read/write of the ticker list, and `_poll_once` passes
    an immutable snapshot into the `asyncio.to_thread` worker rather than the live list.

**Test suite: 95 tests, all passing. Overall coverage 97%.**

## Demo

A Rich terminal demo is available at `backend/market_data_demo.py`:

```bash
cd backend
uv run market_data_demo.py
```

Displays a live-updating dashboard with all 10 tickers, sparklines, color-coded direction arrows, and an event log for notable price moves. Runs 60 seconds or until Ctrl+C.

## Usage for Downstream Code

```python
from app.market import PriceCache, create_market_data_source

# Startup
cache = PriceCache()
source = create_market_data_source(cache)  # Reads MASSIVE_API_KEY
await source.start(["AAPL", "GOOGL", "MSFT", ...])

# Read prices
update = cache.get("AAPL")          # PriceUpdate or None
price = cache.get_price("AAPL")     # float or None
all_prices = cache.get_all()        # dict[str, PriceUpdate]

# Dynamic watchlist
await source.add_ticker("TSLA")
await source.remove_ticker("GOOGL")

# Shutdown
await source.stop()
```
