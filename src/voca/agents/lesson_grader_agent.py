"""Lesson grader: credits review-card use at the end of a lesson.

Runs inside the tutor's `complete_lesson` tool. Grades every target card from
the lesson's transcript slice: recognition (the learner understood it when Voca
brought it up) and, especially, in-context production — the "bonus" that outranks
recognition. Also writes a short per-lesson summary the UI shows as the
lesson-completion card.
"""

from typing import NotRequired, TypedDict

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

from voca.services.languages import language_name
from voca.services.llm import voca_model


class CardGrade(BaseModel):
    card_id: str
    outcome: str = Field(
        description=(
            "'strong_pass' (correct in-context production, effortless), 'pass' (correct "
            "in-context production with effort), 'recognition_pass' (understood when "
            "brought up, never produced), or 'miss' (brought up and not understood)"
        )
    )
    evidence: str = Field(description="The transcript moment this grade comes from")
    bonus_use: bool = Field(
        default=False,
        description="True only for pass/strong_pass: the learner PRODUCED it correctly in context",
    )


class LessonSummary(BaseModel):
    headline: str = Field(description="One vivid sentence about how the lesson went (English)")
    positives: list[str] = Field(description="2-4 specific things the learner did well")
    key_phrases: list[str] = Field(description="2-4 phrases worth remembering (target language)")


class LessonGrades(BaseModel):
    grades: list[CardGrade]
    summary: LessonSummary
    bonus_uses: list[str] = Field(
        description="Sentences from the learner that used a target phrase correctly in context"
    )


class GraderDeps(TypedDict):
    language: NotRequired[str | None]
    lesson: dict  # the active lesson instance (spec, material, target_cards)
    transcript: list[dict]  # the lesson's transcript slice: [{"speaker", "text"}]


lesson_grader_agent = Agent(
    model=voca_model,
    deps_type=GraderDeps,
    output_type=LessonGrades,
    retries=3,
    instructions=(
        "You grade language-learning exercise sessions against their target review cards. "
        "Read the lesson (its spec and material show exactly what the tutor presented) and "
        "the transcript of the exercise that followed.\n\n"
        "1. GRADE every target card. Recognition and production are credited separately:\n"
        "   - The learner understood the target phrase when the tutor/material brought it "
        "up (answered a question about it, reacted appropriately, did the dialogue gap) "
        "-> recognition_pass.\n"
        "   - The learner PRODUCED the phrase itself, correctly and in context, -> pass; "
        "effortless and natural -> strong_pass (set bonus_use=true).\n"
        "   - Brought up but not understood or misused -> miss.\n"
        "   - Never surfaced in the lesson at all -> omit it from `grades` entirely.\n"
        "   Grade on the transcript's actual evidence and quote the moment in `evidence`; "
        "never grade from generosity. `bonus_uses` quotes the learner's own best "
        "sentences, one per production use of a distinct card.\n"
        "2. SUMMARIZE the lesson in the summary: encouraging, concrete, no invented "
        "metrics (no minutes spoken, no scores), at most 2-3 sentences."
    ),
)


@lesson_grader_agent.instructions
def inject_grader_deps(ctx: RunContext[GraderDeps]) -> str:
    language = language_name(ctx.deps.get("language"))
    lesson = ctx.deps["lesson"]
    spec = lesson.get("spec", {})
    targets = "\n".join(
        f"- [{c.get('id')}] {c.get('front', '')} → {c.get('back', '')}"
        for c in lesson.get("target_cards", [])
    )
    material_text = "; ".join(
        f"{b.get('type')}" + (f": {b.get('title')}" if b.get("title") else "")
        for b in lesson.get("material", [])
    )
    transcript_text = "\n".join(
        f"{m.get('speaker', '?')}: {m.get('text', '')}" for m in ctx.deps["transcript"]
    )
    return (
        f"TARGET LANGUAGE: {language}\n\n"
        f"LESSON: template={spec.get('template', 'n/a')}; title={spec.get('title', 'n/a')}; "
        f"topic={spec.get('topic', 'n/a')}; scenario={spec.get('scenario', 'n/a')}; "
        f"material=[{material_text}]\n\n"
        f"TARGET CARDS (grade exactly these):\n{targets or '(none)'}\n\n"
        f"LESSON TRANSCRIPT:\n{transcript_text}"
    )
