"""Endpoint tests for /chat — fully offline.

Auth, ownership, SSE framing, the event pump (text deltas interleaved with
panel events), and the leak-capture pump all get covered here.
"""

import contextlib
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from pydantic_ai.messages import ModelRequest, ModelResponse

from voca import main as voca_main
from voca.main import pydantic_history

AUTH = {"Authorization": "Bearer valid-token"}


class FakeStreamResult:
    def __init__(self, chunks: list[str]) -> None:
        self.chunks = chunks

    async def stream_text(self, delta: bool = False) -> AsyncIterator[str]:
        for chunk in self.chunks:
            yield chunk


class FakeTutorAgent:
    """Stands in for `tutor_agent.run_stream` — yields canned text deltas."""

    def __init__(self, chunks: list[str]) -> None:
        self.chunks = chunks

    @contextlib.asynccontextmanager
    async def run_stream(self, *_args: Any, **_kwargs: Any) -> AsyncIterator[FakeStreamResult]:
        yield FakeStreamResult(self.chunks)


class ToolEventTutorAgent(FakeTutorAgent):
    """A fake tutor whose run mimics a tool firing: pushes events into the queue
    before/around its text stream."""

    def __init__(self, chunks: list[str], events: list[dict[str, Any]]) -> None:
        super().__init__(chunks)
        self._events = events

    @contextlib.asynccontextmanager
    async def run_stream(self, _prompt, deps=None, **_kwargs: Any):
        for event in self._events:
            await deps["events"].put(event)
            if event["type"] == "event" and deps.get("record_event"):
                await deps["record_event"](event["kind"], event["data"])
        yield FakeStreamResult(self.chunks)


def active_session_response(**overrides) -> dict[str, Any]:
    row = {"id": "sess-1", "user_id": "user-1", "status": "active", "language": "es"}
    row.update(overrides)
    return row


class LeakyTutorAgent(FakeTutorAgent):
    """A fake tutor whose stream text contains gemma's raw tool-call syntax."""

    def __init__(self, chunks: list[str]) -> None:
        super().__init__(chunks)

    @contextlib.asynccontextmanager
    async def run_stream(self, *_args: Any, deps=None, **_kwargs: Any):
        import asyncio

        async def play():
            for chunk in self.chunks:
                await asyncio.sleep(0)  # let the queue interleave
                yield chunk

        class _Result:
            async def stream_text(self, delta: bool = False):
                async for piece in play():
                    yield (piece[:1] if delta else piece) + (piece[1:] if delta else "")

        yield _Result()


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=voca_main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


def sse_events(text: str) -> list[dict[str, Any]]:
    return [
        json.loads(line[len("data: ") :])
        for line in text.strip().splitlines()
        if line.startswith("data: ")
    ]


@pytest.mark.asyncio
async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_chat_requires_auth(client):
    response = await client.post("/chat", json={"message": "hola", "session_id": "sess-1"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_chat_rejects_invalid_token(client, monkeypatch, fake_supabase):
    monkeypatch.setattr("voca.main.supabase.auth", fake_supabase.auth)
    response = await client.post(
        "/chat",
        json={"message": "hola", "session_id": "sess-1"},
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_chat_unknown_session_returns_404(client, fake_supabase):
    response = await client.post(
        "/chat", json={"message": "hola", "session_id": "missing"}, headers=AUTH
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_chat_rejects_ended_sessions(client, fake_supabase):
    """Ended sessions are archived: no further tutor turns."""
    fake_supabase.results[("sessions", "select")] = [
        {"id": "sess-1", "user_id": "user-1", "status": "completed"}
    ]
    response = await client.post(
        "/chat", json={"message": "hola", "session_id": "sess-1"}, headers=AUTH
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "Session has already ended"


@pytest.mark.asyncio
async def test_chat_passes_effective_profile_to_tutor(client, monkeypatch, fake_supabase):
    """The tutor sees the session language + the user_languages overlay, not the raw profile."""
    fake_supabase.results[("sessions", "select")] = [active_session_response(language="fr")]
    fake_supabase.results[("profiles", "select")] = [
        {"id": "user-1", "level": "A2", "goals": "global"}
    ]
    fake_supabase.results[("user_languages", "select")] = [{"level": "B1", "goals": "fr goals"}]
    captured: dict[str, Any] = {}

    class CapturingTutor(FakeTutorAgent):
        @contextlib.asynccontextmanager
        async def run_stream(self, _prompt, deps=None, **_kwargs):
            captured["deps"] = deps
            yield FakeStreamResult(["OK"])

    monkeypatch.setattr(voca_main, "tutor_agent", CapturingTutor([]))

    response = await client.post(
        "/chat", json={"message": "bonjour", "session_id": "sess-1"}, headers=AUTH
    )
    assert response.status_code == 200
    deps = captured["deps"]
    assert deps["user_profile"]["target_language"] == "fr"  # pinned to the session language
    assert deps["user_profile"]["level"] == "B1"  # overlaid from user_languages


@pytest.mark.asyncio
async def test_chat_includes_due_cards_in_deps(client, monkeypatch, fake_supabase):
    """Due cards ride into the tutor deps for natural review weaving."""
    fake_supabase.results[("sessions", "select")] = [active_session_response()]
    fake_supabase.results[("profiles", "select")] = [{"id": "user-1"}]
    fake_supabase.results[("cards", "select")] = [
        {"id": "card-1", "front": "quisiera", "back": "I would like"}
    ]
    captured: dict[str, Any] = {}

    class CapturingTutor(FakeTutorAgent):
        @contextlib.asynccontextmanager
        async def run_stream(self, _prompt, deps=None, **_kwargs):
            captured["deps"] = deps
            yield FakeStreamResult(["OK"])

    monkeypatch.setattr(voca_main, "tutor_agent", CapturingTutor([]))

    response = await client.post(
        "/chat",
        json={
            "message": "un cortado, por favor",
            "session_id": "sess-1",
            "history": [
                {"role": "user", "content": "hola"},
                {"role": "assistant", "content": "¡Hola!"},
            ],
        },
        headers=AUTH,
    )
    assert response.status_code == 200
    deps = captured["deps"]
    assert deps["due_cards"] == [{"id": "card-1", "front": "quisiera", "back": "I would like"}]


@pytest.mark.asyncio
async def test_chat_streams_json_frames(client, monkeypatch, fake_supabase):
    """Every SSE frame is a single-line JSON object; deltas keep their newlines."""
    fake_supabase.results[("sessions", "select")] = [active_session_response()]
    fake_supabase.results[("profiles", "select")] = [{"id": "user-1", "level": "A2"}]
    # Due-card lookups are empty (no due cards seeded).
    fake_supabase.results[("cards", "select")] = []
    chunks = ["¡Hola! ", "¿Cómo\nestás?\n", "Bien."]
    monkeypatch.setattr(voca_main, "tutor_agent", FakeTutorAgent(chunks))

    response = await client.post(
        "/chat", json={"message": "hola", "session_id": "sess-1"}, headers=AUTH
    )
    assert response.status_code == 200

    events = sse_events(response.text)
    deltas = [event["text"] for event in events if event["type"] == "delta"]
    assert "".join(deltas) == "".join(chunks)
    assert "".join(deltas).count("\n") == 2, "deltas must not lose their newlines"
    assert events[-1]["type"] == "done"

    # Both turns were persisted: the user's message, then the tutor's full reply.
    saved = fake_supabase.inserted_rows("transcripts")
    assert [row["speaker"] for row in saved] == ["user", "tutor"]
    assert saved[1]["text"] == "".join(chunks)


@pytest.mark.asyncio
async def test_chat_pumps_tool_events_into_the_stream(client, monkeypatch, fake_supabase):
    """Structured events interleave with text deltas, in order, and persist as rows."""
    fake_supabase.results[("sessions", "select")] = [active_session_response()]
    fake_supabase.results[("profiles", "select")] = [{"id": "user-1"}]
    fake_supabase.results[("cards", "select")] = []
    panel = {
        "id": "panel-1",
        "title": "Carta del día",
        "markdown": "| Plato |\n| :--- |\n| Tacos |",
    }
    monkeypatch.setattr(
        voca_main,
        "tutor_agent",
        ToolEventTutorAgent(
            ["Have a look at the card."],
            [
                {"type": "status", "text": "Preparing your panel…"},
                {"type": "event", "kind": "panel_shown", "data": {"panel": panel}},
            ],
        ),
    )

    response = await client.post(
        "/chat", json={"message": "sounds good", "session_id": "sess-1"}, headers=AUTH
    )
    events = sse_events(response.text)
    statuses = [event.get("text") for event in events if event["type"] == "status"]
    assert statuses == ["Preparing your panel…"]
    structured = [event for event in events if event["type"] == "event"]
    assert structured[0]["kind"] == "panel_shown"
    assert structured[0]["data"]["panel"]["id"] == panel["id"]
    # Structured events are persisted as system transcript rows with a payload.
    saved = fake_supabase.inserted_rows("transcripts")
    payload_rows = [row for row in saved if row.get("payload")]
    assert [row["payload"]["kind"] for row in payload_rows] == ["panel_shown"]
    assert payload_rows[0]["payload"]["data"]["panel"]["id"] == panel["id"]


@pytest.mark.asyncio
async def test_chat_yields_error_event_on_backend_failure(client, monkeypatch, fake_supabase):
    fake_supabase.results[("sessions", "select")] = [active_session_response()]
    fake_supabase.results[("profiles", "select")] = [{"id": "user-1"}]
    fake_supabase.results[("cards", "select")] = []

    class ExplodingTutor(FakeTutorAgent):
        @contextlib.asynccontextmanager
        async def run_stream(self, *_args: Any, **_kwargs: Any):
            raise RuntimeError("model exploded")
            yield  # pragma: no cover

    monkeypatch.setattr(voca_main, "tutor_agent", ExplodingTutor([]))

    response = await client.post(
        "/chat", json={"message": "hola", "session_id": "sess-1"}, headers=AUTH
    )
    events = sse_events(response.text)
    assert events[-2]["type"] == "error"
    assert events[-2]["message"] == "The tutor hit an unexpected error. Please try again."
    assert events[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_chat_saves_partial_reply_after_failure(client, monkeypatch, fake_supabase):
    fake_supabase.results[("sessions", "select")] = [active_session_response()]
    fake_supabase.results[("profiles", "select")] = [{"id": "user-1"}]
    fake_supabase.results[("cards", "select")] = []

    class PartialTutor(FakeTutorAgent):
        @contextlib.asynccontextmanager
        async def run_stream(self, *_args: Any, **_kwargs: Any) -> AsyncIterator[FakeStreamResult]:
            # Stream a little text, then blow up mid-stream.
            yield FakeStreamResult(["partial "])
            raise RuntimeError("mid-stream failure")

    monkeypatch.setattr(voca_main, "tutor_agent", PartialTutor(["partial "]))

    response = await client.post(
        "/chat", json={"message": "hola", "session_id": "sess-1"}, headers=AUTH
    )
    saved = fake_supabase.inserted_rows("transcripts")
    assert saved[-1]["speaker"] == "tutor"
    assert saved[-1]["text"].startswith("partial")
    assert response.status_code == 200  # the stream itself still ends cleanly


def test_pydantic_history_maps_roles():
    history = pydantic_history(
        [
            {"role": "user", "content": "hola"},
            {"role": "assistant", "content": "¡hola!"},
            {"role": "assistant", "content": ""},
        ]
    )
    assert isinstance(history[0], ModelRequest)
    assert history[0].parts[0].content == "hola"
    assert isinstance(history[1], ModelResponse)
    assert history[1].parts[0].content == "¡hola!"
    assert isinstance(history[2], ModelResponse)


def test_pydantic_history_handles_empty_input():
    assert pydantic_history(None) == []


# --- Leak capture pump ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_captures_leaked_tool_call_into_a_real_event(client, monkeypatch, fake_supabase):
    """`call:show_panel{...}` leaking as text becomes a panel_shown event."""
    fake_supabase.results[("sessions", "select")] = [active_session_response()]
    fake_supabase.results[("profiles", "select")] = [{"id": "user-1"}]
    fake_supabase.results[("cards", "select")] = []

    leak = (
        '¡Qué picante! call:show_panel{title:<|"|>La ciencia del picante<|"|>, '
        'markdown:<|"|>1. ¿Qué tan picante te gusta?<|"|>}<tool_call|>'
    )
    monkeypatch.setattr(voca_main, "tutor_agent", LeakyTutorAgent([leak]))

    response = await client.post(
        "/chat", json={"message": "jaja sí", "session_id": "sess-1"}, headers=AUTH
    )
    events = sse_events(response.text)
    statuses = [event["text"] for event in events if event["type"] == "status"]
    assert statuses == ["Preparing your panel…"]
    structured = [event for event in events if event["type"] == "event"]
    assert structured and structured[0]["kind"] == "panel_shown"
    panel = structured[0]["data"]["panel"]
    assert panel["title"] == "La ciencia del picante"
    assert "picante" in panel["markdown"]
    # The leaked call syntax never reaches the visible chat.
    deltas = "".join(event["text"] for event in events if event["type"] == "delta")
    assert "call:show_panel" not in deltas
    assert "¡Qué picante!" in deltas
    # The panel is persisted as a transcript payload row.
    payload_rows = [row for row in fake_supabase.inserted_rows("transcripts") if row.get("payload")]
    assert payload_rows and payload_rows[0]["payload"]["data"]["panel"]["id"].startswith("panel-")


@pytest.mark.asyncio
async def test_chat_leak_without_tool_match_stays_visible_text(client, monkeypatch, fake_supabase):
    """A leaked span for an unknown tool is left as plain text (no crash)."""
    fake_supabase.results[("sessions", "select")] = [active_session_response()]
    fake_supabase.results[("profiles", "select")] = [{"id": "user-1"}]
    fake_supabase.results[("cards", "select")] = []

    monkeypatch.setattr(
        voca_main, "tutor_agent", LeakyTutorAgent(["todo: call:some_other_tool{x:1} después"])
    )
    response = await client.post(
        "/chat", json={"message": "hola", "session_id": "sess-1"}, headers=AUTH
    )
    deltas = "".join(
        event["text"] for event in sse_events(response.text) if event["type"] == "delta"
    )
    assert "some_other_tool" in deltas


@pytest.mark.asyncio
async def test_chat_hide_panel_leak_hides_the_panel(client, monkeypatch, fake_supabase):
    """A leaked hide_panel call closes the panel: panel_hidden event, panel_id kept."""
    fake_supabase.results[("sessions", "select")] = [active_session_response()]
    fake_supabase.results[("profiles", "select")] = [{"id": "user-1"}]
    fake_supabase.results[("cards", "select")] = []

    leak = '<tool_code>show_panel(title="Carta", markdown="hola")</tool_code>'
    leak2 = "<tool_code>hide_panel()</tool_code>"
    monkeypatch.setattr(voca_main, "tutor_agent", LeakyTutorAgent([leak, leak2]))

    response = await client.post(
        "/chat", json={"message": "está bien", "session_id": "sess-1"}, headers=AUTH
    )
    events = sse_events(response.text)
    kinds = [event["kind"] for event in events if event["type"] == "event"]
    assert kinds == ["panel_shown", "panel_hidden"]
    hidden = [event for event in events if event["type"] == "event"][-1]
    assert hidden["data"]["panel_id"] == ""  # targets whatever is showing
