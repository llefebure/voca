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
from voca.agents.tutor_agent import TutorDeps, spanish_tutor, tutor_system_prompt


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


@pytest.mark.asyncio
async def test_tutor_agent_output_is_plain_text():
    """After the phase-removal refactor the tutor returns text, not a model."""
    with spanish_tutor.override(model=TestModel()):
        result = await spanish_tutor.run("¡Hola!", deps=TUTOR_DEPS)
    assert isinstance(result.output, str)


@pytest.mark.asyncio
async def test_tutor_agent_sends_profile_in_request():
    with capture_run_messages() as messages_log, spanish_tutor.override(model=TestModel()):
        await spanish_tutor.run("¡Hola!", deps=TUTOR_DEPS)
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
        "due_cards": [{"front": "exhausted", "back": "agotado"}],
    }
    injected = inject_post_session_deps(_StubRunContext(deps))
    assert "estoy agotado" in injected
    assert "exhausted" in injected


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
        "due_cards": [{"id": "card-1", "front": "Revenue"}],
        "available_lessons": [
            {"id": "lesson-1", "title": "Business Meeting", "scenario": "Meetings"}
        ],
    }
