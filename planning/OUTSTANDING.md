# FinAlly — outstanding work

State as of 2026-09-10, end of the agent-team build session. Everything below is
**known and deliberate**, not discovered-and-forgotten. Read alongside
`planning/BUILD_CONTRACT.md`.

## Status

| Area | State |
|---|---|
| Market data (`app/market/`) | Complete, frozen, 95 tests |
| Database (`app/db/`) | Complete, 43 tests |
| API + portfolio service | Complete, verified live |
| AI assistant (`app/llm/`) | Complete, verified live and mocked |
| Frontend | Complete except D-6 below |
| Docker + scripts | Complete, verified end to end |
| E2E (`test/`) | 37 tests, 8/8 scenarios green |

Backend: **358 tests**, ruff clean. Frontend: 63 tests, build/lint/types clean.
E2E: 37 tests green against both a local uvicorn and the container.

## 1. D-6 — watchlist shows session change, not daily change

**Uncommitted work in progress sits in the working tree** —
`frontend/components/Watchlist.tsx` and three test files. Finish or discard it
before starting anything else.

PLAN.md §10 requires a daily change %. The frontend was computing
`(last − first) / first` over sparkline points accumulated since page load,
because when it was written the payload carried only tick-over-tick
`change_percent`. The backend later gained `previous_close`, `day_change` and
`day_change_percent` (see `app/services/reference_prices.py`) but the frontend
was never told, so the fields were dead payload.

Wrong on every row, for every user, on every load. The fix in flight adds the
fields to `WatchlistEntry` and renders `day_change_percent`, keeping
tick-over-tick for the flash animation only — do not switch the flash to the
day figure or it will latch.

**The image currently built does not contain this fix.** Rebuild with
`.\scripts\start_windows.ps1 -Build`.

## 2. D-3 — 422 errors render as "Request failed (422)"

`frontend/lib/api.ts` `request()` adopts `body.detail` only when it is a string.
FastAPI 422s carry an array of objects, so the real message is lost. Currently
unreachable — the `TradeBar` quantity guard and `isValidTicker` block both paths
— but it is a trap for whoever removes a guard. Fix may be included in the
in-flight work above.

## 3. D-4 — unknown tickers are addable and tradeable (product decision)

`POST /api/watchlist {"ticker":"ZZZZ"}` returns 201; three seconds later ZZZZ
quotes at a simulated price and can be bought. A typo becomes a buyable
instrument. Defensible for a simulator, but it should be a decision rather than
an accident. Correctly asymmetric already: a ticker *not* on the watchlist 404s
with `No price available for ZZZZ`.

## 4. Test coverage gap

No E2E test asserts the watchlist percentage — which is how D-6 survived a green
37-test run. The testid exists; the assertion was not written because the
expected value was an open product question. Add it once D-6 is settled.

## 5. Environment constraints on this machine

- **Corporate TLS interception** (EDAG / Group IT / SUBCA5). Host-side HTTPS to
  `openrouter.ai` fails with `CERTIFICATE_VERIFY_FAILED`; the LLM layer needs
  `SSL_CERT_FILE` pointing at an exported Windows root store. Docker's own
  network is *not* affected — the image builds and reaches OpenRouter fine.
- **Container registries are blocked** (`mcr.microsoft.com`, Docker Hub's blob
  CDN). So `test/docker-compose.test.yml`'s Playwright service cannot be pulled
  here and is unverified; the app half is proven via `BASE_URL`. Our own image
  builds because its base layers are cached locally.
- `docker/ca/` accepts corporate CA certificates for both build stages if a
  future network needs them. Never disable verification instead.

## 6. LLM notes

- Free models only, per the project owner. `OPENROUTER_FREE_ONLY=true` refuses
  any model id not ending in `:free` and falls back to mock rather than spending.
- Default `nex-agi/nex-n2.5-mini:free`, chosen by benchmark (fastest free model
  that did not invent trades on read-only prompts).
- **The free model's arithmetic is unreliable.** Observed: context carried
  `TSLA 250.04`, the model quoted `$175.02` (GOOGL's price) in its prose. The
  ledger is safe — validation uses the real server-side price — but chat text can
  contain wrong numbers. Treat `actions` as truth and the message as commentary.
- Switching to a stronger paid model is one env variable, no code change.
- See `backend/app/llm/README.md` for the full record of free-model failure modes.

## 7. Not exercised at all

Live LLM mode under E2E, the Massive market-data path, the PowerShell scripts
under E2E, tablet/narrow layout, the server-side 422 rendering path, and
long-session sparkline capping.
