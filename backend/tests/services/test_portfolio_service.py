"""Tests for app.services.portfolio: valuation maths and trade execution."""

from __future__ import annotations

import threading

import pytest

from app.db import (
    get_cash_balance,
    get_position,
    list_snapshots,
    list_trades,
    list_watchlist,
    set_cash_balance,
    upsert_position,
)
from app.services.portfolio import (
    PriceUnavailableError,
    TradeError,
    build_portfolio,
    execute_trade,
    total_portfolio_value,
)

# --- build_portfolio ---


def test_empty_portfolio_is_all_cash(cache):
    portfolio = build_portfolio(cache)
    assert portfolio["cash_balance"] == 10000.0
    assert portfolio["positions"] == []
    assert portfolio["positions_value"] == 0.0
    assert portfolio["total_value"] == 10000.0
    assert portfolio["total_cost_basis"] == 0.0
    assert portfolio["total_unrealized_pnl"] == 0.0
    assert portfolio["total_unrealized_pnl_percent"] == 0.0


def test_position_valuation_and_pnl(cache):
    upsert_position("AAPL", 10.0, 180.0)
    cache.update("AAPL", 190.0)

    position = build_portfolio(cache)["positions"][0]
    assert position["ticker"] == "AAPL"
    assert position["quantity"] == 10.0
    assert position["avg_cost"] == 180.0
    assert position["current_price"] == 190.0
    assert position["market_value"] == 1900.0
    assert position["unrealized_pnl"] == 100.0
    assert position["unrealized_pnl_percent"] == 5.56


def test_totals_aggregate_across_positions(cache):
    upsert_position("AAPL", 10.0, 180.0)
    upsert_position("MSFT", 2.0, 400.0)

    portfolio = build_portfolio(cache)
    assert portfolio["positions_value"] == 1900.0 + 840.0
    assert portfolio["total_cost_basis"] == 1800.0 + 800.0
    assert portfolio["total_unrealized_pnl"] == 140.0
    assert portfolio["total_value"] == 10000.0 + 2740.0


def test_unpriced_position_falls_back_to_avg_cost(cache):
    upsert_position("ZZZZ", 4.0, 25.0)

    position = next(p for p in build_portfolio(cache)["positions"] if p["ticker"] == "ZZZZ")
    assert position["current_price"] == 25.0
    assert position["market_value"] == 100.0
    assert position["unrealized_pnl"] == 0.0


def test_positions_sorted_by_market_value_desc(cache):
    upsert_position("AAPL", 1.0, 190.0)
    upsert_position("MSFT", 2.0, 420.0)
    upsert_position("GOOGL", 1.0, 175.0)

    tickers = [p["ticker"] for p in build_portfolio(cache)["positions"]]
    assert tickers == ["MSFT", "AAPL", "GOOGL"]


def test_weights_are_fractions_of_total_value(cache):
    upsert_position("MSFT", 2.0, 420.0)

    portfolio = build_portfolio(cache)
    weight = portfolio["positions"][0]["weight"]
    assert weight == pytest.approx(840.0 / portfolio["total_value"], abs=1e-4)
    assert 0 < weight < 1


def test_total_portfolio_value_matches_build(cache):
    upsert_position("AAPL", 3.0, 100.0)
    assert total_portfolio_value(cache) == build_portfolio(cache)["total_value"]


# --- execute_trade: happy paths ---


def test_buy_debits_cash_and_opens_position(cache):
    result = execute_trade(cache, "AAPL", "buy", 10)

    assert result["trade"]["ticker"] == "AAPL"
    assert result["trade"]["side"] == "buy"
    assert result["trade"]["quantity"] == 10.0
    assert result["trade"]["price"] == 190.0
    assert result["cash_balance"] == 8100.0
    assert result["position"] == {"ticker": "AAPL", "quantity": 10.0, "avg_cost": 190.0}
    assert result["total_value"] == 10000.0
    assert get_cash_balance() == pytest.approx(8100.0)
    assert get_position("AAPL")["quantity"] == 10.0


def test_ticker_is_normalised(cache):
    result = execute_trade(cache, " aapl ", "buy", 1)
    assert result["trade"]["ticker"] == "AAPL"
    assert get_position("AAPL") is not None


def test_buy_averages_cost_basis(cache):
    execute_trade(cache, "AAPL", "buy", 10)
    cache.update("AAPL", 210.0)
    result = execute_trade(cache, "AAPL", "buy", 10)

    assert result["position"]["quantity"] == 20.0
    assert result["position"]["avg_cost"] == 200.0


def test_fractional_shares_supported(cache):
    result = execute_trade(cache, "AAPL", "buy", 0.5)
    assert result["position"]["quantity"] == 0.5
    assert result["cash_balance"] == 9905.0


def test_sell_credits_cash_and_keeps_avg_cost(cache):
    execute_trade(cache, "AAPL", "buy", 10)
    cache.update("AAPL", 200.0)
    result = execute_trade(cache, "AAPL", "sell", 4)

    assert result["position"] == {"ticker": "AAPL", "quantity": 6.0, "avg_cost": 190.0}
    assert result["cash_balance"] == 8900.0


def test_selling_everything_closes_the_position(cache):
    execute_trade(cache, "AAPL", "buy", 10)
    result = execute_trade(cache, "AAPL", "sell", 10)

    assert result["position"] is None
    assert get_position("AAPL") is None


def test_dust_quantity_closes_the_position(cache):
    upsert_position("AAPL", 1.0, 190.0)
    result = execute_trade(cache, "AAPL", "sell", 1.0 - 1e-12)
    assert result["position"] is None


def test_trade_is_logged_and_snapshotted(cache):
    execute_trade(cache, "AAPL", "buy", 2)

    trades = list_trades()
    assert len(trades) == 1
    assert trades[0]["ticker"] == "AAPL"

    snapshots = list_snapshots()
    assert len(snapshots) == 1
    assert snapshots[0]["total_value"] == pytest.approx(10000.0)


def test_buying_off_watchlist_ticker_does_not_add_it(cache):
    cache.update("PYPL", 60.0)
    before = list_watchlist()
    execute_trade(cache, "PYPL", "buy", 1)
    assert list_watchlist() == before
    assert "PYPL" not in before


# --- execute_trade: failures ---


def test_insufficient_cash_message(cache):
    with pytest.raises(TradeError) as exc:
        execute_trade(cache, "MSFT", "buy", 100)
    assert str(exc.value) == "Insufficient cash: need $42000.00, have $10000.00"
    assert get_cash_balance() == 10000.0
    assert get_position("MSFT") is None


def test_insufficient_shares_message(cache):
    upsert_position("AAPL", 3.0, 100.0)
    with pytest.raises(TradeError) as exc:
        execute_trade(cache, "AAPL", "sell", 10)
    assert str(exc.value) == "Insufficient shares: tried to sell 10 AAPL, hold 3"
    assert get_position("AAPL")["quantity"] == 3.0


def test_selling_nothing_held_reports_zero(cache):
    with pytest.raises(TradeError) as exc:
        execute_trade(cache, "AAPL", "sell", 2)
    assert str(exc.value) == "Insufficient shares: tried to sell 2 AAPL, hold 0"


def test_unknown_price_raises_price_unavailable(cache):
    with pytest.raises(PriceUnavailableError) as exc:
        execute_trade(cache, "NFLX", "buy", 1)
    assert str(exc.value) == "No price available for NFLX"


@pytest.mark.parametrize("quantity", [0, -5])
def test_non_positive_quantity_rejected(cache, quantity):
    with pytest.raises(TradeError) as exc:
        execute_trade(cache, "AAPL", "buy", quantity)
    assert str(exc.value) == "Quantity must be greater than zero"


def test_invalid_side_rejected(cache):
    with pytest.raises(TradeError):
        execute_trade(cache, "AAPL", "short", 1)


def test_failed_trade_writes_nothing(cache):
    with pytest.raises(TradeError):
        execute_trade(cache, "AAPL", "buy", 1000)
    assert list_trades() == []
    assert list_snapshots() == []


# --- atomicity and concurrency ---


def test_rollback_undoes_a_failure_partway_through(cache, monkeypatch):
    """Cash and the position are written before the trade log; a failure after
    those writes must leave the database exactly as it was."""
    monkeypatch.setattr(
        "app.services.portfolio.record_trade",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("disk on fire")),
    )

    with pytest.raises(RuntimeError, match="disk on fire"):
        execute_trade(cache, "AAPL", "buy", 10)

    assert get_cash_balance() == 10000.0
    assert get_position("AAPL") is None
    assert list_trades() == []
    assert list_snapshots() == []


def test_rollback_undoes_a_failed_snapshot(cache, monkeypatch):
    """The snapshot is the last write; failing there rolls back the trade too."""
    execute_trade(cache, "AAPL", "buy", 1)
    cash_before = get_cash_balance()
    trades_before = len(list_trades())
    snapshots_before = len(list_snapshots())

    monkeypatch.setattr(
        "app.services.portfolio.record_snapshot",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("nope")),
    )
    with pytest.raises(RuntimeError, match="nope"):
        execute_trade(cache, "AAPL", "buy", 1)

    assert get_cash_balance() == cash_before
    assert get_position("AAPL")["quantity"] == 1.0
    assert len(list_trades()) == trades_before
    assert len(list_snapshots()) == snapshots_before


def _buy_from_threads(cache, ticker, quantity, thread_count):
    """Run `thread_count` concurrent buys; return (executed, rejections)."""
    executed: list[dict] = []
    rejected: list[str] = []
    lock = threading.Lock()
    start = threading.Barrier(thread_count)

    def worker() -> None:
        start.wait()
        try:
            result = execute_trade(cache, ticker, "buy", quantity)
        except TradeError as exc:
            with lock:
                rejected.append(str(exc))
        else:
            with lock:
                executed.append(result)

    threads = [threading.Thread(target=worker) for _ in range(thread_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not any(thread.is_alive() for thread in threads), "a trade thread hung"
    return executed, rejected


def test_concurrent_buys_do_not_lose_updates(cache):
    executed, rejected = _buy_from_threads(cache, "AAPL", 1, thread_count=20)

    assert len(executed) == 20
    assert rejected == []
    spent = sum(t["trade"]["quantity"] * t["trade"]["price"] for t in executed)
    assert get_cash_balance() == pytest.approx(10000.0 - spent)
    assert get_position("AAPL")["quantity"] == pytest.approx(20.0)
    assert len(list_trades()) == 20
    assert len(list_snapshots()) == 20


def test_concurrent_buys_never_spend_money_that_is_not_there(cache):
    # Exactly five shares of AAPL are affordable at $190.
    set_cash_balance(950.0)

    executed, rejected = _buy_from_threads(cache, "AAPL", 1, thread_count=20)

    assert len(executed) == 5
    assert len(rejected) == 15
    assert all(message.startswith("Insufficient cash:") for message in rejected)

    spent = sum(t["trade"]["quantity"] * t["trade"]["price"] for t in executed)
    final_cash = get_cash_balance()
    assert final_cash == pytest.approx(950.0 - spent)
    assert final_cash >= 0.0
    assert get_position("AAPL")["quantity"] == pytest.approx(5.0)
    assert len(list_trades()) == 5
