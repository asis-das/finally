"""Structured-output schema for the assistant, and the request/response models
for the chat endpoints.

``ChatResponse`` is handed to LiteLLM as ``response_format``, so its field names
and docstrings are part of the prompt the model sees — keep them descriptive.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Trade(BaseModel):
    """A market order the assistant wants executed."""

    ticker: str = Field(description="Exact uppercase ticker symbol, e.g. AAPL")
    side: Literal["buy", "sell"]
    quantity: float = Field(description="Number of shares, may be fractional, must be > 0")


class WatchlistChange(BaseModel):
    """An addition to or removal from the user's watchlist."""

    ticker: str = Field(description="Exact uppercase ticker symbol, e.g. PYPL")
    action: Literal["add", "remove"]


class ChatResponse(BaseModel):
    """The complete structured reply from the assistant."""

    message: str = Field(description="Conversational response shown to the user")
    trades: list[Trade] = Field(
        default_factory=list,
        description="Trades to execute now. Empty unless the user asked for or agreed to them.",
    )
    watchlist_changes: list[WatchlistChange] = Field(
        default_factory=list, description="Watchlist edits to apply now."
    )


class ChatRequest(BaseModel):
    """Body of ``POST /api/chat``."""

    message: str
