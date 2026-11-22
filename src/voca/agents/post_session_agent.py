from typing import NotRequired, TypedDict

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

from voca.services.languages import language_name
from voca.services.llm import voca_model

# NEW CARDS harvest rules: cards are born from need, not from completeness. Kept as a
# module constant so tests can assert the rules stay prompt-visible.
NEW_CARDS_RULES = (
    "Identify 0-5 new cards. An empty list is a good result when the learner used "
    "everything correctly and asked nothing — do not fill the list for its own sake. "
    "Propose a card only when at least one criterion holds:\n"
    "   (a) UNCERTAINTY — the learner asked what something means or how to say it "
    '("¿cómo se dice…?", "how do you say X", "what does X mean"), hesitated, '
    "restarted a sentence, or repeatedly self-corrected.\n"
    "   (b) INCORRECT USE — the tutor corrected the learner's word, form, or pattern "
    "(wrong word, gender, tense, agreement); the tutor's reformulation in the transcript "
    "is the signal.\n"
    "   (c) BETTER ALTERNATIVE — the learner's phrasing was understandable but awkward or "
    "unidiomatic, the tutor offered a more natural expression, or a phrase from the "
    "session plan would have been stronger than what the learner improvised.\n"
    "   Hard exclusions — never make a card for: words the learner used correctly and "
    "confidently; items the tutor merely used that the learner never engaged with "
    "(unless (c) applies); grammar the learner already produced correctly; anything "
    "whose front or back matches an EXISTING CARD.\n"
    "   Every card must quote the transcript line it came from in `source_sentence`; "
    "its `reason` must name the criterion that fired (a, b, or c) and quote the exact "
    "signal (the question, hesitation, or tutor reformulation). If the same item "
    "appears in several turns, create ONE card, not several.\n"
)


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
    # Recent card front/back pairs (no FSRS state): new cards must not duplicate them.
    existing_cards: NotRequired[list[dict]]
    target_language: NotRequired[str | None]
    # This session's lesson instances (completed/declined): informs the recap; the
    # analyst never re-grades lesson target cards (main.py filters them out already).
    lessons: NotRequired[list[dict]]


post_session_agent = Agent(
    model=voca_model,
    deps_type=PostSessionDeps,
    output_type=PostSessionResult,
    # See the planner: extra output retries for the rare schema slip.
    retries=3,
    instructions=(
        "You are a language learning analyst. Your job is to review a conversation transcript "
        "between a language tutor and a learner and extract valuable learning material. "
        "The session may have contained structured lessons (already graded elsewhere — never "
        "grade their target cards) alongside casual small talk; grade anything the lessons "
        "did not cover.\n\n"
        "1. NEW CARDS: "
        + NEW_CARDS_RULES
        + "2. GRADES: Grade every DUE card by ID as attempted or not_attempted, based on the "
        "transcript (recognition_pass when the learner understood it without producing it).\n"
        "3. RECAP: Create an encouraging and concise recap of the session, informed by the "
        "session's lessons (their summaries show how each went) and the small talk around "
        "them — do not invent metrics like minutes spoken. Return the recap as the structured "
        "object the schema defines (positives, key_corrections, next_time_preview), never as "
        "a plain string.\n"
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
    existing_cards_text = "\n".join(
        f"- {c.get('front', '')}: {c.get('back', '')}" for c in ctx.deps.get("existing_cards", [])
    )
    lessons = ctx.deps.get("lessons") or []
    lessons_text = "\n".join(
        f"- {lesson.get('status', '?')}: {(lesson.get('spec') or {}).get('title', '?')}"
        + (
            f" — summary: {(lesson.get('summary') or {}).get('headline', '')}"
            if lesson.get("summary")
            else ""
        )
        for lesson in lessons
    )
    return (
        f"TARGET LANGUAGE: {language}\n\n"
        f"SESSION TRANSCRIPT:\n{transcript_text}\n\n"
        f"DUE CARDS TO EVALUATE (grade by ID; lesson-covered cards already excluded):\n{due_cards_text}\n\n"
        f"EXISTING CARDS (the learner already has these — never create a card whose front "
        f"or back matches any of them):\n{existing_cards_text}\n\n"
        f"THIS SESSION'S LESSONS:\n{lessons_text or '(none — pure small-talk session)'}"
    )
