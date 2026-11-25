"""Agent wiring tests: prompt construction, output schemas, and tool behavior.

Fully offline: instructions functions run against a stub RunContext, agent runs
use pydantic-ai's TestModel (no LLM calls), and the tutor's tools run with fake
DB callbacks.
"""

import asyncio
from typing import Any

from pydantic_ai import capture_run_messages
from pydantic_ai.models.test import TestModel

from voca.agents.post_session_agent import (
    FSRS_RUBRIC,
    NEW_CARDS_RULES,
    CardGrade,
    PostSessionDeps,
    PostSessionResult,
    post_session_agent,
    post_session_instructions,
)
from voca.agents.tutor_agent import (
    TutorDeps,
    build_panel,
    execute_leaked,
    hide_panel,
    parse_tool_leak,
    show_panel,
    tutor_agent,
    tutor_system_prompt,
)


class _StubRunContext:
    """Just enough of pydantic-ai's RunContext for instructions/tool functions."""

    def __init__(self, deps: dict) -> None:
        self.deps = deps


def tutor_deps(**overrides) -> TutorDeps:
    """A full TutorDeps fixture; overrides patch individual fields."""
    base: TutorDeps = {
        "user_id": "user-1",
        "session_id": "session-1",
        "user_profile": {
            "target_language": "es",
            "goals": "travel to Spain",
            "level": "A2",
            "interests": "architecture",
        },
        "due_cards": [],
        "events": asyncio.Queue(),
        "record_event": None,
    }
    base.update(overrides)
    return base


async def drained(queue: asyncio.Queue) -> list[dict[str, Any]]:
    """All events pushed to a queue so far (non-blocking)."""
    items: list[dict[str, Any]] = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


MENU_MARKDOWN = "| Plato | Precio |\n| :--- | :--- |\n| Tacos | 60 |"


# --- Tutor prompts -------------------------------------------------------------------


def test_tutor_prompt_includes_profile_and_conversational_rules():
    prompt = tutor_system_prompt(_StubRunContext(tutor_deps()))
    assert "Spanish" in prompt and "travel to Spain" in prompt and "A2" in prompt
    assert "casual conversation" in prompt
    assert "NEVER attach example phrases" in prompt
    assert "show_panel" in prompt and "hide_panel" in prompt
    assert "SIDE PANEL" in prompt and "OUT of your chat turns" in prompt


def test_tutor_prompt_defaults_without_profile():
    prompt = tutor_system_prompt(_StubRunContext(tutor_deps(user_profile={})))
    assert "learn Spanish" in prompt and "Intermediate (B1)" in prompt


def test_tutor_prompt_weaves_due_cards_into_small_talk():
    prompt = tutor_system_prompt(
        _StubRunContext(
            tutor_deps(due_cards=[{"id": "c1", "front": "quisiera", "back": "I would like"}])
        )
    )
    assert "REVIEW CARDS" in prompt and "quisiera" in prompt


def test_prompt_without_due_cards_omits_the_block():
    prompt = tutor_system_prompt(_StubRunContext(tutor_deps()))
    assert "REVIEW CARDS" not in prompt


def test_tutor_prompt_carries_the_current_panel():
    panel = {"id": "panel-x", "title": "El cuento de Mateo", "markdown": "Un ingeniero…"}
    prompt = tutor_system_prompt(_StubRunContext(tutor_deps(current_panel=panel)))
    assert "THE CURRENT PANEL" in prompt and "El cuento de Mateo" in prompt
    assert "Un ingeniero…" in prompt
    assert "persists across turns" in prompt and "only to REPLACE" in prompt
    # A panel in context tightens the rules; without one the prompt stays neutral.
    plain = tutor_system_prompt(_StubRunContext(tutor_deps()))
    assert "THE CURRENT PANEL" not in plain


# --- show_panel tool -----------------------------------------------------------------


async def test_show_panel_tool_pushes_and_persists_event():
    recorded: list[tuple[str, dict]] = []
    deps = tutor_deps(record_event=_record(recorded))
    result = await show_panel(_StubRunContext(deps), "Carta del día", MENU_MARKDOWN)
    assert "Call accepted" in result
    # The panel event is the only feedback: no transient status chip.
    events = await drained(deps["events"])
    assert [e for e in events if e["type"] == "status"] == []
    shown = events[0]
    assert shown["type"] == "event" and shown["kind"] == "panel_shown"
    panel = shown["data"]["panel"]
    assert panel["title"] == "Carta del día"
    assert panel["markdown"].startswith("| Plato |")
    assert panel["id"].startswith("panel-")
    assert deps["current_panel_id"] == panel["id"]
    assert deps["current_panel"] == panel
    assert recorded == [("panel_shown", shown["data"])]


def _record(recorded: list) -> Any:
    async def record(kind: str, data: dict) -> None:
        recorded.append((kind, data))

    return record


async def test_show_panel_decodes_escaped_newlines():
    deps = tutor_deps()
    await show_panel(_StubRunContext(deps), "Carta", "**Tacos**\\n\\n| Plato |\\n| :--- |")
    shown = (await drained(deps["events"]))[0]
    markdown = shown["data"]["panel"]["markdown"]
    assert "\\n" not in markdown and "\n\n" in markdown


async def test_show_panel_rejects_empty_markdown():
    deps = tutor_deps(record_event=None)
    result = await show_panel(_StubRunContext(deps), "Menu", "   ")
    assert "rejected" in result and "empty" in result
    assert [e for e in await drained(deps["events"]) if e["type"] == "event"] == []
    assert "current_panel_id" not in deps


# --- hide_panel tool -----------------------------------------------------------------


async def test_hide_panel_closes_the_current_panel():
    recorded: list[tuple[str, dict]] = []
    deps = tutor_deps(record_event=_record(recorded))
    await show_panel(_StubRunContext(deps), "Menu", MENU_MARKDOWN)
    result = await hide_panel(_StubRunContext(deps))
    assert "hidden" in result
    hidden = (await drained(deps["events"]))[-1]
    assert hidden["kind"] == "panel_hidden"
    assert hidden["data"]["panel_id"] == ""  # the UI's walk targets whatever shows
    assert deps["current_panel_id"] is None
    assert recorded[-1] == ("panel_hidden", {"panel_id": ""})


async def test_hide_panel_always_pushes_even_without_a_panel():
    """Per-turn deps cannot track the UI's panel; hiding is always emitted and
    the walk on the client decides whether anything closes."""
    deps = tutor_deps()
    result = await hide_panel(_StubRunContext(deps))
    assert "hidden" in result
    events = await drained(deps["events"])
    assert events[-1]["kind"] == "panel_hidden"


# --- build_panel ---------------------------------------------------------------------


def test_build_panel_rejects_empty_markdown_and_defaults_the_title():
    assert build_panel("Menu", "   ") is None
    assert build_panel("", MENU_MARKDOWN)["title"] == "Panel"


# --- Leak capture --------------------------------------------------------------------


def test_parse_leak_call_shape_with_panel_args():
    text = 'call:show_panel{title:<|"|>Carta<|"|>, markdown:<|"|>| Plato | 60 |<|"|>}'
    parsed = parse_tool_leak("Hola " + text)
    assert parsed is not None
    before, name, args, _consumed = parsed
    assert before == "Hola "
    assert name == "show_panel"
    assert args["title"] == "Carta"
    assert args["markdown"] == "| Plato | 60 |"


def test_parse_leak_tool_code_shape():
    text = '<tool_code>show_panel(title="Carta", markdown="| Plato | 60 |")</tool_code>'
    parsed = parse_tool_leak(text)
    assert parsed is not None
    _before, name, args, _consumed = parsed
    assert name == "show_panel"
    assert args["title"] == "Carta"
    assert args["markdown"] == "| Plato | 60 |"


def test_parse_leak_hide_panel_tolerates_empty_args():
    for shape in ("call:hide_panel{}", "<tool_code>hide_panel()</tool_code>"):
        parsed = parse_tool_leak(shape)
        assert parsed is not None
        _before, name, args, _consumed = parsed
        assert name == "hide_panel"


def test_unterminated_leak_stays_hidden():
    assert parse_tool_leak('call:show_panel{title:"Car') is None


async def test_execute_leaked_runs_the_real_show_panel():
    deps = tutor_deps()
    await execute_leaked(
        "show_panel",
        {"title": "Carta", "markdown": MENU_MARKDOWN},
        deps,
    )
    events = await drained(deps["events"])
    assert events[-1]["kind"] == "panel_shown"
    assert events[-1]["data"]["panel"]["title"] == "Carta"
    assert deps["current_panel"] == events[-1]["data"]["panel"]


async def test_execute_leaked_ignores_unknown_tools():
    await execute_leaked("propose_lesson", {"idea": "x"}, tutor_deps())  # must not raise


# --- Agent-level behavior (TestModel) ------------------------------------------------


async def test_tutor_agent_output_is_plain_text():
    with tutor_agent.override(model=TestModel()):
        result = await tutor_agent.run("Hola", deps=tutor_deps())
    assert result.output and isinstance(result.output, str)


async def test_tutor_agent_sends_profile_in_instructions():
    with tutor_agent.override(model=TestModel(call_tools=[])), capture_run_messages() as messages:
        async with tutor_agent.run_stream("Hola", deps=tutor_deps()):
            pass
    rendered = "\n".join(str(getattr(message, "instructions", "")) for message in messages)
    assert "Spanish" in rendered


# --- Post-session analyst ------------------------------------------------------------


def test_post_session_instructions_render_transcript_and_cards():
    deps = _analyst_deps()
    prompt = post_session_instructions(_StubRunContext(deps))
    assert "¿Qué pones?" in prompt and "quisiera" in prompt and "Spanish" in prompt


def test_post_session_rubric_maps_transcript_to_fsrs():
    text = FSRS_RUBRIC
    for outcome in ("strong_pass", "pass", "recognition_pass", "miss", "not_attempted"):
        assert outcome in text
    for outcome_label in ("FSRS Easy", "FSRS Good", "FSRS Again"):
        assert outcome_label in text


def test_post_session_new_cards_rules_stay_prompt_visible():
    assert "UNCERTAINTY" in NEW_CARDS_RULES and "(c) BETTER ALTERNATIVE" in NEW_CARDS_RULES


async def test_post_session_agent_output_schema():
    with post_session_agent.override(model=TestModel()):
        result = await post_session_agent.run("Analyze.", deps=_analyst_deps())
    assert isinstance(result.output, PostSessionResult)
    assert result.output.recap is not None


def _analyst_deps() -> PostSessionDeps:
    return {
        "user_id": "u1",
        "session_id": "s1",
        "transcript": [{"speaker": "user", "text": "¿Qué pones?"}],
        "due_cards": [{"id": "c1", "front": "quisiera", "back": "I would like"}],
        "existing_cards": [],
        "target_language": "es",
    }


def test_card_grade_schema_has_evidence():
    grade = CardGrade(card_id="c1", outcome="pass", evidence="user: quisiera un café")
    assert grade.evidence == "user: quisiera un café"
