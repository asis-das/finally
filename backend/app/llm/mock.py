"""Deterministic mock assistant — no network, no randomness, no clock.

The E2E suite is written against these rules, so they are frozen: see
``backend/app/llm/README.md`` for the authoritative description. Change the
README and the tests together or not at all.
"""

from __future__ import annotations

import re

from .schemas import ChatResponse, Trade, WatchlistChange

#: Company names the mock understands, matched case-insensitively as whole words.
NAME_TO_TICKER = {
    "apple": "AAPL",
    "google": "GOOGL",
    "microsoft": "MSFT",
    "tesla": "TSLA",
    "nvidia": "NVDA",
    "amazon": "AMZN",
    "meta": "META",
    "netflix": "NFLX",
}

#: Uppercase words that look like tickers but are ordinary English. Without this
#: list "BUY 5 AAPL" would resolve the ticker to "BUY".
STOP_WORDS = frozenset(
    {
        "A", "ADD", "ALL", "AN", "AND", "ANY", "ARE", "AT", "BUY", "BY", "CAN", "DO",
        "FOR", "GET", "HOW", "I", "IF", "IN", "IS", "IT", "ME", "MY", "NEW", "NO",
        "NOT", "NOW", "OF", "OK", "ON", "OR", "OUT", "PLS", "PUT", "SELL", "SO",
        "THE", "TO", "UP", "US", "USD", "WHAT", "WHY", "YES", "YOU",
    }
)

_TICKER_TOKEN = re.compile(r"\b[A-Z]{1,5}\b")
_NAME_TOKEN = re.compile(r"\b(" + "|".join(NAME_TO_TICKER) + r")\b", re.IGNORECASE)
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_WORD = {word: re.compile(rf"\b{word}\b", re.IGNORECASE) for word in ("buy", "sell", "add", "remove")}


def _format_quantity(quantity: float) -> str:
    """10.0 -> '10', 2.5 -> '2.5'."""
    return f"{quantity:g}"


def extract_ticker(message: str) -> str | None:
    """First ticker in the message, scanning left to right.

    Candidates are uppercase tokens of 1-5 letters that are not stop words, and
    company names from :data:`NAME_TO_TICKER`. Whichever appears earliest in the
    message wins; ties are impossible because the spans cannot start at the
    same offset with different casing requirements.
    """
    candidates: list[tuple[int, str]] = []
    for match in _TICKER_TOKEN.finditer(message):
        token = match.group(0)
        if token not in STOP_WORDS:
            candidates.append((match.start(), token))
    for match in _NAME_TOKEN.finditer(message):
        candidates.append((match.start(), NAME_TO_TICKER[match.group(0).lower()]))
    if not candidates:
        return None
    return min(candidates, key=lambda pair: pair[0])[1]


def extract_quantity(message: str) -> float | None:
    """The first number in the message, or ``None``."""
    match = _NUMBER.search(message)
    return float(match.group(0)) if match else None


def _summary(context: dict) -> str:
    portfolio = context.get("portfolio") or {}
    cash = portfolio.get("cash_balance", 0.0) or 0.0
    positions = portfolio.get("positions") or []
    total = portfolio.get("total_value", 0.0) or 0.0
    return (
        f"You have ${cash:,.2f} in cash across {len(positions)} positions, "
        f"total value ${total:,.2f}."
    )


def mock_response(user_message: str, context: dict) -> ChatResponse:
    """The deterministic reply for ``user_message`` given the live ``context``."""
    text = user_message or ""
    ticker = extract_ticker(text)
    quantity = extract_quantity(text)

    if ticker is not None and quantity is not None:
        for side, verb in (("buy", "Bought"), ("sell", "Sold")):
            if _WORD[side].search(text):
                return ChatResponse(
                    message=f"{verb} {_format_quantity(quantity)} {ticker}.",
                    trades=[Trade(ticker=ticker, side=side, quantity=quantity)],
                )

    if ticker is not None:
        if _WORD["add"].search(text):
            return ChatResponse(
                message=f"Added {ticker} to your watchlist.",
                watchlist_changes=[WatchlistChange(ticker=ticker, action="add")],
            )
        if _WORD["remove"].search(text):
            return ChatResponse(
                message=f"Removed {ticker} from your watchlist.",
                watchlist_changes=[WatchlistChange(ticker=ticker, action="remove")],
            )

    return ChatResponse(message=_summary(context))
