# Market Data Backend — Detailed Design

Implementation-ready design for the FinAlly market data subsystem: a unified data-source
interface with two interchangeable implementations (GBM simulator and Massive/Polygon REST
poller), a shared in-memory price cache, and an SSE endpoint that streams prices to the
browser.

Everything described here lives under `backend/app/market/`. All code snippets are the
actual shape of the implementation — copy-paste ready.

---

## Table of Contents

1. [Architecture](#1-architecture)
2. [File Structure](#2-file-structure)
3. [Data Model — `models.py`](#3-data-model--modelspy)
4. [Price Cache — `cache.py`](#4-price-cache--cachepy)
5. [Unified Interface — `interface.py`](#5-unified-interface--interfacepy)
6. [Seed Data & Parameters — `seed_prices.py`](#6-seed-data--parameters--seed_pricespy)
7. [Simulator — `simulator.py`](#7-simulator--simulatorpy)
8. [Massive API Client — `massive_client.py`](#8-massive-api-client--massive_clientpy)
9. [Factory — `factory.py`](#9-factory--factorypy)
10. [SSE Streaming — `stream.py`](#10-sse-streaming--streampy)
11. [FastAPI Lifecycle Integration](#11-fastapi-lifecycle-integration)
12. [Watchlist Coordination](#12-watchlist-coordination)
13. [Consumer Examples](#13-consumer-examples)
14. [Testing Strategy](#14-testing-strategy)
15. [Error Handling & Edge Cases](#15-error-handling--edge-cases)
16. [Configuration Summary](#16-configuration-summary)

---

## 1. Architecture

Two producers, one cache, many consumers. The producer is chosen once at startup from an
environment variable; nothing downstream knows or cares which one is running.

```
             MASSIVE_API_KEY set?
                     │
        ┌────────────┴────────────┐
        │ no                      │ yes
        ▼                         ▼
 SimulatorDataSource       MassiveDataSource
 (GBM, 500ms ticks)        (REST poll, 15s)
        │                         │
        └────────────┬────────────┘
                     │  both implement MarketDataSource (ABC)
                     ▼
              PriceCache  (thread-safe, in-memory, versioned)
                     │
      ┌──────────────┼──────────────┬─────────────────┐
      ▼              ▼              ▼                 ▼
 SSE endpoint   Trade exec    Portfolio val.    LLM chat context
 /api/stream/   (fill price)  (mark-to-market)  (prices in prompt)
   prices
```

Design rules that fall out of this shape:

- **Producers push, consumers pull.** A `MarketDataSource` never returns prices to a
  caller; it writes into the `PriceCache` on its own schedule. Consumers read the cache.
  This is what makes the two implementations swappable despite wildly different cadences
  (500 ms vs 15 s).
- **`PriceUpdate` is the only type that crosses the boundary.** Nothing outside
  `app/market/` sees a `numpy` array or a Massive snapshot object.
- **The cache is the single point of truth for "current price."** Trade fills, portfolio
  valuation, and the SSE stream all read the same value, so a trade always executes at the
  price the user saw.

---

## 2. File Structure

```
backend/
  app/
    market/
      __init__.py             # Public API re-exports
      models.py               # PriceUpdate dataclass
      cache.py                # PriceCache (thread-safe, versioned)
      interface.py            # MarketDataSource ABC
      seed_prices.py          # SEED_PRICES, TICKER_PARAMS, correlation constants
      simulator.py            # GBMSimulator + SimulatorDataSource
      massive_client.py       # MassiveDataSource
      factory.py              # create_market_data_source()
      stream.py               # SSE endpoint (FastAPI router factory)
  tests/
    market/                   # One test module per source module
  market_data_demo.py         # Rich terminal demo of the simulator
```

`__init__.py` re-exports the public surface so the rest of the backend imports from
`app.market` and never reaches into submodules:

```python
"""Market data subsystem for FinAlly."""

from .cache import PriceCache
from .factory import create_market_data_source
from .interface import MarketDataSource
from .models import PriceUpdate
from .stream import create_stream_router

__all__ = [
    "PriceUpdate",
    "PriceCache",
    "MarketDataSource",
    "create_market_data_source",
    "create_stream_router",
]
```

---

## 3. Data Model — `models.py`

`PriceUpdate` is immutable (`frozen=True`) so a snapshot handed to a consumer can never be
mutated underneath it, and uses `slots=True` because thousands of these are created per
minute. Derived values (`change`, `change_percent`, `direction`) are properties rather than
stored fields — they can't drift out of sync with `price`/`previous_price`.

```python
"""Data models for market data."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PriceUpdate:
    """Immutable snapshot of a single ticker's price at a point in time."""

    ticker: str
    price: float
    previous_price: float
    timestamp: float = field(default_factory=time.time)  # Unix seconds

    @property
    def change(self) -> float:
        """Absolute price change from previous update."""
        return round(self.price - self.previous_price, 4)

    @property
    def change_percent(self) -> float:
        """Percentage change from previous update."""
        if self.previous_price == 0:
            return 0.0
        return round((self.price - self.previous_price) / self.previous_price * 100, 4)

    @property
    def direction(self) -> str:
        """'up', 'down', or 'flat'."""
        if self.price > self.previous_price:
            return "up"
        elif self.price < self.previous_price:
            return "down"
        return "flat"

    def to_dict(self) -> dict:
        """Serialize for JSON / SSE transmission."""
        return {
            "ticker": self.ticker,
            "price": self.price,
            "previous_price": self.previous_price,
            "timestamp": self.timestamp,
            "change": self.change,
            "change_percent": self.change_percent,
            "direction": self.direction,
        }
```

**Example**

```python
>>> u = PriceUpdate(ticker="AAPL", price=191.20, previous_price=190.00)
>>> u.change, u.change_percent, u.direction
(1.2, 0.6316, 'up')
>>> u.to_dict()
{'ticker': 'AAPL', 'price': 191.2, 'previous_price': 190.0,
 'timestamp': 1770000000.0, 'change': 1.2, 'change_percent': 0.6316,
 'direction': 'up'}
```

`direction` is what drives the frontend's green/red flash animation; `previous_price` is
included in the payload so the client can verify the transition without keeping its own
history.

---

## 4. Price Cache — `cache.py`

The cache holds exactly one `PriceUpdate` per ticker — memory is `O(tickers)`, not
`O(ticks)`. Historical series (sparklines, P&L chart) are accumulated by the frontend from
the SSE stream and by the `portfolio_snapshots` table, not here.

Two details matter:

- **`threading.Lock`, not an asyncio lock.** The Massive client runs its blocking REST call
  via `asyncio.to_thread`, so writes genuinely arrive from a worker thread.
- **A monotonic `_version` counter.** The SSE generator compares versions instead of
  diffing dicts, so an idle cache produces zero network traffic.

```python
"""Thread-safe in-memory price cache."""

from __future__ import annotations

import time
from threading import Lock

from .models import PriceUpdate


class PriceCache:
    """Thread-safe in-memory cache of the latest price for each ticker.

    Writers: SimulatorDataSource or MassiveDataSource (one at a time).
    Readers: SSE streaming endpoint, portfolio valuation, trade execution.
    """

    def __init__(self) -> None:
        self._prices: dict[str, PriceUpdate] = {}
        self._lock = Lock()
        self._version: int = 0  # Monotonically increasing; bumped on every update

    def update(self, ticker: str, price: float, timestamp: float | None = None) -> PriceUpdate:
        """Record a new price for a ticker. Returns the created PriceUpdate.

        Automatically computes direction and change from the previous price.
        If this is the first update for the ticker, previous_price == price (direction='flat').
        """
        with self._lock:
            ts = timestamp or time.time()
            prev = self._prices.get(ticker)
            previous_price = prev.price if prev else price

            update = PriceUpdate(
                ticker=ticker,
                price=round(price, 2),
                previous_price=round(previous_price, 2),
                timestamp=ts,
            )
            self._prices[ticker] = update
            self._version += 1
            return update

    def get(self, ticker: str) -> PriceUpdate | None:
        """Get the latest price for a single ticker, or None if unknown."""
        with self._lock:
            return self._prices.get(ticker)

    def get_all(self) -> dict[str, PriceUpdate]:
        """Snapshot of all current prices. Returns a shallow copy."""
        with self._lock:
            return dict(self._prices)

    def get_price(self, ticker: str) -> float | None:
        """Convenience: get just the price float, or None."""
        update = self.get(ticker)
        return update.price if update else None

    def remove(self, ticker: str) -> None:
        """Remove a ticker from the cache (e.g., when removed from watchlist)."""
        with self._lock:
            self._prices.pop(ticker, None)

    @property
    def version(self) -> int:
        """Current version counter. Useful for SSE change detection."""
        with self._lock:
            return self._version

    def __len__(self) -> int:
        with self._lock:
            return len(self._prices)

    def __contains__(self, ticker: str) -> bool:
        with self._lock:
            return ticker in self._prices
```

**Example**

```python
cache = PriceCache()
cache.update("AAPL", 190.00)            # first write → direction 'flat'
u = cache.update("AAPL", 191.25)        # → direction 'up', change 1.25
cache.get_price("AAPL")                 # 191.25
"AAPL" in cache                         # True
len(cache)                              # 1
cache.remove("AAPL")
```

Prices are rounded to 2 decimals **on write**, so every consumer sees the identical value —
there is no way for the displayed price and the fill price to disagree by a fraction of a
cent.

---

## 5. Unified Interface — `interface.py`

The whole point of the subsystem: one contract, two implementations, zero downstream
knowledge of which is live.

```python
"""Abstract interface for market data sources."""

from __future__ import annotations

from abc import ABC, abstractmethod


class MarketDataSource(ABC):
    """Contract for market data providers.

    Implementations push price updates into a shared PriceCache on their own
    schedule. Downstream code never calls the data source directly for prices —
    it reads from the cache.

    Lifecycle:
        source = create_market_data_source(cache)
        await source.start(["AAPL", "GOOGL", ...])
        # ... app runs ...
        await source.add_ticker("TSLA")
        await source.remove_ticker("GOOGL")
        # ... app shutting down ...
        await source.stop()
    """

    @abstractmethod
    async def start(self, tickers: list[str]) -> None:
        """Begin producing price updates for the given tickers.

        Starts a background task that periodically writes to the PriceCache.
        Must be called exactly once. Calling start() twice is undefined behavior.
        """

    @abstractmethod
    async def stop(self) -> None:
        """Stop the background task and release resources.

        Safe to call multiple times. After stop(), the source will not write
        to the cache again.
        """

    @abstractmethod
    async def add_ticker(self, ticker: str) -> None:
        """Add a ticker to the active set. No-op if already present."""

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None:
        """Remove a ticker from the active set. No-op if not present.

        Also removes the ticker from the PriceCache.
        """

    @abstractmethod
    def get_tickers(self) -> list[str]:
        """Return the current list of actively tracked tickers."""
```

### Contract guarantees

| Guarantee | Why it matters |
|---|---|
| `start()` seeds the cache before returning | The first SSE poll after startup already has data — no blank watchlist |
| `stop()` is idempotent | Shutdown paths and tests can call it freely |
| `add_ticker()` is a no-op on duplicates | Watchlist routes don't need to pre-check |
| `remove_ticker()` also evicts from the cache | A removed ticker stops appearing in SSE payloads immediately |
| `get_tickers()` is synchronous | Callable from non-async contexts (health checks, logging) |

The interface deliberately does **not** expose `get_price()`. If it did, consumers would
start calling the source directly and the cache would stop being the single point of truth.

---

## 6. Seed Data & Parameters — `seed_prices.py`

Pure constants, no logic — so the numbers can be tuned without touching simulator code.

```python
"""Seed prices and per-ticker parameters for the market simulator."""

# Realistic starting prices for the default watchlist
SEED_PRICES: dict[str, float] = {
    "AAPL": 190.00,
    "GOOGL": 175.00,
    "MSFT": 420.00,
    "AMZN": 185.00,
    "TSLA": 250.00,
    "NVDA": 800.00,
    "META": 500.00,
    "JPM": 195.00,
    "V": 280.00,
    "NFLX": 600.00,
}

# Per-ticker GBM parameters
# sigma: annualized volatility (higher = more price movement)
# mu: annualized drift / expected return
TICKER_PARAMS: dict[str, dict[str, float]] = {
    "AAPL": {"sigma": 0.22, "mu": 0.05},
    "GOOGL": {"sigma": 0.25, "mu": 0.05},
    "MSFT": {"sigma": 0.20, "mu": 0.05},
    "AMZN": {"sigma": 0.28, "mu": 0.05},
    "TSLA": {"sigma": 0.50, "mu": 0.03},  # High volatility
    "NVDA": {"sigma": 0.40, "mu": 0.08},  # High volatility, strong drift
    "META": {"sigma": 0.30, "mu": 0.05},
    "JPM": {"sigma": 0.18, "mu": 0.04},   # Low volatility (bank)
    "V": {"sigma": 0.17, "mu": 0.04},     # Low volatility (payments)
    "NFLX": {"sigma": 0.35, "mu": 0.05},
}

# Default parameters for tickers not listed above (dynamically added)
DEFAULT_PARAMS: dict[str, float] = {"sigma": 0.25, "mu": 0.05}

# Correlation groups for the simulator's Cholesky decomposition
CORRELATION_GROUPS: dict[str, set[str]] = {
    "tech": {"AAPL", "GOOGL", "MSFT", "AMZN", "META", "NVDA", "NFLX"},
    "finance": {"JPM", "V"},
}

# Correlation coefficients
INTRA_TECH_CORR = 0.6     # Tech stocks move together
INTRA_FINANCE_CORR = 0.5  # Finance stocks move together
CROSS_GROUP_CORR = 0.3    # Between sectors / unknown tickers
TSLA_CORR = 0.3           # TSLA does its own thing
```

Volatilities are chosen to be visibly different on screen: TSLA (`0.50`) should twitch
noticeably more than V (`0.17`) within a minute of watching. NVDA carries the highest drift
(`0.08`) so the portfolio tends to have at least one clear winner.

A ticker not in `SEED_PRICES` (anything the user or the LLM adds) starts at a random price
in `[50, 300]` and uses `DEFAULT_PARAMS`. Note `dict(DEFAULT_PARAMS)` is copied per ticker
so per-ticker tuning can never mutate the shared constant.

---

## 7. Simulator — `simulator.py`

Two classes with a clean split: `GBMSimulator` is pure, synchronous math (fully unit
testable, no asyncio, no cache); `SimulatorDataSource` is the thin async adapter that
implements `MarketDataSource` and pumps results into the cache.

### 7.1 The math

Each tick advances every price by one step of geometric Brownian motion:

```
S(t+dt) = S(t) * exp((mu - sigma^2/2) * dt + sigma * sqrt(dt) * Z)
```

- `mu` — annualized drift, `sigma` — annualized volatility (from `TICKER_PARAMS`)
- `Z` — a standard normal draw, correlated across tickers (below)
- `dt` — 500 ms expressed as a fraction of a trading year:
  `0.5 / (252 * 6.5 * 3600) ≈ 8.48e-8`

Because the update is multiplicative through `exp()`, prices are lognormal and **can never
go negative or hit zero** — no clamping needed.

### 7.2 Correlated moves via Cholesky

Independent random walks look wrong: real tech names move together. Given a correlation
matrix `C`, its Cholesky factor `L` (where `L @ L.T == C`) turns independent normals into
correlated ones:

```
Z_correlated = L @ Z_independent
```

The matrix is built from sector membership: tech pairs at 0.6, finance pairs at 0.5,
everything else (including every TSLA pair) at 0.3. It's rebuilt whenever the ticker set
changes — `O(n²)` construction plus an `O(n³)` factorization, negligible for n < 50 and
done only on watchlist edits, never in the tick loop.

### 7.3 Random shock events

Each ticker has a ~0.1% chance per tick of a 2–5% jump in either direction. At 2 ticks/sec
across 10 tickers that's a visible move roughly every 50 seconds — enough drama to make the
dashboard feel alive without destabilizing the price path.

### 7.4 `GBMSimulator`

```python
"""GBM-based market simulator."""

from __future__ import annotations

import asyncio
import logging
import math
import random

import numpy as np

from .cache import PriceCache
from .interface import MarketDataSource
from .seed_prices import (
    CORRELATION_GROUPS,
    CROSS_GROUP_CORR,
    DEFAULT_PARAMS,
    INTRA_FINANCE_CORR,
    INTRA_TECH_CORR,
    SEED_PRICES,
    TICKER_PARAMS,
    TSLA_CORR,
)

logger = logging.getLogger(__name__)


class GBMSimulator:
    """Geometric Brownian Motion simulator for correlated stock prices.

    Math:
        S(t+dt) = S(t) * exp((mu - sigma^2/2) * dt + sigma * sqrt(dt) * Z)
    """

    # 252 trading days * 6.5 hours/day * 3600 seconds/hour = 5,896,800 seconds
    TRADING_SECONDS_PER_YEAR = 252 * 6.5 * 3600
    DEFAULT_DT = 0.5 / TRADING_SECONDS_PER_YEAR  # ~8.48e-8

    def __init__(
        self,
        tickers: list[str],
        dt: float = DEFAULT_DT,
        event_probability: float = 0.001,
    ) -> None:
        self._dt = dt
        self._event_prob = event_probability

        self._tickers: list[str] = []
        self._prices: dict[str, float] = {}
        self._params: dict[str, dict[str, float]] = {}
        self._cholesky: np.ndarray | None = None

        for ticker in tickers:
            self._add_ticker_internal(ticker)
        self._rebuild_cholesky()

    # --- Public API ---

    def step(self) -> dict[str, float]:
        """Advance all tickers by one time step. Returns {ticker: new_price}.

        This is the hot path — called every 500ms. Keep it fast.
        """
        n = len(self._tickers)
        if n == 0:
            return {}

        z_independent = np.random.standard_normal(n)
        if self._cholesky is not None:
            z_correlated = self._cholesky @ z_independent
        else:
            z_correlated = z_independent

        result: dict[str, float] = {}
        for i, ticker in enumerate(self._tickers):
            params = self._params[ticker]
            mu = params["mu"]
            sigma = params["sigma"]

            drift = (mu - 0.5 * sigma**2) * self._dt
            diffusion = sigma * math.sqrt(self._dt) * z_correlated[i]
            self._prices[ticker] *= math.exp(drift + diffusion)

            # Random event: ~0.1% chance per tick per ticker
            if random.random() < self._event_prob:
                shock_magnitude = random.uniform(0.02, 0.05)
                shock_sign = random.choice([-1, 1])
                self._prices[ticker] *= 1 + shock_magnitude * shock_sign
                logger.debug(
                    "Random event on %s: %.1f%% %s",
                    ticker,
                    shock_magnitude * 100,
                    "up" if shock_sign > 0 else "down",
                )

            result[ticker] = round(self._prices[ticker], 2)

        return result

    def add_ticker(self, ticker: str) -> None:
        """Add a ticker to the simulation. Rebuilds the correlation matrix."""
        if ticker in self._prices:
            return
        self._add_ticker_internal(ticker)
        self._rebuild_cholesky()

    def remove_ticker(self, ticker: str) -> None:
        """Remove a ticker from the simulation. Rebuilds the correlation matrix."""
        if ticker not in self._prices:
            return
        self._tickers.remove(ticker)
        del self._prices[ticker]
        del self._params[ticker]
        self._rebuild_cholesky()

    def get_price(self, ticker: str) -> float | None:
        """Current price for a ticker, or None if not tracked."""
        return self._prices.get(ticker)

    def get_tickers(self) -> list[str]:
        """Return the list of currently tracked tickers."""
        return list(self._tickers)

    # --- Internals ---

    def _add_ticker_internal(self, ticker: str) -> None:
        """Add a ticker without rebuilding Cholesky (for batch initialization)."""
        if ticker in self._prices:
            return
        self._tickers.append(ticker)
        self._prices[ticker] = SEED_PRICES.get(ticker, random.uniform(50.0, 300.0))
        self._params[ticker] = TICKER_PARAMS.get(ticker, dict(DEFAULT_PARAMS))

    def _rebuild_cholesky(self) -> None:
        """Rebuild the Cholesky decomposition of the ticker correlation matrix.

        Called whenever tickers are added or removed. O(n^2) but n < 50.
        """
        n = len(self._tickers)
        if n <= 1:
            self._cholesky = None
            return

        corr = np.eye(n)
        for i in range(n):
            for j in range(i + 1, n):
                rho = self._pairwise_correlation(self._tickers[i], self._tickers[j])
                corr[i, j] = rho
                corr[j, i] = rho

        self._cholesky = np.linalg.cholesky(corr)

    @staticmethod
    def _pairwise_correlation(t1: str, t2: str) -> float:
        """Correlation between two tickers based on sector grouping.

          - Same tech sector:    0.6
          - Same finance sector: 0.5
          - TSLA with anything:  0.3 (it does its own thing)
          - Cross-sector:        0.3
          - Unknown tickers:     0.3
        """
        tech = CORRELATION_GROUPS["tech"]
        finance = CORRELATION_GROUPS["finance"]

        # TSLA is in the tech set but behaves independently — check first
        if t1 == "TSLA" or t2 == "TSLA":
            return TSLA_CORR

        if t1 in tech and t2 in tech:
            return INTRA_TECH_CORR
        if t1 in finance and t2 in finance:
            return INTRA_FINANCE_CORR

        return CROSS_GROUP_CORR
```

The correlation matrix must be positive semi-definite or `np.linalg.cholesky` raises.
The structure here — a small set of correlations, all in `[0.3, 0.6]`, with a unit diagonal
— is comfortably PSD. If the sector scheme is ever extended with higher or mixed-sign
correlations, add a nearest-PSD repair step before factorizing.

**Example — using the simulator standalone**

```python
sim = GBMSimulator(tickers=["AAPL", "GOOGL", "TSLA"])
sim.get_price("AAPL")        # 190.0 — the seed, before any step
for _ in range(10):
    prices = sim.step()
prices                        # {'AAPL': 190.02, 'GOOGL': 174.98, 'TSLA': 250.11}
sim.add_ticker("PYPL")        # random seed in [50, 300], Cholesky rebuilt
sim.remove_ticker("GOOGL")
sim.get_tickers()             # ['AAPL', 'TSLA', 'PYPL']
```

### 7.5 `SimulatorDataSource`

```python
class SimulatorDataSource(MarketDataSource):
    """MarketDataSource backed by the GBM simulator.

    Runs a background asyncio task that calls GBMSimulator.step() every
    `update_interval` seconds and writes results to the PriceCache.
    """

    def __init__(
        self,
        price_cache: PriceCache,
        update_interval: float = 0.5,
        event_probability: float = 0.001,
    ) -> None:
        self._cache = price_cache
        self._interval = update_interval
        self._event_prob = event_probability
        self._sim: GBMSimulator | None = None
        self._task: asyncio.Task | None = None

    async def start(self, tickers: list[str]) -> None:
        self._sim = GBMSimulator(
            tickers=tickers,
            event_probability=self._event_prob,
        )
        # Seed the cache with initial prices so SSE has data immediately
        for ticker in tickers:
            price = self._sim.get_price(ticker)
            if price is not None:
                self._cache.update(ticker=ticker, price=price)
        self._task = asyncio.create_task(self._run_loop(), name="simulator-loop")
        logger.info("Simulator started with %d tickers", len(tickers))

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("Simulator stopped")

    async def add_ticker(self, ticker: str) -> None:
        if self._sim:
            self._sim.add_ticker(ticker)
            # Seed cache immediately so the ticker has a price right away
            price = self._sim.get_price(ticker)
            if price is not None:
                self._cache.update(ticker=ticker, price=price)
            logger.info("Simulator: added ticker %s", ticker)

    async def remove_ticker(self, ticker: str) -> None:
        if self._sim:
            self._sim.remove_ticker(ticker)
        self._cache.remove(ticker)
        logger.info("Simulator: removed ticker %s", ticker)

    def get_tickers(self) -> list[str]:
        return self._sim.get_tickers() if self._sim else []

    async def _run_loop(self) -> None:
        """Core loop: step the simulation, write to cache, sleep."""
        while True:
            try:
                if self._sim:
                    prices = self._sim.step()
                    for ticker, price in prices.items():
                        self._cache.update(ticker=ticker, price=price)
            except Exception:
                logger.exception("Simulator step failed")
            await asyncio.sleep(self._interval)
```

Three deliberate behaviors:

1. **`start()` seeds the cache before creating the task** — the first SSE frame after page
   load already shows all ten tickers at their seed prices.
2. **The loop swallows exceptions and keeps going.** A background task that dies silently
   would freeze the whole dashboard; a logged exception and a retry 500 ms later will not.
   Note `await asyncio.sleep()` sits outside the `try`, so cancellation still propagates.
3. **`stop()` awaits the cancelled task** and absorbs `CancelledError`, so shutdown is
   clean and calling it twice is harmless.

---

## 8. Massive API Client — `massive_client.py`

When `MASSIVE_API_KEY` is set, real quotes replace the simulator. The critical constraint
is the free tier's **5 requests/minute** — so the poller fetches every watched ticker in a
*single* snapshot call and defaults to a 15-second interval (4 calls/min, comfortably under
the cap).

### 8.1 API reference

- **Base URL**: `https://api.massive.com` (legacy `https://api.polygon.io` still works)
- **Package**: `massive` (`uv add massive`), auth via `Authorization: Bearer <key>`, handled
  by the client
- **Primary endpoint**: `GET /v2/snapshot/locale/us/markets/stocks/tickers?tickers=AAPL,GOOGL,...`

| Tier | Rate limit | Recommended poll interval |
|---|---|---|
| Free | 5 req/min | 15 s |
| Paid | effectively unlimited | 2–5 s |

Response fields FinAlly consumes, per ticker:

```json
{
  "ticker": "AAPL",
  "day": { "open": 129.61, "high": 130.15, "low": 125.07, "close": 125.07,
           "previous_close": 129.61, "change": -4.54, "change_percent": -3.50 },
  "last_trade": { "price": 125.07, "size": 100, "timestamp": 1675190399000 },
  "last_quote": { "bid_price": 125.06, "ask_price": 125.08 }
}
```

Only `ticker`, `last_trade.price`, and `last_trade.timestamp` are required. Timestamps are
**Unix milliseconds** and must be divided by 1000 to match `PriceUpdate.timestamp`
(seconds), which is what the frontend and the simulator both assume.

### 8.2 Implementation

```python
"""Massive (Polygon.io) API client for real market data."""

from __future__ import annotations

import asyncio
import logging

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
        self._task: asyncio.Task | None = None
        self._client: RESTClient | None = None

    async def start(self, tickers: list[str]) -> None:
        self._client = RESTClient(api_key=self._api_key)
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
        if ticker not in self._tickers:
            self._tickers.append(ticker)
            logger.info("Massive: added ticker %s (will appear on next poll)", ticker)

    async def remove_ticker(self, ticker: str) -> None:
        ticker = ticker.upper().strip()
        self._tickers = [t for t in self._tickers if t != ticker]
        self._cache.remove(ticker)
        logger.info("Massive: removed ticker %s", ticker)

    def get_tickers(self) -> list[str]:
        return list(self._tickers)

    # --- Internal ---

    async def _poll_loop(self) -> None:
        """Poll on interval. First poll already happened in start()."""
        while True:
            await asyncio.sleep(self._interval)
            await self._poll_once()

    async def _poll_once(self) -> None:
        """Execute one poll cycle: fetch snapshots, update cache."""
        if not self._tickers or not self._client:
            return

        try:
            # The Massive RESTClient is synchronous — run in a thread to
            # avoid blocking the event loop.
            snapshots = await asyncio.to_thread(self._fetch_snapshots)
            processed = 0
            for snap in snapshots:
                try:
                    price = snap.last_trade.price
                    # Massive timestamps are Unix milliseconds → convert to seconds
                    timestamp = snap.last_trade.timestamp / 1000.0
                    self._cache.update(
                        ticker=snap.ticker,
                        price=price,
                        timestamp=timestamp,
                    )
                    processed += 1
                except (AttributeError, TypeError) as e:
                    logger.warning(
                        "Skipping snapshot for %s: %s",
                        getattr(snap, "ticker", "???"),
                        e,
                    )
            logger.debug("Massive poll: updated %d/%d tickers", processed, len(self._tickers))

        except Exception as e:
            logger.error("Massive poll failed: %s", e)
            # Don't re-raise — the loop will retry on the next interval.
            # Common failures: 401 (bad key), 429 (rate limit), network errors.

    def _fetch_snapshots(self) -> list:
        """Synchronous call to the Massive REST API. Runs in a thread."""
        return self._client.get_snapshot_all(
            market_type=SnapshotMarketType.STOCKS,
            tickers=self._tickers,
        )
```

Key points:

- **`asyncio.to_thread` for the blocking call.** `RESTClient` is synchronous; calling it on
  the event loop would stall every SSE connection for the duration of the HTTP round trip.
- **Two nested try/excepts, on purpose.** The inner one skips a single malformed snapshot
  (a ticker with no recent trade, a delisted symbol) without losing the other nine; the
  outer one keeps the poll loop alive across auth, rate-limit, and network failures.
- **Ticker normalization on the way in** (`upper().strip()`) — the API is case sensitive
  and the LLM is not reliably uppercase.
- **Stale prices persist rather than disappear.** If a poll fails, the cache keeps the last
  known price. A price that stops moving is far better UX than a watchlist row that empties.

### 8.3 Other endpoints (available, not currently polled)

```python
# One ticker in detail — for the ticker detail panel
snapshot = client.get_snapshot_ticker(market_type=SnapshotMarketType.STOCKS, ticker="AAPL")
snapshot.last_quote.bid_price, snapshot.last_quote.ask_price

# Previous close — useful for day-change baselines
for agg in client.get_previous_close_agg(ticker="AAPL"):
    print(agg.close)

# Historical bars — if the main chart ever needs pre-session history
for bar in client.list_aggs(ticker="AAPL", multiplier=1, timespan="day",
                            from_="2026-01-01", to="2026-01-31", limit=50000):
    print(bar.timestamp, bar.open, bar.high, bar.low, bar.close, bar.volume)
```

---

## 9. Factory — `factory.py`

One environment variable decides the implementation. Everything else in the backend is
written against the ABC and never branches on the source.

```python
"""Factory for creating market data sources."""

from __future__ import annotations

import logging
import os

from .cache import PriceCache
from .interface import MarketDataSource
from .massive_client import MassiveDataSource
from .simulator import SimulatorDataSource

logger = logging.getLogger(__name__)


def create_market_data_source(price_cache: PriceCache) -> MarketDataSource:
    """Create the appropriate market data source based on environment variables.

    - MASSIVE_API_KEY set and non-empty → MassiveDataSource (real market data)
    - Otherwise → SimulatorDataSource (GBM simulation)

    Returns an unstarted source. Caller must await source.start(tickers).
    """
    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()

    if api_key:
        logger.info("Market data source: Massive API (real data)")
        return MassiveDataSource(api_key=api_key, price_cache=price_cache)
    else:
        logger.info("Market data source: GBM Simulator")
        return SimulatorDataSource(price_cache=price_cache)
```

`.strip()` matters: `MASSIVE_API_KEY=` and `MASSIVE_API_KEY="   "` in a `.env` file both
mean "no key," and both correctly fall through to the simulator. The factory returns an
**unstarted** source — construction is synchronous and side-effect free, so it's trivially
testable; `start()` is where background work begins.

`massive` is a declared core dependency and is imported at module level (not lazily), which
keeps `unittest.mock.patch("app.market.massive_client.RESTClient")` working in tests.

---

## 10. SSE Streaming — `stream.py`

One long-lived `text/event-stream` response per client, driven by the cache's version
counter.

```python
"""SSE streaming endpoint for live price updates."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .cache import PriceCache

logger = logging.getLogger(__name__)


def create_stream_router(price_cache: PriceCache) -> APIRouter:
    """Create the SSE streaming router with a reference to the price cache.

    This factory pattern lets us inject the PriceCache without globals.

    A fresh APIRouter is built per call so that creating more than one app
    (as tests do) never double-registers the /prices route.
    """
    router = APIRouter(prefix="/api/stream", tags=["streaming"])

    @router.get("/prices")
    async def stream_prices(request: Request) -> StreamingResponse:
        """SSE endpoint for live price updates."""
        return StreamingResponse(
            _generate_events(price_cache, request),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",  # Disable nginx buffering if proxied
            },
        )

    return router


async def _generate_events(
    price_cache: PriceCache,
    request: Request,
    interval: float = 0.5,
) -> AsyncGenerator[str, None]:
    """Async generator that yields SSE-formatted price events.

    Sends all prices every `interval` seconds when they have changed. Stops
    when the client disconnects.
    """
    # Tell the client to retry after 1 second if the connection drops
    yield "retry: 1000\n\n"

    last_version = -1
    client_ip = request.client.host if request.client else "unknown"
    logger.info("SSE client connected: %s", client_ip)

    try:
        while True:
            if await request.is_disconnected():
                logger.info("SSE client disconnected: %s", client_ip)
                break

            current_version = price_cache.version
            if current_version != last_version:
                last_version = current_version
                prices = price_cache.get_all()

                if prices:
                    data = {ticker: update.to_dict() for ticker, update in prices.items()}
                    payload = json.dumps(data)
                    yield f"data: {payload}\n\n"

            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logger.info("SSE stream cancelled for: %s", client_ip)
```

### Wire format

```
retry: 1000

data: {"AAPL":{"ticker":"AAPL","price":190.52,"previous_price":190.48,"timestamp":1770000000.12,"change":0.04,"change_percent":0.021,"direction":"up"}, "GOOGL":{...}}

data: {"AAPL":{...},"GOOGL":{...}}
```

Every frame carries the **full snapshot** of all tracked tickers, not a delta. At ten
tickers that's roughly 1.5 KB every 500 ms — trivial — and it means a reconnecting client
is fully caught up on its first frame, with no resync protocol to get wrong.

Design notes:

- **`retry: 1000` first.** Sets `EventSource`'s reconnect backoff to 1 s; browser handles
  reconnection with no client code.
- **Version check before serializing.** If no producer wrote since the last frame,
  `json.dumps` never runs and nothing is sent — an idle stream costs nothing.
- **`request.is_disconnected()` each iteration.** Without it, a closed tab leaves the
  generator looping until the next write fails.
- **`X-Accel-Buffering: no`.** Prevents nginx (or any proxy inserted later) from buffering
  the stream into uselessness.

### Client usage

```javascript
const source = new EventSource("/api/stream/prices");

source.onmessage = (event) => {
  const prices = JSON.parse(event.data);          // { AAPL: {...}, GOOGL: {...} }
  for (const [ticker, update] of Object.entries(prices)) {
    applyPrice(ticker, update.price, update.direction);  // flash green/red
    pushSparklinePoint(ticker, update.price);
  }
  setConnectionStatus("connected");
};

source.onerror = () => setConnectionStatus("reconnecting");  // EventSource auto-retries
```

---

## 11. FastAPI Lifecycle Integration

The cache and the data source live for the lifetime of the app, created in the `lifespan`
context manager and stashed on `app.state`.

**In `backend/app/main.py`:**

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from app.market import PriceCache, create_market_data_source, create_stream_router
from app.market.interface import MarketDataSource


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage startup and shutdown of background services."""

    # --- STARTUP ---

    # 1. Shared price cache
    price_cache = PriceCache()
    app.state.price_cache = price_cache

    # 2. Market data source (simulator or Massive, per MASSIVE_API_KEY)
    source = create_market_data_source(price_cache)
    app.state.market_source = source

    # 3. Initial tickers = watchlist ∪ tickers with open positions
    initial_tickers = await load_tracked_tickers()   # reads SQLite, see §12
    await source.start(initial_tickers)

    yield  # --- App is running ---

    # --- SHUTDOWN ---
    await source.stop()


app = FastAPI(title="FinAlly", lifespan=lifespan)

# The SSE router needs the cache, but the cache is only created in lifespan.
# Register the router at import time with a lazy cache lookup, or include it
# inside lifespan before yield — either works; the latter is simpler:
#   app.include_router(create_stream_router(price_cache))


# --- Dependencies for other routers ---

def get_price_cache(request: Request) -> PriceCache:
    return request.app.state.price_cache


def get_market_source(request: Request) -> MarketDataSource:
    return request.app.state.market_source
```

Reading the cache off `request.app.state` (rather than closing over a module-level global)
keeps the app importable in tests without any background task running.

`create_stream_router()` builds a fresh `APIRouter` on every call, so constructing more
than one app in a single process (as the test suite does) is safe — the `/prices` route is
never registered twice.

---

## 12. Watchlist Coordination

The set of tracked tickers is the union of the watchlist and any ticker with an open
position — a user can sell a name off their watchlist while still holding shares, and
portfolio valuation must not go blind.

```python
async def load_tracked_tickers() -> list[str]:
    """Union of watchlist tickers and tickers with open positions."""
    watchlist = await db.get_watchlist_tickers()          # ['AAPL', 'GOOGL', ...]
    held = await db.get_position_tickers()                # ['TSLA', ...]
    return sorted(set(watchlist) | set(held))
```

### Adding a ticker

```
User (or LLM) → POST /api/watchlist {"ticker": "PYPL"}
  → INSERT into watchlist (SQLite)
  → await source.add_ticker("PYPL")
       Simulator: seeds a price, rebuilds Cholesky, writes to cache immediately
       Massive:   appends to poll list, appears on the next poll (≤15s)
  → 200 {"ticker": "PYPL", "price": <from cache, may be null under Massive>}
```

```python
@router.post("/watchlist")
async def add_to_watchlist(
    payload: WatchlistAdd,
    source: MarketDataSource = Depends(get_market_source),
    price_cache: PriceCache = Depends(get_price_cache),
):
    ticker = payload.ticker.upper().strip()
    await db.add_watchlist_entry(ticker)
    await source.add_ticker(ticker)
    return {"ticker": ticker, "price": price_cache.get_price(ticker)}
```

The simulator has a price within microseconds; Massive needs up to one poll interval. The
frontend must tolerate `price: null` on a freshly added ticker and fill it in from the next
SSE frame.

### Removing a ticker

```python
@router.delete("/watchlist/{ticker}")
async def remove_from_watchlist(
    ticker: str,
    source: MarketDataSource = Depends(get_market_source),
):
    ticker = ticker.upper().strip()
    await db.delete_watchlist_entry(ticker)

    # Keep tracking if the user still holds shares — portfolio valuation needs the price
    position = await db.get_position(ticker)
    if position is None or position.quantity == 0:
        await source.remove_ticker(ticker)

    return {"status": "ok", "ticker": ticker}
```

### Buying a ticker that isn't tracked

A trade on an untracked symbol must add it to the source first, or the position will have
no mark:

```python
if price_cache.get_price(ticker) is None:
    await source.add_ticker(ticker)
    # Simulator: price is available immediately.
    # Massive: reject the trade until the next poll supplies a price —
    # never fill at a made-up number.
```

---

## 13. Consumer Examples

### Trade execution — fill at the cached price

```python
@router.post("/portfolio/trade")
async def execute_trade(
    trade: TradeRequest,
    price_cache: PriceCache = Depends(get_price_cache),
):
    price = price_cache.get_price(trade.ticker)
    if price is None:
        raise HTTPException(404, f"No price available for {trade.ticker}")

    # Market order, instant fill, no fees — the price the user saw is the price they get
    return await portfolio.execute(trade.ticker, trade.side, trade.quantity, price)
```

### Portfolio valuation — mark to market

```python
def value_portfolio(positions: list[Position], cash: float, cache: PriceCache) -> dict:
    prices = cache.get_all()          # one consistent snapshot for the whole calculation
    holdings = 0.0
    rows = []
    for p in positions:
        update = prices.get(p.ticker)
        current = update.price if update else p.avg_cost   # fall back to cost basis
        market_value = current * p.quantity
        holdings += market_value
        rows.append({
            "ticker": p.ticker,
            "quantity": p.quantity,
            "avg_cost": p.avg_cost,
            "current_price": current,
            "market_value": market_value,
            "unrealized_pnl": (current - p.avg_cost) * p.quantity,
            "pnl_percent": (current / p.avg_cost - 1) * 100 if p.avg_cost else 0.0,
        })
    return {"positions": rows, "cash": cash, "total_value": cash + holdings}
```

Taking a single `get_all()` snapshot — rather than calling `get_price()` in the loop —
guarantees every row is valued at the same instant, so the totals always add up.

### Watchlist endpoint — tickers with live prices

```python
@router.get("/watchlist")
async def get_watchlist(price_cache: PriceCache = Depends(get_price_cache)):
    tickers = await db.get_watchlist_tickers()
    prices = price_cache.get_all()
    return [
        {"ticker": t, **(prices[t].to_dict() if t in prices else {"price": None})}
        for t in tickers
    ]
```

### Portfolio snapshot task — feeding the P&L chart

```python
async def snapshot_loop(cache: PriceCache, interval: float = 30.0) -> None:
    """Record total portfolio value every 30s for the P&L chart."""
    while True:
        try:
            total = (await compute_portfolio(cache))["total_value"]
            await db.insert_portfolio_snapshot(total_value=total)
        except Exception:
            logger.exception("Portfolio snapshot failed")
        await asyncio.sleep(interval)
```

Same defensive shape as the producer loops: log and continue, never let the task die.

---

## 14. Testing Strategy

Test layout mirrors the source layout — `backend/tests/market/`, one module per unit.
`pytest.ini_options` sets `asyncio_mode = "auto"`, so async tests need no decorator
boilerplate.

| Module | Focus |
|---|---|
| `test_models.py` | `change` / `change_percent` / `direction` / `to_dict`, zero-price guard, frozen-ness |
| `test_cache.py` | Update/get/remove, first-write-is-flat, version increments, rounding, `__len__`/`__contains__` |
| `test_simulator.py` | GBM math, positivity, seeds, add/remove, Cholesky rebuild, correlation lookup |
| `test_simulator_source.py` | Async lifecycle: start seeds cache, loop writes, stop cancels, add/remove |
| `test_massive.py` | Poll parsing with a mocked `RESTClient` — ms→s conversion, malformed snapshots, failure resilience |
| `test_factory.py` | Env-var branching, including empty and whitespace-only keys |
| `test_stream.py` | Router factory isolation; the SSE generator's retry directive, payload schema, version gating, disconnect handling |

### Simulator math

```python
def test_prices_are_always_positive():
    """GBM is multiplicative through exp() — price can never reach zero."""
    sim = GBMSimulator(tickers=["AAPL"])
    for _ in range(10_000):
        assert sim.step()["AAPL"] > 0


def test_initial_price_matches_seed():
    sim = GBMSimulator(tickers=["AAPL"])
    assert sim.get_price("AAPL") == SEED_PRICES["AAPL"]


def test_unknown_ticker_gets_random_seed_in_range():
    sim = GBMSimulator(tickers=["ZZZZ"])
    assert 50.0 <= sim.get_price("ZZZZ") <= 300.0


def test_cholesky_built_for_full_default_watchlist():
    """The 10-ticker correlation matrix must be positive semi-definite."""
    sim = GBMSimulator(tickers=list(SEED_PRICES))
    assert sim._cholesky is not None
    assert sim._cholesky.shape == (10, 10)


def test_no_shock_when_probability_zero():
    """With event_probability=0, moves stay tiny — dt is ~8.5e-8."""
    sim = GBMSimulator(tickers=["AAPL"], event_probability=0.0)
    start = sim.get_price("AAPL")
    for _ in range(100):
        sim.step()
    assert abs(sim.get_price("AAPL") - start) / start < 0.01
```

### Cache

```python
def test_first_update_is_flat():
    cache = PriceCache()
    u = cache.update("AAPL", 190.50)
    assert u.direction == "flat" and u.previous_price == 190.50


def test_version_increments_on_every_write():
    cache = PriceCache()
    v0 = cache.version
    cache.update("AAPL", 190.0)
    cache.update("AAPL", 191.0)
    assert cache.version == v0 + 2


def test_concurrent_writes_are_safe():
    """Two threads hammering the cache must not lose or corrupt updates."""
    cache = PriceCache()
    def writer(t):
        for i in range(1000):
            cache.update(t, 100.0 + i * 0.01)
    threads = [Thread(target=writer, args=(t,)) for t in ("AAPL", "GOOGL")]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert cache.version == 2000 and len(cache) == 2
```

### Simulator data source (async)

```python
async def test_start_seeds_cache_immediately():
    cache = PriceCache()
    source = SimulatorDataSource(price_cache=cache, update_interval=0.01)
    await source.start(["AAPL", "GOOGL"])
    try:
        assert cache.get_price("AAPL") == SEED_PRICES["AAPL"]
    finally:
        await source.stop()


async def test_loop_writes_updates():
    cache = PriceCache()
    source = SimulatorDataSource(price_cache=cache, update_interval=0.01)
    await source.start(["AAPL"])
    v0 = cache.version
    await asyncio.sleep(0.05)
    await source.stop()
    assert cache.version > v0


async def test_stop_is_idempotent():
    source = SimulatorDataSource(price_cache=PriceCache())
    await source.start(["AAPL"])
    await source.stop()
    await source.stop()   # must not raise
```

### Massive client — mock the transport, never the network

`_client` is set directly on the instance so no real `RESTClient` is constructed and no HTTP
call is ever made:

```python
def _make_snapshot(ticker: str, price: float, timestamp_ms: int) -> MagicMock:
    snap = MagicMock()
    snap.ticker = ticker
    snap.last_trade = MagicMock()
    snap.last_trade.price = price
    snap.last_trade.timestamp = timestamp_ms
    return snap


async def test_timestamp_converted_from_milliseconds():
    cache = PriceCache()
    source = MassiveDataSource(api_key="test-key", price_cache=cache)
    source._client = MagicMock()
    source._tickers = ["AAPL"]
    source._fetch_snapshots = MagicMock(
        return_value=[_make_snapshot("AAPL", 190.5, 1675190399000)]
    )
    await source._poll_once()
    assert cache.get("AAPL").timestamp == 1675190399.0


async def test_malformed_snapshot_is_skipped_others_survive():
    cache = PriceCache()
    source = MassiveDataSource(api_key="test-key", price_cache=cache)
    source._client = MagicMock()
    source._tickers = ["AAPL", "GOOGL"]
    bad = MagicMock(); bad.ticker = "AAPL"; bad.last_trade = None
    source._fetch_snapshots = MagicMock(
        return_value=[bad, _make_snapshot("GOOGL", 175.0, 1675190399000)]
    )
    await source._poll_once()
    assert cache.get("AAPL") is None
    assert cache.get_price("GOOGL") == 175.0


async def test_poll_failure_does_not_raise():
    """An API error must be logged and swallowed so the loop survives."""
    cache = PriceCache()
    source = MassiveDataSource(api_key="test-key", price_cache=cache)
    source._client = MagicMock()
    source._tickers = ["AAPL"]
    source._fetch_snapshots = MagicMock(side_effect=RuntimeError("429 rate limited"))
    await source._poll_once()   # must not raise
```

### Factory

```python
def test_no_key_selects_simulator(monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)
    assert isinstance(create_market_data_source(PriceCache()), SimulatorDataSource)


def test_whitespace_key_selects_simulator(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", "   ")
    assert isinstance(create_market_data_source(PriceCache()), SimulatorDataSource)


def test_key_selects_massive(monkeypatch):
    monkeypatch.setenv("MASSIVE_API_KEY", "abc123")
    assert isinstance(create_market_data_source(PriceCache()), MassiveDataSource)
```

### SSE generator

The response body is an infinite generator, so it is exercised directly rather than through
an ASGI test client — httpx's `ASGITransport` buffers the entire response and would never
return for a stream that does not end. A stub request drives the disconnect check, which is
what terminates the loop:

```python
class StubRequest:
    """Minimal stand-in for starlette's Request."""

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
    return [chunk async for chunk in _generate_events(cache, request, interval=0.01)]


async def test_first_chunk_is_retry_directive():
    chunks = await collect(PriceCache(), StubRequest(disconnect_after=1))
    assert chunks[0] == "retry: 1000\n\n"


async def test_unchanged_prices_produce_no_further_frames():
    """Version-based change detection: no writes, no repeat payloads."""
    cache = PriceCache()
    cache.update("AAPL", 190.00)
    frames = data_frames(await collect(cache, StubRequest(disconnect_after=5)))
    assert len(frames) == 1


async def test_empty_cache_sends_no_data_frames():
    assert await collect(PriceCache(), StubRequest(disconnect_after=3)) == ["retry: 1000\n\n"]


async def test_stops_when_client_disconnects():
    cache = PriceCache()
    cache.update("AAPL", 190.00)
    request = StubRequest(disconnect_after=2)
    await collect(cache, request)
    assert request.poll_count == 3   # two False polls, then the disconnect
```

### Running

```bash
cd backend
uv run pytest                              # full suite
uv run pytest --cov=app --cov-report=term  # with coverage
uv run ruff check .                        # lint
```

Current state: **90 tests, 97% overall coverage.** 100% on `models.py`, `cache.py`,
`interface.py`, `seed_prices.py` and `factory.py`; 98% on `simulator.py`; 94% on
`stream.py` and `massive_client.py` — the residual misses in those two are the outermost
layers (a real HTTP round trip, a live ASGI socket) that mocks deliberately don't reach.

### Manual demo

`backend/market_data_demo.py` runs the simulator behind a Rich live dashboard — ten
tickers, unicode sparklines, direction arrows, and an event log for notable moves:

```bash
cd backend
uv run market_data_demo.py     # 60 seconds, or Ctrl+C
```

Useful for eyeballing whether the volatility parameters feel right before wiring up the
frontend.

---

## 15. Error Handling & Edge Cases

| Situation | Behavior |
|---|---|
| Massive returns 401 (bad key) | Logged per poll; cache holds seed-less/stale data. Prefer failing loudly at startup: the first `_poll_once()` in `start()` surfaces the problem in logs immediately |
| Massive returns 429 (rate limit) | Logged, poll skipped, retried next interval. Raise `poll_interval` if it persists |
| Network error mid-poll | Same path as above — last known prices stay in the cache |
| One snapshot malformed | That ticker is skipped with a warning; the rest of the batch is applied |
| Simulator `step()` raises | Logged with traceback; loop sleeps and retries — the task never dies |
| Ticker with no price yet | `get_price()` returns `None`. Trades must 404 rather than guess a price |
| Ticker removed while streaming | Evicted from the cache; it simply stops appearing in SSE frames |
| Duplicate `add_ticker` | No-op in both implementations |
| `remove_ticker` for unknown symbol | No-op; `cache.remove()` tolerates a missing key |
| Client disconnects from SSE | `request.is_disconnected()` breaks the generator on the next tick |
| Empty ticker list | `step()` returns `{}`; `_poll_once()` returns early. No crash, no traffic |
| Single ticker | `_cholesky` is `None`; uncorrelated draws are used directly |
| Cache read during a write | `threading.Lock` serializes; `get_all()` returns a shallow copy so callers can't be mutated mid-iteration |
| Shutdown with in-flight poll | `stop()` cancels and awaits the task, absorbing `CancelledError` |

Two earlier sharp edges have been closed and are worth recording so they don't come back:

- **`PriceCache.version` now reads under the lock** like every other accessor. An `int`
  read is atomic under CPython's GIL, but the free-threaded build (PEP 703) offers no such
  guarantee, and the inconsistency was an easy trap for the next reader.
- **`stream.py` builds its `APIRouter` inside the factory.** It was previously a
  module-level object, so a second `create_stream_router()` call in the same process
  double-registered `/prices` — which blocked testing the endpoint at all.

---

## 16. Configuration Summary

### Environment variables

| Variable | Default | Effect |
|---|---|---|
| `MASSIVE_API_KEY` | *(unset)* | Non-empty → `MassiveDataSource`; unset/blank → `SimulatorDataSource` |

### Tunable constructor parameters

| Parameter | Default | Where | Notes |
|---|---|---|---|
| `update_interval` | `0.5` s | `SimulatorDataSource` | Tick cadence; matches the SSE interval |
| `event_probability` | `0.001` | `SimulatorDataSource`, `GBMSimulator` | Per tick per ticker; `0.0` disables shocks (useful in tests) |
| `dt` | `~8.48e-8` | `GBMSimulator` | 500 ms as a fraction of a trading year |
| `poll_interval` | `15.0` s | `MassiveDataSource` | 15 s for the free tier; 2–5 s on paid tiers |
| `interval` | `0.5` s | `_generate_events` | SSE emit cadence |

### Dependencies (`backend/pyproject.toml`)

```toml
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "numpy>=2.0.0",       # Cholesky decomposition + normal draws
    "massive>=1.0.0",     # Massive/Polygon REST client
    "rich>=13.0.0",       # Terminal demo
]

[tool.hatch.build.targets.wheel]
packages = ["app"]        # Required — uv sync fails without it
```

### Public API surface

```python
from app.market import (
    PriceUpdate,                # Immutable price snapshot
    PriceCache,                 # Thread-safe store
    MarketDataSource,           # ABC for type hints
    create_market_data_source,  # Factory (reads MASSIVE_API_KEY)
    create_stream_router,       # FastAPI SSE router factory
)
```

### Quickstart

```python
cache = PriceCache()
source = create_market_data_source(cache)
await source.start(["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA",
                    "NVDA", "META", "JPM", "V", "NFLX"])

cache.get("AAPL")        # PriceUpdate | None
cache.get_price("AAPL")  # float | None
cache.get_all()          # dict[str, PriceUpdate]

await source.add_ticker("PYPL")
await source.remove_ticker("GOOGL")
await source.stop()
```
