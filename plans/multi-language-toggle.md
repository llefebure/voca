# Multi-language practice with language toggle

## Context

Voca assumes each user learns exactly one language: `profiles.target_language` (default
`'es'`) drives the tutor/planner/post-session agents, TTS voice, and every list. The goal:
users practice **multiple languages** — onboarding selects the starting language, and a
dropdown lets them toggle languages later. After a toggle, the UX switches wholesale:
history, library, progress, and new sessions all belong to the active language.

User decisions (confirmed):
1. Level/goals/interests are tracked **separately per language**.
2. "Add language" flow is **identical to onboarding** (reuse the same page).
3. Toggle ships **now**, with Spanish the only selectable language (French/German/etc.
   shown disabled, "coming soon") — adding language #2 later is a config change only.
4. Toggling away **clears the open session** from the chat UI, but the session **stays
   open (active) and stays visible in History** — when the user toggles back to that
   language and opens their history panel, they see the conversation, still active. This
   is exactly the same semantics as clicking "New session" today: the previous session
   remains open in history. Opening/opening-back an active session works via a **Continue**
   affordance in history (and the transcript page), which restores the session — plan and
   full conversation — into the chat. The chat page does **not** auto-resume anything by
   itself (otherwise "New session" would resurrect stale conversations).

## Current state (findings)

- **Schema** (`supabase/migrations/`): `profiles.target_language TEXT` only.
  `sessions` and `cards` have **no language column** — old data is implicitly Spanish.
  `profiles.preferences` holds correction intensity / speech speed (stays global).
- **Backend** (`src/voca/main.py`):
  - `fetch_profile_by(user_id)` → profile dict, fed as `user_profile` deps to all three
    agents. Tutors/planners read `target_language`, `level`, `goals`, `interests` from it
    (`agents/tutor_agent.py:31`, `agents/session_planner_agent.py:60`).
  - `fetch_due_cards(user_id)` returns all cards regardless of language.
  - `POST /sessions/start` inserts a bare row (no language stamp).
  - `end_session` writes the post-session agent's `profile_updates` (goals/interests/level)
    to `profiles` — per-language details must instead go to a per-language table.
- **Frontend**:
  - Chat (`app/page.tsx`): session is created lazily on first message (`activeSessionId()`),
    exists only in memory after that; plan shown from state; transcripts are never replayed.
    The `/api/chat` proxy sends the full message history every turn, so restoring messages
    into `useChat` state continues conversations correctly with no backend change.
  - "New session" clears only local state — the server-side session row remains
    `status='active'` and shows up in History as Active (today's behavior, which stays).
  - Transcript fetch pattern to reuse: `app/history/[sessionId]/page.tsx` (direct Supabase
    query under RLS).
  - Onboarding (`app/onboarding/page.tsx`) upserts `profiles` and is already idempotent.
  - History/Library query everything (no language filter).
  - `lib/languages.ts` is the frontend language/TTS source of truth;
    `components/ui/dropdown-menu.tsx` (Base UI) available for the toggle.

## Approach

**`profiles.target_language` remains the single "active language" pointer.** Toggling
writes it directly; `/sessions/start` re-syncs it to the session's language (so the most
recently practiced language is what you land on, even from another device). Content is
tagged at creation time and everything reads it back:

- Sessions get their language **stamped at start** and keep it for their whole life. Open
  sessions are never closed implicitly: toggling languages or starting a new session leaves
  them `active` in the database, visible in History.
- Cards are stamped with their session's language; due-card fetching, history, and library
  filter by the active language.
- Per-language learner context (level/goals/interests) lives in a new `user_languages`
  table; the backend merges it over the base profile ("effective profile") before feeding
  agent deps — **agent files themselves need no changes** (post-session profile upgrades
  just get written to `user_languages` instead of `profiles`).
- **Add a language = run the identical onboarding flow.** The sidebar's "Add language…"
  routes to `/onboarding`; its completion step upserts a `user_languages` row for the
  chosen language and sets it active. Today only Spanish passes the picker's enabled gate.

### DB migration — `supabase/migrations/20261113000001_multi_language.sql` (new)

Migration prefixes follow the actual git commit date of each file (not scaffold dates).
Because the local Supabase DB is disposable, the existing files are **renamed in this
change** (git history: four committed 2026-11-09, one 2026-11-13; then a dev-run
`supabase db reset` re-applies the chain cleanly):

| current | new |
|---|---|
| `20240101000000_initial_schema.sql` | `20261109000000_initial_schema.sql` |
| `20240101000001_add_session_phase.sql` | `20261109000001_add_session_phase.sql` |
| `20240101000002_add_plan_to_sessions.sql` | `20261109000002_add_plan_to_sessions.sql` |
| `20240101000003_add_recap_to_sessions.sql` | `20261109000003_add_recap_to_sessions.sql` |
| `20240101000004_target_language_drop_lessons.sql` | `20261113000000_target_language_drop_lessons.sql` |
| — | `20261113000001_multi_language.sql` (**new**, this change) |

```sql
ALTER TABLE sessions ADD COLUMN language TEXT NOT NULL DEFAULT 'es';  -- backfills
ALTER TABLE cards    ADD COLUMN language TEXT NOT NULL DEFAULT 'es';  -- backfills

CREATE TABLE user_languages (
    user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    language TEXT NOT NULL,
    level TEXT,
    goals TEXT,
    interests TEXT,
    last_practiced_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (user_id, language)
);
ALTER TABLE user_languages ENABLE ROW LEVEL SECURITY;
-- Policies: select/insert/update own rows (auth.uid() = user_id), mirroring profiles.
```

### Backend — `src/voca/main.py`

- New helper `fetch_effective_profile(user_id, language)`: fetches the profile row, fetches
  the `user_languages` row for `language`, returns `{**profile, "target_language": language}`
  merged with the row's `level`/`goals`/`interests` when present. Used by `/sessions/plan`,
  `/chat`, and `/sessions/end` so agents always see the session language + its context.
- `fetch_due_cards(user_id)` → add `language` argument with a `.eq("language", language)`
  filter (planner deps and end-session grading both pass the session's language).
- `POST /sessions/start`: read the profile first, insert
  `{user_id, status: "active", language: profile.target_language or "es"}`; upsert
  `user_languages(user_id, language, last_practiced_at=now)`; update
  `profiles.target_language` to that language (keeps "latest practiced" = login view).
- `GET /sessions`: optional `?language=` query param filters rows; each `SessionResponse`
  gains a `language` field.
- `end_session`: use the session's language for `fetch_due_cards`, the post-session
  `target_language` dep, and stamping new cards (`cards.language`); write
  `profile_updates` (goals/interests/level) to the session language's `user_languages` row
  (upsert) instead of `profiles`.
- `/translate` unchanged (already takes explicit langs).

There is **no abandon endpoint**: nothing ever closes a session implicitly. An open
session leaves the chat only through the "End session" dialog (which runs the full
post-session analysis) or stays open in history indefinitely.

**No changes needed in `agents/*` or `services/*`** — agents consume deps.

### Frontend — language context + sidebar toggle

- New `components/language-context.tsx`: a small React context provider used by
  `DashboardLayout`. Holds `activeLanguage`, the user's practiced languages
  (`user_languages`, ordered by `last_practiced_at desc`), and `toggleLanguage(code)` /
  `addLanguage()` (routes to `/onboarding`). Fetches the profile + rows once, exposes
  refetch; toggling upserts `profiles.target_language` and updates context state so every
  page under the layout switches together.
- `components/sidebar.tsx`: replace the static "Voca Tutor" header area with a
  `DropdownMenu` showing practiced languages (checkmark on active), then supported
  not-yet-practiced languages, then disabled `UPCOMING_LANGUAGES` entries ("Soon"), then
  "Add language…". Collapsed state keeps a language icon affordance.
- `app/page.tsx` (chat):
  - Read active language + practiced languages from context (drop the local profile fetch).
  - **Toggle away** → context change → chat resets to a fresh empty page (lazily created
    session as today). The previous session is untouched — active in the DB and visible in
    History for its language.
  - **Continue an open session**: the page honors a `?session=<id>` query param (from the
    History "Continue" button): it verifies the session is owned/active (RLS select),
    restores `sessionId`, sets the plan from `session.plan`, fetches its transcripts (same
    query as the transcript page) and seeds `useChat` messages (user/assistant text parts),
    so the conversation continues seamlessly. This is the only restore path — no auto-resume
    on load or toggle, so "New session" never resurrects old conversations.
  - "New session" button: unchanged (local clear only); the old session stays open in history.
  - TTS: unchanged (`speak(..., targetLanguage)` already in place).
- `app/history/page.tsx`: fetch `/sessions?language=<activeLanguage>`; pass-through now
  just filters — the endpoint falls back to all sessions when the param is absent. Active
  sessions get a **Continue** button (routes to `/?session=<id>`) alongside the existing
  "View Transcript" / "View Recap" actions.
- `app/history/[sessionId]/page.tsx` (transcript): active sessions get the same
  **Continue** button for users who open the transcript first.
- `app/library/page.tsx`: add `.eq('language', activeLanguage)` to the cards query.
- `app/profile/page.tsx`: show the active language's level/goals/interests (from context/
  `user_languages`); editing writes per-language fields to `user_languages` (upsert row for
  the active language) while `preferences` stays on `profiles`. Language switching remains
  via the sidebar dropdown.
- `app/onboarding/page.tsx`: on completion, upsert `profiles` as today **plus** a
  `user_languages` row for the selected language (level/goals/interests,
  `last_practiced_at: null`). No step changes.
- `lib/languages.ts`: unchanged (still the source for names/TTS/`UPCOMING_LANGUAGES`).

### Tests — `tests/test_sessions.py`, `tests/test_chat.py`

- `/sessions/start` stamps the profile's language, syncs `profiles.target_language`, and
  upserts `user_languages.last_practiced_at` (fake supabase records inserts/updates).
- Effective-profile merge: `user_languages` row overlays level/goals/interests and pins
  `target_language`; absence of a row keeps the base profile.
- `fetch_due_cards` / session list respect the language filter (assert recorded filters).
- `end_session` stamps new cards with the session's language and writes profile updates to
  `user_languages`.
- The fake supabase in `tests/conftest.py` already supports everything generically.

## Files to modify

- `supabase/migrations/` — rename five existing files to commit-date prefixes; add
  `20261113000001_multi_language.sql` (**new**)
- `src/voca/main.py` — effective profile, language stamps/filters
- `tests/test_sessions.py`, `tests/test_chat.py` — new/updated cases
- `frontend/components/language-context.tsx` — **new** (context provider)
- `frontend/components/dashboard-layout.tsx` — wrap content in the provider
- `frontend/components/sidebar.tsx` — language dropdown
- `frontend/app/page.tsx` — context consumption, `?session=` continue flow, toggle-clear
- `frontend/app/history/page.tsx` — language filter + Continue button on active sessions
- `frontend/app/history/[sessionId]/page.tsx` — Continue button on the transcript page
- `frontend/app/library/page.tsx` — language filter
- `frontend/app/profile/page.tsx` — per-language details
- `frontend/app/onboarding/page.tsx` — upsert `user_languages`

## Reuse

- `fetch_profile_by`, `db`, `get_current_user`, `get_owned_session` (`src/voca/main.py`)
- `languageName` / `SUPPORTED_LANGUAGES` / `UPCOMING_LANGUAGES` (`frontend/lib/languages.ts`)
- Transcript-fetch RLS pattern from `frontend/app/history/[sessionId]/page.tsx` for restore
- `DropdownMenu` (`frontend/components/ui/dropdown-menu.tsx`), `toast` (`ui/toast`)
- Onboarding wizard itself as the add-language flow; `FakeSupabase` harness
  (`tests/conftest.py`)

## Steps

- [x] 0. Create a feature branch (`feature/multi-language-toggle`); all steps below land
      on this branch, committed incrementally.
- [x] 1. Migration housekeeping: rename existing migration files to their git commit dates
      (table above), then a one-time `supabase db reset` in dev. Add
      `20261113000001_multi_language.sql`: language columns on `sessions`/`cards` (default
      `'es'`), `user_languages` table + RLS policies; verified via `uv run task dev`.
- [x] 2. Backend: `fetch_effective_profile` helper; language-aware `fetch_due_cards`;
      `/sessions/start` stamping + profile sync + `user_languages` upsert.
- [x] 3. Backend: `GET /sessions?language=` language param + language field on responses,
      `end_session` (session-language due cards, card stamps, post-session profile updates
      → `user_languages`).
- [x] 4. Backend tests for all the above.
- [x] 5. Frontend: `language-context.tsx` provider + `DashboardLayout` wiring.
- [x] 6. Sidebar language dropdown (practiced / supported / upcoming / Add language…).
- [x] 7. Chat page: toggle-clear to a fresh page, `?session=` continue flow (verify
          ownership, restore plan + transcript replay into `useChat`).
- [x] 8. History: language filter + Continue button on active sessions (list + transcript
          pages); Library/Profile/Onboarding language wiring.
- [ ] 9. Gates: `uv run task test`, `uv run ruff check .`, frontend typecheck + lint.
- [ ] 10. Push the branch and open a **draft PR** via the `gh` CLI (use the repo's
      `create-pr` skill): summary of the change, the migration rename note (DB reset needed
      once locally), and how to verify; leave it in draft for review.

## Verification

- On `feature/multi-language-toggle`; PR opened in **draft** mode at the end with the
  summary + manual steps below.
- `uv run task test` (offline) — new tests green, suite untouched elsewhere;
  `uv run ruff check .`; `(cd frontend && npm run typecheck && npm run lint)`.
- Manual E2E (`uv run task dev`, supabase migrated):
  1. Fresh user → onboarding (Spanish) → profile row + `user_languages` row exist.
  2. Chat a few turns; reload the page mid-session → fresh chat page, but History still
     lists the session as Active.
  3. Open dropdown: Spanish checked, French/German/etc. disabled; "Add language…" →
     full onboarding flow.
  4. Start/plan a Spanish session, toggle away → chat clears; History shows the session
     still Active (only under Spanish). Toggle back to Spanish, open History → the session
     is there, still open, with a Continue button.
  5. Clicking Continue on the active session → chat restores the plan + full transcript
     conversation mid-session; further turns keep working (proxy history intact). Ending
     it produces the normal recap.
  6. "New session" mid-conversation → old session stays Active/open in history (same
     behavior as toggle-away); a new lazy session starts on the next message.
  7. History/Library reflect only the active language; end session → new cards carry the
     session language (check `cards.language` in Studio), recap unchanged.
  8. Existing pre-migration data all shows under Spanish.
