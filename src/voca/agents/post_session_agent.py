from typing import TypedDict

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from services.llm import ollama_model


# Response structure for the post-session agent
class CardCandidate(BaseModel):
    type: str = Field(description="Card type: 'word', 'phrase', 'correction', or 'grammar'")
    front: str = Field(description="The target (meaning, situation, or error)")
    back: str = Field(description="The correct word/phrase/pattern")
    source_sentence: str = Field(description="The original sentence from the transcript")
    reason: str = Field(description="Why this was selected as a card")

class SessionRecap(BaseModel):
    time_spoken: str
    lesson_completed: bool
    positives: list[str] = Field(description="Things the learner did well")
    key_corrections: list[str] = Field(description="Key corrections to remember")
    next_time_preview: str = Field(description="One-line preview of the next session")

class CardGrade(BaseModel):
    card_id: str
    outcome: str = Field(description="Outcome: 'strong_pass', 'pass', 'recognition_pass', 'miss', or 'not_attempted'")

class PostSessionResult(BaseModel):
    new_cards: list[CardCandidate]
    reviewed_cards: list[CardGrade]
    recap: SessionRecap
    profile_updates: dict = Field(description="Updated profile fields (goals, interests, level notes)")

class PostSessionDeps(TypedDict):
    user_id: str
    session_id: str
    transcript: list[dict]
    due_cards: list[dict]

post_session_agent = Agent(
    model=ollama_model,
    deps_type=PostSessionDeps,
    output_type=PostSessionResult,
    system_prompt=(
        "You are a language learning analyst. Your job is to review a conversation transcript "
        "between a Spanish tutor and a learner and extract valuable learning material.\n\n"
        "1. NEW CARDS: Identify 5-8 new cards. Prioritize items the learner struggled with, "
        "explicitly asked about, or which are critical for their level. Use the provided selection rules.\n"
        "2. RECAP: Create a encouraging and concise recap of the session.\n"
        "3. PROFILE: Suggest updates to the user's profile based on evidence in the transcript "
        "(e.g., newly mentioned interests, improved fluency)."
    ),
)
