"""Portfolio valuation and trade execution.

This module holds the maths so that the REST routes and the LLM layer share a
single implementation. Nothing here raises ``HTTPException`` — callers convert
:class:`TradeError` into whatever their transport needs.
"""

from __future__ import annotations

import sqlite3

from app.db import (
    DEFAULT_USER_ID,
    delete_position,
    get_cash_balance,
    get_position,
    list_positions,
    record_snapshot,
    record_trade,
    set_cash_balance,
    transaction,
    upsert_position,
)
from app.market import PriceCache

#: Quantities at or below this are treated as a fully closed position.
DUST = 1e-9

VALID_SIDES = ("buy", "sell")


class TradeError(Exception):
    """A trade failed validation. The message is user-facing."""


class PriceUnavailableError(TradeError):
    """No price is known for the ticker, so it cannot be traded (HTTP 404)."""


def _normalize_ticker(ticker: str) -> str:
    return ticker.strip().upper()


def _fmt_qty(quantity: float) -> str:
    """Render a share count without a trailing ``.0`` (10.0 -> '10')."""
    return f"{quantity:g}"


def build_portfolio(
    price_cache: PriceCache,
    user_id: str = DEFAULT_USER_ID,
    *,
    conn: sqlite3.Connection | None = None,
) -> dict:
    """Build the exact ``GET /api/portfolio`` payload.

    Pass ``conn`` to read from inside an open transaction — otherwise the reads
    run on their own connection and cannot see that transaction's writes.
    """
    cash_balance = get_cash_balance(user_id, conn=conn)
    positions = []
    positions_value = 0.0
    total_cost_basis = 0.0

    for row in list_positions(user_id, conn=conn):
        ticker = row["ticker"]
        quantity = row["quantity"]
        avg_cost = row["avg_cost"]
        # Fall back to cost basis so a not-yet-priced ticker never shows null.
        current_price = price_cache.get_price(ticker)
        if current_price is None:
            current_price = avg_cost

        market_value = quantity * current_price
        cost_basis = quantity * avg_cost
        unrealized_pnl = market_value - cost_basis
        pnl_percent = (unrealized_pnl / cost_basis * 100) if cost_basis else 0.0

        positions_value += market_value
        total_cost_basis += cost_basis
        positions.append(
            {
                "ticker": ticker,
                "quantity": quantity,
                "avg_cost": round(avg_cost, 2),
                "current_price": round(current_price, 2),
                "market_value": round(market_value, 2),
                "unrealized_pnl": round(unrealized_pnl, 2),
                "unrealized_pnl_percent": round(pnl_percent, 2),
                # Filled in below, once total_value is known.
                "weight": 0.0,
                "_market_value": market_value,
            }
        )

    total_value = cash_balance + positions_value
    for position in positions:
        raw_market_value = position.pop("_market_value")
        position["weight"] = round(raw_market_value / total_value, 4) if total_value else 0.0

    positions.sort(key=lambda p: p["market_value"], reverse=True)

    total_unrealized_pnl = positions_value - total_cost_basis
    total_pnl_percent = (
        (total_unrealized_pnl / total_cost_basis * 100) if total_cost_basis else 0.0
    )

    return {
        "cash_balance": round(cash_balance, 2),
        "positions": positions,
        "positions_value": round(positions_value, 2),
        "total_value": round(total_value, 2),
        "total_cost_basis": round(total_cost_basis, 2),
        "total_unrealized_pnl": round(total_unrealized_pnl, 2),
        "total_unrealized_pnl_percent": round(total_pnl_percent, 2),
    }


def total_portfolio_value(
    price_cache: PriceCache,
    user_id: str = DEFAULT_USER_ID,
    *,
    conn: sqlite3.Connection | None = None,
) -> float:
    """Cash plus the marked-to-market value of every open position."""
    return build_portfolio(price_cache, user_id, conn=conn)["total_value"]


def execute_trade(
    price_cache: PriceCache,
    ticker: str,
    side: str,
    quantity: float,
    user_id: str = DEFAULT_USER_ID,
) -> dict:
    """Execute a market order and return the ``POST /api/portfolio/trade`` payload.

    Raises :class:`TradeError` (or its :class:`PriceUnavailableError` subclass)
    on any validation failure; nothing is written when it raises.

    Cash, position, trade log and snapshot are written in a single
    ``transaction()``. The balance and holding are read on that same connection,
    inside the block, so that ``BEGIN IMMEDIATE`` serialises concurrent trades:
    reading outside the block would let two callers act on the same stale cash
    balance and lose one another's update.
    """
    ticker = _normalize_ticker(ticker)
    side = side.strip().lower()

    if side not in VALID_SIDES:
        raise TradeError(f"Invalid side: {side}")
    if quantity is None or quantity <= 0:
        raise TradeError("Quantity must be greater than zero")

    price = price_cache.get_price(ticker)
    if price is None:
        raise PriceUnavailableError(f"No price available for {ticker}")

    notional = quantity * price

    with transaction() as conn:
        cash_balance = get_cash_balance(user_id, conn=conn)
        existing = get_position(ticker, user_id, conn=conn)
        held_quantity = existing["quantity"] if existing else 0.0
        held_avg_cost = existing["avg_cost"] if existing else 0.0

        if side == "buy":
            if notional > cash_balance + DUST:
                # Raising inside the block rolls it back; nothing is written.
                raise TradeError(
                    f"Insufficient cash: need ${notional:.2f}, have ${cash_balance:.2f}"
                )
            new_cash = cash_balance - notional
            new_quantity = held_quantity + quantity
            new_avg_cost = (held_quantity * held_avg_cost + notional) / new_quantity
        else:
            if quantity > held_quantity + DUST:
                raise TradeError(
                    f"Insufficient shares: tried to sell {_fmt_qty(quantity)} {ticker}, "
                    f"hold {_fmt_qty(held_quantity)}"
                )
            new_cash = cash_balance + notional
            new_quantity = held_quantity - quantity
            new_avg_cost = held_avg_cost

        set_cash_balance(new_cash, user_id, conn=conn)
        if new_quantity <= DUST:
            delete_position(ticker, user_id, conn=conn)
            position_payload = None
        else:
            upsert_position(ticker, new_quantity, new_avg_cost, user_id, conn=conn)
            position_payload = {
                "ticker": ticker,
                "quantity": new_quantity,
                "avg_cost": round(new_avg_cost, 2),
            }

        trade = record_trade(ticker, side, float(quantity), round(price, 2), user_id, conn=conn)

        # Valued on the transaction's own connection so it sees the writes above.
        total_value = total_portfolio_value(price_cache, user_id, conn=conn)
        record_snapshot(total_value, user_id, conn=conn)

    return {
        "trade": trade,
        "cash_balance": round(new_cash, 2),
        "position": position_payload,
        "total_value": total_value,
    }
