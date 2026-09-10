"""The LiteLLM -> OpenRouter call, with the spend guard and failure handling.

Structure follows the ``cerebras`` skill (LiteLLM ``completion``, structured
outputs, ``extra_body`` provider preferences); the provider order is configurable
and empty by default so free models on any provider can serve the request.
"""

from __future__ import annotations

import json
import logging
import re

from litellm import completion

from . import config
from .schemas import ChatResponse

logger = logging.getLogger(__name__)

#: Appended on the retry after the model returns something that is not the
#: required JSON object.
RETRY_INSTRUCTION = (
    "Your previous reply was not valid JSON for the required schema. Reply with a "
    "single JSON object and nothing else: "
    '{"message": "...", "trades": [], "watchlist_changes": []}'
)

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


class LLMError(Exception):
    """The provider call failed. Callers degrade gracefully; never a 500."""


class LLMTimeoutError(LLMError):
    """The provider did not answer within ``OPENROUTER_TIMEOUT`` seconds."""


class MalformedResponseError(LLMError):
    """The model answered, but not with the required JSON object."""


def _is_timeout(exc: BaseException) -> bool:
    """LiteLLM normalises provider timeouts inconsistently across versions, so
    match on the exception's own name rather than importing a moving target."""
    for error in (exc, exc.__cause__, exc.__context__):
        if error is None:
            continue
        name = type(error).__name__
        if "Timeout" in name or "TimedOut" in name:
            return True
    return False


def parse_response(content: str | None) -> ChatResponse:
    """Parse a model reply into :class:`ChatResponse`.

    Tolerates a ``json`` code fence or prose wrapped around the object, because
    not every free model honours ``response_format`` strictly.
    """
    if not content or not content.strip():
        raise MalformedResponseError("The model returned an empty response")

    candidates = [content.strip()]
    fenced = _JSON_FENCE.search(content)
    if fenced:
        candidates.append(fenced.group(1))
    braced = _JSON_OBJECT.search(content)
    if braced:
        candidates.append(braced.group(0))

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        try:
            return ChatResponse.model_validate(payload)
        except Exception:  # noqa: BLE001 - any validation failure -> try the next candidate
            continue

    raise MalformedResponseError("The model response was not valid JSON for the schema")


def _completion_kwargs(messages: list[dict]) -> dict:
    kwargs: dict = {
        "model": config.litellm_model(),
        "messages": messages,
        "response_format": ChatResponse,
        "api_key": config.api_key(),
        "timeout": config.timeout_seconds(),
        # Free models vary wildly in what they accept — OpenRouter rejects
        # reasoning_effort for most of them, and not all support structured
        # outputs. Drop what a model cannot take instead of failing the call;
        # parse_response already tolerates a reply that ignored the schema.
        "drop_params": True,
    }
    effort = config.reasoning_effort()
    if effort:
        kwargs["reasoning_effort"] = effort
    order = config.provider_order()
    if order:
        kwargs["extra_body"] = {"provider": {"order": order}}
    return kwargs


def _content_of(response) -> str | None:
    try:
        return response.choices[0].message.content
    except (AttributeError, IndexError, KeyError, TypeError) as exc:
        raise MalformedResponseError(f"Unexpected response shape: {exc}") from exc


def _call(messages: list[dict]) -> ChatResponse:
    try:
        response = completion(**_completion_kwargs(messages))
    except Exception as exc:  # noqa: BLE001 - every provider failure degrades the same way
        if _is_timeout(exc):
            raise LLMTimeoutError(str(exc)) from exc
        raise LLMError(str(exc)) from exc
    return parse_response(_content_of(response))


def complete(messages: list[dict]) -> ChatResponse:
    """One structured completion, with a single retry on a malformed reply.

    Blocking — call it from a worker thread, not the event loop.

    Raises :class:`LLMTimeoutError`, :class:`MalformedResponseError` or
    :class:`LLMError`; the caller turns all three into a graceful 200.
    """
    reason = config.mock_reason()
    if reason is not None:  # pragma: no cover - the service checks first
        raise LLMError(f"Live inference is disabled: {reason}")

    try:
        return _call(messages)
    except MalformedResponseError as first:
        logger.warning("Malformed LLM response (%s); retrying once", first)

    retry_messages = [*messages, {"role": "system", "content": RETRY_INSTRUCTION}]
    return _call(retry_messages)
