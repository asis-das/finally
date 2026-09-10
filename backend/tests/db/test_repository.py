"""Tests for app.db.repository query functions."""

from __future__ import annotations

import pytest

from app.db import database, repository


@pytest.fixture(autouse=True)
def _init_db(tmp_path):
    database.init_db(str(tmp_path / "finally.db"))


# --- profile ---


def test_get_profile_returns_seeded_default():
    profile = repository.get_profile()
    assert profile["id"] == "default"
    assert profile["cash_balance"] == 10000.0
    assert "created_at" in profile


def test_get_profile_missing_user_raises():
    with pytest.raises(ValueError):
        repository.get_profile(user_id="nobody")


def test_get_cash_balance():
    assert repository.get_cash_balance() == 10000.0


def test_set_cash_balance_persists():
    repository.set_cash_balance(1234.56)
    assert repository.get_cash_balance() == 1234.56


# --- watchlist ---


def test_list_watchlist_returns_default_seed_in_order():
    tickers = repository.list_watchlist()
    assert tickers == database.DEFAULT_WATCHLIST


def test_add_watchlist_ticker_normalizes_case_and_whitespace():
    added = repository.add_watchlist_ticker("  pypl  ")
    assert added is True
    assert "PYPL" in repository.list_watchlist()


def test_add_watchlist_ticker_duplicate_returns_false():
    repository.add_watchlist_ticker("PYPL")
    added_again = repository.add_watchlist_ticker("pypl")
    assert added_again is False
    assert repository.list_watchlist().count("PYPL") == 1


def test_remove_watchlist_ticker():
    repository.add_watchlist_ticker("PYPL")
    removed = repository.remove_watchlist_ticker("pypl")
    assert removed is True
    assert "PYPL" not in repository.list_watchlist()


def test_remove_watchlist_ticker_not_present_returns_false():
    assert repository.remove_watchlist_ticker("NOPE") is False


def test_watchlist_uniqueness_enforced_at_db_level():
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
            ("id-1", "default", "DUPTEST", "2026-01-01T00:00:00+00:00"),
        )
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as conn:
            conn.execute(
                "INSERT INTO watchlist (id, user_id, ticker, added_at) VALUES (?, ?, ?, ?)",
                ("id-2", "default", "DUPTEST", "2026-01-01T00:00:01+00:00"),
            )


# --- positions ---


def test_upsert_position_inserts_new():
    repository.upsert_position("AAPL", 10.0, 190.0)
    position = repository.get_position("aapl")
    assert position["ticker"] == "AAPL"
    assert position["quantity"] == 10.0
    assert position["avg_cost"] == 190.0


def test_upsert_position_updates_existing():
    repository.upsert_position("AAPL", 10.0, 190.0)
    repository.upsert_position("AAPL", 15.0, 191.0)
    positions = repository.list_positions()
    aapl_positions = [p for p in positions if p["ticker"] == "AAPL"]
    assert len(aapl_positions) == 1
    assert aapl_positions[0]["quantity"] == 15.0
    assert aapl_positions[0]["avg_cost"] == 191.0


def test_get_position_missing_returns_none():
    assert repository.get_position("ZZZZ") is None


def test_delete_position():
    repository.upsert_position("AAPL", 10.0, 190.0)
    repository.delete_position("aapl")
    assert repository.get_position("AAPL") is None


def test_positions_uniqueness_enforced_at_db_level():
    import sqlite3

    repository.upsert_position("AAPL", 10.0, 190.0)
    with pytest.raises(sqlite3.IntegrityError):
        with database.transaction() as conn:
            conn.execute(
                "INSERT INTO positions (id, user_id, ticker, quantity, avg_cost, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("dup-id", "default", "AAPL", 1.0, 1.0, "2026-01-01T00:00:00+00:00"),
            )


# --- trades ---


def test_record_trade_returns_expected_shape():
    trade = repository.record_trade("aapl", "buy", 10.0, 192.5)
    assert trade["ticker"] == "AAPL"
    assert trade["side"] == "buy"
    assert trade["quantity"] == 10.0
    assert trade["price"] == 192.5
    assert "id" in trade and "executed_at" in trade


def test_list_trades_newest_first():
    repository.record_trade("AAPL", "buy", 1.0, 100.0)
    repository.record_trade("GOOGL", "buy", 2.0, 200.0)
    trades = repository.list_trades()
    assert [t["ticker"] for t in trades] == ["GOOGL", "AAPL"]


def test_list_trades_respects_limit():
    for i in range(5):
        repository.record_trade("AAPL", "buy", 1.0, 100.0 + i)
    trades = repository.list_trades(limit=2)
    assert len(trades) == 2


# --- snapshots ---


def test_record_snapshot_returns_expected_shape():
    snapshot = repository.record_snapshot(10000.0)
    assert snapshot["total_value"] == 10000.0
    assert "id" in snapshot and "recorded_at" in snapshot


def test_list_snapshots_oldest_first():
    repository.record_snapshot(100.0)
    repository.record_snapshot(200.0)
    repository.record_snapshot(300.0)
    snapshots = repository.list_snapshots()
    assert [s["total_value"] for s in snapshots] == [100.0, 200.0, 300.0]


def test_list_snapshots_respects_limit_keeping_most_recent():
    for value in (100.0, 200.0, 300.0):
        repository.record_snapshot(value)
    snapshots = repository.list_snapshots(limit=2)
    assert [s["total_value"] for s in snapshots] == [200.0, 300.0]


# --- chat ---


def test_add_chat_message_without_actions():
    message = repository.add_chat_message("user", "hello")
    assert message["role"] == "user"
    assert message["content"] == "hello"
    assert message["actions"] is None


def test_add_chat_message_json_roundtrip_list_actions():
    actions = [{"type": "trade", "status": "executed", "ticker": "AAPL"}]
    repository.add_chat_message("assistant", "Bought AAPL.", actions=actions)
    messages = repository.list_chat_messages()
    assert messages[-1]["actions"] == actions


def test_add_chat_message_json_roundtrip_dict_actions():
    actions = {"type": "trade", "status": "executed"}
    repository.add_chat_message("assistant", "Bought AAPL.", actions=actions)
    messages = repository.list_chat_messages()
    assert messages[-1]["actions"] == actions


def test_list_chat_messages_oldest_first():
    repository.add_chat_message("user", "first")
    repository.add_chat_message("assistant", "second")
    messages = repository.list_chat_messages()
    assert [m["content"] for m in messages] == ["first", "second"]


def test_list_chat_messages_respects_limit():
    for i in range(5):
        repository.add_chat_message("user", f"message {i}")
    messages = repository.list_chat_messages(limit=2)
    assert len(messages) == 2
    assert [m["content"] for m in messages] == ["message 3", "message 4"]


# --- ticker normalization ---


def test_record_trade_normalizes_ticker():
    trade = repository.record_trade("  aapl  ", "buy", 1.0, 100.0)
    assert trade["ticker"] == "AAPL"
