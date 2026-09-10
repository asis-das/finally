"""Chat orchestration: persist, contextualise, infer, execute, persist, return.

This is the only module that knows the whole flow. The route layer is a thin
adapter over :func:`handle_chat`.
"""

from __future__ import annotations

import asyncio
import logging

from app.db import add_chat_message, list_chat_messages
from app.market import MarketDataSource, PriceCache

from . import client, config
from .actions import apply_actions
from .mock import mock_response
from .prompt import HISTORY_LIMIT, build_context, build_messages
from .schemas import ChatResponse

logger = logging.getLogger(__name__)

#: Shown when the provider times out. Free-tier queues can run into minutes,
#: so this is a normal outcome, not an error state.
TIMEOUT_MESSAGE = (
    "Sorry — the AI model is taking longer than expected to respond right now "
    "(free-tier inference can queue). Nothing was changed in your portfolio. "
    "Please try again in a moment."
)

#: Shown for any other provider failure.
UNAVAILABLE_MESSAGE = (
    "Sorry — the AI assistant is unavailable right now. Nothing was changed in "
    "your portfolio. Please try again shortly."
)

_free_only_warned = False


def _warn_free_only_once(reason: str) -> None:
    """Log the spend guard loudly, but only once per process."""
    global _free_only_warned
    if _free_only_warned:
        return
    _free_only_warned = True
    logger.warning(
        "=" * 72
        + "\nOPENROUTER SPEND GUARD: falling back to MOCK mode.\n  %s\n"
        "  Set OPENROUTER_MODEL to a ':free' model id, or set "
        "OPENROUTER_FREE_ONLY=false to allow paid calls.\n" + "=" * 72,
        reason,
    )


def _prior_history(exclude_id: str) -> list[dict]:
    """Recent turns, oldest first, minus the message we just persisted."""
    history = list_chat_messages(limit=HISTORY_LIMIT + 1)
    return [entry for entry in history if entry.get("id") != exclude_id][-HISTORY_LIMIT:]


async def _infer(
    user_message: str, context: dict, history: list[dict]
) -> tuple[ChatResponse, bool]:
    """Produce the assistant's structured reply.

    The second element says whether the reply may act: mock replies and real
    model replies both do, a graceful failure does not — a provider outage must
    never half-execute a trade.
    """
    reason = config.mock_reason()
    if reason is not None:
        if config.free_only() and not config.is_free_model() and config.api_key():
            _warn_free_only_once(reason)
        logger.info("Chat served in mock mode (%s)", reason)
        return mock_response(user_message, context), True

    messages = build_messages(context, history, user_message)
    try:
        # Blocking network call with its own timeout; keep it off the event loop.
        reply = await asyncio.to_thread(client.complete, messages)
    except client.LLMTimeoutError:
        logger.warning("LLM call timed out after %gs", config.timeout_seconds())
        return ChatResponse(message=TIMEOUT_MESSAGE), False
    except client.LLMError as exc:
        logger.warning("LLM call failed: %s", exc)
        return ChatResponse(message=UNAVAILABLE_MESSAGE), False
    except Exception:  # noqa: BLE001 - an LLM failure is never a 500 for the user
        logger.exception("Unexpected LLM failure")
        return ChatResponse(message=UNAVAILABLE_MESSAGE), False

    return reply, True


async def handle_chat(
    user_message: str, price_cache: PriceCache, source: MarketDataSource
) -> dict:
    """Run one chat turn and return the ``POST /api/chat`` payload."""
    persisted_user = add_chat_message("user", user_message)
    context = build_context(price_cache)
    history = _prior_history(persisted_user["id"])

    reply, may_act = await _infer(user_message, context, history)
    actions = await apply_actions(reply, price_cache, source) if may_act else []

    persisted = add_chat_message("assistant", reply.message, actions)
    return {
        "message": reply.message,
        "actions": actions,
        "created_at": persisted["created_at"],
    }


def chat_history(limit: int = 50) -> dict:
    """The ``GET /api/chat/history`` payload — oldest first."""
    return {"messages": list_chat_messages(limit=limit)}
