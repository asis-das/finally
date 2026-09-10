"""Connection management and lazy schema initialization for the FinAlly database.

Each call to get_connection()/transaction() opens a short-lived sqlite3
connection configured for WAL mode. This keeps the module free of shared
connection state, which is the simplest way to be safe across the FastAPI
threadpool (sync route handlers) and the background snapshot task.
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Iterator

DEFAULT_USER_ID = "default"
DEFAULT_DB_PATH = "db/finally.db"
DEFAULT_CASH_BALANCE = 10000.0

# Matches app/market/seed_prices.py — the ten default watchlist tickers.
DEFAULT_WATCHLIST = [
    "AAPL",
    "GOOGL",
    "MSFT",
    "AMZN",
    "TSLA",
    "NVDA",
    "META",
    "JPM",
    "V",
    "NFLX",
]

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"

_init_lock = Lock()
_db_path: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_db_path(db_path: str | None) -> str:
    if db_path is not None:
        return db_path
    if _db_path is not None:
        return _db_path
    return os.environ.get("FINALLY_DB_PATH", DEFAULT_DB_PATH)


def _connect(path: str) -> sqlite3.Connection:
    # isolation_level=None puts the connection in full autocommit mode: the
    # sqlite3 module never issues an implicit BEGIN/COMMIT of its own, so
    # transaction() below can explicitly BEGIN IMMEDIATE (acquire the write
    # lock up front) rather than sqlite3's default deferred BEGIN (which only
    # acquires a lock on the first write, letting two transactions interleave
    # a read-then-write and lose an update — see tests/db/test_transactions.py).
    conn = sqlite3.connect(
        path, check_same_thread=False, timeout=5.0, isolation_level=None
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _seed_defaults(conn: sqlite3.Connection) -> None:
    """Insert default profile/watchlist rows only if those tables are empty."""
    profile_count = conn.execute("SELECT COUNT(*) FROM users_profile").fetchone()[0]
    if profile_count == 0:
        conn.execute(
            "INSERT INTO users_profile (id, cash_balance, created_at) VALUES (?, ?, ?)",
            (DEFAULT_USER_ID, DEFAULT_CASH_BALANCE, _now_iso()),
        )

    watchlist_count = conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
    if watchlist_count == 0:
        now = _now_iso()
        conn.executemany(
            "INSERT INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
            [(str(uuid.uuid4()), DEFAULT_USER_ID, ticker, now) for ticker in DEFAULT_WATCHLIST],
        )


def init_db(db_path: str | None = None) -> None:
    """Idempotent. Creates parent dirs, applies schema.sql, seeds defaults if empty.

    Reads FINALLY_DB_PATH when db_path is None. Safe to call on every startup.
    """
    global _db_path
    path = _resolve_db_path(db_path)
    with _init_lock:
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        conn = _connect(path)
        try:
            conn.executescript(_SCHEMA_PATH.read_text())
            _seed_defaults(conn)
            conn.commit()
        finally:
            conn.close()

        _db_path = path


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """Yields a connection with row_factory=sqlite3.Row and foreign_keys=ON."""
    conn = _connect(_resolve_db_path(None))
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """Same as get_connection, but commits on success and rolls back on exception.

    Begins with BEGIN IMMEDIATE, acquiring SQLite's write lock up front (rather
    than on the first write statement). This makes a read-then-write sequence
    inside one transaction() block atomic with respect to other transaction()
    blocks: a second caller's BEGIN IMMEDIATE blocks (up to busy_timeout) until
    the first commits or rolls back, instead of both reading the same stale
    value and one update clobbering the other.
    """
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
