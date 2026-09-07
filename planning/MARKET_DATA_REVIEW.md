# Market Data Backend — Code Review

**Date:** 2026-09-07
**Scope:** `backend/app/market/` (9 source files, ~360 statements) and `backend/tests/market/` (7 test files, 90 tests)
**Reviewer note:** This is an independent re-review of the completed market data component. A prior review exists at `planning/archive/MARKET_DATA_REVIEW.md` (2026-02-10, 7 issues found); this pass verifies those fixes are actually in place and looks for anything new.

---

## 1. Test Results

**90 tests collected, 90 passed, 0 failed.** Run via `uv run --extra dev pytest -v --cov=app`.

`uv` was not preinstalled in this environment (`pip install --user uv` fixed it) and `uv sync --extra dev` completed cleanly — confirming the previously-flagged `pyproject.toml` build bug (missing `[tool.hatch.build.targets.wheel] packages = ["app"]`) is fixed and the wheel builds correctly.

**Lint (`ruff check app/ tests/`):** All checks passed, no warnings.

**Coverage: 97% overall** (350 statements, 9 missed), matching `MARKET_DATA_SUMMARY.md`'s claim exactly.

| Module | Coverage | Uncovered |
|---|---|---|
| models.py | 100% | |
| cache.py | 100% | |
| interface.py | 100% | |
| factory.py | 100% | |
| seed_prices.py | 100% | |
| simulator.py | 98% | L149 (`_add_ticker_internal` duplicate-add guard), L268-269 (exception path in `_run_loop`) |
| stream.py | 94% | L88-89 (`CancelledError` log line in `_generate_events`) |
| massive_client.py | 94% | L85-87 (`_poll_loop`'s own body — trivially a sleep+call), L125 (one line inside `_fetch_snapshots`, the real API call) |

All uncovered lines are either defensive `except` branches or thin wrappers around code that's exercised indirectly elsewhere. None represent meaningful risk.

---

## 2. Verification of the Prior Review's Findings

The archived review (2026-02-10) listed 7 issues. All are confirmed resolved in the current code:

| # | Issue | Status |
|---|---|---|
| 1 | `pyproject.toml` missing wheel packaging config (blocked `uv sync`) | **Fixed** — `[tool.hatch.build.targets.wheel] packages = ["app"]` present; `uv sync` succeeds |
| 2 | `massive` lazy-imported, breaking test patches when package absent | **Fixed** — `from massive import RESTClient` is now a top-level import in `massive_client.py`; `massive>=1.0.0` is a hard dependency, so it's always present. All 10 `test_massive.py` tests pass |
| 3 | `_generate_events` annotated `-> None` despite being a generator | **Fixed** — now `-> AsyncGenerator[str, None]` |
| 4 | `SimulatorDataSource.get_tickers` reached into `GBMSimulator._tickers` (private) | **Fixed** — `GBMSimulator.get_tickers()` is now a public method; the data source delegates to it |
| 5 | `DEFAULT_CORR` defined but unused, confusing vs. `CROSS_GROUP_CORR` | **Fixed** — `DEFAULT_CORR` no longer exists in `seed_prices.py`; only `CROSS_GROUP_CORR` remains |
| 6 | Unused test imports (`pytest`, `math`, `asyncio`) | **Fixed** — `ruff check` is clean |
| 7 | Massive test mocks targeting wrong names | **Fixed** — all mocks now target real module-level names and pass |

The summary document also claims 4 additional follow-up fixes (SSE endpoint tested, router built per call, `version` read under lock, thread-safety/full-watchlist tests). All four are verified present by inspection:
- `stream.py`'s `create_stream_router()` builds a fresh `APIRouter()` per call (no module-level router).
- `PriceCache.version` acquires `self._lock` before reading `self._version`.
- `test_stream.py` (12 tests) exercises `_generate_events` directly via a stub request.
- `test_cache.py` has a `TestPriceCacheThreadSafety` class with concurrent-writer tests, and `test_simulator.py` has a `TestFullWatchlistCorrelation` class confirming the 10-ticker correlation matrix is positive-definite.

No regressions or half-applied fixes found. This module can be treated as closed.

---

## 3. Architecture Assessment (fresh pass)

The design holds up well on a second read:

- **Strategy pattern is clean.** `MarketDataSource` ABC, two conforming implementations, `PriceCache` as the sole shared mutable state. Nothing downstream needs to know which source is active.
- **`PriceUpdate` is a well-formed value object** — frozen, slotted, computed properties (`change`, `change_percent`, `direction`) rather than stored redundant fields, `to_dict()` for the wire format.
- **GBM math is textbook-correct**: `S(t+dt) = S(t) * exp((mu - σ²/2)dt + σ√dt·Z)`, with `dt` correctly derived from a 500ms tick over a 252-day/6.5h trading year. The Cholesky-correlated shocks are a genuine touch of realism for a course capstone.
- **Both background loops (`_run_loop`, `_poll_loop`) are defensively coded** — broad `except Exception` around the per-tick/per-poll body so one bad iteration can't kill the long-running task, with `asyncio.CancelledError` handled separately for clean shutdown.
- **SSE endpoint is minimal and correct**: version-counter change detection avoids redundant payloads, `retry: 1000` enables browser auto-reconnect, `X-Accel-Buffering: no` pre-empts a real deployment gotcha (nginx buffering silently breaking SSE).

## 4. New Observations (not in the prior review)

> **Update (2026-09-07):** Both observations below have since been addressed —
> see `planning/MARKET_DATA_SUMMARY.md` items 12–13. `MassiveDataSource.add_ticker`
> now fires a targeted single-ticker fetch so a newly-watched ticker is priced
> immediately, and all access to `MassiveDataSource._tickers` is guarded by a
> `threading.Lock` with an immutable snapshot passed into the worker thread.

Nothing rises to "must fix." Two minor, genuinely new observations, both low severity:

### 4.1 `MassiveDataSource.add_ticker` doesn't seed the cache (Low)

`SimulatorDataSource.add_ticker` immediately writes a price into the cache so a newly-added ticker appears instantly. `MassiveDataSource.add_ticker` only appends to `self._tickers` and waits for the next poll cycle — at the default 15s interval (free tier), a user adding a ticker to their watchlist would see no price for up to 15 seconds. This is called out in the method's own log message ("will appear on next poll"), so it's a known and reasonable tradeoff given REST polling constraints, not an oversight — flagging only because the two implementations now behave visibly differently at the `MarketDataSource` interface boundary, which the downstream watchlist UI should account for (e.g., show a loading state for a pending ticker rather than assuming a price is always available right after `add_ticker`).

### 4.2 `MassiveDataSource._tickers` mutated across the thread boundary (Trivial)

`add_ticker`/`remove_ticker` mutate `self._tickers` from the event-loop thread while `_fetch_snapshots` (running inside `asyncio.to_thread`) reads the same list from a worker thread. Under CPython's GIL, `list.append` and list-comprehension reassignment are individually atomic, so this can't corrupt the list — worst case is a poll that includes/excludes a just-added/removed ticker by one cycle. Not worth fixing; noted only for completeness since it's a cross-thread shared-mutable-state pattern that would need a lock on a free-threaded (PEP 703) interpreter.

## 5. Verdict

**Ship it.** The market data backend is correct, well-tested (97% coverage, 90/90 passing), lint-clean, and builds cleanly via `uv sync`. Every issue from the prior review is verifiably fixed, not just claimed-fixed. The two new observations above are informational, not blocking — no action required before building the rest of the platform on top of this module.
