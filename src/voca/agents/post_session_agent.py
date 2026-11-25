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


# The FSRS rubric: maps transcript evidence straight onto the FSRS statuses
# (via VOCA_RATING_MAP). Recall quality is part of the outcome definitions, so
# there is no separate recall/bonus scale anywhere in the product. Kept as a
# module constant so tests can assert the rubric stays prompt-visible.
FSRS_RUBRIC = (
    "Grade every DUE card by ID, from transcript evidence alone. One rubric maps "
    "what the learner did to the FSRS rating — recall is inside the outcomes, do "
    "not grade on any separate scale:\n"
    "   - 'strong_pass' (FSRS Easy): the learner produced the item correctly, "
    "unprompted, in a fluent and natural sentence.\n"
    "   - 'pass' (FSRS Good): the learner recalled or produced it correctly, but "
    "with visible effort — hesitation, a restart, a reformulation — or needed a "
    "gentle prompt and absorbed it.\n"
    "   - 'recognition_pass' (FSRS Easy): the learner did not produce the item, "
    "but clearly understood it in context — their reply reacted to it correctly "
    "(answering a question that used it, acting on the information). "
    "Comprehension counts as the recall this rating needs.\n"
    "   - 'miss' (FSRS Again): the learner tried and failed (wrong form, kept to "
    "the tutor's correction), asked what it means, or could not recall it at all.\n"
    "   - 'not_attempted': the item never genuinely came up — no production, no "
    "comprehension signal.\n"
    "   Strict rule: grade ONLY what the transcript shows. When in doubt between "
    "two outcomes, take the lower one.\n"
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
        description=(
            "Outcome from the FSRS rubric: 'strong_pass', 'pass', 'recognition_pass', "
            "'miss', or 'not_attempted'"
        )
    )
    evidence: str = Field(description="The transcript line that justifies the outcome")


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


post_session_agent = Agent(
    model=voca_model,
    deps_type=PostSessionDeps,
    output_type=PostSessionResult,
    # See the planner: extra output retries for the rare schema slip.
    retries=3,
    instructions=(
        "You are a language learning analyst. Your job is to review a conversation transcript "
        "between a language tutor and a learner and map it onto the learner's FSRS card "
        "statuses, plus extract valuable learning material.\n\n"
        "1. NEW CARDS: "
        + NEW_CARDS_RULES
        + "2. GRADES — THE FSRS RUBRIC: "
        + FSRS_RUBRIC
        + "3. RECAP: Write an encouraging and concise recap of the session — what was talked "
        "about, what the learner handled well and what needed help. Do not invent metrics "
        "like minutes spoken. Return the recap as the structured object the schema defines "
        "(positives, key_corrections, next_time_preview), never as a plain string.\n"
        "4. PROFILE: Suggest updates to the user's profile based on evidence in the transcript "
        "(e.g., newly mentioned interests, improved fluency). Leave fields you have no "
        "evidence for unset."
    ),
)


@post_session_agent.instructions
def post_session_instructions(ctx: RunContext[PostSessionDeps]) -> str:
    language = language_name(ctx.deps.get("target_language"))
    transcript_text = "\n".join(f"{m['speaker']}: {m['text']}" for m in ctx.deps["transcript"])
    due_cards_text = "\n".join(
        f"- [{c.get('id')}] {c.get('front', '')}: {c.get('back', '')}"
        for c in ctx.deps.get("due_cards", [])
    )
    existing_cards_text = "\n".join(
        f"- {c.get('front', '')}: {c.get('back', '')}" for c in ctx.deps.get("existing_cards", [])
    )
    return (
        f"TARGET LANGUAGE: {language}\n\n"
        f"SESSION TRANSCRIPT:\n{transcript_text}\n\n"
        f"DUE CARDS TO EVALUATE (grade every one by ID with the FSRS rubric):\n{due_cards_text}\n\n"
        f"EXISTING CARDS (the learner already has these — never create a card whose front "
        f"or back matches any of them):\n{existing_cards_text}"
    )
