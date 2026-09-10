"""Environment-driven configuration for the FinAlly backend.

Every setting is read from ``os.environ`` at call time so that tests can
monkeypatch the environment without reimporting the module. In local
development the project-root ``.env`` is loaded once (never overriding real
environment variables); in Docker the variables are injected with
``--env-file`` and the ``.env`` file simply is not present.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# backend/app/config.py -> backend/app -> backend -> <project root>
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_DB_PATH = "db/finally.db"
DEFAULT_STATIC_DIR = "static"
DEV_CORS_ORIGINS = ["http://localhost:3000"]

#: Value shipped in the committed .env; treated as "no key configured".
PLACEHOLDER_API_KEY = "REPLACE_ME"

_TRUTHY = {"1", "true", "yes", "on"}

_env_loaded = False


def load_env(*, force: bool = False) -> None:
    """Load the project-root ``.env`` once. Real env vars always win."""
    global _env_loaded
    if _env_loaded and not force:
        return
    load_dotenv(PROJECT_ROOT / ".env", override=False)
    _env_loaded = True


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _get_bool(name: str, default: bool = False) -> bool:
    raw = _get(name)
    if not raw:
        return default
    return raw.lower() in _TRUTHY


def db_path() -> str:
    """Absolute SQLite file location.

    A relative ``FINALLY_DB_PATH`` is resolved against the project root, not the
    process working directory, so ``uvicorn`` started from ``backend/`` and from
    the repo root both land on the same ``db/finally.db``.
    """
    raw = _get("FINALLY_DB_PATH") or DEFAULT_DB_PATH
    path = Path(raw)
    return str(path if path.is_absolute() else PROJECT_ROOT / path)


def static_dir() -> Path:
    """Directory holding the exported Next.js frontend (may not exist)."""
    raw = _get("FINALLY_STATIC_DIR") or DEFAULT_STATIC_DIR
    path = Path(raw)
    return path if path.is_absolute() else (Path.cwd() / path)


def dev_cors_enabled() -> bool:
    return _get_bool("DEV_CORS", False)


def massive_api_key() -> str:
    return _get("MASSIVE_API_KEY")


def market_source_name() -> str:
    """``"massive"`` when a Massive key is configured, else ``"simulator"``."""
    return "massive" if massive_api_key() else "simulator"


def openrouter_api_key() -> str:
    """The configured key, or ``""`` when absent/empty/still the placeholder."""
    key = _get("OPENROUTER_API_KEY")
    return "" if key == PLACEHOLDER_API_KEY else key


def llm_mock_enabled() -> bool:
    """Mock mode is on when explicitly requested or when no key is configured."""
    return _get_bool("LLM_MOCK", False) or not openrouter_api_key()
