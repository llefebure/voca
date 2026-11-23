"""The conversation tutor: one continuous chat with a canvas tool.

The tutor converses in the target language; when structured content would help
(a menu, a schedule, a dialogue script, practice questions), it calls
`show_panel` and the UI pops a canvas panel on the right. There is no session
planner, no lesson lifecycle, and no phase — the agent is the only mover. Tools
emit UI events into the request-scoped queue that `/chat` drains into the SSE
stream and persist them as transcript payload rows.
"""

import ast
import inspect
import json
import logging
import re
import uuid
from asyncio import Queue
from collections.abc import Awaitable, Callable
from typing import Any, NotRequired, TypedDict

from pydantic_ai import Agent, RunContext

from voca.services.languages import language_name
from voca.services.llm import voca_model
from voca.services.panel_content import BLOCK_ADAPTER, normalize_blocks

logger = logging.getLogger(__name__)

# A panel holds at most this many validated blocks (content, not a textbook).
MAX_PANEL_BLOCKS = 8


class TutorDeps(TypedDict):
    user_id: str
    session_id: str
    user_profile: dict
    # Compact due cards [{"id", "front", "back"}] — woven in when natural.
    due_cards: NotRequired[list[dict]]
    # SSE side-channel: tools push {"type": "status"|"event", ...}; /chat drains it.
    events: Queue
    # ID of the panel currently on the learner's screen (mutations by the tools).
    current_panel_id: NotRequired[str]
    # main.py-provided persistence (single source of truth for DB writes).
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

    parts = [
        f"You are a friendly and encouraging {language} language tutor. "
        f"Your student's current level is {level}. Their goals are: {goals}. "
        f"Their interests include: {interests}.\n\n",
        "Converse primarily in "
        + language
        + "; use English only for necessary explanations or when the user asks "
        "'How do I say…'. Keep your turns short and always end with something that "
        "invites the learner to speak. Your replies are read aloud: no bulleted "
        "lists, no numbered lists, no markdown formatting, no 'Is there anything "
        "else?' — be a human teacher, not a help desk. Recast mistakes naturally; "
        f"correct significantly wrong forms briefly, in {language} or English.\n\n",
        "MODE: casual conversation. Unstructured, easygoing chat — about their day, "
        "the weather, work, what they read, plans, whatever comes up. When the "
        "learner greets you, answer like a friend and ask one simple follow-up. "
        "NEVER attach example phrases or 'you can say…' scaffolding to a greeting "
        "or small-talk turns.\n\n",
        "REVIEW WORDS: work the due cards below in naturally when the topic touches "
        "them; mention it warmly if the learner uses one well.\n\n",
        "SIDE PANEL: you have a canvas panel on the right of the learner's screen "
        "(they see it as a split view next to your chat). Use `show_panel` whenever "
        "structured content genuinely helps the conversation — a menu you are "
        "role-playing from, an opening-hours table, a dialogue script to study, "
        "comprehension questions, a word bank, practice tasks. Keep the panel's "
        "content OUT of your chat turns: point at it ('look at the menu on the "
        "right') and ask about it. When the content changes materially, show a NEW "
        "panel (it replaces the old); when the learner asks you to remove or close "
        "the panel, or the content is clearly no longer useful, you MUST call "
        "`hide_panel` — never merely SAY you removed it. Do not stack a panel on "
        "small talk that does not need one.\n",
    ]
    due = deps.get("due_cards", [])
    if due:
        parts.append("REVIEW CARDS (weave in when natural):\n" + _cards_text(due))
    return "".join(parts)


def _cards_text(cards: list[dict]) -> str:
    return "\n".join(f"- {card.get('front', '')} ({card.get('back', '')})" for card in cards) + "\n"


# --- Tools ---------------------------------------------------------------------------


async def _push_status(deps: TutorDeps, text: str) -> None:
    await deps["events"].put({"type": "status", "text": text})


async def _push_event(deps: TutorDeps, kind: str, data: dict) -> None:
    await deps["events"].put({"type": "event", "kind": kind, "data": data})
    record_event = deps.get("record_event")
    if record_event is not None:
        await record_event(kind, data)


@tutor_agent.tool
async def show_panel(ctx: RunContext[TutorDeps], title: str, blocks: list[dict[str, Any]]) -> str:
    """Show structured content on the learner's side panel (canvas).

    Call whenever visual content helps the conversation: a menu, a flyer, a
    schedule table, a dialogue script, questions, word banks, or practice
    tasks. `title` is a short display heading; `blocks` is a list of typed
    content blocks. Each block is an object with a `type` of:

    - scenario: {"type": "scenario", "setting": where, "learner_role": …,
      "tutor_role": …, "goal": what success looks like}
    - text: {"type": "text", "markdown": "…"} — paragraphs/lists/tables; a
      menu or flyer is a markdown table here; optional "title"
    - dialogue: {"type": "dialogue", "turns": [{"speaker": "tutor"|"learner",
      "text": "…"}]} — empty learner text marks a gap the learner fills
    - questions: {"type": "questions", "items": ["question", …]}
    - tasks: {"type": "tasks", "items": [{"task": "…", "hint": optional}]}
    - word_bank: {"type": "word_bank", "items": ["term", …]}

    A new call replaces the panel that is showing.
    """
    deps = ctx.deps
    await _push_status(deps, "Preparing your panel…")
    panel = build_panel(title, blocks)
    if panel is None:
        return (
            "(No valid content blocks: keep each block tagged with its type "
            "(scenario/text/dialogue/questions/tasks/word_bank) and the fields "
            "described. Fix the blocks and call show_panel again, or continue "
            "in chat.)"
        )
    deps["current_panel_id"] = panel["id"]
    await _push_event(deps, "panel_shown", {"panel": panel})
    return (
        "The panel is on the learner's screen (right side). Do not repeat its "
        "contents in chat — point at it and converse about it."
    )


@tutor_agent.tool
async def hide_panel(ctx: RunContext[TutorDeps]) -> str:
    """Close the panel that is currently showing."""
    deps = ctx.deps
    # Panel state lives in the UI's event walk (per-turn deps cannot track it),
    # so hiding always pushes; an empty id means "whatever is showing".
    deps["current_panel_id"] = None
    await _push_event(deps, "panel_hidden", {"panel_id": ""})
    return "The panel is hidden. Continue the conversation."


def build_panel(title: str, blocks: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Validate a tool call's panel payload; None when nothing usable remains.

    Blocks are normalized (untagged/aliased shapes coerced) and validated one
    by one; invalid ones are dropped. A panel keeps at most
    `MAX_PANEL_BLOCKS` blocks and needs at least one.
    """
    normalized = normalize_blocks(blocks if isinstance(blocks, list) else [])
    kept: list[dict[str, Any]] = []
    for block in normalized:
        if len(kept) >= MAX_PANEL_BLOCKS:
            break
        try:
            validated = BLOCK_ADAPTER.validate_python(block, strict=False)
        except Exception:  # noqa: BLE001 - one bad block must not sink the panel
            continue
        kept.append(validated.model_dump(mode="json", exclude_none=True))
    if not kept:
        return None
    clean_title = (title or "").strip()
    return {
        "id": f"panel-{uuid.uuid4().hex[:12]}",
        "title": clean_title or "Panel",
        "blocks": kept,
    }


# --- Streaming tool-call leak capture -------------------------------------------------
#
# Streamed tool calls over Ollama's OpenAI-compat endpoint sometimes arrive as
# gemma's raw call syntax in plain content instead of parsed `tool_calls`
# deltas (verified live with gemma4:31b-cloud; non-streaming parses fine):
#   `call:show_panel{title:<|"|>…<|"|>, blocks:[…]}` — optionally `<`-prefixed
# and often suffixed with `<tool_call|>`. The pump recognizes these spans,
# hides them from the visible chat, and executes the real tool.

TOOL_NAMES = ("show_panel", "hide_panel")

_LEAK_START_RE = re.compile("(?:<)?call:((?:" + "|".join(TOOL_NAMES) + r"))")


def parse_tool_leak(text: str):
    """Find a **complete** leaked tool call in buffered streamed text.

    Returns `(before_text, tool_name, args, consumed_end)` or None. An unterminated
    call is left in the buffer (None) so the closing brace/markup can arrive with a
    later delta; the pump keeps the leak's head hidden meanwhile. Recognizes both
    observed gemma shapes: `call:<name>{...}` (optionally `<`-prefixed and
    `<tool_call|>`-suffixed) and `<tool_code>name(...)</tool_code>`.
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
        # attribute shape: `<call:<name> title="..."/>` (args until the close)
        args_str = text[from_idx : from_idx + close_m.start()]
        consumed = from_idx + close_m.end()
        return before, name, _parse_leak_args(args_str), consumed
    return None  # the call's closing markup is still streaming


def _parse_tool_code_leak(text: str):
    """`<tool_code>show_panel(...)</tool_code>` — code-style leak."""
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
    proper JSON, gemma's raw unquoted-key dicts, and code-style kwargs."""
    cleaned = args_str.replace('<|"|>', '"').replace("<|'|>", "'").strip()
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass
    # Gemma's raw dict: unquoted keys (`{"title": "Menu", blocks: [...]}`).
    quoted = re.sub(r"([{,]\s*)([A-Za-z_]\w*)\s*:", r'\1"\2":', cleaned)
    try:
        parsed = json.loads(quoted)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass
    bare = cleaned.strip("{}").strip()
    # Python-style kwargs / bare quotes (the code-style leak shape).
    try:
        call = ast.parse(f"f({bare})").body[0].value
        args: dict[str, Any] = {}
        for keyword in call.keywords:
            args[keyword.arg] = ast.literal_eval(keyword.value)
        for positional in call.args:
            args.setdefault("title", ast.literal_eval(positional))
        return args
    except Exception:  # noqa: BLE001 - weird shapes fall back to the quoted span
        pass
    match = re.search(r'"([^"]+)"', bare)
    if match:
        return {"title": match.group(1)}
    return {"title": bare} if bare else {}


async def execute_leaked(name: str, args: dict[str, Any], deps: TutorDeps) -> None:
    """Run the real tool for a leaked call; its ack is discarded (the model
    already wrote its own continuation text around the call)."""
    tool = globals().get(name)
    if tool is None:
        return
    try:
        params = inspect.signature(tool).parameters
        kwargs = {key: args[key] for key in params if key in args}
        await tool(_LeakRunContext(deps), **kwargs)
    except Exception:  # noqa: BLE001 - a failed leak capture must not kill the stream
        logger.exception("leaked tool call execution failed")


class _LeakRunContext:
    """The slice of pydantic-ai's RunContext the tools actually read."""

    def __init__(self, deps: TutorDeps) -> None:
        self.deps = deps
