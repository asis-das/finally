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
| Frontend | Complete; D-6 and D-3 fixed, 71 tests |
| Docker + scripts | Complete, verified end to end |
| E2E (`test/`) | 37 tests, 8/8 scenarios green |

Backend: **358 tests**, ruff clean. Frontend: **71 tests**, build/lint/types clean.
E2E: 37 tests green against both a local uvicorn and the container.

## 1. D-6 and D-3 — FIXED (2026-09-10)

Both closed and verified. `WatchlistEntry` now declares `previous_close`,
`day_change` and `day_change_percent`, and the watchlist renders
`day_change_percent`; the flash animation still runs off the SSE tick, never the
day figure. `lib/api.ts` gained `errorDetail()`, which joins the `msg` fields of
a FastAPI 422 array instead of dropping them.

Verified live: AAPL `-0.23%` (`Since 190.00`), MSFT `-2.95%`, TSLA `-10.02%`,
against tick `change_percent` of `0.00` for the same rows. Before the fix every
row read `≈+0.00%`.

**The built image predates this.** `.\scripts\start_windows.ps1 -Build` to
refresh it — the image bakes `frontend/out` in at build time by design, so a
running container always serves a snapshot rather than the live directory.

### Open trade-off worth a decision

The day figure is only as fresh as the last `/api/watchlist` fetch, and the
watchlist is re-fetched on load and after a mutation. So between trades the
percentage column sits still while prices move — measured ~0.05pp of drift over
5 seconds on TSLA, and larger over a long idle session.

The alternative is recomputing in the client from the live tick against the
backend's `previous_close`: same arithmetic, same shared reference, current with
the tape. It was not done because an exact-match E2E assertion would break under
a live-recomputed value. Roughly a three-line change if wanted.

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
