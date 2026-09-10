"""FinAlly LLM layer.

Public API:
    ChatRequest, ChatResponse, Trade, WatchlistChange - structured schemas
    handle_chat, chat_history                          - the chat flow
    mock_response                                       - deterministic mock assistant
    config                                              - env-driven settings + spend guard

See ``README.md`` in this package for the mock rules and configuration.
"""

from . import config
from .mock import mock_response
from .schemas import ChatRequest, ChatResponse, Trade, WatchlistChange
from .service import chat_history, handle_chat

__all__ = [
    "ChatRequest",
    "ChatResponse",
    "Trade",
    "WatchlistChange",
    "chat_history",
    "config",
    "handle_chat",
    "mock_response",
]
