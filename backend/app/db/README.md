# app.db

The FinAlly database layer: `schema.sql` (six tables per `planning/PLAN.md` §7),
`database.py` (connection management + lazy init), `repository.py` (all queries).
Import everything from the package root: `from app.db import ...` — see
`app/db/__init__.py` for the full export list.

## Connections

```python
from app.db import init_db, get_connection, transaction
```

- `init_db(db_path=None)` — idempotent, call once at startup. Creates the schema and
  seeds default data only if the relevant tables are empty; never wipes existing data.
- `get_connection()` — a context manager yielding a short-lived read connection
  (`row_factory=sqlite3.Row`, `foreign_keys=ON`). No commit/rollback semantics; use it
  for reads or anything you'll commit yourself.
- `transaction()` — same, but commits on success and rolls back on any exception
  raised inside the `with` block.

Every call to `get_connection()`/`transaction()` opens its own sqlite3 connection
(WAL mode, `busy_timeout=5000`, `check_same_thread=False`) and closes it on exit.
There is no shared/module-level connection, so there's nothing to lock across threads
— this is what makes it safe for FastAPI's threadpool plus the background snapshot task.

## Atomic multi-step writes: the `conn=` parameter

Every repository function — reads and writes — accepts an optional, **keyword-only**
`conn` parameter:

```python
def upsert_position(ticker, quantity, avg_cost, user_id=DEFAULT_USER_ID, *, conn=None) -> None: ...
def get_cash_balance(user_id=DEFAULT_USER_ID, *, conn=None) -> float: ...
```

- **Omit `conn`** (the default): the function opens its own connection and commits
  (writes) or just reads and closes (reads) — exactly the original standalone
  behaviour. Nothing that already calls these functions needs to change.
- **Pass `conn`**: the function runs its statement(s) against *that* connection and
  does **not** commit or roll back — the caller owns the transaction boundary. Use
  this to make a multi-function sequence atomic:

```python
from app.db import database, repository

with database.transaction() as conn:
    repository.set_cash_balance(new_balance, conn=conn)
    repository.upsert_position(ticker, qty, avg_cost, conn=conn)
    trade = repository.record_trade(ticker, "buy", qty, price, conn=conn)
    repository.record_snapshot(total_value, conn=conn)
# All four writes commit together here, or none do if an exception was raised
# anywhere in the block (e.g. a validation error partway through).
```

This is the pattern `services.portfolio.execute_trade` uses so that cash, position,
trade log, and snapshot land as one all-or-nothing unit — a crash or exception
partway through leaves the database exactly as it was before the trade started.

Reads (`get_profile`, `get_cash_balance`, `get_position`, `list_positions`, etc.) also
accept `conn` so you can read a consistent, not-yet-committed view from inside the same
transaction (e.g. reading the current cash balance before writing the new one).

### Rules of thumb

- Never call `conn.commit()` / `conn.rollback()` yourself inside a function that
  received `conn` — that's the outer `transaction()` block's job.
- Don't mix: don't pass a connection from `get_connection()` (no auto-commit) into a
  write call and then forget to commit it yourself — prefer `transaction()` as the
  outer context whenever you're enlisting writes.
- Tickers are still normalised (upper + stripped) regardless of whether `conn` is
  passed.
