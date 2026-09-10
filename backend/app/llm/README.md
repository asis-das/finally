# `app.llm` — the FinAlly AI assistant

The chat layer: builds portfolio context, calls a model (or the deterministic
mock), executes whatever the model asked for, and persists the turn.

```
app/llm/
├── config.py    env-driven settings, model selection, the free-only spend guard
├── schemas.py   pydantic structured-output schema (also the request model)
├── prompt.py    system prompt + portfolio context block + message assembly
├── mock.py      the deterministic mock assistant (no network)
├── client.py    LiteLLM -> OpenRouter call, retry, timeout, error taxonomy
├── actions.py   executes trades and watchlist changes, reports failures
└── service.py   the flow; `handle_chat()` / `chat_history()`
```

Routes live in `app/api/chat.py` (`create_chat_router()`), mounted by
`app/main.py`.

---

## Configuration

| Var | Default | Meaning |
|---|---|---|
| `OPENROUTER_API_KEY` | — | Absent, empty, or the literal `REPLACE_ME` → mock mode. |
| `LLM_MOCK` | `false` | `true` → mock mode, no network at all. |
| `OPENROUTER_MODEL` | `nex-agi/nex-n2.5-mini:free` | Model id. An `openrouter/` prefix is optional and stripped; LiteLLM always receives the prefixed form. |
| `OPENROUTER_FREE_ONLY` | `true` | Refuse to call a model whose id does not end in `:free`. |
| `OPENROUTER_TIMEOUT` | `30` | Seconds. Non-numeric or `<= 0` falls back to 30. |
| `OPENROUTER_PROVIDER_ORDER` | *(empty)* | Comma-separated OpenRouter provider preference, e.g. `cerebras`. Empty → no `provider` block is sent, so any provider may serve the model. |
| `OPENROUTER_REASONING_EFFORT` | `low` | Sent as `reasoning_effort`. Set to the empty string to omit the parameter. |

Calls are made with LiteLLM's `drop_params=True`. Free models differ in what they accept — OpenRouter rejects `reasoning_effort` for most of them, and not all support structured outputs — so an unsupported parameter is dropped rather than failing the request. The parser tolerates a reply that ignored the schema, and a malformed reply still gets one corrective retry.


### The free-only spend guard

`OPENROUTER_FREE_ONLY=true` (the default) is a **hard** guard, not a preference.
If the configured model id does not end in `:free`, the layer logs a loud
one-per-process warning and serves the request from the mock instead of making
a call that could cost money. The `:free` suffix is OpenRouter's only reliable
zero-cost signal, which is why it — and not a model allowlist — is the check.

To use a paid model you must explicitly set `OPENROUTER_FREE_ONLY=false`.

### Pointing back at Cerebras

The `cerebras` skill's call structure is intact — LiteLLM `completion`,
structured outputs via `response_format`, `extra_body={"provider": {...}}`. Only
the provider order became configurable:

```bash
OPENROUTER_MODEL=openai/gpt-oss-120b
OPENROUTER_PROVIDER_ORDER=cerebras
OPENROUTER_FREE_ONLY=false     # gpt-oss-120b is not free
```

---

## Mock mode — the exact rules

Mock mode is active when **any** of these holds (checked in order, first match
is reported as the reason):

1. `LLM_MOCK=true`
2. `OPENROUTER_API_KEY` is absent, empty, or exactly `REPLACE_ME`
3. `OPENROUTER_FREE_ONLY` is true **and** `OPENROUTER_MODEL` does not end in `:free`

In mock mode no network call is made and no LiteLLM code path is entered.

Mock output is a pure function of `(user message, portfolio context)`. No
randomness, no clock, no I/O.

### Ticker extraction

Two kinds of candidate are collected from the **original** message (casing
matters):

* **Uppercase tokens** matching `\b[A-Z]{1,5}\b` that are not stop words.
* **Company names** matched case-insensitively as whole words:
  `apple→AAPL`, `google→GOOGL`, `microsoft→MSFT`, `tesla→TSLA`,
  `nvidia→NVDA`, `amazon→AMZN`, `meta→META`, `netflix→NFLX`.

The candidate with the **smallest start offset** wins. If there are no
candidates the ticker is `None`.

Stop words (uppercase English that would otherwise look like tickers):

```
A ADD ALL AN AND ANY ARE AT BUY BY CAN DO FOR GET HOW I IF IN IS IT ME MY
NEW NO NOT NOW OF OK ON OR OUT PLS PUT SELL SO THE TO UP US USD WHAT WHY
YES YOU
```

Consequence worth knowing: `BUY 5 AAPL` resolves to `AAPL`, not `BUY`. But an
all-caps company-shaped word not on the list (e.g. `NICE`) would be read as a
ticker.

### Quantity extraction

The **first** match of `\d+(\.\d+)?` anywhere in the message, as a float.
Fractional quantities are supported. No match → `None`.

Quantities are rendered with `%g`, so `10.0` prints as `10` and `2.5` as `2.5`.

### Intent selection

Keyword tests are case-insensitive whole-word matches (`\bbuy\b`, `\bsell\b`,
`\badd\b`, `\bremove\b`). The first rule that matches wins:

| # | Condition | Result |
|---|---|---|
| 1 | ticker **and** quantity **and** `buy` | `trades: [{ticker, side:"buy", quantity}]`, message `Bought <qty> <TICKER>.` |
| 2 | ticker **and** quantity **and** `sell` | `trades: [{ticker, side:"sell", quantity}]`, message `Sold <qty> <TICKER>.` |
| 3 | ticker **and** `add` | `watchlist_changes: [{ticker, action:"add"}]`, message `Added <TICKER> to your watchlist.` |
| 4 | ticker **and** `remove` | `watchlist_changes: [{ticker, action:"remove"}]`, message `Removed <TICKER> from your watchlist.` |
| 5 | otherwise | portfolio summary, no actions |

Notes:

* Rules 1 and 2 need **all three** of ticker, quantity and keyword. `buy AAPL`
  with no number falls through to rules 3–5 and normally lands on the summary.
* `buy` is checked before `sell`; a message containing both produces a single
  buy. The mock never emits more than one trade or more than one watchlist
  change per message.
* Rules 3 and 4 do **not** require a quantity, so `add 5 PYPL` is an add.
* The mock message is chosen **before** the action runs, so it does not reflect the
  outcome: `buy 100000 AAPL` still says `Bought 100000 AAPL.` while the action comes
  back `status: "failed"` with an `Insufficient cash: …` detail. Assert on the action,
  not the message, when testing a rejected trade.

### Rule 5 — the summary

Built from the live portfolio context, not from anything invented:

```
You have $<cash> in cash across <N> positions, total value $<total>.
```

`<cash>` and `<total>` are formatted `{:,.2f}` (thousands separators, two
decimals); `<N>` is the number of open positions. Example on a fresh database:

```
You have $10,000.00 in cash across 0 positions, total value $10,000.00.
```

---

## Live mode

1. Persist the user message.
2. Build context: `build_portfolio(price_cache)`, the watchlist with live
   prices, and the previous 20 chat turns (the just-persisted message is
   excluded so it is not duplicated).
3. `litellm.completion(model="openrouter/<model>", messages=…,
   response_format=ChatResponse, timeout=…)`, run in a worker thread.
4. Parse. A reply that is not valid schema JSON is retried **once** with an
   explicit correction instruction; parsing tolerates a ```json fence or prose
   around the object.
5. Apply actions, persist the assistant message, return.

### Failure handling

Chat **never** returns a 500 for an LLM failure. Every provider failure yields
`200` with an apologetic `message` and `actions: []`:

| Failure | Behaviour |
|---|---|
| Timeout (`OPENROUTER_TIMEOUT`, default 30s) | `LLMTimeoutError` → "taking longer than expected… free-tier inference can queue" |
| Malformed JSON | one retry, then `MalformedResponseError` → "assistant is unavailable" |
| Any other provider error | `LLMError` → "assistant is unavailable" |
| Anything unexpected in the route | caught in `app/api/chat.py` → same shape |

When inference fails, **no** actions are executed — a provider outage can never
half-place a trade.

---

## Action execution

Watchlist changes run first, then trades, so `add PYPL and buy 5` works.

Trades go through `app.services.portfolio.execute_trade` (the same validation as
a manual trade); watchlist edits go through the `app.db` repository **and**
`market_source.add_ticker/remove_ticker`. A removal keeps the ticker priced when
an open position still holds it. Nothing here makes an HTTP call back into the
app.

A failed action is reported, not raised — one rejected trade does not lose the
rest of the reply.

### Hostility to the model's own output

Trades auto-execute with no confirmation dialog, and the JSON schema constrains
*shape*, not *sanity*. Two of six benchmarked free models emitted structurally
valid nonsense:

* `liquid/lfm-2.5-2.6b:free` answered "buy me 10 Apple shares" with the correct
  trade **plus** a fabricated `sell 1925 CASH`.
* `dots-studio/dots-3-note-preview:free` answered "Sell 4 of my Apple shares"
  with `{"ticker": "AAPL", "side": "sell", "quantity": -4}`.

So the executor never bypasses `execute_trade`, and never repairs a bad value:

* A negative or zero quantity is **rejected, not `abs()`-ed**. Guessing intent on
  an auto-executing trade is the wrong instinct, so it comes back
  `status: "failed"`, `detail: "Quantity must be greater than zero"`, with the
  offending quantity reported verbatim.
* A fabricated ticker has no price, so it comes back `status: "failed"`,
  `detail: "No price available for CASH"`.
* Neither writes anything: cash, positions and the trade log are untouched.
* A partially bad response still does the good part — the valid trade executes
  and the invalid one reports failed, in the order the model listed them.

Covered by `TestHostileModelOutput` in `tests/llm/test_actions.py` and
`TestHallucinatedTrades` in `tests/llm/test_service.py`.

Action shapes (`status` ∈ `executed | failed`, `detail` is what the frontend
renders):

```json
{"type": "trade", "status": "executed", "ticker": "AAPL", "side": "buy",
 "quantity": 10.0, "price": 192.5, "detail": "Bought 10 AAPL @ $192.50"}

{"type": "trade", "status": "failed", "ticker": "AAPL", "side": "buy",
 "quantity": 999.0, "price": null,
 "detail": "Insufficient cash: need $192307.50, have $10000.00"}

{"type": "watchlist", "status": "failed", "ticker": "PYPL", "action": "add",
 "detail": "Ticker PYPL is already on the watchlist"}
```

Failure details come verbatim from `TradeError` / the repository, so they match
the REST endpoints' wording. An `Invalid ticker '…'` detail is produced for
anything that fails `^[A-Z.\-]{1,10}$` after upper-casing and stripping.

---

## Endpoints

`POST /api/chat` — `{"message": "..."}` →

```json
{"message": "...", "actions": [ … ], "created_at": "2026-09-10T12:00:00+00:00"}
```

`actions` is always an array, empty when nothing ran.

`GET /api/chat/history?limit=50` — `{"messages": [...]}`, oldest first, straight
from `list_chat_messages`. `limit` is clamped to 1–500.

---

## Tests

`backend/tests/llm/`. They never touch the network: `app.llm.client.completion`
is patched in every live-mode test.

```bash
cd backend
uv run --extra dev pytest tests/llm -v
```

---

## Free-model behaviour: what the guardrails are actually for

The default model is `nex-agi/nex-n2.5-mini:free`, chosen by benchmarking every
free OpenRouter model that supports structured outputs (2026-09-10). It was the
fastest that did not invent trades in response to read-only prompts — 4/4 on a
four-prompt test, avg 3.6s.

Structured outputs constrain **shape, not sanity**. Observed failures across the
free pool, all of which the executor must survive:

| Model | Prompt | Output |
|---|---|---|
| `liquid/lfm-2.5-2.6b:free` | "buy me 10 Apple shares" | the correct trade **plus** a fabricated `sell 1925 CASH` |
| `dots-studio/dots-3-note-preview:free` | "Sell 4 of my Apple shares" | `quantity: -4` |
| `nex-agi/nex-n2.5-mini:free` (before the prompt fix) | "Buy 5000 shares of TSLA" with $10k cash | silently bought 20 instead, disclosing it only in prose |

Hence the two rules this package enforces:

1. **Every model-proposed trade goes through `services.portfolio.execute_trade`,**
   the same validation a manual trade gets. That is what turns a hallucinated
   `CASH` ticker into a `PriceUnavailableError` and a negative quantity into a
   rejection, reported as `status: "failed"` with the error in `detail`.
2. **Never coerce the model's numbers.** No `abs()` on a negative quantity, no
   clamping an unaffordable size. Guessing intent on a trade that auto-executes
   without a confirmation dialog is precisely the wrong instinct.

### Quantity substitution is forbidden in the prompt

Silently resizing is more dangerous than a hallucination: the trade is
plausible, it executes, and the only evidence is a sentence in a chat bubble.
Disclosure is not consent. The prompt now requires the model to emit exactly
the quantity the user stated, let validation reject it, and *offer* an
alternative in `message` for the user to accept on the next turn.

Verified live after the change — "Buy 5000 shares of TSLA" with $10,000 cash:

```
message: "That requires $875,100, but you have $10,000, so the trade will fail.
          I could buy 57 TSLA shares instead for $9,976.14; want me to submit that?"
action:  trade failed | qty 5000.0 | Insufficient cash: need $1250200.00, have $10000.00
portfolio afterwards: cash 10000.0, positions []
```

Regression tests: `tests/llm/test_actions.py::TestQuantityIsNeverSubstituted`.

### Known limitation: the free model's arithmetic is unreliable

In the run above the context carried `TSLA 250.04`, but the model quoted
`$175.02` per share — GOOGL's price. Both its stated cost and its "57 shares
instead" suggestion are therefore wrong. The **ledger is unaffected**: the
rejection used the real price, server-side. But the assistant's prose can
contain wrong numbers even though the prompt forbids inventing prices.

Treat the chat text as commentary and the `actions` array as the truth. If
accurate figures in prose matter more than zero cost, point
`OPENROUTER_MODEL` at a stronger paid model and set `OPENROUTER_FREE_ONLY=false`
— it is a one-variable change, no code edit.

### `reasoning_effort` is dropped, not sent

OpenRouter rejects `reasoning_effort` for free models
(`litellm.UnsupportedParamsError`). The client passes `drop_params=True`, so
unsupported parameters are dropped rather than failing the call. The project's
`cerebras` skill teaches the parameter as mandatory — anyone copying it verbatim
against a free model will hit this.
