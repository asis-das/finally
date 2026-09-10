"""FinAlly database layer.

Public API:
    init_db, get_connection, transaction, DEFAULT_USER_ID  - connection management
    get_profile, get_cash_balance, set_cash_balance          - profile
    list_watchlist, add_watchlist_ticker, remove_watchlist_ticker - watchlist
    list_positions, get_position, upsert_position, delete_position - positions
    record_trade, list_trades                                - trades
    record_snapshot, list_snapshots                           - portfolio snapshots
    add_chat_message, list_chat_messages                      - chat history
"""

from .database import DEFAULT_USER_ID, get_connection, init_db, transaction
from .repository import (
    add_chat_message,
    add_watchlist_ticker,
    delete_position,
    get_cash_balance,
    get_position,
    get_profile,
    list_chat_messages,
    list_positions,
    list_snapshots,
    list_trades,
    list_watchlist,
    record_snapshot,
    record_trade,
    remove_watchlist_ticker,
    set_cash_balance,
    upsert_position,
)

__all__ = [
    "DEFAULT_USER_ID",
    "get_connection",
    "init_db",
    "transaction",
    "get_profile",
    "get_cash_balance",
    "set_cash_balance",
    "list_watchlist",
    "add_watchlist_ticker",
    "remove_watchlist_ticker",
    "list_positions",
    "get_position",
    "upsert_position",
    "delete_position",
    "record_trade",
    "list_trades",
    "record_snapshot",
    "list_snapshots",
    "add_chat_message",
    "list_chat_messages",
]
