# Tutor canvas — the simpler direction

A branch off `llefebure/rework-tutor-planner-agents` that replaces the formal
small-talk ⇄ lesson loop with one continuous conversation plus a canvas: the
tutor itself decides when to put structured content on the right side of the
screen. Grading becomes a single transcript→FSRS rubric at session end, with no
per-lesson credit UI (no ⭐ marks).

## Core model

- **One chat, one agent.** No phase machine, no proposals/accept/decline, no
  lesson templates, no planner or per-lesson grader agents. The tutor
  converses; when structured content would help (a menu, a schedule, a
  dialogue script, comprehension questions, a word bank, practice tasks), it
  calls a tool and the UI pops a canvas panel on the right (split view: chat
  left, panel right). The chat itself stays whole — panels are exhibits, not a
  separate conversation stream.
- **`show_panel` tool** (tutor agent): `title` + typed content blocks (the
  six primitives kept from the lesson work: scenario / text / dialogue /
  questions / tasks / word_bank, in `services/panel_content.py`). Blocks are
  normalized and validated defensively (invalid shapes coerce or drop; the
  model gets a corrective ack when nothing valid remains). Emits the SSE event
  `panel_shown {panel: {id, title, blocks}}`, persisted as a
  `transcripts.payload` row for restore.
- **`hide_panel` tool**: closes the currently shown panel (event
  `panel_hidden {panel_id}`). The user's ✕ on the canvas is a client-side
  dismissal only — panels in history never disappear.
- **Panel lifecycle**: one panel at a time; `show_panel` replaces. Restore
  derives the open panel by replaying payload rows (last shown, minus hidden).
  Non-active panels render in the chat as collapsed, expandable records.
- **Grading rubric** (session end): the analyst's instructions carry the
  rubric that maps transcript evidence to FSRS statuses — recall quality woven
  into the outcome definitions (strong_pass / pass / recognition_pass / miss /
  not_attempted → FSRS ratings via `VOCA_RATING_MAP`). Nothing about recall or
  "bonus" appears in the UI; the recap stays a prose summary + new cards.

## Removals

- `services/lesson_flow.py`, `services/lesson_templates.py`,
  `agents/session_planner_agent.py`, `agents/lesson_grader_agent.py`.
- Endpoints `/sessions/lessons/accept|decline`, the force-proposal net, the
  run_proposal plumbing, lesson close-out in `/sessions/end`.
- `sessions.lessons` and `card_reviews.lesson_id` (migration rewritten in
  place — branch-local), proposal cards, LessonDock, LessonThreadBlock stars,
  the ⭐ bonus UI, the recap's lessons section.
- Frontend `lib/lesson-templates.ts`, `lib/lesson-events.ts` (→
  `lib/panel-events.ts`), lesson components (→ `components/panel/`).

## Streaming

The gemma leak capture stays (it is transport-level), retargeted at
`show_panel`/`hide_panel`; large leaked calls must stay hidden (hold from the
first `call:` marker instead of capping the whole buffer).

## Validation

- Offline gates: `uv run task test`, ruff, `uv run task check:frontend`.
- Live: single-chat driver (greets, asks for a menu → expects a
  `panel_shown` event), restore replay, `/sessions/end` rubric grading
  (mocked-analyst path in tests + a live run of `/sessions/end`), e2e smoke.
