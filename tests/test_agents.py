"""Agent wiring tests: prompt construction and output schemas, fully offline.

These use a stub RunContext for the instructions functions and pydantic-ai's
TestModel (no LLM calls) for run-level tests.
"""

import pytest
from pydantic import BaseModel
from pydantic_ai import capture_run_messages
from pydantic_ai.models.test import TestModel

from voca.agents.post_session_agent import (
    PostSessionDeps,
    PostSessionResult,
    post_session_agent,
)
from voca.agents.session_planner_agent import (
    PlannerDeps,
    SessionPlan,
    session_planner_agent,
)
from voca.agents.tutor_agent import TutorDeps, tutor_agent, tutor_system_prompt
from voca.services.lesson_templates import LESSON_TEMPLATES


class _StubRunContext:
    """Just enough of pydantic-ai's RunContext for instructions functions."""

    def __init__(self, deps: dict) -> None:
        self.deps = deps


TUTOR_DEPS: TutorDeps = {
    "user_id": "user-1",
    "user_profile": {
        "name": "Alex",
        "goals": "travel to Spain",
        "level": "A2",
        "interests": "architecture",
    },
    "session_id": "session-1",
}


def test_tutor_system_prompt_includes_profile():
    prompt = tutor_system_prompt(_StubRunContext(TUTOR_DEPS))
    assert "travel to Spain" in prompt
    assert "A2" in prompt
    assert "architecture" in prompt
    # TTS-optimized: the tutor is told not to use lists/markdown.
    assert "NO bulleted lists" in prompt


def test_tutor_system_prompt_defaults_without_profile():
    prompt = tutor_system_prompt(_StubRunContext({"user_profile": {}}))
    assert "learn Spanish" in prompt
    assert "Intermediate (B1)" in prompt


def test_tutor_system_prompt_uses_profile_language():
    deps: TutorDeps = {"user_id": "u", "user_profile": {"target_language": "es"}, "session_id": "s"}
    prompt = tutor_system_prompt(_StubRunContext(deps))
    assert "Spanish language tutor" in prompt

    deps_unknown: TutorDeps = {
        "user_id": "u",
        "user_profile": {"target_language": "xx"},
        "session_id": "s",
    }
    fallback = tutor_system_prompt(_StubRunContext(deps_unknown))
    assert "Spanish language tutor" in fallback


def test_tutor_system_prompt_renders_session_plan():
    deps: TutorDeps = {
        "user_id": "user-1",
        "user_profile": {"target_language": "es"},
        "session_id": "session-1",
        "session_plan": {
            "lesson": {
                "template": "role_play",
                "topic": "At the pharmacy",
                "scenario": "Pharmacist and customer",
                "objectives": ["describe symptoms", "ask for a recommendation"],
            },
            "opening_hook": "¡Hola Alex!",
            "cards": [{"id": "c1", "front": "exhausted", "back": "agotado"}],
        },
    }
    prompt = tutor_system_prompt(_StubRunContext(deps))
    assert "TODAY'S LESSON" in prompt
    assert "Role Play" in prompt
    assert "At the pharmacy" in prompt
    assert "Pharmacist and customer" in prompt
    assert "describe symptoms" in prompt
    assert "¡Hola Alex!" in prompt
    assert "exhausted → agotado" in prompt


def test_tutor_system_prompt_without_plan_stays_simple():
    prompt = tutor_system_prompt(_StubRunContext(dict(TUTOR_DEPS)))
    assert "TODAY'S LESSON" not in prompt


@pytest.mark.asyncio
async def test_tutor_agent_output_is_plain_text():
    """After the phase-removal refactor the tutor returns text, not a model."""
    with tutor_agent.override(model=TestModel()):
        result = await tutor_agent.run("¡Hola!", deps=TUTOR_DEPS)
    assert isinstance(result.output, str)


@pytest.mark.asyncio
async def test_tutor_agent_sends_profile_in_request():
    with capture_run_messages() as messages_log, tutor_agent.override(model=TestModel()):
        await tutor_agent.run("¡Hola!", deps=TUTOR_DEPS)
    prompt_parts = [part for message in messages_log for part in message.parts]
    user_parts = [part for part in prompt_parts if part.part_kind == "user-prompt"]
    assert any("¡Hola!" in str(part) for part in user_parts)


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
    }
    injected = inject_post_session_deps(_StubRunContext(deps))
    assert "estoy agotado" in injected
    assert "card-1" in injected
    assert "SESSION PLAN: " in injected  # absent plan renders as a placeholder


def test_post_session_agent_injects_plan():
    from voca.agents.post_session_agent import inject_post_session_deps

    deps: PostSessionDeps = {
        "user_id": "user-1",
        "session_id": "session-1",
        "transcript": [],
        "due_cards": [],
        "target_language": "es",
        "session_plan": {
            "lesson": {
                "template": "reading_comprehension",
                "topic": "A trip to the market",
                "objectives": ["literal recall", "inference"],
            }
        },
    }
    injected = inject_post_session_deps(_StubRunContext(deps))
    assert "reading_comprehension" in injected
    assert "A trip to the market" in injected
    assert "literal recall" in injected


@pytest.mark.asyncio
async def test_post_session_agent_output_schema():
    with post_session_agent.override(model=TestModel()):
        result = await post_session_agent.run("Analyze.", deps=_analyst_deps())
    assert isinstance(result.output, PostSessionResult)
    assert isinstance(result.output.recap, BaseModel)


@pytest.mark.asyncio
async def test_session_planner_output_schema():
    with session_planner_agent.override(model=TestModel()):
        result = await session_planner_agent.run("Plan.", deps=_planner_deps())
    assert isinstance(result.output, SessionPlan)


def test_planner_instructions_inject_templates_and_compact_cards():
    from voca.agents.session_planner_agent import inject_planner_deps

    injected = inject_planner_deps(_StubRunContext(_planner_deps()))
    for template in LESSON_TEMPLATES:
        assert template["id"] in injected
    assert "[card-1] Revenue" in injected
    # No lesson bank: templates, not DB lessons, get injected.
    assert "AVAILABLE LESSONS" not in injected


def test_lesson_templates_cover_the_catalog():
    ids = {template["id"] for template in LESSON_TEMPLATES}
    assert ids == {"role_play", "reading_comprehension", "free_conversation"}


def _analyst_deps() -> PostSessionDeps:
    return {
        "user_id": "user-1",
        "session_id": "session-1",
        "transcript": [{"speaker": "user", "text": "hola"}],
        "due_cards": [],
    }


def _planner_deps() -> PlannerDeps:
    return {
        "user_id": "user-1",
        "user_profile": {"goals": "business Spanish", "level": "B1", "interests": "finance"},
        "due_cards": [{"id": "card-1", "front": "Revenue", "back": "ingresos"}],
    }
