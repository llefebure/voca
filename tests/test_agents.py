"""Agent wiring tests: prompt construction, output schemas, and tool behavior.

Fully offline: instructions functions run against a stub RunContext, agent runs
use pydantic-ai's TestModel (no LLM calls), and the tutor's tools run with fake
DB callbacks.
"""

import asyncio

import pytest
from pydantic import BaseModel
from pydantic_ai import capture_run_messages
from pydantic_ai.models.test import TestModel

from voca.agents.lesson_grader_agent import GraderDeps, LessonGrades, lesson_grader_agent
from voca.agents.post_session_agent import (
    PostSessionDeps,
    PostSessionResult,
    post_session_agent,
)
from voca.agents.session_planner_agent import (
    LessonProposal,
    PlannerDeps,
    session_planner_agent,
)
from voca.agents.tutor_agent import (
    TutorDeps,
    begin_lesson,
    complete_lesson,
    propose_lesson,
    tutor_agent,
    tutor_system_prompt,
)
from voca.services import lesson_flow
from voca.services.lesson_flow import LessonSpec, new_lesson
from voca.services.lesson_templates import LESSON_TEMPLATES


class _StubRunContext:
    """Just enough of pydantic-ai's RunContext for instructions/tool functions."""

    def __init__(self, deps: dict) -> None:
        self.deps = deps


def tutor_deps(**overrides) -> TutorDeps:
    """A full TutorDeps fixture; overrides patch individual fields."""
    base: TutorDeps = {
        "user_id": "user-1",
        "session_id": "session-1",
        "user_profile": {
            "target_language": "es",
            "goals": "travel to Spain",
            "level": "A2",
            "interests": "architecture",
        },
        "phase": lesson_flow.PHASE_SMALL_TALK,
        "active_lesson": None,
        "pending_proposal": None,
        "session_lessons": [],
        "due_cards": [],
        "smalltalk_turns": 0,
        "events": asyncio.Queue(),
        "run_planner": None,
        "activate_proposal": None,
        "grade_and_complete": None,
        "record_event": None,
    }
    base.update(overrides)
    return base


def cafe_lesson() -> dict:
    spec = LessonSpec(
        template="role_play",
        title="At the café",
        topic="ordering coffee",
        objectives=["order a coffee", "ask for the check"],
        minutes=8,
    )
    return new_lesson(
        spec,
        [
            {
                "type": "scenario",
                "setting": "a café in Madrid",
                "learner_role": "customer",
                "tutor_role": "barista",
                "goal": "order and pay",
            },
            {"type": "dialogue", "turns": [{"speaker": "tutor", "text": "¡Buenas! ¿Qué pones?"}]},
            {"type": "word_bank", "items": ["un cortado, por favor"]},
        ],
        [{"id": "card-1", "front": "I would like…", "back": "quisiera…"}],
        "the learner talked about coffee",
        "¡Hola! Imagina que estamos en una cafetería…",
    )


# --- Tutor prompts -------------------------------------------------------------------


def test_tutor_prompt_includes_profile_and_conversational_rules():
    prompt = tutor_system_prompt(_StubRunContext(tutor_deps(smalltalk_turns=1)))
    assert "travel to Spain" in prompt
    assert "A2" in prompt
    assert "architecture" in prompt
    assert "Spanish language tutor" in prompt
    # TTS-optimized: the tutor is told not to use lists/markdown.
    assert "no bulleted lists" in prompt
    # Small talk is unstructured: greeting must never get lesson scaffolding.
    assert "NEVER attach lesson offers" in prompt
    assert "casual conversation" in prompt.lower()
    # Before the nudge threshold, no proposal instruction appears.
    assert "propose_lesson" not in prompt


def test_tutor_prompt_defaults_without_profile():
    prompt = tutor_system_prompt(_StubRunContext(tutor_deps(user_profile={})))
    assert "learn Spanish" in prompt
    assert "Intermediate (B1)" in prompt


def test_tutor_prompt_weaves_due_cards_into_small_talk():
    deps = tutor_deps(due_cards=[{"id": "c1", "front": "tener sed", "back": "to be thirsty"}])
    prompt = tutor_system_prompt(_StubRunContext(deps))
    assert "tener sed" in prompt


def test_tutor_prompts_at_the_nudge_threshold():
    deps = tutor_deps(smalltalk_turns=4)
    prompt = tutor_system_prompt(_StubRunContext(deps))
    assert "propose_lesson" in prompt
    assert "NUDGE" in prompt


def test_tutor_prompt_no_nudge_while_a_proposal_is_pending():
    deps = tutor_deps(smalltalk_turns=6, pending_proposal=cafe_lesson())
    prompt = tutor_system_prompt(_StubRunContext(deps))
    assert "NUDGE" not in prompt


def test_tutor_prompt_awaiting_accept_describes_card_and_flow():
    deps = tutor_deps(phase=lesson_flow.PHASE_AWAITING_ACCEPT, pending_proposal=cafe_lesson())
    prompt = tutor_system_prompt(_StubRunContext(deps))
    assert "proposal is waiting" in prompt
    assert "At the café" in prompt
    assert "begin_lesson" in prompt


def test_tutor_prompt_lesson_phase_renders_active_lesson():
    deps = tutor_deps(phase=lesson_flow.PHASE_LESSON, active_lesson=cafe_lesson())
    prompt = tutor_system_prompt(_StubRunContext(deps))
    assert "complete_lesson" in prompt
    assert "casual chat" in prompt
    assert "At the café" in prompt
    assert "quisiera…" in prompt
    assert "SCENARIO" in prompt
    assert "a café in Madrid" in prompt
    assert "no re-greeting" in prompt


def test_tutor_prompt_lesson_phase_has_no_due_cards_nudge():
    # build_tutor_deps leaves due_cards empty in the lesson phase; the prompt
    # must not ask the tutor to weave them in there.
    deps = tutor_deps(phase=lesson_flow.PHASE_LESSON, active_lesson=cafe_lesson())
    prompt = tutor_system_prompt(_StubRunContext(deps))
    assert "NUDGE" not in prompt


def test_tutor_prompt_lists_done_and_declined_lessons():
    history = [
        {"spec": {"title": "At the café"}, "status": "completed"},
        {"spec": {"title": "Reading"}, "status": "declined"},
    ]
    deps = tutor_deps(
        phase=lesson_flow.PHASE_LESSON, active_lesson=cafe_lesson(), session_lessons=history
    )
    prompt = tutor_system_prompt(_StubRunContext(deps))
    assert "At the café" in prompt  # completed (in history block)
    assert "DECLINED: Reading" in prompt


# --- Tutor tools -------------------------------------------------------------------------


async def _test_tool_ctx(**overrides) -> _StubRunContext:
    return _StubRunContext(tutor_deps(**overrides))


@pytest.mark.asyncio
async def test_propose_lesson_tool_happy_path():
    calls: list[str] = []
    events = asyncio.Queue()
    done = asyncio.Event()
    created = cafe_lesson()

    async def run_planner(idea: str):
        calls.append(idea)
        return created

    async def record_event(kind, data):
        calls.append(kind)
        done.set()

    deps = tutor_deps(events=events, run_planner=run_planner, record_event=record_event)
    ack = await propose_lesson(_StubRunContext(deps), "a café role play")

    assert "proposal card" in ack
    assert calls[:1] == ["a café role play"]
    first = events.get_nowait()
    assert first == {"type": "status", "text": "Designing your lesson…"}
    second = events.get_nowait()
    assert second["kind"] == "proposal_ready"
    assert second["data"]["lesson"] == created
    await asyncio.wait_for(done.wait(), 1)
    assert calls[1:] == ["proposal_ready"]  # event persisted to the transcript


@pytest.mark.asyncio
async def test_propose_lesson_guard_refuses_out_of_phase():
    deps = tutor_deps(session_lessons=[cafe_lesson(), {"id": "x", "status": "active"}])
    ack = await propose_lesson(_StubRunContext(deps))
    assert "refused" in ack and "already in progress" in ack
    assert deps["events"].empty()


@pytest.mark.asyncio
async def test_propose_lesson_survives_planner_failure():
    async def failing_planner(idea: str):
        return None

    deps = tutor_deps(run_planner=failing_planner, record_event=record_noop)
    ack = await propose_lesson(_StubRunContext(deps))
    assert "planner unavailable" in ack
    # No proposal event was pushed; only the transient status chip appeared.
    assert deps["events"].get_nowait()["type"] == "status"


async def record_noop(kind, data):  # test helper
    return None


@pytest.mark.asyncio
async def test_begin_lesson_tool_activates_and_emits_event():
    lesson = cafe_lesson()
    pending = lesson  # + status "proposed" from the fixture
    pending["status"] = "proposed"
    events = asyncio.Queue()
    activated: list[str] = []

    async def activate_proposal():
        activated.append("begin")
        lesson["status"] = "active"
        return lesson

    deps = tutor_deps(
        phase=lesson_flow.PHASE_AWAITING_ACCEPT,
        session_lessons=[pending],
        pending_proposal=pending,
        events=events,
        activate_proposal=activate_proposal,
        record_event=record_noop,
    )
    ack = await begin_lesson(_StubRunContext(deps))
    assert "lesson is live" in ack
    first = events.get_nowait()
    assert first == {"type": "status", "text": "Starting your lesson…"}
    second = events.get_nowait()
    assert second["kind"] == "lesson_started" and second["data"]["lesson"]["id"] == lesson["id"]
    assert activated == ["begin"]


@pytest.mark.asyncio
async def test_complete_lesson_tool_emits_summary_event():
    lesson = cafe_lesson()
    lesson["status"] = "active"
    finished = dict(lesson, status="completed")
    events = asyncio.Queue()

    async def grade_and_complete():
        return finished

    deps = tutor_deps(
        phase=lesson_flow.PHASE_LESSON,
        active_lesson=lesson,
        session_lessons=[lesson],
        events=events,
        grade_and_complete=grade_and_complete,
        record_event=record_noop,
    )
    ack = await complete_lesson(_StubRunContext(deps))
    assert "no re-greeting" in ack
    second = deps_events_skip_status(events)
    assert second["kind"] == "lesson_completed"
    assert second["data"]["lesson"]["status"] == "completed"


def deps_events_skip_status(queue: asyncio.Queue) -> dict:
    event = queue.get_nowait()
    while event["type"] == "status":
        event = queue.get_nowait()
    return event


# --- Planner ------------------------------------------------------------------------


def planner_deps() -> PlannerDeps:
    return {
        "user_id": "user-1",
        "user_profile": {
            "target_language": "es",
            "goals": "business Spanish",
            "level": "B1",
            "interests": "finance",
        },
        "due_cards": [{"id": "card-1", "front": "Revenue", "back": "ingresos"}],
        "recent_transcript": [{"speaker": "user", "text": "Tengo una reunión mañana"}],
        "session_lessons": [],
    }


@pytest.mark.asyncio
async def test_session_planner_output_schema():
    with session_planner_agent.override(model=TestModel()):
        result = await session_planner_agent.run("Plan.", deps=planner_deps())
    assert isinstance(result.output, LessonProposal)


def test_planner_instructions_inject_templates_chat_and_cards():
    from voca.agents.session_planner_agent import inject_planner_deps

    injected = inject_planner_deps(_StubRunContext(planner_deps()))
    for template in LESSON_TEMPLATES:
        assert template["id"] in injected
    assert "[card-1] Revenue → ingresos" in injected
    # Grounded in the recent chat turns.
    assert "Tengo una reunión mañana" in injected
    # No lesson bank: templates, not DB lessons, get injected.
    assert "AVAILABLE LESSONS" not in injected
    # The block primitives are described.
    assert "scenario(" in injected


def test_planner_instructions_render_idea_and_history():
    from voca.agents.session_planner_agent import inject_planner_deps

    deps: PlannerDeps = {
        **planner_deps(),
        "idea": "a menu role play",
        "session_lessons": [{"status": "completed", "title": "At the café"}],
    }
    injected = inject_planner_deps(_StubRunContext(deps))
    assert "a menu role play" in injected
    assert "At the café" in injected


# --- Lesson grader --------------------------------------------------------------------


def grader_deps() -> GraderDeps:
    lesson = cafe_lesson()
    lesson["status"] = "active"
    lesson["accepted_at"] = "2025-01-01T00:00:10+00:00"
    return {
        "language": "es",
        "lesson": lesson,
        "transcript": [
            {"speaker": "tutor", "text": "¡Hola! Imagina que estamos en una cafetería…"},
            {"speaker": "user", "text": "Quisiera un cortado, por favor."},
        ],
    }


@pytest.mark.asyncio
async def test_lesson_grader_output_schema():
    with lesson_grader_agent.override(model=TestModel()):
        result = await lesson_grader_agent.run("Grade.", deps=grader_deps())
    assert isinstance(result.output, LessonGrades)
    assert isinstance(result.output.summary, BaseModel)


def test_grader_instructions_render_lesson_and_targets():
    from voca.agents.lesson_grader_agent import inject_grader_deps

    injected = inject_grader_deps(_StubRunContext(grader_deps()))
    assert "card-1" in injected
    assert "At the café" in injected
    assert "Quisiera un cortado" in injected
    # The transcript the grades come from is included.
    assert "LESSON TRANSCRIPT" in injected


@pytest.mark.asyncio
async def test_tutor_agent_output_is_plain_text():
    """The tutor is a chat agent: text out, even with tools registered."""
    with tutor_agent.override(model=TestModel()):
        result = await tutor_agent.run("¡Hola!", deps=tutor_deps())
    assert isinstance(result.output, str)


@pytest.mark.asyncio
async def test_tutor_agent_sends_profile_in_request():
    with capture_run_messages() as messages_log, tutor_agent.override(model=TestModel()):
        await tutor_agent.run("¡Hola!", deps=tutor_deps())
    prompt_parts = [part for message in messages_log for part in message.parts]
    user_parts = [part for part in prompt_parts if part.part_kind == "user-prompt"]
    assert any("¡Hola!" in str(part) for part in user_parts)


# --- Post-session analyst --------------------------------------------------------------


def test_post_session_agent_shapes_transcript_and_cards():
    """The instructions builder expects DB-shaped rows (speaker/text)."""
    from voca.agents.post_session_agent import inject_post_session_deps

    deps: PostSessionDeps = {
        "user_id": "user-1",
        "session_id": "session-1",
        "transcript": [
            {"speaker": "user", "text": "¿Cómo se dice 'I am exhausted'?"},
            {"speaker": "tutor", "text": "Se dice 'estoy agotado'."},
        ],
        "due_cards": [{"id": "card-1", "front": "exhausted", "back": "agotado"}],
        "existing_cards": [
            {"front": "the bill / check", "back": "la cuenta"},
            {"front": "I am exhausted", "back": "estoy agotado"},
        ],
        "lessons": [cafe_lesson() | {"status": "completed"}],
    }
    injected = inject_post_session_deps(_StubRunContext(deps))
    assert "estoy agotado" in injected
    assert "card-1" in injected
    assert "EXISTING CARDS" in injected
    assert "never create a card" in injected
    # Lesson coverage (already graded) is visible to the analyst.
    assert "At the café" in injected
    assert "SESSION PLAN" not in injected


def test_post_session_agent_instructions_allow_zero_cards():
    """The harvest rules: 0-5 cards, criteria-gated, no confident-use cards."""
    from voca.agents.post_session_agent import NEW_CARDS_RULES as rules

    assert "0-5 new cards" in rules
    assert "An empty list is a good result" in rules
    assert "UNCERTAINTY" in rules and "¿cómo se dice…?" in rules
    assert "INCORRECT USE" in rules and "reformulation" in rules
    assert "BETTER ALTERNATIVE" in rules
    assert "Hard exclusions" in rules
    assert "criterion" in rules


def test_post_session_instructions_without_lessons():
    from voca.agents.post_session_agent import inject_post_session_deps

    deps: PostSessionDeps = {
        "user_id": "user-1",
        "session_id": "session-1",
        "transcript": [],
        "due_cards": [],
        "target_language": "es",
        "lessons": [],
    }
    injected = inject_post_session_deps(_StubRunContext(deps))
    assert "(none — pure small-talk session)" in injected


@pytest.mark.asyncio
async def test_post_session_agent_output_schema():
    with post_session_agent.override(model=TestModel()):
        result = await post_session_agent.run(
            "Analyze.", deps={"user_id": "u", "session_id": "s", "transcript": [], "due_cards": []}
        )
    assert isinstance(result.output, PostSessionResult)
    assert isinstance(result.output.recap, BaseModel)


def test_planner_untangles_lesson_nested_material_and_missing_title():
    """The proposal's shape slips are coerced before validation: material lifted
    out of `lesson`, and a missing title falls back to topic/template."""
    proposal = LessonProposal.model_validate(
        {
            "lesson": {
                "template": "reading_discussion",
                "objectives": ["literal recall"],
                "material": [{"type": "text", "markdown": "A passage."}],
                "target_card_ids": ["card-1"],
            },
            "material": [{"type": "text", "markdown": "A passage."}],
            "target_card_ids": ["card-1"],
            "intro_line": "Lee esto.",
            "reason": "r",
        }
    )
    assert proposal.lesson.title == "Reading + Discussion practice"

    titled_from_topic = LessonProposal.model_validate(
        {
            "lesson": {"template": "role_play", "topic": "At the pharmacy", "objectives": []},
            "material": [
                {
                    "type": "scenario",
                    "setting": "s",
                    "learner_role": "l",
                    "tutor_role": "t",
                    "goal": "g",
                }
            ],
            "target_card_ids": [],
            "intro_line": "x",
            "reason": "y",
        }
    )
    assert titled_from_topic.lesson.title == "At the pharmacy"
