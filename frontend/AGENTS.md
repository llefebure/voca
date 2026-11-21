<!-- BEGIN:nextjs-agent-rules -->

## This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

## Testing (this app)

- **Unit tests** (`frontend/tests/`, Vitest + RTL, offline): run `npm run test` or `uv run task check:frontend`. Supabase is mocked via `tests/helpers/supabase-mock.ts` (canned per-table rows), `next/navigation` via `tests/helpers/test-navigation.ts`; `pages-smoke.test.tsx` smoke-renders every route (recharts is mocked there: its ResponsiveContainer never lets `act()` settle in jsdom). Extend these when adding pages/components.
- **E2E smoke** (`frontend/e2e/`, Playwright): run `uv run task test:e2e` with the dev stack (`uv run task dev`) up — that task is the canonical AND only supported invocation (it exports the seeder's env via task dotenv). Extra Playwright args pass through: e.g. `uv run task test:e2e -- -g progress` or `-- --ui`. Visits every route signed in and fails on uncaught page errors / console errors.
- Gotchas learned here: React's `use(params)` on a raw resolved promise never resumes under RTL — pass a promise pre-tagged `{ status: 'fulfilled', value }` (see `detailPageParams` in `tests/pages-smoke.test.tsx`); page smoke renders settle with real timers instead of `act()`. Next 16 differs from older knowledge — read the block above before writing Next code.
