"""Live-LLM integration tests — opt-in only (needs a local Ollama server).

Excluded from the default run via `-m "not integration"` (see pyproject).
Run with: `uv run task test:all`. The planner/post-session tests exercise the
`gemma4:31b-cloud` planning model end-to-end, proving schema adherence where
the small local model used to fail.
"""

import pytest

from voca.agents.post_session_agent import PostSessionResult, post_session_agent
from voca.agents.session_planner_agent import SessionPlan, session_planner_agent
from voca.agents.tutor_agent import TutorDeps, tutor_agent

TUTOR_DEPS: TutorDeps = {
    "user_id": "user-1",
    "user_profile": {"goals": "travel to Spain", "level": "A2", "interests": "architecture"},
    "session_id": "session-1",
}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tutor_replies_in_spanish():
    """The tutor answers a Spanish prompt with a short, plain-text reply."""
    result = await tutor_agent.run("Hola, ¿qué tal? Me llamo Alex.", deps=TUTOR_DEPS)
    assert isinstance(result.output, str)
    assert result.output.strip()
    # TTS-optimized tutor turns should stay short.
    assert len(result.output) < 2000


@pytest.mark.integration
@pytest.mark.asyncio
async def test_session_planner_produces_valid_plan():
    """The planning model must emit schema-valid output (the original pain point)."""
    deps = {
        "user_id": "user-1",
        "user_profile": {
            "target_language": "es",
            "goals": "travel to Mexico",
            "level": "A2",
            "interests": "cooking",
        },
        "due_cards": [
            {"id": "card-1", "front": "exhausted", "back": "agotado"},
            {"id": "card-2", "front": "the bill / check", "back": "la cuenta"},
            {"id": "card-3", "front": "I would like…", "back": "quisiera…"},
            {"id": "card-4", "front": "spicy", "back": "picante"},
        ],
    }
    result = await session_planner_agent.run("Plan the session.", deps=deps)  # type: ignore[arg-type]
    assert isinstance(result.output, SessionPlan)
    plan = result.output
    # Selected IDs must reference due cards, not invented content.
    valid_ids = {card["id"] for card in deps["due_cards"]}
    assert plan.card_ids, "planner should select at least one card"
    assert set(plan.card_ids) <= valid_ids
    assert plan.lesson.template in {"role_play", "reading_comprehension", "free_conversation"}
    assert plan.lesson.topic.strip()
    assert plan.opening_hook.strip()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_post_session_produces_valid_analysis():
    """Schema-valid post-session output: card grades by ID, typed profile updates."""
    deps = {
        "user_id": "user-1",
        "session_id": "session-1",
        "target_language": "es",
        "session_plan": {
            "lesson": {
                "template": "free_conversation",
                "topic": "Ordering at a taquería",
                "objectives": ["order politely", "ask about prices"],
            },
            "cards": [{"id": "card-2", "front": "the bill / check", "back": "la cuenta"}],
        },
        "transcript": [
            {"speaker": "tutor", "text": "¡Hola! Que gusto verte. ¿Listo para la taquería?"},
            {"speaker": "user", "text": "Hola! Sí. Quisiero un tacos de pastor, por favor."},
            {
                "speaker": "tutor",
                "text": "Casi perfecto: decimos 'quisiera unos tacos'. ¿Algo de tomar?",
            },
            {"speaker": "user", "text": "Sí, un agua de horchata. ¿Cuánto cuesta todo?"},
            {
                "speaker": "tutor",
                "text": "Muy bien preguntado. '¿Cuánto cuesta todo?' es perfecto.",
            },
        ],
        "due_cards": [
            {"id": "card-1", "front": "exhausted", "back": "agotado"},
            {"id": "card-2", "front": "the bill / check", "back": "la cuenta"},
        ],
    }
    result = await post_session_agent.run("Analyze the session.", deps=deps)  # type: ignore[arg-type]
    assert isinstance(result.output, PostSessionResult)
    analysis = result.output
    valid_ids = {card["id"] for card in deps["due_cards"]}
    for grade in analysis.reviewed_cards:
        assert grade.card_id in valid_ids
    assert analysis.recap.next_time_preview.strip()
