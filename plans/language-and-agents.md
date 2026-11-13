# Selectable target language + make planner/post-session agents functional

## Context

Three problems, one overhaul:

1. **Spanish is hardcoded everywhere.** Agent prompts ("Spanish tutor", "next Spanish
   conversation"), the tutor variable (`spanish_tutor`), the `/translate` defaults, TTS
   model/voice, onboarding copy, chat-page labels, and a stray "Pensando…" loader in the
   otherwise-English UI. Spanish must become configuration — the only supported *target*
   (learning) language for now, selectable, with the UI remaining English.
2. **Planner + post-session agents are barely functional.** They share tiny
   granite4.2:3b with the chat tutor, which struggles with JSON/schema adherence
   (`retries=3` exists to paper over it). They move to `gemma4:31b-cloud` (Ollama cloud
   model, native tools + thinking; routes via the local server, needs `ollama signin`;
   local Ollama ≥ 0.18 — installed: 0.40.13 ✓). Tutor + translator stay on granite.
3. **The "lesson bank" is a fiction and the plan is dead code.** The `lessons` table and
   `suggested_lesson_id` imply a curriculum bank nothing seeds or consumes. Lessons are
   generated *on the fly*: a handful of structural templates the planner instantiates per
   user/session. Currently the plan is stored but never used — the frontend never calls
   `/sessions/plan`, and `/chat` never reads it. Per user decision: the frontend awaits
   `/sessions/plan` right after session start, and `/chat` injects the plan into the
   tutor.

Efficiency targets in the planner: the model re-emits whole review cards
(`PlannedCard(card_id, content, reason)`) instead of selecting IDs, and full card rows
(including `fsrs_data` JSON blobs) enter the prompts.

**Decisions confirmed via Inbox:** plan generated right after session start (awaited by
frontend) · three templates (role play, reading passage + questions, free conversation
driven by due-card vocabulary) · tutor + translator stay granite, planner + post-session
on gemma4:31b-cloud · onboarding language picker (Spanish enabled, French/German/Italian/
Portuguese disabled "coming soon" chips) stored as `profiles.target_language`, shown and
editable on the profile page.

## Approach

### 1. Language abstraction (Spanish = the only entry; nothing hardcoded)

- **New** `src/voca/services/languages.py`: `SUPPORTED_LANGUAGES: dict[str, str]`
  mapping code → display name (`{"es": "Spanish"}`), `DEFAULT_LANGUAGE = "es"`, and
  `language_name(code)` with graceful fallback to the default. Future language = one
  entry.
- **Migration** `20240101000004_target_language_drop_lessons.sql`:
  `ALTER TABLE profiles ADD COLUMN target_language TEXT NOT NULL DEFAULT 'es';` and
  `DROP TABLE lessons;` (verified: nothing but `/sessions/plan` reads `lessons`).
  Every agent already receives the profile row via `fetch_profile_by`, so the language
  needs no extra deps plumbing — agents read `user_profile["target_language"]`.
- **Tutor** (`tutor_agent.py`): rename `spanish_tutor` → `tutor_agent`; instructions use
  `{language_name}` ("friendly and encouraging {language} tutor", default goal
  "learn {language}", corrections "in {language} or English", converse "primarily in
  {language}").
- **Planner / post-session** instructions: `{language_name}` instead of "Spanish".
- **`/translate`**: endpoint unchanged (already parameterized); the frontend sends the
  profile's language instead of hardcoded `'es'`.
- **Frontend** `frontend/lib/languages.ts` (new): the same code→name map plus per-language
  TTS config (`es` → `phonon:40m-es` / `Alicia`) — the only place TTS is configured.
  `/api/tts` accepts an optional `lang` and resolves model/voice through it.
- **UI copy**: onboarding gets a language picker step-section (Spanish enabled; French,
  German, Italian, Portuguese disabled chips labeled "coming soon"); profile page shows
  and edits it (same picker); chat-page header "Spanish Session" → `{language} Session`,
  placeholder "Type your message in {language}…", empty-state copy; the profile select in
  the auth-check effect gains `target_language`; "Pensando…" → "Thinking…".
- TTS is intentionally Spanish-only still — the mapping table is the future seam.

### 2. Model split

- `src/voca/services/llm.py`: keep `ollama_model` (granite + its
  `reasoning_effort: none` settings); add `planning_model` = `OllamaModel(
  os.getenv("LLM_PLANNING_MODEL", "gemma4:31b-cloud"), …)` with plain settings. If gemma
  thinking proves slow/costly in testing, disable the same way (`reasoning_effort:
  "none"` through the OpenAI-compat endpoint) — verify during integration tests.
- `session_planner_agent` and `post_session_agent` use `planning_model`; keep `retries=3`.
- `src/voca/.env`: add `LLM_PLANNING_MODEL=gemma4:31b-cloud` (and note the `ollama
  signin` requirement in the plan's verification steps, not in the repo).

### 3. Lessons = three templates + on-the-fly instantiation

- **New** `src/voca/services/lesson_templates.py`: `LESSON_TEMPLATES` — descriptors
  `(id, name, structure)` where structure is a compact phase outline the tutor follows:
  1. `role_play` — set a scenario/roles, target phrases, twist, success criteria
  2. `reading_comprehension` — tutor reads a short passage, learner answers questions
  3. `free_conversation` — open conversation that deliberately works in due-card vocab
- **Planner output schema** (`SessionPlan`) becomes:
  - `lesson: LessonSpec { template: str, topic: str, scenario: str | None, objectives:
    list[str] }` — the planner instantiates a template id with a topic tailored to the
    profile, level, interests, and due cards
  - `card_ids: list[str]` — selection only, no content duplication
  - `opening_hook: str` — unchanged
- **`/sessions/plan`** flow: fetch profile + due cards → run planner → reject/filter
  `card_ids` that aren't actually due → fetch `front/back` for the selected IDs → store
  enriched plan JSON (spec + resolved cards) in `sessions.plan` → return it. Resolving
  cards at plan time means `/chat` needs zero extra queries.
- **`/chat`** consumes it: session row (already loaded via `get_owned_session`) provides
  `plan`; `TutorDeps` gains `session_plan: dict | None`; the tutor instructions render a
  "Today's lesson" section: template name + structure, topic/scenario, objectives, and
  "Target vocabulary (weave in): front → back" lines, plus the opening hook for message 1
  (history empty). Absent/old plan → behaves exactly as today.
- **Post-session**: `PostSessionDeps` gains `session_plan`; `lesson_completed` and
  `next_time_preview` are judged against the plan's objectives/lesson. `recap` schema
  unchanged.
- Drop the `lessons` query from `/sessions/plan`, `available_lessons` deps, and the table.

### 4. Efficiency

- Planner deps: compact due cards `[{"id", "front", "back"}]` via a small projection
  helper in `main.py`; output = `card_ids` only.
- Post-session deps: same compact projection (DB fetch keeps full rows — `/sessions/end`
  needs `fsrs_data` for SRS updates — but only id/front/back enter the prompt); grades
  are already ID+outcome.
- `profile_updates: dict` → `ProfileUpdates { goals, interests, level: str | None }`;
  only non-None fields are written to `profiles` (blocks arbitrary-column writes too).

## Files to modify

Backend:
- `src/voca/services/languages.py`, `src/voca/services/lesson_templates.py` (new)
- `src/voca/services/llm.py`
- `src/voca/agents/tutor_agent.py`, `src/voca/agents/session_planner_agent.py`,
  `src/voca/agents/post_session_agent.py`
- `src/voca/main.py`
- `supabase/migrations/20240101000004_target_language_drop_lessons.sql` (new)
- `src/voca/.env` (add `LLM_PLANNING_MODEL`)

Frontend:
- `frontend/lib/languages.ts` (new), `frontend/lib/api.ts` (TTS constants → per-language
  resolution), `frontend/app/api/tts/route.ts`
- `frontend/app/onboarding/page.tsx`, `frontend/app/profile/page.tsx`
- `frontend/app/page.tsx` (copy, profile language fetch, plan display + `/sessions/plan`
  call after session start, translate + TTS language param)

Tests:
- `tests/test_agents.py`, `tests/test_sessions.py`, `tests/test_chat.py` — rename
  `spanish_tutor`, new planner schema (`card_ids`, `lesson`), template deps, compact card
  deps, ProfileUpdates writes
- `tests/test_integration_llm.py` — tutor Spanish reply (unchanged behavior, new name) +
  **new live tests: planner and post-session on gemma4:31b-cloud must emit schema-valid
  output with `card_ids ⊆ due card ids`** (the original pain point)

## Reuse

- `fetch_profile_by`, `fetch_due_cards`, `get_owned_session` (`src/voca/main.py`) — the
  profile row carries `target_language` with no extra calls; the session row carries
  `plan`.
- `OllamaModel`/`OllamaProvider` pattern and `_build_provider` in
  `src/voca/services/llm.py` — copy for `planning_model`.
- `sessions.plan` JSONB (`20240101000002_add_plan_to_sessions.sql`) — new plan shape fits
  without further migrations.
- Test infra: FakeSupabase + TestModel + `capture_run_messages` (`tests/conftest.py`,
  `tests/test_agents.py`).
- pydantic-ai pattern: single `Agent` per job with `output_type` + instructions functions
  (existing agents) — kept as-is, only model/schema changes.

## Steps

1. Migration + `languages.py`; rename tutor agent; make all three agent prompts
   language-aware (`tutor_agent`, planner, post-session).
2. `llm.py` model split + `.env` key; point planner/post-session at `planning_model`.
3. `lesson_templates.py` (3 templates); planner schema → `lesson` + `card_ids`; compact
   card deps; drop `lessons` table/query/deps; update `/sessions/plan` (filter IDs,
   store enriched plan). `ProfileUpdates` model in post-session + narrowed DB write.
4. `/chat` injects plan into tutor deps+instructions; post-session gets plan for recap.
5. Frontend: `lib/languages.ts`, TTS lang mapping, onboarding picker, profile page
   picker/display; chat page — dynamic copy, `target_language` from profile, call
   `/sessions/plan` after `/sessions/start` (planning indicator), show the lesson line,
   translate + TTS use the language, "Pensando…" → "Thinking…".
6. Offline test updates; then `gemma4` live integration tests for planner + post-session
   schema adherence (tune thinking mode if problematic).
7. Gates: `uv run task test` + `uv run ruff check .` +
   `uv run task check:frontend`; fix breakage before claiming done; tidy via
   `uv run task tidy`.

## Verification

- `uv run task test` green offline; `uv run ruff check .` clean; frontend typecheck+lint
  clean.
- `uv run task test:all` with Ollama signed in (`ollama signin` if needed): tutor replies
  in Spanish; **planner and post-session produce schema-valid output through
  `gemma4:31b-cloud`**; selected `card_ids` all reference due cards.
- Manual: `uv run task dev` → onboarding picker (only Spanish selectable) → start chat →
  planning step runs → "Today's lesson" visible in tutor behavior/opening reply → end
  session → recap reflects lesson + new cards → profile page can display the language
  (other options stay disabled).
- `plannotator` guided review of the final diff.
