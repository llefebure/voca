"""Unit tests for the lesson state machine and material validation (pure, offline)."""

from voca.services import lesson_flow
from voca.services.lesson_flow import (
    DECLINE_COOLDOWN_SECONDS,
    FORCE_PROPOSE_TURNS,
    LessonSpec,
    activate,
    active_lesson,
    complete,
    decline,
    derive_phase,
    eligible_for_force_propose,
    guard_begin,
    guard_complete,
    guard_propose,
    new_lesson,
    non_terminal,
    pending_proposal,
    update_lessons,
    validate_material,
)
from voca.services.lesson_templates import (
    allowed_blocks,
    template_catalog,
    template_minutes,
    template_name,
    template_structure,
)


def lesson(status: str = "proposed", lesson_id: str = "l1", **overrides) -> dict:
    spec = LessonSpec(template="role_play", title="At the café")
    base = new_lesson(
        spec,
        [
            {
                "type": "scenario",
                "setting": "a café",
                "learner_role": "customer",
                "tutor_role": "barista",
                "goal": "order",
            }
        ],
        [{"id": "card-1", "front": "pedir", "back": "to order"}],
        "ties to the chat",
        "¡Hola! Imagina que estamos en una cafetería…",
    )
    base["id"] = lesson_id
    base["status"] = status
    base.update(overrides)
    return base


def test_new_lesson_proposes_with_full_shape():
    instance = lesson()
    assert instance["status"] == "proposed"
    assert instance["spec"]["template"] == "role_play"
    assert instance["target_cards"] == [{"id": "card-1", "front": "pedir", "back": "to order"}]
    assert instance["proposed_at"]
    assert not any("opening_hook" in key for key in instance)  # the old planner field is gone
    assert instance["grades"] == []


def test_derive_phase_from_lessons_array():
    assert derive_phase([]) == lesson_flow.PHASE_SMALL_TALK
    assert derive_phase([lesson("completed")]) == lesson_flow.PHASE_SMALL_TALK
    assert derive_phase([lesson("declined")]) == lesson_flow.PHASE_SMALL_TALK
    assert derive_phase([lesson("proposed")]) == lesson_flow.PHASE_AWAITING_ACCEPT
    assert derive_phase([lesson("active")]) == lesson_flow.PHASE_LESSON
    # Exactly one non-terminal lesson: older terminal entries don't confuse it.
    assert derive_phase([lesson("completed", "l0"), lesson("active", "l1")]) == (
        lesson_flow.PHASE_LESSON
    )


def test_active_and_pending_selectors():
    done, active = lesson("completed", "l-done"), lesson("active", "l-active")
    assert active_lesson([lesson("proposed")]) is None
    assert active_lesson([lesson("active")])["status"] == "active"
    assert pending_proposal([lesson("active")]) is None
    assert pending_proposal([lesson("proposed")])["status"] == "proposed"
    assert [instance["id"] for instance in non_terminal([done, active])] == ["l-active"]


def test_guards_block_out_of_phase_actions():
    assert guard_propose([lesson("active", "l-active")]) is not None
    assert guard_propose([lesson("proposed", "l-props")]) is not None
    assert guard_propose([lesson("completed", "l-done")]) is None

    assert guard_begin([]) is not None
    assert guard_begin([lesson("active", "l-active")]) is not None
    assert guard_begin([lesson("proposed", "l-props")]) is None

    assert guard_complete([]) is not None
    assert guard_complete([lesson("proposed", "l-props")]) is not None
    assert guard_complete([lesson("active", "l-active")]) is None


def test_force_propose_eligibility():
    from datetime import UTC, datetime, timedelta

    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    assert not eligible_for_force_propose([], smalltalk_turns=FORCE_PROPOSE_TURNS - 1, now=now)
    assert eligible_for_force_propose([], smalltalk_turns=FORCE_PROPOSE_TURNS, now=now)
    # Non-small-talk phases never force.
    assert not eligible_for_force_propose(
        [lesson("proposed")], smalltalk_turns=FORCE_PROPOSE_TURNS, now=now
    )
    assert not eligible_for_force_propose(
        [lesson("active")], smalltalk_turns=FORCE_PROPOSE_TURNS, now=now
    )
    # A recent decline is respected; an old one is not.
    recent = decline(lesson("proposed"), "not now")
    assert not eligible_for_force_propose([recent], smalltalk_turns=FORCE_PROPOSE_TURNS, now=now)
    old = dict(
        recent, declined_at=(now - timedelta(seconds=DECLINE_COOLDOWN_SECONDS + 1)).isoformat()
    )
    assert eligible_for_force_propose([old], smalltalk_turns=FORCE_PROPOSE_TURNS, now=now)


def test_transitions_write_timestamps_and_payloads():
    active = activate(lesson("proposed"))
    assert active["status"] == "active" and active["accepted_at"]

    graded = complete(
        active,
        [{"card_id": "card-1", "outcome": "pass", "bonus_use": True, "evidence": "lo usó"}],
        {"headline": "Great", "positives": [], "key_phrases": [], "bonus_uses": ["¡lo usó!"]},
    )
    assert graded["status"] == "completed" and graded["completed_at"]
    assert len(graded["grades"]) == 1
    assert graded["summary"]["bonus_uses"] == ["¡lo usó!"]

    dropped = decline(lesson("proposed"), "too long")
    assert dropped["status"] == "declined" and dropped["declined_reason"] == "too long"


def test_update_lessons_replaces_by_id():
    old_a = lesson("proposed", "a")
    old_b = lesson("active", "b")
    replacement = activate(old_a)
    result = update_lessons([old_a, old_b], "a", replacement)
    assert [instance["id"] for instance in result] == ["a", "b"]
    assert result[0]["status"] == "active"
    assert result[1]["status"] == "active"  # untouched


def test_validate_material_drops_disallowed_blocks():
    blocks, dropped = validate_material(
        "reading_discussion",
        [
            {"type": "text", "markdown": "A short passage."},
            {"type": "questions", "items": ["What happened?"]},
            {
                "type": "scenario",
                "setting": "x",
                "learner_role": "y",
                "tutor_role": "z",
                "goal": "w",
            },
        ],
    )
    assert [b.type for b in blocks] == ["text", "questions"]
    assert dropped == ["scenario"]


def test_validate_material_unknown_template_drops_everything():
    blocks, dropped = validate_material("mystery_template", [{"type": "text", "markdown": "x"}])
    assert blocks == []
    assert dropped == ["text"]


def test_validate_material_preserves_block_payloads():
    blocks, _ = validate_material(
        "dialogue_gaps",
        [
            {
                "type": "dialogue",
                "turns": [
                    {"speaker": "tutor", "text": "¡Buenas!"},
                    {"speaker": "learner", "text": ""},
                ],
            },
            {"type": "word_bank", "items": ["un café con leche"]},
        ],
    )
    assert blocks[0].turns[1].text == ""
    assert blocks[1].items == ["un café con leche"]


def test_template_catalog_carries_minutes_and_blocks():
    catalog = template_catalog()
    assert "role_play: Role Play (5-10 min)" in catalog
    assert "required blocks: scenario" in catalog
    assert "required blocks: text, questions" in catalog


def test_template_helpers_fall_back_gracefully():
    assert template_name("mystery") == "Lesson"
    assert template_structure("mystery") == ""
    assert template_minutes("mystery") == ""
    assert allowed_blocks("mystery") is None
    assert template_minutes("sentence_sprint") == "3-6"
