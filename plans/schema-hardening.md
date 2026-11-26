# Schema hardening — pre-deploy (squash + harden)

Status: implemented on `feature/schema-hardening`.

## What happened

The 10-migration history collapsed into one clean baseline migration that
hardens the schema for first real users. Nothing was deployed, so no data
migration was needed; every stack database resets and replays the baseline.

Single baseline: `supabase/migrations/20261126135231_initial_schema.sql`
(created by `uv run task migration:new -- initial_schema`).

Schema changes:

- `public.language_code` domain — the single canonical supported-language
  list. All five language-typed columns (profiles.target_language,
  sessions.language, cards.language, user_languages.language,
  card_reviews.language) use it, `NOT NULL DEFAULT 'es'`. Adding a language =
  one ALTER DOMAIN migration + entries in both app maps. Drift-guard tests
  parse the domain line: `tests/test_language_domain.py` (pytest) and
  `frontend/tests/languages.test.ts` (Vitest).
- Tables rebuilt with NOT NULLs + CHECKs on enum-ish columns (sessions.status,
  transcripts.speaker, cards.type, card_reviews.rating, fsrs_data object
  shape), `ON DELETE CASCADE` from auth.users through profiles/sessions/
  cards, and the app's hot-path indexes only.
- `profiles` slims to identity + pointers (`target_language`,
  `onboarded_at`, `updated_at`); `user_languages` solely owns per-language
  learner context — the legacy `profiles.goals/level/interests` copies are
  dropped.
- `sessions.recap` carried forward (the analyst writes it; history/progress
  read it).
- RLS rewritten: every policy `TO authenticated`, USING/WITH CHECK pairs,
  dead INSERT policies dropped (no browser inserts to sessions/transcripts/
  cards/profiles; card_reviews is SELECT-only; user_languages keeps
  INSERT/UPDATE as the one browser-written table).
- `handle_new_user()` trigger on auth.users auto-creates the profiles row
  (SECURITY DEFINER, empty search_path, EXECUTE revoked from web roles).

## Filename convention — the empirical finding

The plan proposed underscore-dated `YYYY_MM_DD_<seq>_<name>.sql` filenames.
The Supabase CLI (v3.1.0) keys migrations by the *leading digit-run* of the
filename, so those names degenerate: version recorded as `2026`, and the
**second migration of the day fails** with

    ERROR: duplicate key value violates unique constraint "schema_migrations_pkey"
    Key (version)=(2026) already exists.

Verified empirically (probe migration through `supabase db reset`), so the
plan's fallback applies: filenames are CLI-canonical
`YYYYMMDDHHMMSS_<name>.sql`, produced ONLY by `uv run task migration:new --
<name>` (never hand-typed). The generator test
`tests/test_migration_generator.py` pins the 14-digit-stamp contract
permanently.

## App-side changes

- `harvest_new_cards` drops card candidates whose `type` is outside the four
  DB-allowed values (prevents LLM output 500ing session end on the cards.type
  CHECK).
- `fetch_effective_profile` reads profiles + the language's user_languages
  row; the legacy overlay logic is gone. A not-yet-onboarded language
  surfaces as "no context yet" (tutor-agent defaults render).
- Onboarding wizard: single write of learner context into user_languages;
  the profiles upsert became an update stamped with `onboarded_at`,
  confirmed via `.select('id')` (0 rows ⇒ setup-error toast).
- Chat page gates on `onboarded_at is not null` (the row always exists now);
  profile page prefills from user_languages only (blank form otherwise).
- E2E seeder + Vitest canned rows updated (profiles: id, target_language,
  onboarded_at).
- Config hygiene: `minimum_password_length` 6 → 8; `supabase/seed.sql`
  placeholder added (config enabled `[db.seed]` without the file).

## Verification

- Gates all green offline: `uv run task test` (85 passed),
  `uv run ruff check .`, `uv run task check:frontend` (54 tests).
- `supabase db reset` applies the baseline cleanly;
  `supabase migration list --local` records `20261126135231`;
  `supabase db advisors` → zero findings.
- DB probes: signup trigger auto-creates profiles (target_language 'es',
  onboarded_at NULL); domain CHECK rejects non-'es'; cards.type CHECK
  rejects junk; auth.users delete cascades (0 orphans); two consecutive
  migrations apply in sorted version order.
- Browser E2E (`uv run task test:e2e`, 8/8 routes) green against
  `uv run task dev`.
- Manual cycle against the real stack: signup → trigger profile →
  onboarding writes (RLS-checked PATCH + user_languages upsert) →
  `/sessions/start` → streamed chat (real LLM) → `/sessions/end` (recap) →
  library card delete (204). Negative RLS probes: browser INSERT to
  sessions/transcripts → 403; cross-user PATCH → 0 rows.
