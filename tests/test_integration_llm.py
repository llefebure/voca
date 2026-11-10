"""Live-LLM integration tests — opt-in only (needs a local Ollama server).

Excluded from the default run via `-m "not integration"` (see pyproject).
Run with: `uv run task test:all`
"""

import pytest

from voca.agents.tutor_agent import TutorDeps, spanish_tutor

TUTOR_DEPS: TutorDeps = {
    "user_id": "user-1",
    "user_profile": {"goals": "travel to Spain", "level": "A2", "interests": "architecture"},
    "session_id": "session-1",
}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tutor_replies_in_spanish():
    """The tutor answers a Spanish prompt with a short, plain-text reply."""
    result = await spanish_tutor.run("Hola, ¿qué tal? Me llamo Alex.", deps=TUTOR_DEPS)
    assert isinstance(result.output, str)
    assert result.output.strip()
    # TTS-optimized tutor turns should stay short.
    assert len(result.output) < 2000
