# Frontend test suite

**Status:** shipped · **Branch:** `feature/frontend-tests`

## Problem

UI errors kept cropping up after agent-driven changes because the frontend's
only gates were `tsc --noEmit` + eslint — both blind to runtime breakage
(provider misuse, hydration errors, undefined-data access, crashing handlers).
There were zero frontend tests; the backend, meanwhile, had a solid offline
pytest suite to imitate.

## Decision (per the person, via Plannotator)

Build **both** layers:

1. **Vitest + React Testing Library + jsdom** — offline, deterministic, wired
   into `uv run task check` (via `task check:frontend`). Targets:
   - `lib/stats.ts` (pure math, deliberately extractable — was untested),
   - `lib/languages.ts`,
   - `components/language-context.tsx` (provider contract: load, sort,
     toggle/persist, revert-on-error, signed-out clear),
   - `tests/pages-smoke.test.tsx` — smoke-renders every route with Supabase
     mocked (canned per-table rows, same philosophy as the backend suite).
2. **Playwright browser smoke** — `frontend/e2e/smoke.spec.mjs` visits every
   route signed in and fails on any uncaught page error or real console error.
   Separate `uv run task test:e2e`; needs `uv run task dev` up. Self-seeds its
   test user (`e2e-test@voca.local`) into local Supabase via the service-role
   key read from `src/voca/.env` (nothing secret committed).

Skipped on purpose: vendored `components/ui/*` shadcn primitives (CLI-managed).

## Notable gotchas (recorded in frontend/AGENTS.md too)

- `vi.mock` factories run while the test file's imports are evaluated, so any
  per-test tunable config must be created inside `vi.hoisted` — and closures
  must read the seed object tests mutate.
- recharts' `ResponsiveContainer` keeps `act()` from ever settling in jsdom →
  mocked with passthroughs in the smoke test; real chart rendering is the
  Playwright layer's job.
- RTL `act()` may never settle for pages mounted with Base UI internals; the
  page smoke renders settle with real timers and assert with `findBy*`.
- React 19 `use(params)` on a raw resolved `Promise.resolve` suspends forever
  under RTL; pre-tagging the promise `{ status: 'fulfilled', value }` (what
  Next's prerendered params carry) unwraps synchronously.
- Next's route announcer (`__next-route-announcer__`) duplicates page titles:
  E2E asserts on `getByRole('heading', …)`, not text.

## Verification

- `uv run task check` — 44 backend tests + ruff + typecheck + eslint + **35
  frontend unit tests (offline, ~3s)**.
- `uv run task test:e2e` with the dev stack — 8/8 browser smoke (seed, sign-in,
  7 routes × no-crash/no-uncaught-errors) in ~7s.
