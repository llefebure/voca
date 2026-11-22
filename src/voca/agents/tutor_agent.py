"""The conversation tutor: small talk ⇄ lesson loop.

The backend owns the session's phase (derived from `sessions.lessons`); this
agent is the conversational layer on top of it. In small talk it chats and —
after enough turns or on request — formalizes a lesson idea with the
`propose_lesson` tool. Once a lesson is active it teaches the material and
closes it with `complete_lesson`. Tools do the state changes; this module only
converses and emits UI events into the request-scoped queue that `/chat` drains
into the SSE stream.
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import NotRequired, TypedDict

from pydantic_ai import Agent, RunContext

from voca.services.languages import language_name
from voca.services.lesson_flow import (
    PHASE_AWAITING_ACCEPT,
    PHASE_LESSON,
    PHASE_SMALL_TALK,
    guard_begin,
    guard_complete,
    guard_propose,
)
from voca.services.llm import voca_model

NudgeTurn = 4


class TutorDeps(TypedDict):
    user_id: str
    session_id: str
    user_profile: dict
    # Phase derived from the session's lessons array in `lesson_flow`.
    phase: str
    active_lesson: dict | None
    pending_proposal: dict | None
    # The full lessons array (done/declined/active/proposed) for context + guards.
    session_lessons: list[dict]
    # Compact due cards [{"id", "front", "back"}] — woven in during small talk.
    due_cards: NotRequired[list[dict]]
    smalltalk_turns: int
    # SSE side-channel: tools push {"type": "status"|"event", ...}; /chat drains it.
    events: asyncio.Queue
    # --- main.py-provided operations (single source of truth for DB writes) ---
    run_planner: Callable[[str], Awaitable[dict | None]]
    activate_proposal: Callable[[], Awaitable[dict | None]]
    grade_and_complete: Callable[[], Awaitable[dict | None]]
    record_event: Callable[[str, dict], Awaitable[None]]


tutor_agent = Agent(
    model=voca_model,
    deps_type=TutorDeps,
    tools=[],
)


@tutor_agent.instructions
def tutor_system_prompt(ctx: RunContext[TutorDeps]) -> str:
    deps = ctx.deps
    profile = deps.get("user_profile", {})
    language = language_name(profile.get("target_language"))
    goals = profile.get("goals", f"learn {language}")
    level = profile.get("level", "Intermediate (B1)")
    interests = profile.get("interests", "general topics")
    phase = deps.get("phase", PHASE_SMALL_TALK)
    smalltalk_turns = deps.get("smalltalk_turns", 0)

    base = (
        f"You are a friendly and encouraging {language} language tutor. "
        f"Your student's current level is {level}. Their goals are: {goals}. "
        f"Their interests include: {interests}.\n\n"
        f"Converse primarily in {language}; use English only for necessary explanations or "
        "when the user asks 'How do I say…'. Keep your turns short and always end with "
        "something that invites the learner to speak. Your replies are read aloud: no "
        "bulleted lists, no numbered lists, no markdown formatting, no 'Is there anything "
        "else?' — be a human teacher, not a help desk. Recast mistakes naturally; correct "
        f"significantly wrong forms briefly, in {language} or English.\n"
    )

    if phase == PHASE_LESSON:
        phase_block = _lesson_phase_block(deps)
    elif phase == PHASE_AWAITING_ACCEPT:
        phase_block = _awaiting_phase_block(deps)
    else:
        phase_block = _small_talk_block(deps, smalltalk_turns)

    history_block = _lessons_history_block(deps)
    return base + phase_block + history_block


def _small_talk_block(deps: TutorDeps, smalltalk_turns: int) -> str:
    parts = [
        "MODE: casual conversation. Unstructured, easygoing small talk — about their day, "
        "the weather, work, what they read, plans, whatever comes up.\n"
        "1. GREETINGS: when the learner greets you, answer like a friend — 'Hi, how are "
        "you today?' — and ask one simple follow-up. NEVER attach lesson offers, example "
        "phrases, or 'you can say…' scaffolding to a greeting or small-talk turns.\n"
        "2. DO NOT STRUCTURE: no agenda, no lesson plan, no mini-tutorial unless asked for "
        "a word or explanation.\n"
        "3. REVIEW WORDS: work the due cards below in naturally when the topic touches "
        "them; a used-in-context card counts extra for the learner — mention it warmly if "
        "they use one well.\n",
    ]
    if smalltalk_turns >= NudgeTurn and not deps.get("pending_proposal"):
        parts.append(
            "NUDGE (IMPORTANT): it is now time to offer a lesson — the learner is settled "
            "into casual chat. In THIS reply you must: (1) name ONE concrete lesson idea "
            "clearly tied to what they just talked about, and (2) call `propose_lesson` "
            "with it as the idea (when they gave a lesson idea themselves, use exactly "
            "that). Do not just ask a follow-up question instead. After the tool result, "
            "invite them to have a look at the card — one short line. If they decline, "
            "stay in casual chat and do not re-offer the same idea again.\n"
        )
    due = deps.get("due_cards", [])
    if due:
        parts.append("REVIEW CARDS (weave in when natural):\n" + _cards_text(due))
    return "".join(parts)


def _awaiting_phase_block(deps: TutorDeps) -> str:
    proposal = deps.get("pending_proposal") or {}
    title = ((proposal.get("spec") or {}).get("title")) or "a lesson"
    reason = proposal.get("reason", "")
    return (
        "MODE: a lesson proposal is waiting for the learner's answer (the proposal card "
        "is on their screen — never restate its contents in chat).\n"
        "1. If the learner agrees (their words, any language), call `begin_lesson` right "
        "away; your next reply opens the lesson.\n"
        "2. If they decline, acknowledge it warmly, call nothing, and stay in casual "
        "chat. A different, better-shaped idea can come later.\n"
        "3. Remind at most once, briefly, if they drift off without answering; do not "
        f"pressure.\n"
        f"THE PENDING PROPOSAL: {title}" + (f" — {reason}" if reason else "") + "\n"
    )


def _lesson_phase_block(deps: TutorDeps) -> str:
    lesson = deps.get("active_lesson") or {}
    spec = lesson.get("spec", {})
    lines = [
        "MODE: formal lesson in progress (visually on the learner's screen — talk around "
        "the material, never dump its contents into chat).\n"
        "1. Follow the lesson's material and phase outline below, briskly. Keep every "
        "turn short and pointed at the current step.\n"
        "2. Target cards: bring them up inside the exercise; when the learner clearly "
        "understands one, say so; when they use one correctly in context, praise it "
        "specifically. Credit is recorded when the lesson closes.\n"
        "3. WRAP-UP: when the objectives are covered, or the learner seems done or asks "
        "to move on, call `complete_lesson`. After it finishes: one warm, specific "
        "sign-off line, then drop back into casual chat — no re-greeting, no repeating "
        "the lesson, and follow the learner's lead. If the learner proposes another "
        "lesson idea, that's welcome: chat on, and propose it via `propose_lesson`.\n",
    ]
    lines.append(
        f"ACTIVE LESSON: {spec.get('title', 'Untitled')} "
        f"({spec.get('template', 'template')}, ~{spec.get('minutes') or '5-10'} min)\n"
        f"- Steps: {spec.get('scenario') or spec.get('topic') or 'see material'}\n"
    )
    objectives = spec.get("objectives") or []
    if objectives:
        lines.append("- Objectives: " + "; ".join(objectives) + "\n")
    if lesson.get("intro_line"):
        lines.append(f"- Opening line (reword freely): {lesson['intro_line']}\n")
    for card in lesson.get("target_cards") or []:
        front, back = card.get("front", ""), card.get("back", "")
        if front or back:
            lines.append(f"- Target to weave in: {front} → {back}\n")
    materials = lesson.get("material") or []
    if materials:
        lines.append("- Material on learner's screen:\n")
        for block in materials:
            lines.append(f"  * {str(block.get('type', '?')).upper()}\n")
            text = block.get("markdown")
            if text:
                lines.append("    " + text.replace("\n", "\n    ") + "\n")
            elif block.get("setting"):
                lines.append(
                    f"    setting={block['setting']}; learner={block.get('learner_role')}; "
                    f"tutor={block.get('tutor_role')}; goal={block.get('goal')}\n"
                )
            elif block.get("turns"):
                lines.append("    (scripted exchange with learner gaps)\n")
            elif block.get("items"):
                lines.append("    " + "; ".join(str(i) for i in block["items"]) + "\n")
    return "".join(lines)


def _lessons_history_block(deps: TutorDeps) -> str:
    done: list[str] = []
    for lesson in deps.get("session_lessons", []):
        status = lesson.get("status")
        if status in ("completed", "declined"):
            spec = lesson.get("spec") or {}
            done.append(f"- {status.upper()}: {spec.get('title', 'Untitled')}")
    if not done:
        return ""
    return (
        "THIS SESSION'S LESSONS SO FAR (never repeat their ideas; declining a different "
        "shape after a DECLINE):\n" + "\n".join(done) + "\n"
    )


def _cards_text(cards: list[dict]) -> str:
    return "\n".join(f"- {card.get('front', '')} ({card.get('back', '')})" for card in cards) + "\n"


# --- Tools ---------------------------------------------------------------------------


async def _push_status(deps: TutorDeps, text: str) -> None:
    await deps["events"].put({"type": "status", "text": text})


async def _push_event(deps: TutorDeps, kind: str, data: dict) -> None:
    await deps["events"].put({"type": "event", "kind": kind, "data": data})
    await deps["record_event"](kind, data)


@tutor_agent.tool
async def propose_lesson(ctx: RunContext[TutorDeps], idea: str = "") -> str:
    """Formalize a lesson idea into a proposal card the learner can accept.

    Call when offering a structured lesson (on your own nudge or the learner's
    request). `idea` is a concrete one-line description of the lesson.
    """
    deps = ctx.deps
    if refusal := guard_propose(deps.get("session_lessons", [])):
        return refusal
    if deps.get("run_planner") is None:
        return "(planner unavailable: continue the conversation casually, try again later)"
    await _push_status(deps, "Designing your lesson…")
    lesson = await deps["run_planner"](idea)
    if lesson is None:
        return "(planner unavailable: continue the conversation casually, try again later)"
    await _push_event(deps, "proposal_ready", {"lesson": lesson})
    return (
        "The proposal card is on screen. Invite the learner to have a look in one short "
        "line — do NOT restate the plan or its contents."
    )


@tutor_agent.tool
async def begin_lesson(ctx: RunContext[TutorDeps]) -> str:
    """Start the lesson the learner just agreed to (a proposal is pending)."""
    deps = ctx.deps
    if refusal := guard_begin(deps.get("session_lessons", [])):
        return refusal
    if deps.get("activate_proposal") is None:
        return "(lesson activation unavailable: continue the conversation naturally)"
    await _push_status(deps, "Starting your lesson…")
    lesson = await deps["activate_proposal"]()
    if lesson is None:
        return "(no pending proposal remained: continue the conversation naturally)"
    await _push_event(deps, "lesson_started", {"lesson": lesson})
    return (
        "The lesson is live and its material is on the learner's screen. Open it now "
        "with the lesson's opening line, then run the first step."
    )


@tutor_agent.tool
async def complete_lesson(ctx: RunContext[TutorDeps]) -> str:
    """Close the active lesson: record grades and return to casual chat."""
    deps = ctx.deps
    if refusal := guard_complete(deps.get("session_lessons", [])):
        return refusal
    if deps.get("grade_and_complete") is None:
        return "(grading unavailable: close the lesson verbally and continue casually)"
    await _push_status(deps, "Wrapping up your lesson…")
    lesson = await deps["grade_and_complete"]()
    if lesson is None:
        return "(grading failed: close the lesson verbally and continue casually)"
    await _push_event(deps, "lesson_completed", {"lesson": lesson})
    return (
        "Lesson recorded and credit noted. Sign off warmly with one specific, earned point "
        "of praise, then continue as casual chat — no re-greeting."
    )
