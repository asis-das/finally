"""System prompt and portfolio-context construction.

The model never sees a database; everything it is allowed to reason about is
serialised here. Prices in the context are the live ones from the price cache,
which is why the prompt forbids inventing any.
"""

from __future__ import annotations

import json

from app.db import list_watchlist
from app.market import PriceCache
from app.services.portfolio import build_portfolio

SYSTEM_PROMPT = """You are FinAlly, an AI trading assistant embedded in a simulated \
trading workstation. The user trades a virtual $10,000 portfolio; no real money is \
involved.

How to respond:
- Be concise and data-driven. Two or three sentences unless the user asks for depth.
- Analyse what the numbers actually show: portfolio composition, concentration risk, \
diversification, and realised/unrealised P&L.
- Suggest trades with a short reason. Say what you would do and why.

Rules you must never break:
- Only emit a trade in `trades` when the user asked for it or explicitly agreed to it. \
Suggesting a trade in `message` is not permission to execute it.
- Use exact uppercase ticker symbols from the context. Never guess a symbol.
- `quantity` is a share count, not a dollar amount. If the user asks in dollars, divide \
by the current price from the context and say what you did.
- Never invent, estimate, or recall prices. Every price you state must come from the \
PORTFOLIO CONTEXT block below.
- Only sell shares the context shows as held.
- NEVER change a quantity the user stated. Emit exactly the number they asked for, even when the cash balance cannot cover it or they hold fewer shares than that. Do not round, scale, clamp, or substitute a "safer" size. Every trade is validated and an impossible one is rejected with an accurate error the user sees; silently resizing a trade executes something the user never asked for, and explaining it in `message` is not their consent.
- If a requested trade cannot succeed, still emit it exactly as asked, and use `message` to say why it will fail and offer an alternative they can accept next turn - for example "that needs $950,000 but you have $8,075; I could buy 42 shares instead - want me to?".
- Choose a quantity yourself only when the user left it to you ("buy some NVDA", "invest half my cash"). Only then may you size the trade to the available cash, and say what you chose.
- You may manage the watchlist proactively via `watchlist_changes`; a ticker must be on \
the watchlist (or already held) before it has a price and can be traded.
- Always respond with valid JSON matching the required schema. `message` is required; \
`trades` and `watchlist_changes` are empty arrays when there is nothing to do.
"""

#: Chat turns fed back to the model. Deliberately small — the context block
#: below already carries the current state, so older turns add little.
HISTORY_LIMIT = 20


def build_context(price_cache: PriceCache, user_id: str | None = None) -> dict:
    """Snapshot everything the model is allowed to reason about."""
    portfolio = (
        build_portfolio(price_cache)
        if user_id is None
        else build_portfolio(price_cache, user_id)
    )
    watchlist = []
    tickers = list_watchlist() if user_id is None else list_watchlist(user_id)
    for ticker in tickers:
        update = price_cache.get(ticker)
        watchlist.append(
            {
                "ticker": ticker,
                "price": round(update.price, 2) if update else None,
                "change_percent": round(update.change_percent, 2) if update else 0.0,
            }
        )
    return {"portfolio": portfolio, "watchlist": watchlist}


def render_context(context: dict) -> str:
    """The context block appended to the system message."""
    return (
        "PORTFOLIO CONTEXT (live, authoritative — use these numbers verbatim):\n"
        f"{json.dumps(context, indent=2, sort_keys=True)}"
    )


def build_messages(context: dict, history: list[dict], user_message: str) -> list[dict]:
    """Assemble the full chat payload: system + context, prior turns, new message.

    ``history`` is oldest-first as returned by ``list_chat_messages`` and must
    not already contain ``user_message``.
    """
    messages: list[dict] = [
        {"role": "system", "content": f"{SYSTEM_PROMPT}\n{render_context(context)}"}
    ]
    for entry in history:
        role = entry.get("role")
        if role not in ("user", "assistant"):
            continue
        messages.append({"role": role, "content": entry.get("content") or ""})
    messages.append({"role": "user", "content": user_message})
    return messages
