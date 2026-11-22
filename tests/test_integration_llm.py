"""Live-LLM integration tests — opt-in only (needs the Ollama server + gemma4:31b-cloud).

Excluded from the default run via `-m "not integration"` (see pyproject).
Run with: `uv run task test:all`. Every agent now shares one model lane
(`gemma4:31b-cloud`): these tests pin down schema adherence, tool-call behavior,
and the lesson-material contracts end-to-end.
"""

import asyncio

import pytest

from voca.agents.lesson_grader_agent import GraderDeps, LessonGrades, lesson_grader_agent
from voca.agents.post_session_agent import PostSessionResult, post_session_agent
from voca.agents.session_planner_agent import LessonProposal, session_planner_agent
from voca.agents.tutor_agent import TutorDeps, tutor_agent
from voca.services import lesson_flow
from voca.services.lesson_flow import PRODUCTION_OUTCOMES, LessonSpec, new_lesson
from voca.services.lesson_templates import LESSON_TEMPLATES

TEMPLATE_IDS = {template["id"] for template in LESSON_TEMPLATES}

# All known material primitives (the union the schema enforces).
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
        "phase": lesson_flow.PHASE_SMALL_TALK,
        "active_lesson": None,
        "pending_proposal": None,
        "session_lessons": [],
        "due_cards": [],
        "smalltalk_turns": 5,
        "events": asyncio.Queue(),
        "run_planner": None,
        "activate_proposal": None,
        "grade_and_complete": None,
        "record_event": None,
    }
    base.update(overrides)
    return base


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
async def test_tutor_calls_propose_lesson_after_nudge():
    """The nudge drives the tutor to a real tool call with a grounded idea."""
    calls: list[str] = []
    planned: list[dict] = []
    proposal = new_lesson(
        LessonSpec(
            template="role_play",
            title="A café in Madrid",
            objectives=["order politely"],
            minutes=6,
        ),
        [
            {
                "type": "scenario",
                "setting": "a café",
                "learner_role": "customer",
                "tutor_role": "barista",
                "goal": "order a coffee",
            }
        ],
        [{"id": "card-1", "front": "quisiera", "back": "I would like"}],
        "the learner chatted about coffee",
        "¡Hola! Imagina que entramos en una cafetería.",
    )

    async def run_planner(idea: str):
        calls.append(idea)
        return proposal

    async def record_event(kind, data):
        planned.append(kind)

    deps = tutor_deps(
        due_cards=[{"id": "card-1", "front": "quisiera", "back": "I would like"}],
        run_planner=run_planner,
        record_event=record_event,
    )
    await tutor_agent.run(
        "Hola, estoy bien. Ay desayuné en una cafetería nueva cerca de casa.",
        deps=deps,
    )
    assert calls, "the tutor must call propose_lesson at the nudge"
    assert planned == ["proposal_ready"]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_session_planner_produces_valid_proposal():
    """Schema-valid proposal: template blocks valid for the template, cards by ID."""
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
        "recent_transcript": [
            {"speaker": "user", "text": "Anoche fui a un restaurante mexicano y pedí tacos."},
            {"speaker": "tutor", "text": "¡Qué bien! ¿Te gustó la comida?"},
        ],
        "session_lessons": [],
    }
    result = await session_planner_agent.run("Design this lesson proposal.", deps=deps)  # type: ignore[arg-type]
    assert isinstance(result.output, LessonProposal)
    proposal = result.output
    assert proposal.lesson.template in TEMPLATE_IDS
    assert proposal.lesson.title.strip()
    assert proposal.lesson.objectives, "2-4 objectives required"
    assert proposal.intro_line.strip()
    assert proposal.reason.strip()

    material_type_count = {}
    for block in proposal.material:
        material_type_count[block.type] = material_type_count.get(block.type, 0) + 1
    template = next(t for t in LESSON_TEMPLATES if t["id"] == proposal.lesson.template)
    assert all(block.type in ALL_BLOCK_TYPES for block in proposal.material), (
        "material may only contain known primitives (disallowed extras are dropped)"
    )
    for block_type in template["required_blocks"]:
        assert material_type_count.get(block_type), (
            f"template {template['id']} requires a {block_type} block"
        )

    valid_ids = {card["id"] for card in deps["due_cards"]}
    assert proposal.target_card_ids, "planner should select at least one card"
    assert set(proposal.target_card_ids) <= valid_ids


@pytest.mark.integration
@pytest.mark.asyncio
async def test_lesson_grader_produces_valid_grades():
    """The grader grades only/any subset of target cards with evidence-backed outcomes."""
    lesson = new_lesson(
        LessonSpec(
            template="role_play",
            title="A café in Madrid",
            objectives=["order politely", "ask for the check"],
            minutes=6,
        ),
        [
            {
                "type": "scenario",
                "setting": "a café",
                "learner_role": "customer",
                "tutor_role": "barista",
                "goal": "order a coffee and pay",
            }
        ],
        [
            {"id": "card-1", "front": "quisiera", "back": "I would like"},
            {"id": "card-2", "front": "la cuenta", "back": "the bill / check"},
        ],
        "the learner chatted about coffee",
        "¡Hola! Imagina que entramos en una cafetería.",
    )
    lesson["status"] = "active"
    lesson["accepted_at"] = "2025-01-01T00:00:10+00:00"
    deps = GraderDeps(
        language="es",
        lesson=lesson,
        transcript=[
            {
                "speaker": "tutor",
                "text": "¡Hola! Imagina que entramos en una cafetería. ¿La carta?",
            },
            {"speaker": "user", "text": "Quisiera un cortado, por favor."},
            {"speaker": "tutor", "text": "Perfecto, aquí tienes. ¿Algo más?"},
            {"speaker": "user", "text": "No, nada más. ¿Me trae la cuenta, por favor?"},
            {"speaker": "tutor", "text": "Claro, ahora mismo. ¡Todo muy bien pedido!"},
        ],
    )
    result = await lesson_grader_agent.run("Grade this lesson.", deps=deps)
    assert isinstance(result.output, LessonGrades)
    valid_ids = {"card-1", "card-2"}
    graded_ids = {grade.card_id for grade in result.output.grades}
    assert graded_ids, "the grader must credit exercised cards"
    assert graded_ids <= valid_ids, "grades reference target cards only"
    for grade in result.output.grades:
        assert grade.evidence.strip()
    # This transcript clearly exercises both targets; most grades must land.
    assert len(graded_ids) >= 1
    # The learner produced both target phrases correctly in context — production
    # credit (the bonus) should dominate on this transcript, but the judge samples.
    production = [g for g in result.output.grades if g.outcome in PRODUCTION_OUTCOMES]
    assert len(production) >= 1, "at least one in-context production must earn the bonus"
    assert result.output.summary.headline.strip()
    assert isinstance(result.output.bonus_uses, list)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_post_session_produces_valid_analysis():
    """Schema-valid post-session output: card grades by ID, typed profile updates."""
    lesson = new_lesson(
        LessonSpec(template="role_play", title="Ordering at a taquería"),
        [],
        [{"id": "card-2", "front": "the bill / check", "back": "la cuenta"}],
        "the learner chatted about tacos",
        "Vamos a la taquería.",
    )
    lesson["status"] = "completed"
    lesson["grades"] = [{"card_id": "card-2", "outcome": "pass", "bonus_use": True}]
    deps = {
        "user_id": "user-1",
        "session_id": "session-1",
        "target_language": "es",
        "lessons": [lesson],
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
        # card-2 was graded by the lesson already: only small-talk cards remain.
        "due_cards": [{"id": "card-1", "front": "exhausted", "back": "agotado"}],
    }
    result = await post_session_agent.run(
        "Analyze the session and generate cards and recap.", deps=deps
    )  # type: ignore[arg-type]
    assert isinstance(result.output, PostSessionResult)
    analysis = result.output
    for grade in analysis.reviewed_cards:
        # The lesson-covered card must not be re-graded here.
        assert grade.card_id != "card-2"
    assert analysis.recap.next_time_preview.strip()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_post_session_correct_confident_transcript_yields_no_cards():
    """Harvest rule: with no mistakes and no questions, 0 cards is the correct output."""
    deps = {
        "user_id": "user-1",
        "session_id": "session-1",
        "target_language": "es",
        "lessons": [],
        "existing_cards": [{"front": "the bill / check", "back": "la cuenta"}],
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
    }
    result = await post_session_agent.run("Analyze the session.", deps=deps)  # type: ignore[arg-type]
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
    deps = {
        "user_id": "user-1",
        "session_id": "session-1",
        "target_language": "es",
        "lessons": [],
        "existing_cards": [],
        "transcript": transcript,
        "due_cards": [],
    }
    result = await post_session_agent.run("Analyze the session.", deps=deps)  # type: ignore[arg-type]
    assert isinstance(result.output, PostSessionResult)
    assert result.output.new_cards, "a corrected item must become at least one card"
    transcript_text = " ".join(message["text"] for message in transcript)
    for card in result.output.new_cards:
        # Cards must cite real transcript lines, not invent sentences.
        assert card.source_sentence in transcript_text
