"""The deterministic mock assistant. These rules are frozen — the E2E suite and
``app/llm/README.md`` are written against them.
"""

from __future__ import annotations

import pytest

from app.llm.mock import extract_quantity, extract_ticker, mock_response

EMPTY_CONTEXT = {
    "portfolio": {"cash_balance": 10000.0, "positions": [], "total_value": 10000.0},
    "watchlist": [],
}

RICH_CONTEXT = {
    "portfolio": {
        "cash_balance": 8075.5,
        "positions": [{"ticker": "AAPL"}, {"ticker": "MSFT"}],
        "total_value": 12345.67,
    },
    "watchlist": [],
}


class TestTickerExtraction:
    @pytest.mark.parametrize(
        "message,expected",
        [
            ("buy 10 AAPL", "AAPL"),
            ("BUY 5 AAPL", "AAPL"),
            ("SELL 5 TSLA NOW", "TSLA"),
            ("buy 10 apple shares", "AAPL"),
            ("Buy 3 shares of Netflix please", "NFLX"),
            ("add PYPL to my watchlist", "PYPL"),
            ("what is my portfolio worth?", None),
            ("hello there", None),
        ],
    )
    def test_extraction(self, message, expected):
        assert extract_ticker(message) == expected

    def test_earliest_candidate_wins(self):
        assert extract_ticker("MSFT then AAPL") == "MSFT"
        assert extract_ticker("tesla or NVDA") == "TSLA"

    def test_stop_words_are_never_tickers(self):
        assert extract_ticker("BUY IT NOW") is None
        # ...but an uppercase word that is not on the list still looks like one.
        assert extract_ticker("BUY THE DIP") == "DIP"

    def test_names_map_case_insensitively(self):
        for name, ticker in (
            ("apple", "AAPL"),
            ("GOOGLE", "GOOGL"),
            ("Microsoft", "MSFT"),
            ("tesla", "TSLA"),
            ("nvidia", "NVDA"),
            ("amazon", "AMZN"),
            ("meta", "META"),
            ("netflix", "NFLX"),
        ):
            assert extract_ticker(f"tell me about {name} today") == ticker


class TestQuantityExtraction:
    @pytest.mark.parametrize(
        "message,expected",
        [("buy 10 AAPL", 10.0), ("buy 2.5 AAPL", 2.5), ("buy AAPL", None), ("", None)],
    )
    def test_extraction(self, message, expected):
        assert extract_quantity(message) == expected

    def test_first_number_wins(self):
        assert extract_quantity("buy 3 AAPL and 7 MSFT") == 3.0


class TestIntents:
    def test_buy(self):
        reply = mock_response("buy 10 AAPL", EMPTY_CONTEXT)
        assert reply.message == "Bought 10 AAPL."
        assert len(reply.trades) == 1
        assert reply.trades[0].model_dump() == {
            "ticker": "AAPL",
            "side": "buy",
            "quantity": 10.0,
        }
        assert reply.watchlist_changes == []

    def test_sell(self):
        reply = mock_response("sell 2.5 tesla", EMPTY_CONTEXT)
        assert reply.message == "Sold 2.5 TSLA."
        assert reply.trades[0].side == "sell"
        assert reply.trades[0].quantity == 2.5

    def test_add(self):
        reply = mock_response("add PYPL", EMPTY_CONTEXT)
        assert reply.message == "Added PYPL to your watchlist."
        assert reply.watchlist_changes[0].model_dump() == {"ticker": "PYPL", "action": "add"}
        assert reply.trades == []

    def test_remove(self):
        reply = mock_response("remove NVDA from the watchlist", EMPTY_CONTEXT)
        assert reply.message == "Removed NVDA from your watchlist."
        assert reply.watchlist_changes[0].action == "remove"

    def test_add_ignores_a_quantity(self):
        reply = mock_response("add 5 PYPL", EMPTY_CONTEXT)
        assert reply.watchlist_changes[0].ticker == "PYPL"
        assert reply.trades == []

    def test_buy_without_a_quantity_is_not_a_trade(self):
        reply = mock_response("buy AAPL", EMPTY_CONTEXT)
        assert reply.trades == []
        assert reply.watchlist_changes == []
        assert reply.message.startswith("You have $")

    def test_buy_beats_sell_when_both_appear(self):
        reply = mock_response("sell 4 AAPL and buy 4 MSFT", EMPTY_CONTEXT)
        assert len(reply.trades) == 1
        assert reply.trades[0].side == "buy"
        assert reply.trades[0].ticker == "AAPL"

    def test_summary_uses_real_context(self):
        reply = mock_response("how am I doing?", RICH_CONTEXT)
        assert reply.message == (
            "You have $8,075.50 in cash across 2 positions, total value $12,345.67."
        )
        assert reply.trades == []
        assert reply.watchlist_changes == []

    def test_summary_on_a_fresh_portfolio(self):
        reply = mock_response("hello", EMPTY_CONTEXT)
        assert reply.message == (
            "You have $10,000.00 in cash across 0 positions, total value $10,000.00."
        )

    def test_summary_tolerates_an_empty_context(self):
        reply = mock_response("hello", {})
        assert reply.message == "You have $0.00 in cash across 0 positions, total value $0.00."


class TestDeterminism:
    @pytest.mark.parametrize(
        "message", ["buy 10 AAPL", "sell 1 MSFT", "add PYPL", "remove V", "how am I doing?"]
    )
    def test_same_input_same_output(self, message):
        first = mock_response(message, RICH_CONTEXT)
        second = mock_response(message, RICH_CONTEXT)
        assert first.model_dump() == second.model_dump()
