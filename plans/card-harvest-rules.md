# Plan: card-harvest-rules — review cards only from uncertainty, error, or missed opportunities

Branch: `feature/card-harvest-rules` · Worktree: `uv run task worktree:new -- feature/card-harvest-rules`

## Problem

The post-session analyst creates 5–8 cards per session
(`src/voca/agents/post_session_agent.py`), but the instruction is loose:
"Prioritize items the learner struggled with, explicitly asked about, or which are
critical for their level." In practice it harvests words the learner used *correctly*
without hesitation — which trains nothing and pollutes the FSRS queue. Cards should be
born from actual need:

- **(a) Uncertainty** — the learner asked what something means / how to say something,
  hesitated, restarted, or self-corrected.
- **(b) Incorrect use** — the tutor corrected a word, form, or pattern (gender, tense,
  agreement, wrong word).
- **(c) Better alternative** — the learner's version was understandable but awkward or
  unidiomatic, or an expression from the session plan would have been stronger where the
  learner improvised something weaker.

## Changes

### Agent (`src/voca/agents/post_session_agent.py`)

1. Rewrite the NEW CARDS section of `instructions`:
   - Replace "Identify 5-8 new cards" with: "Identify **0–5** new cards. An empty list is
     a good result when the learner made no mistakes and asked nothing." Cards MUST
     satisfy at least one of (a)/(b)/(c) above, with explicit example signals per
     criterion (e.g. "¿cómo se dice…?", "what does X mean", repeated self-correction;
     tutor reformulations in the transcript).
   - Hard exclusions: words used correctly and confidently; items the tutor merely used
     and the learner never engaged with (unless (c) applies); grammar the learner
     produced correctly; duplicating a due card's content.
   - Every card must cite its transcript line in `source_sentence` and its `reason`
     must name which criterion (a/b/c) fired and quote the signal.
   - When the same item appears under several turns, keep one card.
2. New dep `existing_cards: list[dict]` (front + back only): the user's recent cards for
   the session's language, read in `/sessions/end`
   (`src/voca/main.py`: select front/back where user_id + language, order created_at
   desc, cap ~300). Instructions say to skip anything whose front/back matches an
   existing card.
3. Deterministic backstops in `/sessions/end` (don't rely on prompt compliance):
   - Dedupe: casefold + strip punctuation; drop a candidate whose normalized front or
     back matches an existing card or an already-accepted candidate this session.
   - (Optional) `len(analysis.new_cards) > 5` → keep the first 5.

No schema changes: `CardCandidate` keeps exactly its current fields — which criterion
(a/b/c) justified a card lives in its free-text `reason` (see step 1), not in a new
field.

### Tests

- `tests/test_agents.py`: extend the `inject_post_session_deps` test for the new
  `existing_cards` dep. `CardCandidate` is unchanged, so the existing TestModel
  output-schema test stays valid as-is.
- `tests/test_sessions.py`: dedupe/normalization backstops (same front in existing cards
  → not inserted; duplicate candidates within a session → one inserted; the stored recap
  payload's `new_cards` shape is unchanged).
- `tests/test_integration_llm.py` (marker `integration`): a transcript where the learner
  used every word correctly and asked nothing must yield `new_cards == []`; a transcript
  with a tutor correction must yield a card citing it. Tune in the worktree against the
  live `gemma4:31b-cloud` until both hold.

## Risks / notes

- Prompt-only behavior is unverifiable offline — that's why the instruction examples
  (with per-criterion signals), the `reason`-must-cite-the-signal rule, and the
  deterministic dedupe in code all carry weight.
- If quality still slips after the prompt rewrite, the next escalation (out of scope):
  a two-pass design (extract candidates → a second agent validates against a/b/c). Note
  it in the PR; revisit only if the live tests show the single pass failing.
- **No DB migrations, by design**: nothing changes the `cards`/`sessions`/`transcripts`
  schema. New-card rows are inserted exactly as today (type/front/back/source_sentence);
  `existing_cards` is a read-only select; the recap payload keeps its exact current
  shape. Auditability of why a card exists rides solely on the free-text `reason`
  requirement in the prompt.

## Gates

`uv run task test`, `uv run ruff check .`, `uv run task check:frontend` (recap page is
unchanged in UI, but run the gate anyway), plus the integration marker in the worktree
with Ollama signed in.
