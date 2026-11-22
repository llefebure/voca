"""Session planner: instantiates a lesson proposal mid-conversation.

No longer a session-start planner — the proposal is grounded in what the
learner actually just talked about in small talk, and is invoked by the tutor's
`propose_lesson` tool (or the backend's force-propose safety net). The full
lesson material is generated here so accepting a proposal starts the lesson
with zero additional generation wait.
"""

from typing import Any, NotRequired, TypedDict

from pydantic import BaseModel, Field, field_validator
from pydantic_ai import Agent, RunContext

from voca.services.languages import language_name
from voca.services.lesson_flow import LessonSpec
from voca.services.lesson_material import MaterialList
from voca.services.lesson_templates import template_catalog, template_ids
from voca.services.llm import voca_model


def _untangle_proposal(value: Any) -> Any:
    """Recover the model's common shape slips before schema validation.

    ``material`` and ``target_card_ids`` sometimes arrive nested inside
    ``lesson`` (they were one object in an earlier schema); lift them to the
    top level so the real schema can fail for real problems, not shape ones.
    """
    if not isinstance(value, dict):
        return value
    lesson = value.get("lesson")
    if isinstance(lesson, dict):
        for key in ("material", "target_card_ids"):
            if key in lesson and key not in value:
                return {**value, key: lesson.pop(key)}
    return value


class LessonProposal(BaseModel):
    """One lesson proposal; pydantic-ai wraps the model's tool call in this schema."""

    model_config = {"extra": "ignore"}

    lesson: LessonSpec
    material: MaterialList = Field(
        description=(
            "The lesson's visual material, containing exactly the blocks this template "
            "requires and optionally its allowed extras. Documents (passage, menu, flyer…) "
            "are ALWAYS `text` blocks with markdown, never chat prose."
        )
    )
    target_card_ids: list[str] = Field(
        description="IDs of 3-8 due cards selected for this lesson (no card content)"
    )
    intro_line: str = Field(
        description=(
            "One short, natural line IN THE TARGET LANGUAGE the tutor opens the lesson "
            "with (no lists, no scaffolding)"
        )
    )
    reason: str = Field(
        description="One sentence (English): why this lesson fits this learner right now"
    )

    @field_validator("lesson", mode="before")
    @classmethod
    def _untangle(cls, value: Any) -> Any:
        return _untangle_proposal(value)


class PlannerDeps(TypedDict):
    user_id: str
    user_profile: dict
    # Compact card rows: {"id", "front", "back"} — no FSRS state or other columns.
    due_cards: NotRequired[list[dict]]
    # Recent small-talk turns: [{"speaker", "text"}] — the grounding for the lesson idea.
    recent_transcript: NotRequired[list[dict]]
    # Lesson summaries already done/declined this session: {status, title, reason}.
    session_lessons: NotRequired[list[dict]]
    # The learner's requested lesson idea, when the proposal is learner-initiated.
    idea: NotRequired[str]


session_planner_agent = Agent(
    model=voca_model,
    deps_type=PlannerDeps,
    output_type=LessonProposal,
    # Cheap insurance: the validation-feedback retry loop recovers the rare
    # schema slip.
    retries=3,
    instructions=(
        "You are a lesson designer for a language learning app. You create ONE structured "
        "lesson proposal for the learner's next exercise in their target language, based "
        "on how the conversation just went.\n\n"
        "1. GROUND IT: read the RECENT CHAT turns. The lesson must connect to what the "
        "learner actually talked about or asked for (their `idea`, when present, wins — "
        "it is the learner's own request).\n"
        "2. TEMPLATE: pick the template best suited to that idea, then instantiate its "
        "blocks concretely (see the catalog below every template's required/optional "
        "blocks). `text` blocks are real documents: a passage written at the learner's "
        "level, a menu as a markdown table with plausible prices, a flyer, a listing — "
        "never scaffolded filler. `dialogue` learner turns are often empty (the learner "
        "fills them); write only the tutor lines and at most a learner line here and "
        "there.\n"
        "3. LANGUAGE: `text` and `dialogue` content is written in the TARGET LANGUAGE at "
        "the learner's level. The lesson `title`, `objectives`, and `reason` are in "
        "English (UI labels). The short `scenario` field, when set, is English too.\n"
        "4. CARDS: select 3-8 due cards BY ID whose vocabulary fits the lesson (never "
        "invent card content). The learner gets credit for understanding them and bonus "
        "credit for using them in context during the lesson.\n"
        "5. INTRO: `intro_line` opens the lesson in the target language — one warm, "
        "natural sentence that pulls the learner into the material, no lists.\n"
        "6. FRESHNESS: skip ideas a `session_lessons` entry already used; never "
        "re-propose something the learner declined."
    ),
)


@session_planner_agent.instructions
def inject_planner_deps(ctx: RunContext[PlannerDeps]) -> str:
    profile = ctx.deps["user_profile"]
    language = language_name(profile.get("target_language"))
    due_cards = ctx.deps.get("due_cards", [])
    transcript = ctx.deps.get("recent_transcript", [])
    ideas = "\n".join(f"- {m.get('speaker', '?')}: {m.get('text', '')}" for m in transcript) or (
        "(no recent turns captured — fall back to the profile only)"
    )
    history = "\n".join(
        f"- {lesson.get('status', '?')}: {lesson.get('title', '?')}"
        for lesson in ctx.deps.get("session_lessons", [])
    )
    idea = ctx.deps.get("idea", "")
    cards_text = (
        "\n".join(
            f"- [{card.get('id')}] {card.get('front', '')} → {card.get('back', '')}"
            for card in due_cards
        )
        or "(no cards currently due)"
    )
    return (
        f"TARGET LANGUAGE: {language}\n\n"
        f"USER PROFILE: {profile}\n\n"
        f"LEARNER'S REQUESTED IDEA: {idea or '(tutor-initiated)'}\n\n"
        f"RECENT CHAT (ground the lesson in this):\n{ideas}\n\n"
        f"LESSONS ALREADY PROPOSED/DONE THIS SESSION (do not repeat):\n{history or '(none)'}\n\n"
        f"DUE CARDS (select these by ID):\n{cards_text}\n\n"
        f"LESSON TEMPLATES (instantiate exactly one):\n{template_catalog()}\n\n"
        "AVAILABLE BLOCK PRIMITIVES: scenario(setting, learner_role, tutor_role, goal); "
        "text(title?, markdown); dialogue(turns: speaker tutor|learner, text — empty learner "
        "text = gap); questions(items); tasks(items: task, hint?); word_bank(items). "
        f"`lesson.template` must be one of: {template_ids()}."
    )
