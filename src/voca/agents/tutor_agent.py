"""The conversation tutor: small talk ⇄ lesson loop.

The backend owns the session's phase (derived from `sessions.lessons`); this
agent is the conversational layer on top of it. In small talk it chats and —
after enough turns or on request — formalizes a lesson idea with the
`propose_lesson` tool. Once a lesson is active it teaches the material and
closes it with `complete_lesson`. Tools do the state changes; this module only
converses and emits UI events into the request-scoped queue that `/chat` drains
into the SSE stream.
"""

import ast
import asyncio
import inspect
import json
import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any, NotRequired, TypedDict

from pydantic_ai import Agent, RunContext

from voca.services.languages import language_name
from voca.services.lesson_flow import (
    NUDGE_TURNS,
    PHASE_AWAITING_ACCEPT,
    PHASE_LESSON,
    PHASE_SMALL_TALK,
    guard_begin,
    guard_complete,
    guard_propose,
)
from voca.services.llm import voca_model

logger = logging.getLogger(__name__)


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
    if smalltalk_turns >= NUDGE_TURNS and not deps.get("pending_proposal"):
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


# --- Streaming tool-call leak capture -------------------------------------------------
#
# Streamed tool calls over Ollama's OpenAI-compat endpoint sometimes arrive as
# gemma's raw call syntax in plain content instead of parsed `tool_calls`
# deltas (verified live with gemma4:31b-cloud; non-streaming parses fine):
#   `call:propose_lesson{idea:<|"|>…<|"|>}` — optionally `<`-prefixed and often
#   suffixed with `<tool_call|>`. The pump recognizes these spans, hides them
#   from the visible chat, and executes the real tool.

TOOL_NAMES = ("propose_lesson", "begin_lesson", "complete_lesson")

_LEAK_START_RE = re.compile("(?:<)?call:((?:" + "|".join(TOOL_NAMES) + r"))")
_LEAK_CALL_TAGS = ("call:", "<tool_code>")


def parse_tool_leak(text: str):
    """Find a **complete** leaked tool call in buffered streamed text.

    Returns `(before_text, tool_name, args, consumed_end)` or None. An unterminated
    call is left in the buffer (None) so the closing brace/markup can arrive with a
    later delta; the pump keeps the leak's head hidden meanwhile. Recognizes both
    observed gemma shapes: `call:<name>{...}` (optionally `<`-prefixed and
    `<tool_call|>`-suffixed) and `<tool_code>name(idea="...")</tool_code>`.
    """
    return _parse_call_leak(text) or _parse_tool_code_leak(text)


def _parse_call_leak(text: str):
    match = _LEAK_START_RE.search(text)
    if not match:
        return None
    before = text[: match.start()]
    name = match.group(1)
    from_idx = match.end()
    brace_start = text.find("{", from_idx)
    close_m = re.search(r"\s*/?>", text[from_idx:])
    if brace_start != -1 and (close_m is None or brace_start < from_idx + close_m.start()):
        # brace-args shape: `call:<name>{...}` (JSON-ish, gemma quote tokens)
        args_start = brace_start
        depth = 0
        args_end = -1
        for idx in range(args_start, len(text)):
            ch = text[idx]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    args_end = idx
                    break
        if args_end == -1:
            return None
        args_str = text[args_start : args_end + 1]
        after = text[args_end + 1 :]
        trailing = re.match(r"\s*>(\s*<tool_call\|>)?", after)
        consumed = args_end + 1 + (trailing.end() if trailing else 0)
        return before, name, _parse_leak_args(args_str), consumed
    elif close_m is not None:
        # attribute shape: `<call:<name> idea="..."/>` (args until the close)
        args_str = text[from_idx : from_idx + close_m.start()]
        consumed = from_idx + close_m.end()
        return before, name, _parse_leak_args(args_str), consumed
    return None  # the call's closing markup is still streaming
    args_str = text[args_start : args_end + 1]
    after = text[args_end + 1 :]
    # Trailing gemma markup (`>` and/or `<tool_call|>`) may arrive one delta later.
    trailing = re.match(r"\s*>(\s*<tool_call\|>)?", after)
    consumed = args_end + 1 + (trailing.end() if trailing else 0)
    return before, name, _parse_leak_args(args_str), consumed


def _parse_tool_code_leak(text: str):
    """`<tool_code>propose_lesson(idea="...")</tool_code>` — code-style leak."""
    start = text.find("<tool_code>")
    if start == -1:
        return None
    before = text[:start]
    from_idx = start + len("<tool_code>")
    call_match = re.match(r"\s*(?:(?:</)?<?\s*call:?\s*)?(\w+)\s*\(", text[from_idx:])
    if not call_match:
        return None
    name = call_match.group(1)
    if name not in TOOL_NAMES:
        # Not one of ours: the pump's passthrough cap flushes it as plain text.
        return None
    args_start = from_idx + call_match.end()
    depth = 0
    args_end = -1
    for idx in range(args_start - 1, len(text)):
        ch = text[idx]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                args_end = idx
                break
    if args_end == -1:
        return None  # arguments still streaming
    args_str = text[args_start:args_end]
    close_idx = text.find("</tool_code>", args_end)
    if close_idx == -1:
        return None  # closing tag still streaming
    consumed = close_idx + len("</tool_code>")
    return before, name, _parse_leak_args(args_str), consumed


def _parse_leak_args(args_str: str) -> dict[str, Any]:
    """Best-effort arguments for a leaked call, tolerant of the observed shapes:
    proper JSON, gemma's `{idea:<|"|>TEXT<|"|>}`, and code-style kwargs."""
    cleaned = args_str.replace('<|"|>', '"').replace("<|'|>", "'").strip()
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else {"idea": cleaned}
    except json.JSONDecodeError:
        pass
    bare = cleaned.strip("{}").strip()
    # gemma's raw shape: `idea:"TEXT"` / `idea:TEXT` (token quotes normalized above).
    raw = re.search(r"(?i)idea\s*[\":]\s*(.*)$", bare)
    if raw:
        value = raw.group(1).strip().strip('"').strip()
        return {"idea": value} if value else {}
    # Python-style kwargs / bare quotes (the code-style leak shape).
    try:
        call = ast.parse(f"f({bare})").body[0].value
        args: dict[str, Any] = {}
        for keyword in call.keywords:
            args[keyword.arg] = ast.literal_eval(keyword.value)
        for positional in call.args:
            args.setdefault("idea", ast.literal_eval(positional))
        return args
    except Exception:  # noqa: BLE001 - weird shapes fall back to the quoted span
        pass
    match = re.search(r'"([^"]+)"|\(([^)]+)\)', bare)
    if match:
        return {"idea": match.group(1) or match.group(2)}
    return {"idea": bare} if bare else {}


async def execute_leaked(name: str, args: dict[str, Any], deps: TutorDeps) -> None:
    """Run the real tool for a leaked call; its ack is discarded (the model
    already wrote its own continuation text around the call)."""
    tool = globals().get(name)
    if tool is None:
        return
    try:
        if "idea" in inspect.signature(tool).parameters:
            await tool(_LeakRunContext(deps), idea=args.get("idea", ""))
        else:
            await tool(_LeakRunContext(deps))
    except Exception:  # noqa: BLE001 - a failed leak capture must not kill the stream
        logger.exception("leaked tool call execution failed")


class _LeakRunContext:
    """The slice of pydantic-ai's RunContext the tools actually read."""

    def __init__(self, deps: TutorDeps) -> None:
        self.deps = deps
