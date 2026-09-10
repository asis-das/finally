"""Reference prices for the "daily" change shown in the watchlist.

PLAN.md §10 asks for a *daily* change %, but the price cache only carries
tick-over-tick movement (~±0.05%), which reads as flicker rather than signal.

There is no real trading day behind the simulator, so the reference is:

1. the ticker's seed price from ``app.market.seed_prices.SEED_PRICES`` — those
   are the simulator's notional prior closes (AAPL 190.00, NVDA 800.00, ...); or
2. for a ticker with no seed (anything the user adds later), the first price
   this process ever observed for it.

So the "day" is really *since the backend started*. That is stated plainly
rather than implying a precision we do not have — but it is stable across page
reloads and identical for every connected client, which a client-side
"since page load" figure is not.

Reading ``SEED_PRICES`` does not modify the frozen ``app.market`` package.
"""

from __future__ import annotations

import threading

from app.market.seed_prices import SEED_PRICES


class ReferencePrices:
    """Thread-safe store of the per-ticker reference price.

    Lives on ``app.state`` rather than at module level so that the several app
    instances the test suite builds never share references.
    """

    def __init__(self) -> None:
        self._first_seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def reference(self, ticker: str, current_price: float | None = None) -> float | None:
        """Reference price for `ticker`, or None if it has never had a price.

        Passing `current_price` records it as the reference the first time a
        non-seeded ticker is seen; later calls keep that original value.
        """
        seed = SEED_PRICES.get(ticker)
        if seed is not None:
            return seed
        with self._lock:
            if current_price is None:
                return self._first_seen.get(ticker)
            return self._first_seen.setdefault(ticker, current_price)

    def day_move(self, ticker: str, current_price: float | None) -> tuple[float | None, float, float]:
        """(reference, day_change, day_change_percent) — zeros when unavailable."""
        reference = self.reference(ticker, current_price)
        if reference is None or current_price is None or reference == 0:
            return reference, 0.0, 0.0
        change = current_price - reference
        return reference, round(change, 2), round(change / reference * 100, 2)
