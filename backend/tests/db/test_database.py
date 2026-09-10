"""Tests for app.db.database: init_db, get_connection, transaction."""

from __future__ import annotations

import sqlite3
import threading

import pytest

from app.db import database


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "finally.db")
    database.init_db(path)
    return path


def test_init_db_creates_parent_dirs(tmp_path):
    path = str(tmp_path / "nested" / "dir" / "finally.db")
    database.init_db(path)
    assert (tmp_path / "nested" / "dir" / "finally.db").exists()


def test_init_db_creates_all_tables(db_path):
    with database.get_connection() as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    table_names = {row["name"] for row in rows}
    expected = {
        "users_profile",
        "watchlist",
        "positions",
        "trades",
        "portfolio_snapshots",
        "chat_messages",
    }
    assert expected.issubset(table_names)


def test_init_db_seeds_default_profile(db_path):
    with database.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users_profile WHERE id = ?", (database.DEFAULT_USER_ID,)
        ).fetchone()
    assert row is not None
    assert row["cash_balance"] == 10000.0


def test_init_db_seeds_default_watchlist(db_path):
    with database.get_connection() as conn:
        rows = conn.execute(
            "SELECT ticker FROM watchlist WHERE user_id = ?",
            (database.DEFAULT_USER_ID,),
        ).fetchall()
    tickers = {row["ticker"] for row in rows}
    assert tickers == set(database.DEFAULT_WATCHLIST)
    assert len(rows) == 10


def test_init_db_is_idempotent(db_path):
    # Calling init_db again must not wipe or duplicate seed data.
    database.init_db(db_path)
    database.init_db(db_path)
    with database.get_connection() as conn:
        profile_count = conn.execute("SELECT COUNT(*) FROM users_profile").fetchone()[0]
        watchlist_count = conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]
    assert profile_count == 1
    assert watchlist_count == 10


def test_init_db_never_wipes_existing_data(db_path):
    with database.transaction() as conn:
        conn.execute(
            "UPDATE users_profile SET cash_balance = ? WHERE id = ?",
            (5000.0, database.DEFAULT_USER_ID),
        )
        conn.execute("DELETE FROM watchlist WHERE ticker != 'AAPL'")

    # Re-running init_db must not re-seed over the modified state.
    database.init_db(db_path)

    with database.get_connection() as conn:
        profile = conn.execute(
            "SELECT cash_balance FROM users_profile WHERE id = ?",
            (database.DEFAULT_USER_ID,),
        ).fetchone()
        watchlist_count = conn.execute("SELECT COUNT(*) FROM watchlist").fetchone()[0]

    assert profile["cash_balance"] == 5000.0
    assert watchlist_count == 1


def test_get_connection_row_factory_and_pragmas(db_path):
    with database.get_connection() as conn:
        assert conn.row_factory is sqlite3.Row
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert journal_mode.lower() == "wal"


def test_transaction_commits_on_success(db_path):
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
            ("test-id", "default", "PYPL", "2026-01-01T00:00:00+00:00"),
        )
    with database.get_connection() as conn:
        row = conn.execute("SELECT * FROM watchlist WHERE ticker = 'PYPL'").fetchone()
    assert row is not None


def test_transaction_rolls_back_on_exception(db_path):
    with pytest.raises(RuntimeError):
        with database.transaction() as conn:
            conn.execute(
                "INSERT INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
                ("test-id-2", "default", "ROLLBACK_ME", "2026-01-01T00:00:00+00:00"),
            )
            raise RuntimeError("boom")

    with database.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM watchlist WHERE ticker = 'ROLLBACK_ME'"
        ).fetchone()
    assert row is None


def test_concurrent_writes_do_not_corrupt_or_deadlock(db_path):
    errors: list[Exception] = []

    def add_ticker(n: int) -> None:
        try:
            with database.transaction() as conn:
                conn.execute(
                    "INSERT INTO watchlist (id, user_id, ticker, added_at) "
                    "VALUES (?, ?, ?, ?)",
                    (f"id-{n}", "default", f"TCK{n}", "2026-01-01T00:00:00+00:00"),
                )
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=add_ticker, args=(n,)) for n in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    with database.get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM watchlist WHERE ticker LIKE 'TCK%'"
        ).fetchone()[0]
    assert count == 20
