# FinAlly — Build Contract

**Status:** Authoritative. Every agent builds against this document.
**Read `planning/PLAN.md` first** — this file resolves PLAN.md into exact signatures,
payload shapes, and file ownership so that agents working in parallel do not collide.

If you believe something here is wrong, **do not silently deviate**. Report it to the
orchestrator in your final summary and build to the contract in the meantime.

---

## 1. What already exists

`backend/app/market/` is **complete and reviewed — do not modify it.** See
`planning/MARKET_DATA_SUMMARY.md` and `backend/CLAUDE.md`.

Public API:

```python
from app.market import (
    PriceCache,               # thread-safe price store
    PriceUpdate,              # frozen dataclass
    MarketDataSource,         # ABC
    create_market_data_source,# factory, reads MASSIVE_API_KEY
    create_stream_router,     # -> APIRouter mounting GET /api/stream/prices
)
```

`PriceCache`: `update(ticker, price, timestamp=None)`, `get(ticker) -> PriceUpdate | None`,
`get_price(ticker) -> float | None`, `get_all() -> dict[str, PriceUpdate]`, `remove(ticker)`,
`.version` (monotonic int).

`MarketDataSource`: `await start(tickers)`, `await stop()`, `await add_ticker(t)`,
`await remove_ticker(t)`, `get_tickers()`.

95 tests live in `backend/tests/market/`. They must still pass at the end. Don't touch them.

---

## 2. File ownership

**Only edit files you own.** If you need a change in another agent's file, say so in your
final report; the orchestrator will route it.

| Agent | Owns |
|---|---|
| **Database Engineer** | `backend/app/db/**`, `backend/tests/db/**` |
| **Backend API Engineer** | `backend/app/main.py`, `backend/app/api/**` (except `chat.py`), `backend/app/services/portfolio.py`, `backend/app/config.py`, `backend/tests/api/**`, `backend/tests/services/**` |
| **LLM Engineer** | `backend/app/llm/**`, `backend/app/api/chat.py`, `backend/tests/llm/**` |
| **Frontend Engineer** | `frontend/**` |
| **DevOps Engineer** | `Dockerfile`, `.dockerignore`, `docker-compose.yml`, `scripts/**`, `.env.example`, `db/.gitkeep` |
| **Integration Tester** | `test/**` |

Shared, orchestrator-mediated: `backend/pyproject.toml` (adding a dependency is fine —
use `uv add`, never hand-edit the `[project] dependencies` list at the same time as
another agent; if `uv add` reports a lock conflict, retry once, then report it),
`planning/**`, `CLAUDE.md`, `README.md`.

---

## 3. Configuration

Environment variables (backend reads them via `os.environ`, `.env` loaded by
`python-dotenv` from the project root in local dev; Docker injects them with `--env-file`):

| Var | Default | Meaning |
|---|---|---|
| `OPENROUTER_API_KEY` | — | LLM key. Absent, empty, or the literal placeholder `REPLACE_ME` → chat behaves as if `LLM_MOCK=true`. |
| `MASSIVE_API_KEY` | empty | Set → real market data; empty → simulator. |
| `LLM_MOCK` | `false` | `true` → deterministic mock LLM, no network. |
| `FINALLY_DB_PATH` | `db/finally.db` | SQLite file path. Docker sets `/app/db/finally.db`. |
| `DEV_CORS` | `false` | `true` → backend allows CORS from `http://localhost:3000` (local frontend dev only). |

`.env` is gitignored; `.env.example` is committed (DevOps owns it).

A root `.env` already exists with placeholder values and `LLM_MOCK=true`; the real `OPENROUTER_API_KEY` will be supplied later. Everything must therefore work end to end with no LLM key present, and must switch to live inference the moment a real key replaces the placeholder — no code change, no rebuild of anything but the container's env.

---

## 4. Database layer (Database Engineer)

Package: `backend/app/db/`. Schema SQL lives at `backend/app/db/schema.sql`
(PLAN.md says `backend/db/`; we use `backend/app/db/` so it is importable as `app.db` and
covered by the hatch wheel config — this is the one deliberate deviation).

### 4.1 Module layout

- `schema.sql` — `CREATE TABLE IF NOT EXISTS` for all six tables in PLAN.md §7.
- `database.py` — connection management + lazy init.
- `repository.py` — all query functions.
- `__init__.py` — re-exports everything below.

### 4.2 Connection contract

```python
from app.db import init_db, get_connection, transaction, DEFAULT_USER_ID

def init_db(db_path: str | None = None) -> None:
    """Idempotent. Creates parent dirs, applies schema.sql, seeds defaults if empty.
    Reads FINALLY_DB_PATH when db_path is None. Safe to call on every startup."""

@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """Yields a connection with row_factory=sqlite3.Row and foreign_keys=ON."""

@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """Same, but commits on success and rolls back on exception. Use for trades."""
```

Requirements:
- `check_same_thread=False`, WAL mode (`PRAGMA journal_mode=WAL`), `busy_timeout=5000`.
- Thread-safe: FastAPI runs sync route handlers in a threadpool, and a background
  snapshot task writes concurrently. Either use a lock or a per-thread connection.
- Seeding: one `users_profile` row (`id="default"`, `cash_balance=10000.0`) and the ten
  default watchlist tickers (AAPL, GOOGL, MSFT, AMZN, TSLA, NVDA, META, JPM, V, NFLX),
  **only if those tables are empty**. Never wipe existing data.

### 4.3 Repository functions

All are **synchronous**, all take a trailing `user_id: str = DEFAULT_USER_ID`, all return
plain `dict` / `list[dict]` (never `sqlite3.Row`), and all ISO timestamps are UTC
`datetime.now(timezone.utc).isoformat()`.

```python
# --- profile ---
get_profile(user_id=...) -> dict            # {"id","cash_balance","created_at"}
get_cash_balance(user_id=...) -> float
set_cash_balance(balance: float, user_id=...) -> None

# --- watchlist ---
list_watchlist(user_id=...) -> list[str]                 # ordered by added_at ASC
add_watchlist_ticker(ticker: str, user_id=...) -> bool   # False if already present
remove_watchlist_ticker(ticker: str, user_id=...) -> bool# False if not present

# --- positions ---
list_positions(user_id=...) -> list[dict]   # {"ticker","quantity","avg_cost","updated_at"}
get_position(ticker: str, user_id=...) -> dict | None
upsert_position(ticker: str, quantity: float, avg_cost: float, user_id=...) -> None
delete_position(ticker: str, user_id=...) -> None

# --- trades ---
record_trade(ticker: str, side: str, quantity: float, price: float, user_id=...) -> dict
    # -> {"id","ticker","side","quantity","price","executed_at"}
list_trades(limit: int = 100, user_id=...) -> list[dict]  # newest first

# --- snapshots ---
record_snapshot(total_value: float, user_id=...) -> dict  # {"id","total_value","recorded_at"}
list_snapshots(limit: int = 500, user_id=...) -> list[dict]  # oldest first (chart order)

# --- chat ---
add_chat_message(role: str, content: str, actions: list | dict | None = None,
                 user_id=...) -> dict
    # actions is JSON-encoded on write, JSON-decoded on read (None -> None)
list_chat_messages(limit: int = 50, user_id=...) -> list[dict]
    # -> {"id","role","content","actions","created_at"}, oldest first
```

Tickers are normalised to **uppercase, stripped** on write and on lookup.

Unit tests: `backend/tests/db/`, using a `tmp_path` SQLite file. Cover seeding idempotency,
uniqueness constraints, JSON round-tripping of `actions`, and concurrent writes.

---

## 5. Backend API (Backend API Engineer)

### 5.1 App wiring — `backend/app/main.py`

```python
app = FastAPI(title="FinAlly", lifespan=lifespan)
```

Lifespan startup order:
1. `init_db()`
2. `price_cache = PriceCache()`
3. `source = create_market_data_source(price_cache)`
4. `await source.start(list_watchlist())`
5. start the snapshot background task (every 30s: compute total value, `record_snapshot`)

Shutdown: cancel the snapshot task, `await source.stop()`.

Shared state lives on `app.state` (`app.state.price_cache`, `app.state.market_source`) and
is exposed to routers through FastAPI dependencies — **no module-level globals**, because
tests build multiple app instances.

Router mounting, in this order:
```python
app.include_router(create_stream_router(price_cache))   # from app.market
app.include_router(health_router)
app.include_router(portfolio_router)
app.include_router(watchlist_router)
app.include_router(create_chat_router())                # from app.llm — see §6.1
```
Then static files **last**, so `/api/*` always wins:
```python
# Serve the Next.js export from STATIC_DIR (default: "static", override: FINALLY_STATIC_DIR)
# if the directory exists. Mount with html=True so client routing and / both work.
# If it does not exist (backend-only dev), skip the mount silently.
```
A catch-all must return `index.html` for unknown non-`/api` paths.

If `DEV_CORS=true`, add `CORSMiddleware` allowing `http://localhost:3000`.

### 5.2 Endpoints

All JSON. All monetary floats rounded to 2dp in responses; percentages to 2dp.
Errors use FastAPI's default `{"detail": "..."}` shape.

#### `GET /api/health`
```json
{"status": "ok", "market_source": "simulator", "tickers": 10, "db": "ok"}
```
`market_source` is `"simulator"` or `"massive"`.

#### `GET /api/portfolio`
```json
{
  "cash_balance": 8075.00,
  "positions": [
    {"ticker": "AAPL", "quantity": 10.0, "avg_cost": 190.00, "current_price": 192.50,
     "market_value": 1925.00, "unrealized_pnl": 25.00, "unrealized_pnl_percent": 1.32,
     "weight": 0.19}
  ],
  "positions_value": 1925.00,
  "total_value": 10000.00,
  "total_cost_basis": 1900.00,
  "total_unrealized_pnl": 25.00,
  "total_unrealized_pnl_percent": 1.32
}
```
- `current_price` falls back to `avg_cost` when the cache has no price yet (never `null`).
- `weight` = `market_value / total_value`, `0.0` when `total_value == 0`. Rounded to **4dp**
  (not 2dp): at 2dp any position under ~0.5% of the book collapses to `0.0` and vanishes
  from the treemap. Money and percentage fields stay at 2dp.
- `positions` sorted by `market_value` descending.

#### `POST /api/portfolio/trade`
Request: `{"ticker": "AAPL", "quantity": 10, "side": "buy"}`
(`side` ∈ `"buy" | "sell"`, `quantity` > 0, fractional allowed.)

Response `200`:
```json
{
  "trade": {"id": "...", "ticker": "AAPL", "side": "buy", "quantity": 10.0,
            "price": 192.50, "executed_at": "2026-09-10T12:00:00+00:00"},
  "cash_balance": 8075.00,
  "position": {"ticker": "AAPL", "quantity": 10.0, "avg_cost": 192.50},
  "total_value": 10000.00
}
```
`position` is `null` when a sell closes the position.

Errors (`400` unless noted):
| Condition | detail |
|---|---|
| quantity <= 0 | `Quantity must be greater than zero` (422 from pydantic is also acceptable) |
| unknown side | 422 from pydantic |
| no price for ticker | `No price available for AAPL` (404), raised as `PriceUnavailableError(TradeError)` |
| insufficient cash | `Insufficient cash: need $1925.00, have $100.00` |
| insufficient shares | `Insufficient shares: tried to sell 10 AAPL, hold 3` |

Execution rules (in **one** `transaction()`):
- price = `price_cache.get_price(ticker)`.
- buy: `cash -= qty*price`; new `avg_cost = (old_qty*old_avg + qty*price)/(old_qty+qty)`.
- sell: `cash += qty*price`; `avg_cost` unchanged; quantity `<= 1e-9` → delete the position.
- `record_trade(...)`, then `record_snapshot(total_value)` immediately after the trade.
- **All of it inside one `database.transaction()`**, with the cash and position reads made on
  that same connection via `conn=conn`. `transaction()` uses `BEGIN IMMEDIATE`, so it takes the
  write lock up front — but that only protects reads issued on the transaction's own connection.
  Reading cash outside the block and writing inside reintroduces a lost-update race.
- Buying a ticker not on the watchlist is allowed and **must not** add it to the watchlist.
- Trading is only possible for tickers with a live price, i.e. ones the market source
  already tracks. To trade an untracked ticker the user adds it to the watchlist first.

#### `GET /api/portfolio/history?limit=500`
```json
{"snapshots": [{"total_value": 10000.00, "recorded_at": "2026-09-10T12:00:00+00:00"}]}
```
Oldest first. If empty, return one synthetic point for "now" so the chart is never blank.

#### `GET /api/watchlist`
```json
{"tickers": [
  {"ticker": "AAPL", "price": 192.50, "previous_price": 192.00, "change": 0.50,
   "change_percent": 0.26, "direction": "up",
   "previous_close": 190.00, "day_change": 2.50, "day_change_percent": 1.32}
]}
```

`change`/`change_percent` are **tick-over-tick** — tiny (~±0.05%) and used only to drive
the frontend's flash animation. `day_change`/`day_change_percent` are measured against
`previous_close`, which is what PLAN.md §10's "daily change %" means here.

There is no real trading day behind the simulator, so `previous_close` is:
1. the ticker's `SEED_PRICES` entry (AAPL 190.00, NVDA 800.00, ...), else
2. the first price this process ever observed for it (tickers the user adds later).

So "day" is really *since the backend started* — stated plainly rather than implying a
precision we do not have. It is stable across page reloads and identical for every
client, which a client-side "since page load" figure is not. See
`app/services/reference_prices.py`; reading `SEED_PRICES` does not modify the frozen
`app/market/` package.
`price` may be `null` if the cache has no entry yet; `direction` then `"flat"`.
Order = watchlist insertion order.

#### `POST /api/watchlist`
Request `{"ticker": "pypl"}` → normalised to `PYPL`.
Response `201`: `{"ticker": "PYPL", "added": true}`.
Also calls `await market_source.add_ticker("PYPL")` so prices start flowing.
`409` `Ticker PYPL is already on the watchlist`.
`400` `Invalid ticker` for anything not `^[A-Z.\-]{1,10}$` after normalisation.

#### `DELETE /api/watchlist/{ticker}`
`200` `{"ticker": "PYPL", "removed": true}`; `404` `Ticker PYPL is not on the watchlist`.
Calls `await market_source.remove_ticker(...)` **only if** no open position holds it
(keep pricing positions we still own).

### 5.3 Portfolio service

`backend/app/services/portfolio.py` holds the maths so both the API and the LLM layer use
one implementation:

```python
def build_portfolio(price_cache: PriceCache, user_id: str = DEFAULT_USER_ID) -> dict
    """Exactly the GET /api/portfolio payload."""

def execute_trade(price_cache: PriceCache, ticker: str, side: str, quantity: float,
                  user_id: str = DEFAULT_USER_ID) -> dict
    """Exactly the POST /api/portfolio/trade payload.
    Raises TradeError(message) on any validation failure."""

class TradeError(Exception): ...
class PriceUnavailableError(TradeError): ...  # route maps this to 404, everything else 400
```

The route layer converts `TradeError` to an `HTTPException`. **The LLM layer calls
`execute_trade` directly and catches `TradeError`** — it must not make HTTP calls to itself.

Unit tests: `backend/tests/services/` and `backend/tests/api/` (FastAPI `TestClient`,
a temp DB via `FINALLY_DB_PATH` monkeypatch, and a pre-populated `PriceCache`).

---

## 6. LLM layer (LLM Engineer)

Read `.claude/skills/cerebras/SKILL.md` for the LiteLLM → OpenRouter call structure.
Add deps with `uv add litellm pydantic` from `backend/` (`python-dotenv` is already in).

**Model selection overrides PLAN.md §9.** The user requires free models only.
`openai/gpt-oss-120b` is NOT free on OpenRouter (~$0.037/$0.17 per M) and has no `:free`
variant; Cerebras serves no free models. So the model is env-driven:

| Var | Default | Meaning |
|---|---|---|
| `OPENROUTER_MODEL` | `nex-agi/nex-n2.5-mini:free` | The model to call. Chosen by benchmark: fastest free model that did not hallucinate trades. |
| `OPENROUTER_FREE_ONLY` | `true` | If the id does not end in `:free`, refuse the live call, log loudly, fall back to mock. Hard spend guard. |
| `OPENROUTER_PROVIDER_ORDER` | empty | Comma-separated provider preference for `extra_body`. Set to `cerebras` to restore PLAN.md behaviour. |
| `OPENROUTER_TIMEOUT` | `30` | Seconds. Free-tier latency is erratic — a probe once queued >10 min before erroring. |

Benchmark (2026-09-10, all six free models supporting structured outputs). Four prompts,
three of which must yield zero trades (a read-only question, an opinion request, and an
anxious statement about a holding) plus one explicit sell. `nex-agi/nex-n2.5-mini:free`
scored 4/4 at avg 3.6s and is the default. `openrouter/free` was excluded despite 3.9s:
it auto-routes across the free pool, so model identity is not stable, which breaks both
reproducible E2E runs and any hallucination guarantee.

Measured free-tier latency: 3.6s-20.5s, and one model (`liquid/lfm-2.5-2.6b:free`)
hallucinated a trade selling a nonexistent `CASH` ticker. Since trades auto-execute with no
confirmation, **every LLM-proposed trade must go through the same `execute_trade` validation
as a manual one** — that is what rejects a hallucinated ticker (no price → `PriceUnavailableError`).
Never bypass it.

### 6.1 Router factory — `backend/app/api/chat.py`

```python
def create_chat_router() -> APIRouter:
    """Mounts POST /api/chat and GET /api/chat/history under prefix /api."""
```
It reads the `PriceCache` from `request.app.state.price_cache` and the market source from
`request.app.state.market_source` (do not import them from `main`, that would be circular).

#### `POST /api/chat`
Request: `{"message": "buy me 10 apple shares"}`

Response `200`:
```json
{
  "message": "Bought 10 AAPL at $192.50. Your cash is now $8,075.00.",
  "actions": [
    {"type": "trade", "status": "executed", "ticker": "AAPL", "side": "buy",
     "quantity": 10.0, "price": 192.50,
     "detail": "Bought 10 AAPL @ $192.50"},
    {"type": "watchlist", "status": "failed", "ticker": "PYPL", "action": "add",
     "detail": "Ticker PYPL is already on the watchlist"}
  ],
  "created_at": "2026-09-10T12:00:00+00:00"
}
```
`actions` is always an array (empty when nothing ran). `status` ∈ `"executed" | "failed"`.
Every action carries a human-readable `detail` — the frontend renders that string.

Never return a 500 to the user for an LLM failure: catch provider errors and respond `200`
with a `message` explaining the assistant is unavailable and `actions: []`.

#### `GET /api/chat/history?limit=50`
```json
{"messages": [{"id":"...","role":"user","content":"...","actions":null,
               "created_at":"..."}]}
```
Oldest first — straight from `list_chat_messages`.

### 6.2 Flow

1. Persist the user message (`add_chat_message("user", text)`).
2. Build context: `build_portfolio(price_cache)`, `list_watchlist()` with live prices,
   `list_chat_messages(limit=20)` for history.
3. Call the model with structured output (pydantic model → `response_format`):
   ```python
   class Trade(BaseModel):
       ticker: str; side: Literal["buy","sell"]; quantity: float
   class WatchlistChange(BaseModel):
       ticker: str; action: Literal["add","remove"]
   class ChatResponse(BaseModel):
       message: str
       trades: list[Trade] = []
       watchlist_changes: list[WatchlistChange] = []
   ```
4. Execute watchlist changes, then trades, in order, collecting action dicts.
   Trades go through `services.portfolio.execute_trade`; watchlist changes go through the
   repository **and** `market_source.add_ticker/remove_ticker`.
5. Persist the assistant message with its `actions`.
6. Return the payload.

Timeouts: 30s on the LLM call. Malformed JSON from the model → one retry, then a graceful
fallback message.

### 6.3 Mock mode

`LLM_MOCK=true` (or a missing `OPENROUTER_API_KEY`) → no network at all. The mock must be
deterministic and drive the E2E suite. Required behaviours, matched case-insensitively on
the user message:

| User message contains | Mock response |
|---|---|
| `buy` + a ticker + a number | `trades: [{ticker, side:"buy", quantity:N}]`, message `Bought N TICKER.` |
| `sell` + a ticker + a number | `trades: [{ticker, side:"sell", quantity:N}]`, message `Sold N TICKER.` |
| `add` + a ticker | `watchlist_changes: [{ticker, action:"add"}]` |
| `remove` + a ticker | `watchlist_changes: [{ticker, action:"remove"}]` |
| anything else | a portfolio summary built from real context: `You have $X in cash across N positions, total value $Y.` |

Tickers in the mock are matched as an uppercase token of 1–5 letters, or one of a small
name map (`apple→AAPL`, `google→GOOGL`, `microsoft→MSFT`, `tesla→TSLA`, `nvidia→NVDA`,
`amazon→AMZN`, `meta→META`, `netflix→NFLX`). Document the exact rules in
`backend/app/llm/README.md` — the Integration Tester writes tests against them.

### 6.4 System prompt

"You are FinAlly, an AI trading assistant…" — per PLAN.md §9. Must instruct: be concise and
data-driven, analyse concentration/risk/P&L, only emit trades the user asked for or agreed
to, use exact ticker symbols, quantities are share counts, and never invent prices
(the context carries the real ones).

Unit tests: `backend/tests/llm/` — mock-mode determinism, structured-output parsing,
malformed-response handling, action execution including failures, and the full chat route
with `TestClient`.

---

## 7. Frontend (Frontend Engineer)

### 7.1 Stack

- Next.js (App Router) + TypeScript, `output: 'export'`, `images: {unoptimized: true}`,
  `trailingSlash: true`. Build output goes to `frontend/out`.
- Tailwind CSS, dark theme only.
- Charts: **Recharts** (P&L line chart, detail chart) — canvas-free is fine at this scale;
  the treemap heatmap may use Recharts' `Treemap` or hand-rolled flex/CSS.
- No server components requiring a runtime, no route handlers, no `next/image` loader,
  no middleware — it must build as a pure static export.
- State: React hooks + context. No Redux.

### 7.2 API access

```ts
// lib/api.ts
export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";
```
Empty string = same origin (production). `npm run dev` against a local backend uses
`NEXT_PUBLIC_API_BASE=http://localhost:8000` with `DEV_CORS=true` on the backend.

SSE: `new EventSource(`${API_BASE}/api/stream/prices`)`. Each `message` event's `data` is a
JSON **object keyed by ticker**:
```json
{"AAPL": {"ticker":"AAPL","price":192.5,"previous_price":192.0,"timestamp":1757505600.0,
          "change":0.5,"change_percent":0.26,"direction":"up"}}
```
Note `timestamp` is **Unix seconds as a float**, not ISO. Handle `onerror` by showing the
connection dot as yellow (EventSource retries by itself); only go red after ~3 failed
retries. Close the connection on unmount.

Sparklines accumulate client-side from the stream since page load — cap history at ~120
points per ticker so memory stays flat.

### 7.3 Required UI

Per PLAN.md §10: header (total value, cash, connection dot), watchlist panel with flash
animation + sparklines, main detail chart for the selected ticker, portfolio heatmap
(treemap), P&L chart from `/api/portfolio/history`, positions table, trade bar,
AI chat panel. Colours: accent `#ecad0a`, primary `#209dd7`, secondary `#753991`
(submit buttons), background `#0d1117`.

Flash: apply a class for ~500ms on price change, then remove it. Uptick green, downtick red.

After any successful trade or watchlist mutation, re-fetch `/api/portfolio` and
`/api/watchlist` — do not try to patch state locally.

### 7.4 Test hooks — **required, the E2E suite depends on these exact values**

Add `data-testid` attributes:

| testid | Element |
|---|---|
| `connection-status` | the dot; also `data-status="connected\|reconnecting\|disconnected"` |
| `total-value` | header total portfolio value |
| `cash-balance` | header cash |
| `watchlist` | the watchlist container |
| `watchlist-row-{TICKER}` | one row, e.g. `watchlist-row-AAPL` |
| `watchlist-price-{TICKER}` | the price cell |
| `watchlist-remove-{TICKER}` | remove button |
| `watchlist-add-input` / `watchlist-add-submit` | add-ticker form |
| `positions-table` | positions table container |
| `position-row-{TICKER}` | one position row |
| `position-qty-{TICKER}` / `position-pnl-{TICKER}` | cells |
| `trade-ticker` / `trade-quantity` / `trade-buy` / `trade-sell` | trade bar |
| `trade-error` | inline error message after a rejected trade |
| `portfolio-heatmap` | heatmap container |
| `heatmap-tile-{TICKER}` | one tile |
| `pnl-chart` | P&L chart container |
| `detail-chart` | main chart container |
| `chat-panel` / `chat-input` / `chat-send` | chat |
| `chat-message-user` / `chat-message-assistant` | message bubbles (many) |
| `chat-action` | an inline action confirmation line |
| `chat-loading` | the loading indicator, present only while awaiting a reply |

Unit tests: React Testing Library + Vitest (or Jest) in `frontend/`, `npm test`.

---

## 8. Docker & scripts (DevOps Engineer)

### 8.1 Dockerfile (multi-stage, at the repo root)

```
Stage 1  node:20-slim   → copy frontend/, npm ci, npm run build  → /app/frontend/out
Stage 2  python:3.12-slim
         install uv, copy backend/, uv sync --frozen --no-dev
         copy --from=0 /app/frontend/out  →  /app/static
         ENV FINALLY_DB_PATH=/app/db/finally.db FINALLY_STATIC_DIR=/app/static
         EXPOSE 8000
         HEALTHCHECK → GET /api/health
         CMD uvicorn app.main:app --host 0.0.0.0 --port 8000
```
Working dir for stage 2 is `/app/backend` (so `app.main` imports), or install the package
and run from `/app` — either is fine as long as `uvicorn app.main:app` resolves.
`.dockerignore` must exclude `node_modules`, `.next`, `out`, `.venv`, `__pycache__`,
`db/*.db`, `.git`, `test/`.

### 8.2 Scripts (idempotent, both platforms)

`scripts/start_mac.sh`, `scripts/stop_mac.sh`, `scripts/start_windows.ps1`,
`scripts/stop_windows.ps1`.

Start: build the image if missing or `--build` passed; stop+remove any existing
`finally` container; run detached with `-v finally-data:/app/db -p 8000:8000 --env-file .env`;
wait for `/api/health` to answer; print the URL; open the browser unless `--no-open`.
If `.env` is missing, create it from `.env.example` with a warning rather than failing.

Stop: stop and remove the container; **never** remove the volume.

`docker-compose.yml` at the root is a convenience wrapper over the same image, volume and
port.

### 8.3 `.env.example`

Exactly the five variables in §3 with the defaults shown, each with a one-line comment.

---

## 9. E2E tests (Integration Tester)

Location `test/`. Playwright + TypeScript. `test/docker-compose.test.yml` brings up the app
image with `LLM_MOCK=true`, `MASSIVE_API_KEY=` (empty), a throwaway DB volume, and a
Playwright container. Also support running against an already-running
`http://localhost:8000` via `BASE_URL`.

Scenarios (PLAN.md §12):
1. Fresh start — 10 default tickers, `$10,000.00` cash, prices tick within 5s.
2. Watchlist add + remove round trip.
3. Buy — cash falls, position row appears, total value updates.
4. Sell — cash rises, position shrinks or disappears.
5. Rejected trade — buying more than cash allows shows `trade-error`.
6. Heatmap tiles and P&L chart render with data after a trade.
7. Chat (mock) — `buy 5 AAPL` produces an assistant message, a `chat-action` line, and a
   real position.
8. SSE resilience — prices resume after a simulated offline/online cycle.

Rules: no `waitForTimeout` as a synchronisation primitive — use web-first assertions with
generous timeouts (prices are stochastic; assert on *change*, not on exact values). Money
assertions use regex, not equality against a stochastic value. Tests must be re-runnable
against a persistent DB, so never assume a zero-position starting state except in the
fresh-volume compose run — derive expected values from what the page shows first.

When a test fails, the Integration Tester **reports the defect with evidence** (failing
assertion, screenshot path, the API payload) and does not fix code outside `test/`.

---

## 10. Definition of done

- `cd backend && uv run --extra dev pytest` — all green (including the 95 market tests).
- `cd backend && uv run --extra dev ruff check app/ tests/` — clean.
- `cd frontend && npm run build` — static export succeeds; `npm test` green; `tsc` clean.
- `docker build -t finally .` succeeds; `scripts/start_*` brings up a working app.
- The Playwright suite passes against the container.
- No secrets committed. `.env` stays gitignored.
