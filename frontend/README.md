# FinAlly frontend

Next.js (App Router) + TypeScript + Tailwind, built as a static export. The backend
serves `out/` as static files, so there is no Node runtime in production.

## Commands

| Command | What it does |
|---|---|
| `npm run build` | Static export to `out/` — this is what the Dockerfile copies |
| `npm run dev` | Dev server on :3000 |
| `npm test` | Vitest + React Testing Library |
| `npm run typecheck` | `tsc --noEmit` |
| `npm run lint` | ESLint (flat config, `eslint-config-next`) |

## Developing against a local backend

The app talks to the same origin by default. To run `npm run dev` on :3000 against a
backend on :8000:

```bash
# backend, from the project root
DEV_CORS=true uv run --directory backend uvicorn app.main:app --port 8000

# frontend
NEXT_PUBLIC_API_BASE=http://localhost:8000 npm run dev
```

`NEXT_PUBLIC_API_BASE` is baked in at build time, so leave it unset for the
production image.

## Layout

- `app/` — the single page (`page.tsx` wires the data hooks to the panes) and the
  design tokens (`globals.css`).
- `components/` — presentational panes. They take props and hold no fetching logic,
  which is what makes them straightforward to unit test.
- `lib/` — the API client, the SSE hook, formatting, and the treemap layout.
- `tests/` — unit tests. `tests/fixtures.ts` holds payloads copied verbatim from
  `planning/BUILD_CONTRACT.md`, so a contract drift surfaces as a failing test.

## Notes

- Fonts are pulled by `next/font/google` at **build time** and self-hosted from
  `out/_next/static/media`, so the Docker build needs network access to
  `fonts.googleapis.com`, and the running app needs none.
- Sparkline history is accumulated client-side from the SSE stream and capped at 120
  points per ticker (`lib/usePriceStream.ts`).
- The `data-testid` attributes in `planning/BUILD_CONTRACT.md` §7.4 are a contract with
  the Playwright suite. Do not rename them.
