"""Environment-driven configuration for the LLM layer.

Kept separate from :mod:`app.config` (owned by another agent) but reusing its
``load_env`` / ``openrouter_api_key`` / ``llm_mock_enabled`` helpers so there is
exactly one definition of "is a key configured".

Everything is read from ``os.environ`` at call time, so tests can monkeypatch
the environment without reimporting anything.
"""

from __future__ import annotations

import os

from app import config as app_config

#: Free model used unless ``OPENROUTER_MODEL`` says otherwise. Swapping models
#: is a one-variable change; nothing in the code hardcodes a provider.
#: Chosen by benchmark across the free models that support structured outputs:
#: 4/4 on a suite where three of four prompts must produce no trades, avg 3.6s.
DEFAULT_MODEL = "nex-agi/nex-n2.5-mini:free"

#: LiteLLM routes to OpenRouter via this prefix.
OPENROUTER_PREFIX = "openrouter/"

#: OpenRouter marks zero-cost model ids with this suffix. It is the only
#: reliable spend guarantee, hence the free-only guard keys off it.
FREE_SUFFIX = ":free"

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_REASONING_EFFORT = "low"

_TRUTHY = {"1", "true", "yes", "on"}


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _get_bool(name: str, default: bool) -> bool:
    raw = _get(name)
    if not raw:
        return default
    return raw.lower() in _TRUTHY


def load_env() -> None:
    """Load the project-root ``.env`` once (real env vars always win)."""
    app_config.load_env()


def model() -> str:
    """The configured model id, exactly as written in the environment.

    No ``openrouter/`` prefix — see :func:`litellm_model` for the routed form.
    """
    raw = _get("OPENROUTER_MODEL") or DEFAULT_MODEL
    return raw[len(OPENROUTER_PREFIX) :] if raw.startswith(OPENROUTER_PREFIX) else raw


def litellm_model() -> str:
    """The model id in the form LiteLLM needs to route through OpenRouter."""
    return f"{OPENROUTER_PREFIX}{model()}"


def free_only() -> bool:
    """When true (the default), refuse to call a model without ``:free``."""
    return _get_bool("OPENROUTER_FREE_ONLY", True)


def is_free_model(model_id: str | None = None) -> bool:
    return (model_id if model_id is not None else model()).endswith(FREE_SUFFIX)


def timeout_seconds() -> float:
    raw = _get("OPENROUTER_TIMEOUT")
    if not raw:
        return DEFAULT_TIMEOUT_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS
    return value if value > 0 else DEFAULT_TIMEOUT_SECONDS


def provider_order() -> list[str]:
    """Ordered OpenRouter provider preference, empty by default.

    ``OPENROUTER_PROVIDER_ORDER=cerebras`` pins inference back to Cerebras
    without a code change.
    """
    raw = _get("OPENROUTER_PROVIDER_ORDER")
    return [part.strip() for part in raw.split(",") if part.strip()]


def reasoning_effort() -> str:
    """``""`` means "do not send the parameter at all"."""
    raw = os.environ.get("OPENROUTER_REASONING_EFFORT")
    return DEFAULT_REASONING_EFFORT if raw is None else raw.strip()


def api_key() -> str:
    """The key, or ``""`` when absent, empty, or still the ``REPLACE_ME`` placeholder."""
    return app_config.openrouter_api_key()


def mock_reason() -> str | None:
    """Why mock mode is active, or ``None`` when live inference should be used.

    Three independent triggers, checked in this order:

    1. ``LLM_MOCK=true`` — explicit.
    2. No usable ``OPENROUTER_API_KEY``.
    3. ``OPENROUTER_FREE_ONLY`` is true and the model id lacks ``:free`` —
       a hard spend guard, not a soft preference.
    """
    if _get_bool("LLM_MOCK", False):
        return "LLM_MOCK=true"
    if not api_key():
        return "OPENROUTER_API_KEY is not configured"
    if free_only() and not is_free_model():
        return (
            f"OPENROUTER_FREE_ONLY is enabled and model {model()!r} is not a "
            f"'{FREE_SUFFIX}' model, so calling it could incur spend"
        )
    return None


def mock_enabled() -> bool:
    return mock_reason() is not None
