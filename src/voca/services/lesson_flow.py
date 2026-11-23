"""The session lesson state machine: pure helpers over `sessions.lessons`.

A session's conversation moves through phases, all derived from the lesson
instances stored in the session's `lessons` JSONB array (never a stored phase):

- `small_talk`       — no non-terminal lesson; casual chat, nudge after ~4 turns.
- `awaiting_accept`  — a proposal exists; the learner can accept/decline (UI or voice).
- `lesson`           — a lesson is active; the tutor follows its material.

At most one lesson may be in a non-terminal state (proposed/active) at a time.
This module holds the pure rules (instance shape, guards, transitions); all
database access stays in `voca.main`.
"""

import uuid
from datetime import UTC, datetime
from typing import Any, TypedDict

from pydantic import BaseModel

from voca.services.lesson_material import MaterialBlock, filter_allowed, parse_material
from voca.services.lesson_templates import allowed_blocks

PHASE_SMALL_TALK = "small_talk"
PHASE_AWAITING_ACCEPT = "awaiting_accept"
PHASE_LESSON = "lesson"

# Production outcomes earn the "bonus" star; recognition still counts as credit.
PRODUCTION_OUTCOMES = {"pass", "strong_pass"}
CREDITED_OUTCOMES = {"recognition_pass", "pass", "strong_pass"}

# Small-talk threshold where the tutor is nudged to offer a lesson; the backend
# force-proposes two turns later if a reply went by without a tool call.
NUDGE_TURNS = 4
FORCE_PROPOSE_TURNS = NUDGE_TURNS + 2
# After a decline, wait a bit before offering a fresh idea again.
DECLINE_COOLDOWN_SECONDS = 180


class LessonSpec(BaseModel):
    template: str
    title: str
    topic: str | None = None
    scenario: str | None = None
    objectives: list[str] = []
    minutes: int | None = None


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def new_lesson(
    spec: LessonSpec,
    material: list[dict],
    target_cards: list[dict[str, str]],
    reason: str,
    intro_line: str,
) -> dict[str, Any]:
    """A fresh proposal instance ready to append to `sessions.lessons`."""
    return {
        "id": str(uuid.uuid4()),
        "status": "proposed",
        "spec": spec.model_dump(),
        "material": material,
        "target_cards": target_cards,
        "reason": reason,
        "intro_line": intro_line,
        "proposed_at": now_iso(),
        "accepted_at": None,
        "completed_at": None,
        "declined_reason": None,
        "grades": [],
        "summary": None,
    }


def non_terminal(lessons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [lesson for lesson in lessons if lesson.get("status") in ("proposed", "active")]


def derive_phase(lessons: list[dict[str, Any]]) -> str:
    pending = non_terminal(lessons)
    if any(lesson["status"] == "active" for lesson in pending):
        return PHASE_LESSON
    if pending:
        return PHASE_AWAITING_ACCEPT
    return PHASE_SMALL_TALK


def active_lesson(lessons: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The one active lesson, if any (newest wins defensively)."""
    matches = [lesson for lesson in lessons if lesson.get("status") == "active"]
    return matches[-1] if matches else None


def pending_proposal(lessons: list[dict[str, Any]]) -> dict[str, Any] | None:
    matches = [lesson for lesson in lessons if lesson.get("status") == "proposed"]
    return matches[-1] if matches else None


# --- Guards ----------------------------------------------------------------------------


def _guard_message(blocked_by: str) -> str:
    return (
        f"(action refused: {blocked_by}. Do not retry; continue the conversation naturally "
        "with what is already happening.)"
    )


def guard_propose(lessons: list[dict[str, Any]]) -> str | None:
    """A refusal message when `propose_lesson` is not allowed, else None."""
    if active := active_lesson(lessons):
        return _guard_message(
            f"a lesson is already in progress ({(active.get('spec') or {}).get('title', 'Untitled')})"
        )
    if pending_proposal(lessons):
        return _guard_message("a lesson proposal is already waiting for the learner's answer")
    return None


def guard_begin(lessons: list[dict[str, Any]]) -> str | None:
    if active_lesson(lessons):
        return _guard_message("a lesson is already in progress")
    if not pending_proposal(lessons):
        return _guard_message("there is no lesson proposal waiting to start")
    return None


def guard_complete(lessons: list[dict[str, Any]]) -> str | None:
    if not active_lesson(lessons):
        return _guard_message("no lesson is currently in progress")
    return None


# --- Transitions ------------------------------------------------------------------------


def activate(lesson: dict[str, Any]) -> dict[str, Any]:
    lesson = dict(lesson)
    lesson["status"] = "active"
    lesson["accepted_at"] = now_iso()
    return lesson


def decline(lesson: dict[str, Any], reason: str | None = None) -> dict[str, Any]:
    lesson = dict(lesson)
    lesson["status"] = "declined"
    lesson["declined_at"] = now_iso()
    lesson["declined_reason"] = reason
    return lesson


def complete(lesson: dict[str, Any], grades: list[dict[str, str]], summary: dict) -> dict[str, Any]:
    lesson = dict(lesson)
    lesson["status"] = "completed"
    lesson["completed_at"] = now_iso()
    lesson["grades"] = grades
    lesson["summary"] = summary
    return lesson


# --- Validation -------------------------------------------------------------------------


def validate_material(
    template_id: str, raw_material: list[dict]
) -> tuple[list[MaterialBlock], list[str]]:
    """Parse the planner's material for `template_id`, dropping disallowed block types.

    Returns `(blocks, dropped_types)`; callers surface dropped types as
    validation feedback to the planner rather than failing the whole lesson.
    """
    blocks = parse_material(raw_material)
    allowed = allowed_blocks(template_id)
    if allowed is None:
        return [], [block.type for block in blocks]
    return filter_allowed(blocks, allowed)


def eligible_for_force_propose(
    lessons: list[dict[str, Any]],
    smalltalk_turns: int,
    *,
    now: datetime | None = None,
) -> bool:
    """Whether the backend should propose on its own after a quiet reply.

    The tutor model drives lesson transitions through tools, but its calls are
    stochastic (verified live: it occasionally writes an invitation without any
    call). Past ``FORCE_PROPOSE_TURNS`` of small talk with nothing pending —
    and no recent decline — the backend generates the proposal itself."""
    if smalltalk_turns < FORCE_PROPOSE_TURNS:
        return False
    if derive_phase(lessons) != PHASE_SMALL_TALK:
        return False
    moment = now or datetime.now(UTC)
    for lesson in lessons:
        if lesson.get("status") != "declined":
            continue
        declined_at = lesson.get("declined_at")
        if declined_at:
            try:
                passed = (moment - datetime.fromisoformat(declined_at)).total_seconds()
            except ValueError:
                continue
            if passed < DECLINE_COOLDOWN_SECONDS:
                return False  # respect the learner's "not now" before re-offering
    return True


def update_lessons(
    lessons: list[dict[str, Any]], lesson_id: str, replacement: dict[str, Any]
) -> list[dict[str, Any]]:
    return [replacement if lesson["id"] == lesson_id else lesson for lesson in lessons]


def lesson_status_typed(lesson: dict[str, Any]) -> str:
    return str(lesson.get("status", "unknown"))


class LessonCard(TypedDict):
    id: str
    front: str
    back: str
