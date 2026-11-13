from typing import NotRequired, TypedDict

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

from voca.services.languages import language_name
from voca.services.llm import planning_model


# Response structure for the post-session agent
class CardCandidate(BaseModel):
    type: str = Field(description="Card type: 'word', 'phrase', 'correction', or 'grammar'")
    front: str = Field(description="The target (meaning, situation, or error)")
    back: str = Field(description="The correct word/phrase/pattern")
    source_sentence: str = Field(description="The original sentence from the transcript")
    reason: str = Field(description="Why this was selected as a card")


class SessionRecap(BaseModel):
    positives: list[str] = Field(description="Things the learner did well")
    key_corrections: list[str] = Field(description="Key corrections to remember")
    next_time_preview: str = Field(description="One-line preview of the next session")


class CardGrade(BaseModel):
    card_id: str
    outcome: str = Field(
        description="Outcome: 'strong_pass', 'pass', 'recognition_pass', 'miss', or 'not_attempted'"
    )


class ProfileUpdates(BaseModel):
    """Profile fields worth writing back; unset fields are not persisted."""

    goals: str | None = Field(default=None, description="Updated goals, if evident")
    interests: str | None = Field(default=None, description="Interests newly evident this session")
    level: str | None = Field(default=None, description="Updated level estimate (A1-C2)")


class PostSessionResult(BaseModel):
    new_cards: list[CardCandidate]
    reviewed_cards: list[CardGrade]
    recap: SessionRecap
    profile_updates: ProfileUpdates


class PostSessionDeps(TypedDict):
    user_id: str
    session_id: str
    transcript: list[dict]
    # Compact card rows: {"id", "front", "back"} — no FSRS state or other columns.
    due_cards: NotRequired[list[dict]]
    target_language: NotRequired[str | None]
    session_plan: NotRequired[dict | None]


post_session_agent = Agent(
    model=planning_model,
    deps_type=PostSessionDeps,
    output_type=PostSessionResult,
    # See the planner: extra output retries for the rare schema slip.
    retries=3,
    instructions=(
        "You are a language learning analyst. Your job is to review a conversation transcript "
        "between a language tutor and a learner and extract valuable learning material.\n\n"
        "1. NEW CARDS: Identify 5-8 new cards. Prioritize items the learner struggled with, "
        "explicitly asked about, or which are critical for their level. "
        "Use the provided selection rules.\n"
        "2. GRADES: Grade every due card by ID as attempted or not_attempted, based on the "
        "transcript (recognition_pass when the learner understood it without producing it).\n"
        "3. RECAP: Create an encouraging and concise recap of the session, informed by the "
        "session plan (its objectives and lesson) — do not invent metrics like minutes "
        "spoken.\n"
        "4. PROFILE: Suggest updates to the user's profile based on evidence in the transcript "
        "(e.g., newly mentioned interests, improved fluency). Leave fields you have no "
        "evidence for unset."
    ),
)


@post_session_agent.instructions
def inject_post_session_deps(ctx: RunContext[PostSessionDeps]) -> str:
    language = language_name(ctx.deps.get("target_language"))
    transcript_text = "\n".join(f"{m['speaker']}: {m['text']}" for m in ctx.deps["transcript"])
    due_cards_text = "\n".join(
        f"- [{c.get('id')}] {c.get('front', '')}: {c.get('back', '')}"
        for c in ctx.deps.get("due_cards", [])
    )
    plan = ctx.deps.get("session_plan") or {}
    lesson = plan.get("lesson") or {}
    plan_text = (
        f"template={lesson.get('template', 'n/a')}; topic={lesson.get('topic', 'n/a')}; "
        f"objectives={' | '.join(lesson.get('objectives') or []) or 'n/a'}"
    )
    return (
        f"TARGET LANGUAGE: {language}\n\n"
        f"SESSION TRANSCRIPT:\n{transcript_text}\n\n"
        f"DUE CARDS TO EVALUATE (grade by ID):\n{due_cards_text}\n\n"
        f"SESSION PLAN: {plan_text}"
    )
