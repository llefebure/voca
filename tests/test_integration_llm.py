"""Live-LLM integration tests — opt-in only (needs the Ollama server + gemma4:31b-cloud).

Excluded from the default run via `-m "not integration"` (see pyproject).
Run with: `uv run task test:all`. Every agent shares one model lane
(`gemma4:31b-cloud`): these tests pin down schema adherence, tool-call behavior
(the tutor's `show_panel` canvas calls), and the FSRS rubric end-to-end.
"""

import asyncio

import pytest

from voca.agents.post_session_agent import PostSessionDeps, PostSessionResult, post_session_agent
from voca.agents.tutor_agent import TutorDeps, tutor_agent

ALL_BLOCK_TYPES = {"scenario", "text", "dialogue", "questions", "tasks", "word_bank"}


def tutor_deps(**overrides) -> TutorDeps:
    base: TutorDeps = {
        "user_id": "user-1",
        "session_id": "session-1",
        "user_profile": {
            "target_language": "es",
            "goals": "travel to Spain",
            "level": "A2",
            "interests": "architecture",
        },
        "due_cards": [],
        "events": asyncio.Queue(),
        "record_event": None,
    }
    base.update(overrides)
    return base


async def drained(queue: asyncio.Queue) -> list[dict]:
    items: list[dict] = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tutor_replies_in_spanish():
    """The tutor answers a Spanish prompt with a short, plain-text reply."""
    result = await tutor_agent.run("Hola, ¿qué tal? Me llamo Alex.", deps=tutor_deps())
    assert isinstance(result.output, str)
    assert result.output.strip()
    # TTS-optimized tutor turns should stay short.
    assert len(result.output) < 2000


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tutor_shows_menu_panel_when_role_playing_a_restaurant():
    """A menu request drives the real show_panel tool: a panel_shown event.

    The model's tool-calling is stochastic, so the prompt retries once with a
    blunter ask if the first turn produced no panel.
    """
    async def record_event(kind, data):
        pass

    deps = tutor_deps(record_event=record_event)
    prompts = [
        "Estoy sentado en un restaurante mexicano y me has dado la carta. "
        "Enséñamela, por favor.",
        "Muéstrame la carta en el panel, por favor.",
    ]
    for prompt in prompts:
        await tutor_agent.run(prompt, deps=deps)
    # Status chips may queue; the assert is on typed events only.
    events = await drained(deps["events"])
    panels = [
        event
        for event in events
        if event.get("type") == "event" and event.get("kind") == "panel_shown"
    ]
    assert panels, "the tutor must call show_panel for a menu request"
    panel = panels[0]["data"]["panel"]
    assert panel["title"].strip()
    assert panel["blocks"], "the panel carries at least one content block"
    for block in panel["blocks"]:
        assert block["type"] in ALL_BLOCK_TYPES


@pytest.mark.integration
@pytest.mark.asyncio
async def test_tutor_small_talk_stays_panel_free():
    """Casual chat without a content need must not stack a panel."""

    async def record_event(kind, data):
        pass

    deps = tutor_deps(record_event=record_event)
    await tutor_agent.run(
        "Hola, ¿qué tal? Hoy fue un día larguísimo en el trabajo, pero bien.",
        deps=deps,
    )
    events = await drained(deps["events"])
    panels = [event for event in events if event.get("kind") == "panel_shown"]
    assert panels == [], "small talk needs no panel"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_post_session_produces_valid_analysis():
    """Schema-valid post-session output: FSRS rubric grades by ID, typed updates."""
    deps: PostSessionDeps = {
        "user_id": "user-1",
        "session_id": "session-1",
        "target_language": "es",
        "transcript": [
            {"speaker": "tutor", "text": "¡Hola! Dime, ¿qué se te antoja hoy?"},
            {"speaker": "user", "text": "Quisiero un tacos de pastor, por favor."},
            {
                "speaker": "tutor",
                "text": "Casi perfecto: decimos 'quisiera unos tacos'. ¿Ya conoces 'la cuenta'?",
            },
            {"speaker": "user", "text": "¿La cuenta? No sé. ¿Qué es?"},
            {"speaker": "tutor", "text": "Es el billete o ticket cuando terminas de comer."},
        ],
        "due_cards": [
            {"id": "card-1", "front": "I would like…", "back": "quisiera…"},
            {"id": "card-2", "front": "the bill / check", "back": "la cuenta"},
        ],
        "existing_cards": [],
    }
    result = await post_session_agent.run(
        "Analyze the session and generate cards and recap.", deps=deps
    )
    assert isinstance(result.output, PostSessionResult)
    analysis = result.output
    for grade in analysis.reviewed_cards:
        assert grade.card_id in {"card-1", "card-2"}
        assert grade.evidence.strip(), "each rubric grade cites the transcript"
        assert grade.outcome in {
            "strong_pass",
            "pass",
            "recognition_pass",
            "miss",
            "not_attempted",
        }
    # card-1 was used (wrongly once, then corrected): it must be graded, not ignored.
    graded_ids = {grade.card_id for grade in analysis.reviewed_cards}
    assert "card-1" in graded_ids, "the rubric grades every card the transcript touched"
    assert analysis.recap.next_time_preview.strip()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_post_session_correct_confident_transcript_yields_no_cards():
    """Harvest rule: with no mistakes and no questions, 0 cards is the correct output."""
    deps: PostSessionDeps = {
        "user_id": "user-1",
        "session_id": "session-1",
        "target_language": "es",
        "transcript": [
            {"speaker": "tutor", "text": "¡Hola Alex! ¿Cómo estás hoy?"},
            {
                "speaker": "user",
                "text": "Hola, estoy muy bien, gracias. Hoy quiero hablar "
                "de mi viaje a Oaxaca el año pasado.",
            },
            {"speaker": "tutor", "text": "¡Qué bonito! ¿Qué fue lo mejor de tu viaje?"},
            {
                "speaker": "user",
                "text": "Lo mejor fue la comida. Probé el mole en un "
                "mercado pequeño y era delicioso. También conocí a mucha gente amable.",
            },
            {
                "speaker": "tutor",
                "text": "Perfecto, tu español suena muy natural. ¿Volverías a Oaxaca?",
            },
            {
                "speaker": "user",
                "text": "Sí, definitivamente volvería. Me encantaría "
                "explorar más pueblos cerca de la ciudad.",
            },
        ],
        "due_cards": [],
        "existing_cards": [{"front": "the bill / check", "back": "la cuenta"}],
    }
    result = await post_session_agent.run("Analyze the session.", deps=deps)
    assert isinstance(result.output, PostSessionResult)
    assert result.output.new_cards == []


@pytest.mark.integration
@pytest.mark.asyncio
async def test_post_session_corrected_item_yields_card_citing_transcript():
    """Harvest rule: a tutor correction produces a card citing the transcript line."""
    transcript = [
        {"speaker": "tutor", "text": "¡Hola Alex! ¿Qué hiciste el fin de semana?"},
        {"speaker": "user", "text": "Yo comí tacos en la fiesta y yo mucho me divertí."},
        {
            "speaker": "tutor",
            "text": "Casi: decimos 'me divertí mucho'. Y también puedes decir "
            "'la pasé genial'. ¿Con quién fuiste?",
        },
        {"speaker": "user", "text": "Fui con mi hermana. ¿Qué tiempo hace para ir al cine?"},
    ]
    deps: PostSessionDeps = {
        "user_id": "user-1",
        "session_id": "session-1",
        "target_language": "es",
        "transcript": transcript,
        "due_cards": [],
        "existing_cards": [],
    }
    result = await post_session_agent.run("Analyze the session.", deps=deps)
    assert isinstance(result.output, PostSessionResult)
    assert result.output.new_cards, "a corrected item must become at least one card"
    transcript_text = " ".join(message["text"] for message in transcript)
    for card in result.output.new_cards:
        # Cards must cite real transcript lines, not invent sentences.
        assert card.source_sentence in transcript_text
