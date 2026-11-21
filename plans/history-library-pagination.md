# Plan: history-library-pagination — keep History and the card Library usable as data grows

Branch: `feature/history-library-pagination` · Worktree: `uv run task worktree:new -- feature/history-library-pagination`

## Problem

- `/sessions` (`src/voca/main.py#list_sessions`) returns every session of the user, no
  limit. The History page (`frontend/app/history/page.tsx`) renders the whole list.
- The card Library (`frontend/app/library/page.tsx`) loads every card of the language via
  supabase, and the search box filters the whole array client-side.

As sessions and cards accumulate both pages degrade (payload size, render cost) with no
way for the user to see where they are in the list.

## Approach

Server-driven pagination in both places, page numbers in the UI, server-side search.

### Backend — `/sessions` (sessions list)

1. Query params: `limit` (default 50, cap 100), `offset` (default 0). Keep `language`.
2. Response gains a `total: int` (Postgres `count` under RLS via the supabase client
   `.select(..., count='exact')` equivalent on the Python client: `select('*', count='exact')`
   — read `.count` off the response). `SessionListResponse` gains `total: int = 0`
   (additive; old clients ignore it).
3. Order stays `created_at desc`. Tests in `tests/test_sessions.py`: limit/offset slicing,
   total correctness, default behavior.

### Library — cards via the supabase client (frontend)

1. Replace the one-shot `select('*')` with:
   `.range(offset, offset + PAGE - 1)` + `count: 'exact'` on the same select →
   `{ data, count }`. Default page 24 (3-column grid, 8 rows).
2. Search becomes server-side and debounced (250 ms): when `filter` is non-empty, add
   `.ilike('front', %q%).or(back, %q%)` (supabase-js: `.or('front.ilike.%q%,back.ilike.%q%')`)
   and reset to the first page; empty query drops the filter. This replaces the
   client-side filter entirely (no hidden out-of-page results).
3. Delete interaction: after a successful delete, refetch the current page (not just the
   local array) so totals, page size, and the last-page clamp stay correct. If the page
   becomes empty and `offset > 0`, step back one page.

### UI (`frontend`)

4. Pagination control: check the base-nova registry first
   (`npx shadcn@latest add pagination` inside `frontend/`); if a base-nova-compatible
   pagination primitive ships for this preset, use it. If it's not available, compose the
   existing primitives **in page code** (Buttons + "Showing X–Y of N" + prev/next) —
   do not hand-roll a new `components/ui/` primitive (project convention).
5. History gets prev/next + "Showing X–Y of N" over the new backend params; both pages
   keep their existing empty/loading states (empty applies to any page of results).

## Tests

- Backend: `test_sessions.py` cases above.
- Frontend: extend `tests/helpers/supabase-mock.ts` to support the `range` + `count`
  terminator shape (the mock is pass-through by query builder and resolves on
  terminators — add `range` as a recognized terminator returning `{ data, count }`).
- New page tests: Library page-count changes with a large canned set; server-side search
  calls with the ilike filter; History page navigation refetches with new limit/offset.
- `pages-smoke.test.tsx` keeps passing (query builders are mocked; smoke only pins
  renders). E2E unchanged; run `uv run task test:e2e` if the query seams change.

## Risks / notes

- supabase-js `.or()` + `ilike` strings need escaping for user input containing commas
  (`%` and `,` are special in the or-filter syntax) — sanitize by stripping `,()*` from
  the search term before building the filter string.
- The backend count + page query run as two round trips; fine at this scale.
- Card delete + exact-count pagination: rely on `count='exact'` each fetch; cheap here.

## Gates

`uv run task test`, `uv run ruff check .`, `uv run task check:frontend`.
