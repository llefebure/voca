from typing import NotRequired, TypedDict

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

from voca.services.languages import language_name
from voca.services.lesson_templates import template_catalog, template_ids
from voca.services.llm import planning_model


class LessonSpec(BaseModel):
    template: str = Field(description=f"Id of the lesson template to use, one of: {template_ids()}")
    topic: str = Field(description="Concrete topic for this learner's session")
    scenario: str | None = Field(
        default=None,
        description="Setting and roles; set this for role_play (e.g. 'customer buying fruit')",
    )
    objectives: list[str] = Field(description="2-4 things the learner will practice this session")


class SessionPlan(BaseModel):
    lesson: LessonSpec
    card_ids: list[str] = Field(
        description="IDs of 3-8 due cards selected for this session (no card content)"
    )
    opening_hook: str = Field(description="A suggested opening hook for the tutor to use")


class PlannerDeps(TypedDict):
    user_id: str
    user_profile: dict
    # Compact card rows: {"id", "front", "back"} — no FSRS state or other columns.
    due_cards: NotRequired[list[dict]]


session_planner_agent = Agent(
    model=planning_model,
    deps_type=PlannerDeps,
    output_type=SessionPlan,
    # Cheap insurance: the validation-feedback retry loop recovers the rare
    # schema slip even on a capable model.
    retries=3,
    instructions=(
        "You are a session planner for a language learning app. Your goal is to create a "
        "customized plan for the learner's next conversation in their target language.\n\n"
        "1. CARDS: Select 3-8 due cards BY ID (never invent card content). Favor the most "
        "relevant to the learner's level, goals, and the lesson you choose.\n"
        "2. LESSON: Pick one lesson template and instantiate it for this learner: choose a "
        "concrete topic that fits their profile, and write 2-4 focused objectives.\n"
        "3. HOOK: Write a warm, personal opening hook for the tutor, referencing the user's "
        "profile or past sessions.\n\n"
        "Ensure the learner's current level and goals are considered."
    ),
)


@session_planner_agent.instructions
def inject_planner_deps(ctx: RunContext[PlannerDeps]) -> str:
    profile = ctx.deps["user_profile"]
    language = language_name(profile.get("target_language"))
    due_cards = ctx.deps.get("due_cards", [])

    cards_text = "\n".join(
        f"- [{card.get('id')}] {card.get('front', '')} → {card.get('back', '')}"
        for card in due_cards
    )
    return (
        f"TARGET LANGUAGE: {language}\n\n"
        f"USER PROFILE: {profile}\n\n"
        f"DUE CARDS (select these by ID):\n{cards_text}\n\n"
        f"LESSON TEMPLATES (instantiate one):\n{template_catalog()}"
    )
