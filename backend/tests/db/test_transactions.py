"""Tests that repository functions can enlist in a single outer transaction()
via the optional `conn=` parameter, per backend/app/db/README.md.
"""

from __future__ import annotations

import threading

import pytest

from app.db import database, repository


@pytest.fixture(autouse=True)
def _init_db(tmp_path):
    database.init_db(str(tmp_path / "finally.db"))


def _run_trade_sequence(conn, *, ticker="AAPL", quantity=10.0, price=192.5, blow_up=False):
    """Mimics the shape of services.portfolio.execute_trade: cash, position,
    trade log, snapshot — all against the same connection."""
    cash = repository.get_cash_balance(conn=conn)
    repository.set_cash_balance(cash - quantity * price, conn=conn)
    repository.upsert_position(ticker, quantity, price, conn=conn)
    if blow_up:
        raise RuntimeError("simulated crash mid-trade")
    repository.record_trade(ticker, "buy", quantity, price, conn=conn)
    repository.record_snapshot(cash - quantity * price + quantity * price, conn=conn)


def test_atomic_sequence_commits_together_on_success():
    starting_cash = repository.get_cash_balance()

    with database.transaction() as conn:
        _run_trade_sequence(conn)

    assert repository.get_cash_balance() == starting_cash - 10.0 * 192.5
    assert repository.get_position("AAPL") is not None
    assert len(repository.list_trades()) == 1
    assert len(repository.list_snapshots()) == 1


def test_atomic_sequence_rolls_back_entirely_on_failure():
    starting_cash = repository.get_cash_balance()

    with pytest.raises(RuntimeError):
        with database.transaction() as conn:
            _run_trade_sequence(conn, blow_up=True)

    # Nothing landed: cash unchanged, no position, no trade, no snapshot.
    assert repository.get_cash_balance() == starting_cash
    assert repository.get_position("AAPL") is None
    assert repository.list_trades() == []
    assert repository.list_snapshots() == []


def test_conn_passed_call_does_not_commit_before_outer_block_exits():
    with database.transaction() as conn:
        repository.upsert_position("AAPL", 5.0, 100.0, conn=conn)

        # A separate connection, opened while the outer transaction is still
        # open, must not see the uncommitted write (WAL snapshot isolation).
        with database.get_connection() as outside_conn:
            row = outside_conn.execute(
                "SELECT * FROM positions WHERE ticker = 'AAPL'"
            ).fetchone()
            assert row is None

    # After the outer block exits (and commits), it is visible.
    assert repository.get_position("AAPL") is not None


def test_standalone_calls_without_conn_still_commit_independently():
    # Backward-compatible behaviour: no conn passed -> each call is its own
    # standalone, immediately-committed transaction.
    repository.set_cash_balance(4242.0)
    repository.upsert_position("GOOGL", 3.0, 150.0)
    assert repository.get_cash_balance() == 4242.0
    assert repository.get_position("GOOGL")["quantity"] == 3.0


def test_read_functions_accept_conn_within_outer_transaction():
    with database.transaction() as conn:
        repository.upsert_position("AAPL", 10.0, 190.0, conn=conn)
        # Reads against the same conn see the not-yet-committed write.
        position = repository.get_position("AAPL", conn=conn)
        positions = repository.list_positions(conn=conn)
        profile = repository.get_profile(conn=conn)

    assert position["quantity"] == 10.0
    assert any(p["ticker"] == "AAPL" for p in positions)
    assert profile["id"] == "default"


def test_concurrent_atomic_trades_do_not_corrupt_or_deadlock():
    errors: list[Exception] = []

    def buy(n: int) -> None:
        try:
            with database.transaction() as conn:
                repository.set_cash_balance(
                    repository.get_cash_balance(conn=conn) - 1.0, conn=conn
                )
                repository.record_trade("AAPL", "buy", 1.0, 1.0, conn=conn)
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=buy, args=(n,)) for n in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert len(repository.list_trades()) == 20
    assert repository.get_cash_balance() == 10000.0 - 20.0
