import pytest
from src.voca.agents.tutor_agent import spanish_tutor, TutorDeps
from src.voca.agents.post_session_agent import post_session_agent, PostSessionDeps
from src.voca.agents.session_planner_agent import session_planner_agent, PlannerDeps

@pytest.mark.asyncio
async def test_tutor_agent_opener(mock_supabase):
    """Test that the TutorAgent starts a session correctly in the opener phase."""
    deps: TutorDeps = {
        "user_id": "user_123",
        "user_profile": {"name": "Alex", "goals": "travel to Spain", "level": "A2", "interests": "architecture"},
        "session_id": "sess_456",
        "current_phase": "opener"
    }

    result = await spanish_tutor.run("¡Hola!", deps=deps)

    # pydantic-ai AgentRunResult uses .output for the final result
    data = result.output
    assert data.text is not None
    assert len(data.text) > 0
    assert data.next_phase in ["small_talk", None]

@pytest.mark.asyncio
async def test_tutor_agent_lesson_pitch(mock_supabase):
    """Test that the TutorAgent uses the get_suggested_lesson tool during the lesson_pitch phase."""
    # Setup mock supabase to return a lesson
    mock_lesson = {"title": "At the Airport", "scenario": "Checking in for a flight", "objectives": "Learn travel vocab"}
    mock_supabase.table().select().limit().execute.return_value.data = [mock_lesson]

    deps: TutorDeps = {
        "user_id": "user_123",
        "user_profile": {"name": "Alex", "goals": "travel to Spain", "level": "A2", "interests": "architecture"},
        "session_id": "sess_456",
        "current_phase": "lesson_pitch"
    }

    result = await spanish_tutor.run("I'm ready for a lesson!", deps=deps)

    data = result.output
    assert data.text is not None
    assert "Airport" in data.text
    assert data.next_phase in ["lesson_execution", None]

@pytest.mark.asyncio
async def test_post_session_agent():
    """Test that the PostSessionAgent can analyze a transcript and generate cards/recap."""
    deps: PostSessionDeps = {
        "user_id": "user_123",
        "session_id": "sess_456",
        "transcript": [
            {"role": "tutor", "content": "¡Hola Alex! ¿Cómo estás?"},
            {"role": "user", "content": "Estoy bien, pero no sé cómo decir 'I am exhausted' en español."},
            {"role": "tutor", "content": "Se dice 'Estoy agotado' o 'Estoy exhausto'."},
            {"role": "user", "content": "Ah, 'estoy agotado'. Gracias."},
        ],
        "due_cards": []
    }

    result = await post_session_agent.run("Analyze this session.", deps=deps)

    data = result.output
    assert data.recap is not None
    assert len(data.new_cards) > 0
    # Check if "agotado" was captured
    found_agotado = any("agotado" in card.back.lower() or "agotado" in card.front.lower() for card in data.new_cards)
    assert found_agotado, "Should have captured 'estoy agotado' as a new card"

@pytest.mark.asyncio
async def test_session_planner_agent():
    """Test that the SessionPlannerAgent creates a plan with a hook and lesson."""
    deps: PlannerDeps = {
        "user_id": "user_123",
        "user_profile": {"name": "Alex", "goals": "business Spanish", "level": "B1", "interests": "finance"},
        "due_cards": [
            {"id": "card_1", "front": "Revenue", "back": "Ingresos"},
            {"id": "card_2", "front": "Expense", "back": "Gasto"},
        ],
        "available_lessons": [
            {"id": "lesson_biz_1", "title": "Business Meeting", "scenario": "Leading a meeting"},
        ]
    }

    result = await session_planner_agent.run("Plan the next session.", deps=deps)

    data = result.output
    assert data.opening_hook is not None
    assert len(data.target_cards) > 0
    assert data.suggested_lesson_id == "lesson_biz_1"
