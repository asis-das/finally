"""Query functions for the FinAlly database.

All functions are synchronous, take a trailing user_id (defaulting to
DEFAULT_USER_ID), and return plain dict / list[dict] — never sqlite3.Row.
Tickers are normalised to uppercase + stripped on write and on lookup.

Every function also accepts an optional keyword-only `conn`. Pass a
connection obtained from an outer `database.transaction()` block to enlist
the call in that transaction (it will read/write on `conn` and will NOT
commit — the caller's transaction owns the commit/rollback). Omit `conn`
for the original standalone behaviour: each call opens and commits (or
rolls back) its own connection. See backend/app/db/README.md.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from .database import DEFAULT_USER_ID, get_connection, transaction


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_ticker(ticker: str) -> str:
    return ticker.strip().upper()


def _row_to_dict(row) -> dict:
    return dict(row)


@contextmanager
def _read_conn(conn: sqlite3.Connection | None) -> Iterator[sqlite3.Connection]:
    """Yield `conn` as-is if given, else open (and close) a fresh connection."""
    if conn is not None:
        yield conn
    else:
        with get_connection() as new_conn:
            yield new_conn


@contextmanager
def _write_conn(conn: sqlite3.Connection | None) -> Iterator[sqlite3.Connection]:
    """Yield `conn` as-is if given (caller commits/rolls back), else run in
    a standalone transaction() that commits on success / rolls back on error."""
    if conn is not None:
        yield conn
    else:
        with transaction() as new_conn:
            yield new_conn


# --- profile ---


def get_profile(user_id: str = DEFAULT_USER_ID, *, conn: sqlite3.Connection | None = None) -> dict:
    """Returns {"id", "cash_balance", "created_at"}."""
    with _read_conn(conn) as c:
        row = c.execute(
            "SELECT id, cash_balance, created_at FROM users_profile WHERE id = ?",
            (user_id,),
        ).fetchone()
    if row is None:
        raise ValueError(f"No profile for user_id={user_id!r}")
    return _row_to_dict(row)


def get_cash_balance(
    user_id: str = DEFAULT_USER_ID, *, conn: sqlite3.Connection | None = None
) -> float:
    with _read_conn(conn) as c:
        row = c.execute(
            "SELECT cash_balance FROM users_profile WHERE id = ?",
            (user_id,),
        ).fetchone()
    if row is None:
        raise ValueError(f"No profile for user_id={user_id!r}")
    return row["cash_balance"]


def set_cash_balance(
    balance: float, user_id: str = DEFAULT_USER_ID, *, conn: sqlite3.Connection | None = None
) -> None:
    with _write_conn(conn) as c:
        c.execute(
            "UPDATE users_profile SET cash_balance = ? WHERE id = ?",
            (balance, user_id),
        )


# --- watchlist ---


def list_watchlist(
    user_id: str = DEFAULT_USER_ID, *, conn: sqlite3.Connection | None = None
) -> list[str]:
    """Ordered by added_at ASC."""
    with _read_conn(conn) as c:
        rows = c.execute(
            "SELECT ticker FROM watchlist WHERE user_id = ? ORDER BY added_at ASC",
            (user_id,),
        ).fetchall()
    return [row["ticker"] for row in rows]


def add_watchlist_ticker(
    ticker: str, user_id: str = DEFAULT_USER_ID, *, conn: sqlite3.Connection | None = None
) -> bool:
    """Returns False if the ticker is already present."""
    ticker = _normalize_ticker(ticker)
    with _write_conn(conn) as c:
        existing = c.execute(
            "SELECT 1 FROM watchlist WHERE user_id = ? AND ticker = ?",
            (user_id, ticker),
        ).fetchone()
        if existing is not None:
            return False
        c.execute(
            "INSERT INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), user_id, ticker, _now_iso()),
        )
        return True


def remove_watchlist_ticker(
    ticker: str, user_id: str = DEFAULT_USER_ID, *, conn: sqlite3.Connection | None = None
) -> bool:
    """Returns False if the ticker was not present."""
    ticker = _normalize_ticker(ticker)
    with _write_conn(conn) as c:
        cur = c.execute(
            "DELETE FROM watchlist WHERE user_id = ? AND ticker = ?",
            (user_id, ticker),
        )
        return cur.rowcount > 0


# --- positions ---


def list_positions(
    user_id: str = DEFAULT_USER_ID, *, conn: sqlite3.Connection | None = None
) -> list[dict]:
    """Returns [{"ticker", "quantity", "avg_cost", "updated_at"}, ...]."""
    with _read_conn(conn) as c:
        rows = c.execute(
            "SELECT ticker, quantity, avg_cost, updated_at FROM positions "
            "WHERE user_id = ? ORDER BY ticker ASC",
            (user_id,),
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def get_position(
    ticker: str, user_id: str = DEFAULT_USER_ID, *, conn: sqlite3.Connection | None = None
) -> dict | None:
    ticker = _normalize_ticker(ticker)
    with _read_conn(conn) as c:
        row = c.execute(
            "SELECT ticker, quantity, avg_cost, updated_at FROM positions "
            "WHERE user_id = ? AND ticker = ?",
            (user_id, ticker),
        ).fetchone()
    return _row_to_dict(row) if row is not None else None


def upsert_position(
    ticker: str,
    quantity: float,
    avg_cost: float,
    user_id: str = DEFAULT_USER_ID,
    *,
    conn: sqlite3.Connection | None = None,
) -> None:
    ticker = _normalize_ticker(ticker)
    now = _now_iso()
    with _write_conn(conn) as c:
        existing = c.execute(
            "SELECT id FROM positions WHERE user_id = ? AND ticker = ?",
            (user_id, ticker),
        ).fetchone()
        if existing is not None:
            c.execute(
                "UPDATE positions SET quantity = ?, avg_cost = ?, updated_at = ? "
                "WHERE user_id = ? AND ticker = ?",
                (quantity, avg_cost, now, user_id, ticker),
            )
        else:
            c.execute(
                "INSERT INTO positions (id, user_id, ticker, quantity, avg_cost, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), user_id, ticker, quantity, avg_cost, now),
            )


def delete_position(
    ticker: str, user_id: str = DEFAULT_USER_ID, *, conn: sqlite3.Connection | None = None
) -> None:
    ticker = _normalize_ticker(ticker)
    with _write_conn(conn) as c:
        c.execute(
            "DELETE FROM positions WHERE user_id = ? AND ticker = ?",
            (user_id, ticker),
        )


# --- trades ---


def record_trade(
    ticker: str,
    side: str,
    quantity: float,
    price: float,
    user_id: str = DEFAULT_USER_ID,
    *,
    conn: sqlite3.Connection | None = None,
) -> dict:
    """Returns {"id", "ticker", "side", "quantity", "price", "executed_at"}."""
    ticker = _normalize_ticker(ticker)
    trade = {
        "id": str(uuid.uuid4()),
        "ticker": ticker,
        "side": side,
        "quantity": quantity,
        "price": price,
        "executed_at": _now_iso(),
    }
    with _write_conn(conn) as c:
        c.execute(
            "INSERT INTO trades (id, user_id, ticker, side, quantity, price, executed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (trade["id"], user_id, ticker, side, quantity, price, trade["executed_at"]),
        )
    return trade


def list_trades(
    limit: int = 100, user_id: str = DEFAULT_USER_ID, *, conn: sqlite3.Connection | None = None
) -> list[dict]:
    """Newest first."""
    with _read_conn(conn) as c:
        rows = c.execute(
            "SELECT id, ticker, side, quantity, price, executed_at FROM trades "
            "WHERE user_id = ? ORDER BY executed_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


# --- snapshots ---


def record_snapshot(
    total_value: float, user_id: str = DEFAULT_USER_ID, *, conn: sqlite3.Connection | None = None
) -> dict:
    """Returns {"id", "total_value", "recorded_at"}."""
    snapshot = {
        "id": str(uuid.uuid4()),
        "total_value": total_value,
        "recorded_at": _now_iso(),
    }
    with _write_conn(conn) as c:
        c.execute(
            "INSERT INTO portfolio_snapshots (id, user_id, total_value, recorded_at) "
            "VALUES (?, ?, ?, ?)",
            (snapshot["id"], user_id, total_value, snapshot["recorded_at"]),
        )
    return snapshot


def list_snapshots(
    limit: int = 500, user_id: str = DEFAULT_USER_ID, *, conn: sqlite3.Connection | None = None
) -> list[dict]:
    """Oldest first (chart order). Returns the most recent `limit` snapshots."""
    with _read_conn(conn) as c:
        rows = c.execute(
            "SELECT id, total_value, recorded_at FROM portfolio_snapshots "
            "WHERE user_id = ? ORDER BY recorded_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    snapshots = [_row_to_dict(row) for row in rows]
    snapshots.reverse()
    return snapshots


# --- chat ---


def add_chat_message(
    role: str,
    content: str,
    actions: list | dict | None = None,
    user_id: str = DEFAULT_USER_ID,
    *,
    conn: sqlite3.Connection | None = None,
) -> dict:
    """actions is JSON-encoded on write, JSON-decoded on read (None -> None)."""
    message = {
        "id": str(uuid.uuid4()),
        "role": role,
        "content": content,
        "actions": actions,
        "created_at": _now_iso(),
    }
    actions_json = json.dumps(actions) if actions is not None else None
    with _write_conn(conn) as c:
        c.execute(
            "INSERT INTO chat_messages (id, user_id, role, content, actions, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (message["id"], user_id, role, content, actions_json, message["created_at"]),
        )
    return message


def list_chat_messages(
    limit: int = 50, user_id: str = DEFAULT_USER_ID, *, conn: sqlite3.Connection | None = None
) -> list[dict]:
    """Returns [{"id", "role", "content", "actions", "created_at"}, ...], oldest first."""
    with _read_conn(conn) as c:
        rows = c.execute(
            "SELECT id, role, content, actions, created_at FROM chat_messages "
            "WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    messages = []
    for row in rows:
        message = _row_to_dict(row)
        message["actions"] = json.loads(message["actions"]) if message["actions"] else None
        messages.append(message)
    messages.reverse()
    return messages
