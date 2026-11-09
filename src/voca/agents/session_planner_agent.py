from typing import TypedDict

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from services.llm import ollama_model


class PlannedCard(BaseModel):
    card_id: str
    content: str
    reason: str = Field(description="Why this card was selected for this session")

class SessionPlan(BaseModel):
    suggested_lesson_id: str | None = Field(description="The ID of the suggested lesson template")
    target_cards: list[PlannedCard]
    opening_hook: str = Field(description="A suggested opening hook for the tutor to use")

class PlannerDeps(TypedDict):
    user_id: str
    user_profile: dict
    due_cards: list[dict]
    available_lessons: list[dict]

session_planner_agent = Agent(
    model=ollama_model,
    deps_type=PlannerDeps,
    output_type=SessionPlan,
    system_prompt=(
        "You are a session planner for a language learning app. Your goal is to create a customized "
        "plan for the learner's next Spanish conversation.\n\n"
        "1. CARDS: Select 3-8 due cards. Favor the most overdue and those that fit the suggested lesson.\n"
        "2. LESSON: Pick a lesson template that matches the user's goals and level.\n"
        "3. HOOK: Write a warm, personal opening hook for the tutor, referencing the user's profile or past sessions.\n\n"
        "Ensure the laenr's current level and goals are considered."
    ),
)
