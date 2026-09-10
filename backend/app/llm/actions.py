"""Execution of the actions the assistant asked for.

Nothing here reimplements portfolio maths or SQL: trades go through
``app.services.portfolio.execute_trade`` and watchlist edits go through the
``app.db`` repository plus the live market source. A failed action is reported,
never raised — one bad trade must not lose the rest of the reply.
"""

from __future__ import annotations

import logging
import re

from app.db import add_watchlist_ticker, get_position, remove_watchlist_ticker
from app.market import MarketDataSource, PriceCache
from app.services.portfolio import TradeError, execute_trade

from .schemas import ChatResponse, Trade, WatchlistChange

logger = logging.getLogger(__name__)

#: Same rule the REST watchlist endpoint enforces.
TICKER_PATTERN = re.compile(r"^[A-Z.\-]{1,10}$")


def _normalize(ticker: str) -> str:
    return (ticker or "").strip().upper()


def _fmt_qty(quantity: float) -> str:
    return f"{quantity:g}"


def _watchlist_action(ticker: str, action: str, status: str, detail: str) -> dict:
    return {
        "type": "watchlist",
        "status": status,
        "ticker": ticker,
        "action": action,
        "detail": detail,
    }


def _trade_action(
    ticker: str, side: str, quantity: float, price: float | None, status: str, detail: str
) -> dict:
    return {
        "type": "trade",
        "status": status,
        "ticker": ticker,
        "side": side,
        "quantity": quantity,
        "price": price,
        "detail": detail,
    }


async def apply_watchlist_change(change: WatchlistChange, source: MarketDataSource) -> dict:
    ticker = _normalize(change.ticker)
    action = change.action

    if not TICKER_PATTERN.match(ticker):
        return _watchlist_action(ticker, action, "failed", f"Invalid ticker {change.ticker!r}")

    if action == "add":
        if not add_watchlist_ticker(ticker):
            return _watchlist_action(
                ticker, action, "failed", f"Ticker {ticker} is already on the watchlist"
            )
        await source.add_ticker(ticker)
        return _watchlist_action(
            ticker, action, "executed", f"Added {ticker} to the watchlist"
        )

    if not remove_watchlist_ticker(ticker):
        return _watchlist_action(
            ticker, action, "failed", f"Ticker {ticker} is not on the watchlist"
        )
    # Keep pricing anything we still hold, even once it leaves the watchlist.
    if get_position(ticker) is None:
        await source.remove_ticker(ticker)
    return _watchlist_action(ticker, action, "executed", f"Removed {ticker} from the watchlist")


def apply_trade(trade: Trade, price_cache: PriceCache) -> dict:
    ticker = _normalize(trade.ticker)
    side = (trade.side or "").strip().lower()
    quantity = trade.quantity

    try:
        result = execute_trade(price_cache, ticker, side, quantity)
    except TradeError as exc:
        return _trade_action(ticker, side, quantity, None, "failed", str(exc))

    executed = result["trade"]
    verb = "Bought" if side == "buy" else "Sold"
    price = executed["price"]
    return _trade_action(
        ticker,
        side,
        executed["quantity"],
        price,
        "executed",
        f"{verb} {_fmt_qty(executed['quantity'])} {ticker} @ ${price:,.2f}",
    )


async def apply_actions(
    reply: ChatResponse, price_cache: PriceCache, source: MarketDataSource
) -> list[dict]:
    """Apply watchlist changes first, then trades.

    Order matters: "add PYPL and buy 5" only works if the ticker is being priced
    before the order is placed.
    """
    actions: list[dict] = []
    for change in reply.watchlist_changes:
        actions.append(await apply_watchlist_change(change, source))
    for trade in reply.trades:
        actions.append(apply_trade(trade, price_cache))
    return actions
