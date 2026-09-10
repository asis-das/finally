# FinAlly — end-to-end tests

Playwright + TypeScript. Covers the eight scenarios in
`planning/BUILD_CONTRACT.md` §9 (PLAN.md §12) against a real backend, a real
SQLite database and the real static frontend export.

33 tests, one browser project (Chromium, 1600×1000 — the layout's `xl`
three-column terminal).

```
test/
├── e2e/                     one spec per contract scenario
│   ├── 01-fresh-start.spec.ts
│   ├── 02-watchlist.spec.ts
│   ├── 03-buy.spec.ts
│   ├── 04-sell.spec.ts
│   ├── 05-rejected-trade.spec.ts
│   ├── 06-visualisation.spec.ts
│   ├── 07-chat.spec.ts
│   └── 08-sse-resilience.spec.ts
├── fixtures/
│   ├── app.ts               Workstation page object, ApiClient, evidence capture
│   └── global-setup.ts      health gate + environment guard
├── docker-compose.test.yml
└── playwright.config.ts
```

---

## Running

### 1. Against an already-running instance (primary path)

Start the app however you like, then point `BASE_URL` at it. The environment
**must** be the simulator plus the mock assistant — `global-setup` refuses to run
against `market_source: "massive"`, and `07-chat` fails loudly if the real model
is answering.

```bash
# terminal 1 — the app (backend serving the built frontend, same origin)
cd backend
LLM_MOCK=true \
MASSIVE_API_KEY= \
OPENROUTER_API_KEY= \
FINALLY_DB_PATH=/tmp/finally-e2e.db \
FINALLY_STATIC_DIR=../frontend/out \
uv run uvicorn app.main:app --port 8000

# terminal 2 — the suite
cd test
npm ci
BASE_URL=http://localhost:8000 npx playwright test
```

PowerShell equivalent for terminal 1:

```powershell
cd backend
$env:LLM_MOCK="true"; $env:MASSIVE_API_KEY=""; $env:OPENROUTER_API_KEY=""
$env:FINALLY_DB_PATH="$env:TEMP\finally-e2e.db"
$env:FINALLY_STATIC_DIR="$PWD\..\frontend\out"
uv run uvicorn app.main:app --port 8000
```

`frontend/out` must exist (`cd frontend && npm run build`). Without it the
backend serves the API only and `global-setup` aborts with a message saying so.

Add `FRESH_DB=1` when the database file did not exist before the run — see
[Fresh vs. reused database](#fresh-vs-reused-database).

### 2. Against the container (`docker-compose.test.yml`)

Brings up the production image on a throwaway named volume with `LLM_MOCK=true`,
`MASSIVE_API_KEY=` empty, plus a Playwright container that runs the suite over
the compose network.

```bash
docker compose -f test/docker-compose.test.yml up --build \
  --abort-on-container-exit --exit-code-from tests
docker compose -f test/docker-compose.test.yml down -v      # -v drops the DB volume
```

The app is also published on **http://localhost:8001** so you can watch a failure
in your own browser, and so you can drive the suite from the host instead of from
the Playwright container:

```bash
docker compose -f test/docker-compose.test.yml up -d app
cd test && BASE_URL=http://localhost:8001 FRESH_DB=1 npx playwright test
```

Because the volume is fresh on `up` after a `down -v`, `FRESH_DB=1` is set for the
containerised runner.

> **Known blocker on the EDAG corporate network.** `mcr.microsoft.com` and the
> Docker Hub blob CDN are unreachable from this machine, so the `tests` service's
> image cannot be pulled:
> ```
> Error response from daemon: failed to resolve reference
> "mcr.microsoft.com/playwright:v1.58.0-noble": failed to do request:
> Head "https://mcr.microsoft.com/v2/playwright/manifests/v1.58.0-noble": EOF
> ```
> The `app` service builds and runs fine (its base layers are already cached).
> Use the host-driven form above on this network. `cdn.playwright.dev` itself
> *is* reachable, so `npx playwright install` works on the host.

---

## Environment variables

| Var | Default | Meaning |
|---|---|---|
| `BASE_URL` | `http://localhost:8000` | The app under test. |
| `FRESH_DB` | unset | `1` → the database was empty at start; enables the exact `$10,000.00` and exactly-ten-tickers assertions. |
| `PW_RETRIES` | `0` | Retries. Left at 0 on purpose — a retry that turns red into green hides a race. |
| `HEALTH_TIMEOUT_MS` | `120000` | How long `global-setup` waits for `/api/health`. |

## Playwright version is pinned on purpose

`@playwright/test` is pinned to **1.58.0** because that is the release whose
browser revision (`chromium-1208`) matches the build already present in
`%USERPROFILE%\AppData\Local\ms-playwright` on the build machine. Bumping the
package without also running `npx playwright install` will fail with
"browser not found".

---

## Conventions the suite holds itself to

**No `waitForTimeout` as a synchronisation primitive.** Every wait is a web-first
assertion or `expect.poll`. The single `waitForTimeout`-shaped construct in the
suite is a promise gate in `07-chat` that holds an intercepted response open, and
it is released deterministically.

**Prices are stochastic; assert on change and on shape.** Money is matched with
`/^[+-]?\$[\d,]+\.\d{2}$/`, prices with `/^[\d,]+\.\d{2}$/`. Where a number has
to be checked, it is checked as a *direction* (cash fell after a buy) or as a
*plausibility band* (the implied fill price is between \$1 and \$10,000), never
against a value the simulator happened to produce.

Ticking is asserted across the whole tape rather than on one symbol: GBM rounded
to two decimals can leave a single ticker unchanged for several seconds, but not
all ten.

**Tests are independent and re-runnable against a persistent database.** Each
spec arranges its own starting state through the REST API (`ApiClient` in
`fixtures/app.ts` — `closePosition`, `ensureTickerPresent`, `ensureTickerAbsent`,
`ensurePosition`) and derives expected numbers from what the page showed first.
Both orders were verified: a fresh volume and then the same volume again.

### Fresh vs. reused database

Only two assertions are gated on `FRESH_DB=1`:

* cash and total value are exactly `$10,000.00`
* the watchlist holds *exactly* the ten seed tickers

Without the flag, the same tests assert money-shape and that the ten seed tickers
are all *present*. Leaving the flag off on a reused database is the safe default;
setting it on a reused database will (correctly) fail.

**Evidence on failure.** `trace: retain-on-failure`, `screenshot:
only-on-failure`, `video: retain-on-failure`, all under `test-results/`. The
`app` fixture additionally attaches:

* `api-traffic.log` — every non-stream `/api/*` request/response body seen during
  the test, timestamped
* `browser-console-errors.log` — console errors and uncaught page errors

```bash
npx playwright show-report                       # the HTML report
npx playwright show-trace test-results/<dir>/trace.zip
```

**Single worker.** FinAlly is single-user by design: one cash balance, one
watchlist, one position book. Parallel workers would be testing SQLite's locking,
not the application.

---

## Scenario 8 — why it does not use `setOffline`

`browserContext.setOffline(true)` does **not** interrupt an already-established
`EventSource` in Chromium. Measured against this build: with the context offline,
the stream kept delivering frames (41 messages received during a 12-second
offline window) and the connection dot correctly stayed `connected` the whole
time. Chromium's offline emulation applies to new connections, not to an open
response body.

So `08-sse-resilience.spec.ts` simulates the outage by aborting the
`/api/stream/prices` request at Playwright's route layer with
`connectionfailed`, which is what a dropped connection looks like to
`EventSource`. Recovery is then left entirely to the browser's built-in retry —
the suite never reloads the page or re-subscribes to prove the dot goes green
again.

## Scenario 7 — chat is asserted against the mock's documented rules

The exact strings come from `backend/app/llm/README.md` §"Mock mode — the exact
rules". Two of them are easy to get wrong:

* The mock composes its message **before** the action executes, so
  `buy 100000 AAPL` replies "Bought 100000 AAPL." while the action carries
  `status: "failed"`. The rejected-trade test asserts on the action's
  `data-status`, never on the message text.
* Rule 5's summary is the canary for mock mode being active at all:
  `You have $X in cash across N positions, total value $Y.` The first test in
  `07-chat` checks that string against `POST /api/chat` directly, so a run against
  a live model fails immediately and unambiguously rather than flaking later.
