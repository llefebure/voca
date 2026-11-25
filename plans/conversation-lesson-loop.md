# Rework the tutor & session planner into a small-talk ⇄ lesson conversation loop

## Context

Today a session is one shot: the frontend awaits `POST /sessions/plan` right after
`/sessions/start`, the planner produces a single `SessionPlan` (template + topic +
objectives + card_ids + opening_hook) stored in `sessions.plan`, and the tutor is briefed
with it from turn 1 — so the very first reply is a lesson-flavored opener. The user wants
a fundamentally different shape:

1. **Unstructured small talk** first (4–5 turns, fluid, no lesson packaging — "Hi, how are you
   today?" with zero "you could say…" scaffolding).
2. **Transition to a formal lesson**: Voca proposes a structured lesson plan mid-conversation
   (idea similar to the current planner); on approval the lesson starts.
3. **Loop back**: when the lesson is done the conversation returns to small talk (no re-greeting);
   either side can propose the next lesson idea. A session may contain several lessons.

Plus three cross-cutting requirements:

- **Lesson taxonomy** — more structured lesson types, each with typed material the UI can render
  (a reading passage is visually distinct from a chat bubble; a menu renders as styled `text`
  material, not as a chat bubble).
- **Review-word injection throughout**, with learners getting **credit** for demonstrating
  understanding of a brought-up review word, and **bonus credit** for using it correctly in context.
- **Generic material primitives, not hardcoded artifacts**: a menu is not a block type — it is
  `text` content (markdown, tables supported) plus a scenario/dialogue about it, exactly like a
  reading passage with discussion questions. The block set stays small and composable.
- A formal lesson targets **~5–10 minutes** (short, contained exercise).

Current seams that make this viable: sessions already carry JSONB (`plan`, `recap`) and the chat
SSE proxy already re-frames backend frames into AI SDK UI-message-stream; `card_reviews` already
records per-session FSRS grades with a recognition/pass/strong_pass outcome ladder. The current
two-lane model split (chat = granite4.2:3b local, structured agents = gemma4:31b-cloud) goes
away in this rework — every agent moves onto gemma4:31b-cloud (see Decisions).

## Decisions made in this plan (flag anything you disagree with before implementation)

- **The backend owns a session state machine** derived from a new `sessions.lessons` JSONB array
  (proposal / active lesson / back to small talk). The tutor model drives transitions via tools;
  the frontend always has an explicit Accept/Decline path so the flow never depends on tool-call
  reliability alone (see Risks).
- **The planner is invoked mid-conversation**, not at session start: no upfront `/sessions/plan`.
  Proposal generation is grounded in the small-talk transcript so far (topics the learner actually
  raised), the learner's profile, due cards, and any lessons already done this session.
- **Full lesson material (blocks) is generated at proposal time** by the planner, so accepting a
  proposal starts the lesson instantly (no second generation wait) and previews what the lesson is.
- **Credit semantics** map onto the existing FSRS outcome ladder — recognition (understood when the
  tutor brought it up) → `recognition_pass`; in-context production → `pass`/`strong_pass` as the
  "bonus" — credited per lesson (guaranteed) and swept again at session end for small-talk usage.
  Live per-message bonus chips are a stretch goal, not v1.
- **One model lane**: every agent — the streaming tutor included — runs `gemma4:31b-cloud`
  (`services/llm.py` collapses to a single `LLM_MODEL`; granite is retired). Native tool calling
  on gemma is what makes tutor-driven transitions dependable, and the stronger model simply does
  the tutor's job better. Model settings are left at their defaults — any "too slow" concern is
  raised by the product owner from actual use, and handled then.
- **Nothing legacy**: no compatibility shims anywhere — `sessions.plan` and the planner's
  `opening_hook` field go away entirely (destructive migration; old rows are cleared), and the
  new `sessions.lessons` array is the single lesson store.

## Approach

### 1. Lesson taxonomy + typed material blocks (`services/lesson_templates.py` rework)

Templates stay a data catalog ("adding a lesson format means adding one entry"); each entry gains
a declared **material schema** — the typed blocks the planner must produce — plus a minutes hint
and a phase outline the tutor follows.

Block types (pydantic models in **new** `services/lesson_material.py`, discriminated by `type`) —
a deliberately small, composable primitive set. Documents are *content, never types*: a menu,
a flyer, a listing or a reading passage are all `text` (markdown — tables included):

| Block | Fields | Rendered as |
|---|---|---|
| `scenario` | `setting`, `learner_role`, `tutor_role`, `goal` | tinted "setting the scene" card |
| `text` | `title?`, `markdown` (written for the learner's level — a passage, a menu as a markdown table, a flyer, a booking confirmation…) | material reading card (markdown incl. tables) + 🔊 play (TTS) |
| `dialogue` | `turns[{speaker: "tutor"\|"learner", text}]` (learner turns may be `""` = gaps) | script card, gaps shown as fill-in lines |
| `questions` | `items[]` | numbered list attached below a `text` block |
| `tasks` | `items[{task, hint?}]` | checkbox-style task/goal list |
| `word_bank` | `items[]` | chips row of target expressions |

V1 template set (minutes; material; outline):

1. `role_play` — 5–10 — `scenario` + optional `text` prop (e.g. a menu as a markdown table, a
   flyer, an appointment card) + optional `word_bank` — set the scene → perform (introduce one
   small complication midway) → debrief key phrases. A restaurant-menu encounter is this template
   with a menu-shaped `text` block; nothing menu-specific exists in code.
2. `reading_discussion` — 5–10 — `text` + `questions` — read (learner; tutor reads aloud on
   request) → answer 3–5 literal→inference questions → learner's opinion.
3. `dialogue_gaps` — 5–8 — `dialogue` (+ `word_bank`) — preview the target phrases → learner fills
   the gaps line by line → replay one exchange freely.
4. `story_telling` — 5–10 — `scenario` (story starter) + `word_bank` — elicit a narration → recast
   tense/connector mistakes → learner retells one improved bit.
5. `explain_describe` — 5–8 — `tasks` (+ `word_bank`) — 2–4 describe/explain tasks (your city, how
   to cook X, compare two things), tutor asks follow-ups.
6. `sentence_sprint` — 3–6 — `tasks` (+ `word_bank`) — 4–6 quick production tasks, one target
   structure each; brisk pacing, tutor keeps score.

Planned v2 (recorded in the catalog as placeholders/comment, not implementable): `opinion_debate`,
`interview` (tutor as journalist), `news_reaction`, `pronunciation_drill` (TTS minimal pairs),
`image_description` (needs image generation), `song_lyrics`. Free conversation leaves the template
set — casual chat is the loop's permanent background, not a "lesson".

`LessonSpec` becomes `{template, title, topic?, scenario?, objectives[], minutes}`; template ids
mirror into `frontend/lib/lesson-templates.ts` (names + per-template copy), replacing
`LESSON_TEMPLATE_NAMES` in `lib/languages.ts`.

### 2. Session state machine (DB + `services/lesson_flow.py`)

- Migration: `ALTER TABLE sessions ADD COLUMN lessons JSONB NOT NULL DEFAULT '[]'` +
  `ALTER TABLE sessions DROP COLUMN plan;` (destructive — no legacy rows kept);
  `ALTER TABLE transcripts ADD COLUMN payload JSONB` (nullable — structured-event rows:
  `speaker='system'`, `payload={kind, data}`); `ALTER TABLE card_reviews ADD COLUMN lesson_id
  TEXT` (nullable, set when a grade came from a lesson grader).
- A **Lesson instance** is `{id, status: proposed|active|completed|declined, spec, material,
  target_cards: [{id, front, back}], reason, proposed_at, accepted_at, completed_at, grades,
  summary}`. At most one non-terminal lesson per session (backend-enforced guard in new
  `services/lesson_flow.py`).
- **Phase is derived**, never stored: `small_talk` (no non-terminal lesson) / `awaiting_accept` /
  `lesson` — helpers in `lesson_flow.py` used by `/chat` deps and both new endpoints. This replaces
  any `current_phase`-style column (dropped in `20261116000000_quality_cleanup.sql`).
- `sessions.plan` is **dropped** with the migration above; the lessons array is the single source
  of truth for lesson state (the recap page's `session.plan` read is deleted along with it).

### 3. Reworked planner agent (`agents/session_planner_agent.py`)

- **Removes** `opening_hook` (the tutor greets by itself in small talk; no upfront plan anymore)
  and outputs a **`LessonProposal`**: `lesson: LessonSpec`, `material: list[MaterialBlock]`
  (validated against the chosen template's allowed blocks), `target_card_ids: list[str]`,
  `intro_line: str` (in-language line the tutor opens the lesson with — guidance, not verbatim),
  `reason: str` (why this lesson fits what the learner was just talking about).
- **Deps** become: profile, due cards, the recent small-talk transcript (what the learner actually
  discussed — the main new input), lessons already done/declined this session (avoid repeats and
  don't re-propose a declined idea), and an optional `idea` string (the learner's requested topic,
  when the proposal is learner-initiated).
- Instructions: instantiate one template's blocks concretely for this learner (`text` written at
  their level — document-shaped content like a menu is written as a markdown table inside it;
  `dialogue` gaps solvable with the word bank); pick 3–8
  target cards relevant to the lesson; keep the `objectives` checkable within the minutes hint;
  `intro_line` in the target language, short, no lists.
- `/sessions/plan` (the endpoint) is **removed**. The planner is invoked from the tutor's
  `propose_lesson` tool (§4).

### 4. Tutor agent rework (`agents/tutor_agent.py`) — phases, tools, event side-channel

- `TutorDeps` becomes: `user_profile`, `session_id`, `phase`, `active_lesson`, `pending_proposal`,
  `session_lessons` (done/declined so far), `smalltalk_turns`, and `events: asyncio.Queue` — the
  side-channel the agent's tools push structured SSE events through.
- **System prompt per phase** (single dynamic instructions fn, as today):
  - *small_talk*: pure conversation. Explicit rules: never wrap a greeting in lesson scaffolding
    ("Hi, how are you today?" — no "you could say…"); do not propose a lesson before the nudge
    threshold or if the learner seems engrossed in chat; the nudge line appears in deps once
    `smalltalk_turns ≥ 4` and nothing is pending ("a natural moment to offer a structured lesson").
  - *awaiting_accept*: the proposal card is on screen; remind gently at most once; if the learner
    verbally agrees, call `begin_lesson`; a verbal decline → acknowledge, stay in chat.
  - *lesson*: follow the active lesson's material & phase outline, keep exchanges short, weave the
    target cards in and **praise usage immediately in-line** (visible credit arrives at
    completion); steer to the `intro_line`; when the objectives are covered or the learner wants
    out, wrap up and call `complete_lesson`. After `complete_lesson`: return to casual mode, no
    re-greeting, no repetition of done material.
- **Tools** (pydantic-ai tools on the same gemma4 lane — native tool calling):
  - `propose_lesson(idea: str = "")` — guarded to `small_talk`; pushes `proposal_generating`, runs
    the planner (same gemma lane, 10–40 s), writes the proposal row (`sessions.lessons`), pushes `proposal_ready`, returns a short ack telling the tutor to invite the learner
    to look at the card (its own reply stays chat-shaped, no material dump).
  - `begin_lesson()` — guarded to `pending proposal exists`; activates it, records `lesson_started`
    transcript event, ack: "your next words open the lesson with its `intro_line`".
  - `complete_lesson()` — guarded to an active lesson; pushes `lesson_completing`, runs the lesson
    grader (§6), pushes `lesson_completed`, updates the lesson row + FSRS, ack: "wrap up warmly,
    then casual chat, no greeting".
  - Tools consult `lesson_flow.py` guards and return plain-string results (small models).
- `/chat` wires an `asyncio.Queue` per request; `event_generator` concurrently streams text deltas
  and drains queue events as new SSE frames. Everything a tool does is recorded: proposal rows,
  transcript event rows (for restore), FSRS writes.

### 5. Chat protocol extension (backend SSE + frontend proxy)

Backend frames (single-line JSON as today) gain:

```
data: {"type":"delta","text":"…"}                              (unchanged)
data: {"type":"status","text":"Designing your lesson…"}        (transient chip)
data: {"type":"event","kind":"proposal_ready","data":{…}}      (proposal payload)
data: {"type":"event","kind":"lesson_started","data":{…}}      (spec + material + intro_line)
data: {"type":"event","kind":"lesson_completed","data":{…}}    (summary + grades)
data: {"type":"done"} / {"type":"error"}                       (unchanged)
```

- The AI SDK proxy (`app/api/chat/route.ts`) maps `status` → a `data-status` part and each `event`
  → a `data-<kind>` part (`writer.write({type:'data-proposal_ready', id, data})`). **Verify the
  installed `ai@7` / `@ai-sdk/react@4` custom-data-part API against the package's docs before
  implementing** (node_modules isn't installed in worktrees — `npm install` first).
- **New endpoints**: `POST /sessions/lessons/accept` — activates the pending proposal, then streams
  the tutor's lesson-opening turn back as SSE (same frame protocol; brief deps = active lesson +
  `intro_line`) so the opener arrives without a user message; `POST /sessions/lessons/decline` —
  marks the lesson `declined` (+ reason) so the tutor stops referring to it.
- **Persistence/restore**: `transcripts.payload` rows replay through the same data-part mapping on
  continue-session; the restored view also re-derives banner state from `sessions.lessons` (any
  active lesson → lesson banner + material; proposed-but-unanswered → proposal card again).

Explicit non-goal: live credit chips (`credit` events from a tutor-side `record_usage` tool) —
deferred; guaranteed credit in §6 already rewards production use.

### 6. Grading loop — credit & "bonus points"

- **New `agents/lesson_grader_agent.py`** (same gemma lane): input = the lesson (spec, material,
  the slide of transcript since `lesson_started`), target cards; output = `LessonGrades {grades:
  [{card_id, outcome}], summary: {headline, positives[], key_phrases[]}, bonus_uses:
  [{card_id, sentence}]}`. Outcomes reuse the existing ladder: `recognition_pass` (the learner
  clearly understood when the tutor brought the word up) → FSRS Easy-with-recognition rating as
  today; correct **in-context production** → `pass`/`strong_pass` — this is the "bonus": a
  production use outranks a mere recognition. `complete_lesson` writes `card_reviews` rows
  (now with `lesson_id`), updates FSRS state, and stores grades/summary in the lesson instance.
- **Session end** keeps the existing post-session analyst, with two changes: `session_plan` dep →
  the `lessons` list (so the recap narrates each lesson) and `due_cards` minus already-graded ids —
  closing the loop for target-card use during *small talk* (recognition credit there, exactly the
  existing behavior, minus double-grading). Recap gains `lessons: [{title, template, summary,
  bonus_uses_count}]`; the recap page renders them instead of `session.plan`.
- UI surfaces the bonus as it lands: the `lesson_completed` card lists each target card as
  ✅ used / 👀 understood / ⏸ not touched, with ⭐ marks (and the count) for in-context production.

### 7. Frontend rework (`app/page.tsx` + new `components/lesson/`)

- **Banner/header**: dynamic phase line — "Casual chat · say anything" → "Lesson proposed —
  review it" → "Lesson: Menu Role Play — 2 of 3 objectives" → back. Sourced from stream events +
  restored `sessions.lessons`; the upfront `planSession()` call and its "Today's lesson" line go
  away (planning happens when Voca proposes).
- **New components** (`components/lesson/`, shadcn base-nova primitives only — never hand-roll
  `ui/` pieces): `proposal-card.tsx` (template badge, title, 2–3 objective chips, minutes,
  sample-block preview, Accept / Not now buttons), `material-blocks.tsx` (one renderer per block
  type; the visual distinction demanded above), `lesson-summary.tsx` (headline, ✅/👀/⭐ list,
  key phrases).
- **Message flow**: data parts render via the new components inside the existing
  `MessageScroller`/`Bubble` pattern; the `data-status` part renders the shimmer chip; Accept
  streams the opener reply through the same `useChat` message list; TTS behavior unchanged for text
  bubbles; `text` blocks get a play button reusing `useSpeech`.
- **Restore** (`?session=` continue): replay `transcripts` including `payload` event rows; fetch
  `sessions.lessons` for banner/pending state.
- **Recap page**: per-lesson section replaces the old plan display; the `SessionPlanShape` /
  `session.plan` code path is deleted together with the column.
- Extend offline tests (Vitest + RTL with the supabase mock): proposal accept/decline flows,
  material block rendering (incl. an unknown block type → graceful fallback), restore replay of
  payload rows, and pages-smoke for the reworked pages.

## API & data summary

- `POST /chat` — extended frame types; deps carry phase/lesson context; transcript rows gain
  optional `payload`.
- `POST /sessions/lessons/accept` (new), `POST /sessions/lessons/decline` (new).
- `POST /sessions/plan` — **removed** (frontends never call it; planner is tool-internal).
- `POST /sessions/start` — no longer plans anything (no other change).
- `POST /sessions/end` — analyst input swap (`lessons`), graded-card exclusion, recap shape.
- Migration ~`20261201000000_lesson_loop.sql`: `sessions.lessons` JSONB, `DROP COLUMN
  sessions.plan`, `transcripts.payload` JSONB, `card_reviews.lesson_id` TEXT.
- `services/llm.py` — one lane: `LLM_MODEL` (default `gemma4:31b-cloud`); `LLM_PLANNING_MODEL` and
  the granite-specific settings disappear; `src/voca/.env` updated to match.

## Files to modify

Backend:
- `src/voca/services/llm.py` (collapse to one lane), `src/voca/services/lesson_templates.py`
  (new taxonomy + per-template block schemas),
  `src/voca/services/lesson_material.py` (new, block models), `src/voca/services/lesson_flow.py`
  (new, state machine + guards + helpers)
- `src/voca/agents/tutor_agent.py` (phases, tools, event queue), `src/voca/agents/
  session_planner_agent.py` (LessonProposal), `src/voca/agents/lesson_grader_agent.py` (new),
  `src/voca/agents/post_session_agent.py` (lessons dep, recap shape)
- `src/voca/main.py` (`/chat` event pump + deps; accept/decline endpoints; drop `/sessions/plan`;
  `/sessions/end` sweep; `/chat` deps assembly from `lesson_flow`)
- `supabase/migrations/20261201000000_lesson_loop.sql` (new)

Frontend:
- `app/page.tsx` (phase banner, data-part rendering, accept/decline, restore replay)
- `app/api/chat/route.ts` (data-part mapping), `lib/lesson-templates.ts` (new, template copy),
  `lib/lesson-events.ts` (new, typed payload shapes shared by components)
- `components/lesson/proposal-card.tsx`, `components/lesson/material-blocks.tsx`,
  `components/lesson/lesson-summary.tsx` (new)
- `app/recap/[sessionId]/page.tsx` (lessons section; plan read removed)
- `lib/languages.ts` (drop `LESSON_TEMPLATE_NAMES` mirror, now in `lesson-templates.ts`)

Tests:
- `tests/test_agents.py` (planner schema w/ material validation, grader, phase-prompt variants),
  `tests/test_chat.py` (event pump, accept/decline, transcript payloads), `tests/test_sessions.py`
  (end sweep exclusions, recap shape), `tests/conftest.py` (canned `lessons` rows)
- `frontend/tests/` (proposal card, material blocks, event replay, pages-smoke, history/recap);
  `frontend/e2e/smoke.spec.mjs` (a full loop case driven via API to dodge LLM nondeterminism)

## Reuse

- Single model lane (`services/llm.py`): all agents on `gemma4:31b-cloud` through one `LLM_MODEL`
  constant — the existing `OllamaModel`/`OllamaProvider` builder is reused; pydantic-ai
  `Agent`/`output_type` patterns unchanged; new structured agents keep `retries=3`; the tutor
  keeps `run_stream`.
- `lesson_flow`'s proposal writing reuses the `/sessions/plan` body from `main.py` today
  (fetch due cards → run planner → resolve card content → store) — moved into a service fn.
- FSRS plumbing (`review_card_state`, `VOCA_RATING_MAP`, `card_reviews` insert block in
  `/sessions/end`) — extracted into `lesson_flow.py` and called from both the grader and the sweep.
- SSE framing (`sse()`), proxy transcode pattern, `useSpeech`, message-scroller/bubble primitives,
  supabase-mock helpers, `plans/` + worktree conventions.

## Steps

1. **One model lane + planner rework**: `services/llm.py` → single `LLM_MODEL` (gemma4
   everywhere, default settings), `.env` swap; migration (`sessions.lessons`,
   `DROP COLUMN plan`, `transcripts.payload`, `card_reviews.lesson_id`); `lesson_material.py`;
   rework `lesson_templates.py`; planner rework (block validation, no `opening_hook`);
   `lesson_flow.py` (instance CRUD, phase derivation). Backend tests for schema/guards.
2. **Tutor rework + event pump**: tools, phase prompts, deps assembly, `/chat` side-channel and
   frames; remove `/sessions/plan`; transcript payload rows. Unit tests with `TestModel` tool
   calls (and a fake queue) + SSE framing tests.
3. **Grader + session-end sweep**: `lesson_grader_agent.py`, `complete_lesson` wiring, FSRS +
   `card_reviews.lesson_id` writes, post-session swap + recap enrichment.
4. **Accept/decline endpoints** (accept streams the opener turn) with tests.
5. **Frontend**: data-part mapping in the proxy, lesson components, page rework, restore replay,
   recap page, template copy; offline vitest suite extended.
6. **Live integration** (`uv run task test:all`): tutor tool-call behavior on gemma4:31b-cloud
   verified first (see Risks), planner block validity per template, grader outcomes, then
   `uv run task test:e2e` for the end-to-end loop.
7. **Gates + docs**: `uv run task test`, `uv run ruff check .`, `uv run task check:frontend` (fix
   before claiming done; `uv run task tidy`); update root `AGENTS.md` (architecture blurb: phase
   loop, new endpoints, event protocol, single model lane — the "two lanes" description goes) and
   `frontend/AGENTS.md` if test conventions shift.

## Risks & fallbacks

- **Cloud chat latency/cost** applies to every tutor turn (gemma4:31b-cloud streams; tool calls
  add round-trips mid-stream) and is accepted as-is: default model settings, no latency tuning in
  this rework — the product owner will voice it if it feels slow in use. The UI affordances
  (Accept button, "Finish lesson") and a lightweight backend safety net (force-propose when
  `smalltalk_turns ≥ 4`, and every +3 thereafter with a fresh idea) keep transitions working
  regardless of model behavior.
- **ai@7 custom data parts API** must be verified from the installed package docs before the proxy
  work (breaking-change-era versions; no node_modules in worktrees until `npm install`).
- **Planner latency** (10–40 s cloud generation of full material): shown as `proposal_generating`;
  the proposal card must not depend on streaming timing; keep material concise per template.
- **Lesson length control** (5–10 min): minutes hint + objectives + tutor prompt; deliberately no
  hard backend timer; the "Finish lesson" affordance guarantees an exit hatch.
- **Double-grading** target cards (lesson grader + session sweep): sweep filters ids already graded
  in any completed lesson of the session; single graded instance per card per session.

## Verification

- Offline: `uv run task test` green; `uv run ruff check .` clean; `uv run task check:frontend`
  green (typecheck + lint + vitest).
- Live (`uv run task test:all`): planner emits template-valid blocks for all 6 templates; the
  tutor (gemma4:31b-cloud) triggers `propose_lesson` after the nudge and completes lessons via
  `complete_lesson`; grader outcomes land in FSRS + `card_reviews`.
- `uv run task dev` manual pass: greet → 4–5 turns of plain small talk (no scaffolding, no early
  proposal) → proposal card appears → Accept → material renders visually distinct + opener
  streams → lesson runs → lesson-summary card with ✅/👀/⭐ → natural small-talk continuation, no
  re-greeting → propose again (fresh idea, no repeat) → End session → recap lists lessons and
  bonus uses → continue an open session: proposal/material state restores.
- E2E smoke through `uv run task test:e2e` with the dev stack up (lesson-loop case driven via API
  where LLM nondeterminism would flake).
- `plannotator`-style review of the final diff before merge.
