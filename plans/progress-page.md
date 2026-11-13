# Progress page — dedicated sidebar tab with learning metrics

## Context

Today the only SRS presence for users is a placeholder card at the bottom of the
Profile page ("SRS Progress — your spaced repetition progress will be visualized
here"). It shows no data. Meanwhile real progress signals already exist in the
database:

- `cards.fsrs_data` — FSRS state per card (due, stability, difficulty, last_review)
- `cards.next_review` — materialized due date
- `sessions` — start/end times, `recap.user_word_count` (words the learner spoke)
- (missing) **review history** — FSRS v6 `Card.to_dict()` has no `reps`/`lapses`
  counters and `/sessions/end` discards the `ReviewLog` after updating card state,
  so "number of positive recalls" and any review-activity-over-time metric cannot
  be computed today.

**Goal:** a new "Progress" sidebar tab (`/progress`) replacing the placeholder,
with activity metrics (sessions/day, active days, words spoken/day), review-card
metrics (due counts, positive recalls, etc.), a weekly/monthly/yearly time toggle,
and due dates displayed on the card library page.

## Decisions

- New sidebar nav item **Progress** → `frontend/app/progress/page.tsx` (between
  Library and Profile).
- Remove the "SRS Progress" placeholder card from `app/profile/page.tsx` (page
  becomes profile-only; nothing lost).
- Add a `card_reviews` log table (migration + write in `/sessions/end`) so positive
  recalls and review activity over time become computable. FSRS state alone
  (fsrs >= 6) does not keep review counts.
- Card library cards show due badges from `next_review` (+ FSRS state label).

## Answers from the person (round 1 — resolved)

1. **Time toggle**: Week / Month / Year / All. Week & Month = daily bars
   (last 7 / 30 days); Year = last 12 months monthly; All = monthly since the
   first session.
2. **Language scope**: active language only (sidebar dropdown controls it),
   consistent with Library/History.
3. **Charts**: add **recharts** as a dependency (bar charts with tooltips/axes);
   use a React-19-compatible recharts v3.
4. **Toggle scope**: the time toggle applies to **both** speaking metrics and
   review-activity metrics; current-state review snapshot cards stay always visible.

## Data available (verified)

- `fsrs` 6.3.2: `Card.to_dict()` → `card_id, difficulty, due, last_review, stability, state, step`.
  **No review counters.**
- `ReviewLog` → `card_id, rating, review_datetime, review_duration`.
- `VOCA_RATING_MAP` (`services/srs.py`): strong_pass/recognition_pass→Easy, pass→Good, miss→Again.
- FSRS `Rating` enum: Again=1, Hard=2, Good=3, Easy=4. Voca emits Again/Good/Easy
  (never Hard). "Positive recall" = rating >= 3 (Good or Easy); "missed" = Again.
- FSRS 6 `State` enum: Learning=1, Review=2, Relearning=3 (no 0). A fresh card
  serializes as `state: 1, stability: null, last_review: null` — i.e. **"new" =
  `last_review IS NULL`**, not a distinct state value. The `cards.state` text column
  is a stale label — derive card-state labels from `fsrs_data`, never from it.
- `sessions.recap.user_word_count` set at `/sessions/end` (completed sessions only;
  in-progress sessions have no recap yet).
- UI primitives available: `components/ui/tabs.tsx` (Base UI Tabs — good fit for the
  Week/Month/Year toggle), Card, Badge, Table; `date-fns` is installed for date math.

## Approach

Progress data aggregates **client-side from Supabase** (anon key + RLS), matching how
`app/library/page.tsx` already queries `cards` directly — no new backend read API.
Pure bucketing/grouping helpers live in `frontend/lib/stats.ts` so the page stays thin.
The only backend change is **writing** review logs at review time.

### 1. Review log table (unblocks "positive recalls" + review time series)

`supabase/migrations/2026…_add_card_reviews.sql`:

```sql
CREATE TABLE card_reviews (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    card_id UUID NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    language TEXT NOT NULL,           -- denormalized: enables per-language filters
    rating INT NOT NULL,              -- FSRS rating: 1=Again 2=Hard 3=Good 4=Easy
    reviewed_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
ALTER TABLE card_reviews ENABLE ROW LEVEL SECURITY;
-- view/insert own rows (RLS pattern copied from initial migration)
```

`/sessions/end` currently calls `update_card_state` and throws away the returned
`ReviewLog`. Change `services/srs.py` to return `(state_json, review_log_dict)`
(e.g. re-purpose `update_card_state` or add `review_card_state`), and have the route
insert a `card_reviews` row (with the session's `language` and the mapped rating as
an int) next to each card-state update.

### 2. Progress page (`frontend/app/progress/page.tsx`)

New page under `DashboardLayout`. Fetches are RLS-scoped to the user + active
language via `useLanguage()` (per the Library pattern). All aggregation math lives
in pure helpers in `frontend/lib/stats.ts` (types + bucketing + counting) so the
page stays thin and the math is reviewable.

- **Time toggle**: a small Tabs list — Week / Month / Year / All — controlling every
  charted series (speaking *and* review activity). Bucketing per the resolved
  answers above; "All" starts at the user's first session (or first review).
- **Speaking activity** (time-scoped, from `sessions`):
  - Stat cards: sessions practiced, active days (≥1 session), words spoken
    (Σ `sessions.recap.user_word_count`), plus per-day averages over the range.
  - recharts bar chart: words spoken per bucket (daily/monthly).
- **Review activity** (time-scoped, from `card_reviews`):
  - Stat cards: reviews in range, positive recalls in range, recall rate.
  - recharts stacked bar chart per bucket: positive (Good/Easy) vs missed (Again).
- **Review-card snapshot** (always visible, not time-scoped; from `cards`):
  - Stat cards: total cards, due now (`next_review <= now`, incl. overdue),
    new (never studied), learning, review-state counts, lifetime positive
    recalls / total reviews, lifetime recall rate.
- Data sources (three simple selects, same style as `app/library/page.tsx`):
  - `sessions` → `start_time, status, recap, language` (language filter = active)
  - `cards` → `fsrs_data, next_review, language` (language filter = active)
  - `card_reviews` → `rating, reviewed_at, language` (language filter = active)
- Charts use recharts (`BarChart` + `ResponsiveContainer`) themed from the app's CSS
  variables (muted/foreground) and wrapped in existing Card components.
- Empty states follow the Library/History pattern (icon + "no data yet" copy).

### 3. Sidebar + Profile cleanup

- `sidebar.tsx`: add `{ name: "Progress", href: "/progress", icon: <chart icon> }` after
  Library (pick an available lucide chart icon during implementation).
- `profile/page.tsx`: delete the SRS placeholder card + now-unused imports.

### 4. Card library due dates (`app/library/page.tsx`)

- The existing query uses `select('*')`, so `next_review`/`fsrs_data` already arrive
  — only the `CardRow` type and rendering change.
- Each card gets a state label (New = `last_review` null; Learning/Relearning/Review
  from `fsrs_data.state`) and a due badge: highlighted "Due now" (incl. overdue) or
  formatted due date via `date-fns`.

### Branch

Feature branch `feature/progress-page` cut from `main` (repo convention: never commit to main).

## Files to modify

- `supabase/migrations/2026…_add_card_reviews.sql` (new)
- `src/voca/services/srs.py` — return `(state_json, review_log)` from the review step
- `src/voca/main.py` — `/sessions/end` inserts `card_reviews` rows
- `tests/test_sessions.py` — assert the review-log inserts
- `frontend/package.json` — add recharts (`cd frontend && npm install recharts`;
  verify a React-19-compatible v3 installs on Next 16)
- `frontend/lib/stats.ts` (new) — pure bucketing/counting helpers + row types
- `frontend/components/sidebar.tsx` — Progress nav item
- `frontend/app/progress/page.tsx` (new) — the Progress page
- `frontend/app/profile/page.tsx` — remove placeholder card + unused imports
- `frontend/app/library/page.tsx` — due/state badges

## Steps

1. [ ] Cut `feature/progress-page` from `main`
2. [ ] Migration: `card_reviews` table + RLS policies
3. [ ] `srs.py`: surface the review log from the state update; `main.py`
       `/sessions/end` inserts one `card_reviews` row per graded card
4. [ ] Backend tests for the review-log insert; `uv run task test` + ruff green
5. [ ] Install recharts in `frontend/`
6. [ ] `lib/stats.ts`: row types, range/window + daily/monthly bucketing helpers
7. [ ] `/progress` page: fetches, stat cards, recharts charts, Week/Month/Year/All
       Tabs, active-language scoping, empty states
8. [ ] Sidebar nav item "Progress"; remove Profile placeholder card
9. [ ] Library cards: state label + due badge
10. [ ] `uv run task tidy`, `uv run task test`, `npm run typecheck && npm run lint` green
11. [ ] Manual end-to-end (see Verification) on `uv run task dev`

## Verification

- Backend: `uv run task test` — extend `tests/test_sessions.py` so `/sessions/end`
  (with mocked supabase + TestModel agents) asserts a `card_reviews` insert per
  reviewed card with the mapped rating; `uv run ruff check .`.
- Frontend: `(cd frontend && npm run typecheck && npm run lint)`.
- Migration applies cleanly: `uv run task dev` (supabase start + migrate).
- Manual end-to-end:
  1. Run a chat session, have it create cards, end the session with a few reviewed
     cards (pass/miss outcomes).
  2. `/progress` shows the session, active day, word count; card snapshot shows due
     counts and positive recalls; toggle Week/Month/Year/All changes scope.
  3. Card library shows due badges + state labels per card.
  4. Profile page no longer shows the placeholder.
