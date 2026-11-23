"""Endpoint tests for /chat + the lesson accept/decline endpoints — fully offline.

Auth, ownership, SSE framing, the event pump (text deltas interleaved with
tool events), and the session lesson state machine all get covered here.
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
from voca.services.lesson_flow import LessonSpec, new_lesson

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


def cafe_lesson(status: str = "proposed") -> dict[str, Any]:
    spec = LessonSpec(template="role_play", title="At the café", objectives=["order"])
    lesson = new_lesson(
        spec,
        [
            {
                "type": "scenario",
                "setting": "a café",
                "learner_role": "customer",
                "tutor_role": "barista",
                "goal": "order",
            }
        ],
        [{"id": "card-1", "front": "quisiera", "back": "I would like"}],
        "ties to the chat",
        "¡Hola! Imagina una cafetería…",
    )
    lesson["status"] = status
    return lesson


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
    fake_supabase.results[("sessions", "select")] = [
        active_session_response(language="fr", lessons=[])
    ]
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
    assert deps["phase"] == "small_talk"  # no lessons → small talk


@pytest.mark.asyncio
async def test_chat_builds_tutor_deps_from_lessons(client, monkeypatch, fake_supabase):
    """Phase + lesson context derive from sessions.lessons; lesson phase skips due cards."""
    lesson = cafe_lesson(status="active")
    fake_supabase.results[("sessions", "select")] = [active_session_response(lessons=[lesson])]
    fake_supabase.results[("profiles", "select")] = [{"id": "user-1"}]
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
    assert deps["phase"] == "lesson"
    assert deps["active_lesson"]["id"] == lesson["id"]
    assert deps["due_cards"] == []  # in a lesson, targets come from the lesson
    assert deps["smalltalk_turns"] == 1  # one prior user turn in history


@pytest.mark.asyncio
async def test_chat_streams_json_frames(client, monkeypatch, fake_supabase):
    """Every SSE frame is a single-line JSON object; deltas keep their newlines."""
    fake_supabase.results[("sessions", "select")] = [active_session_response(lessons=[])]
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
    fake_supabase.results[("sessions", "select")] = [active_session_response(lessons=[])]
    fake_supabase.results[("profiles", "select")] = [{"id": "user-1"}]
    fake_supabase.results[("cards", "select")] = []
    lesson = cafe_lesson()
    monkeypatch.setattr(
        voca_main,
        "tutor_agent",
        ToolEventTutorAgent(
            ["Have a look at the card."],
            [
                {"type": "status", "text": "Designing your lesson…"},
                {"type": "event", "kind": "proposal_ready", "data": {"lesson": lesson}},
            ],
        ),
    )

    response = await client.post(
        "/chat", json={"message": "sounds good", "session_id": "sess-1"}, headers=AUTH
    )
    events = sse_events(response.text)
    statuses = [event.get("text") for event in events if event["type"] == "status"]
    assert statuses == ["Designing your lesson…"]
    structured = [event for event in events if event["type"] == "event"]
    assert structured[0]["kind"] == "proposal_ready"
    assert structured[0]["data"]["lesson"]["id"] == lesson["id"]
    # Structured events are persisted as system transcript rows with a payload.
    saved = fake_supabase.inserted_rows("transcripts")
    payload_rows = [row for row in saved if row.get("payload")]
    assert [row["payload"]["kind"] for row in payload_rows] == ["proposal_ready"]
    assert payload_rows[0]["payload"]["data"]["lesson"]["id"] == lesson["id"]


@pytest.mark.asyncio
async def test_chat_yields_error_event_on_backend_failure(client, monkeypatch, fake_supabase):
    fake_supabase.results[("sessions", "select")] = [active_session_response(lessons=[])]
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
    fake_supabase.results[("sessions", "select")] = [active_session_response(lessons=[])]
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


# --- Lesson lifecycle endpoints -------------------------------------------------------


@pytest.mark.asyncio
async def test_accept_lesson_starts_and_streams_opener(client, monkeypatch, fake_supabase):
    lesson = cafe_lesson(status="proposed")
    fake_supabase.results[("sessions", "select")] = [active_session_response(lessons=[lesson])]
    fake_supabase.results[("profiles", "select")] = [{"id": "user-1"}]
    captured: dict[str, Any] = {}

    class CapturingTutor(FakeTutorAgent):
        @contextlib.asynccontextmanager
        async def run_stream(self, prompt, deps=None, **_kwargs):
            captured["prompt"] = prompt
            captured["deps"] = deps
            yield FakeStreamResult(["¡Hola! Imagina una cafetería…"])

    monkeypatch.setattr(voca_main, "tutor_agent", CapturingTutor([]))

    response = await client.post(
        "/sessions/lessons/accept", json={"session_id": "sess-1"}, headers=AUTH
    )
    assert response.status_code == 200
    events = sse_events(response.text)
    assert events[0]["type"] == "event"
    assert events[0]["kind"] == "lesson_started"
    assert events[0]["data"]["lesson"]["id"] == lesson["id"]

    deltas = [event["text"] for event in events if event["type"] == "delta"]
    assert "".join(deltas) == "¡Hola! Imagina una cafetería…"
    # The opener prompt asks the tutor to open the lesson (no user message needed).
    assert "Open the lesson" in captured["prompt"]
    assert captured["deps"]["phase"] == "lesson"

    # The session's lesson moved to active and the event + opener turn persisted.
    session_updates = fake_supabase.updated_rows("sessions")
    assert any(session_update["values"].get("lessons") for session_update in session_updates)
    saved = fake_supabase.inserted_rows("transcripts")
    assert any(
        row["speaker"] == "system"
        and row["payload"]["kind"] == "lesson_started"
        and row["payload"]["data"]["lesson"]["id"] == lesson["id"]
        for row in saved
    )
    assert saved[-1]["speaker"] == "tutor"
    assert saved[-1]["text"] == "¡Hola! Imagina una cafetería…"


@pytest.mark.asyncio
async def test_accept_lesson_requires_pending_proposal(client, fake_supabase):
    fake_supabase.results[("sessions", "select")] = [active_session_response(lessons=[])]
    response = await client.post(
        "/sessions/lessons/accept", json={"session_id": "sess-1"}, headers=AUTH
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "No lesson proposal is waiting"


@pytest.mark.asyncio
async def test_accept_lesson_rejects_ended_session(client, fake_supabase):
    fake_supabase.results[("sessions", "select")] = [
        {"id": "sess-1", "user_id": "user-1", "status": "completed"}
    ]
    response = await client.post(
        "/sessions/lessons/accept", json={"session_id": "sess-1"}, headers=AUTH
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_decline_lesson_marks_declined_and_persists(client, fake_supabase):
    lesson = cafe_lesson(status="proposed")
    fake_supabase.results[("sessions", "select")] = [active_session_response(lessons=[lesson])]
    response = await client.post(
        "/sessions/lessons/decline",
        json={"session_id": "sess-1", "reason": "too long today"},
        headers=AUTH,
    )
    assert response.status_code == 200
    assert response.json() == {"status": "declined", "lesson_id": lesson["id"]}

    updates = fake_supabase.updated_rows("sessions")
    stored = updates[-1]["values"]["lessons"]
    assert stored[0]["status"] == "declined"
    assert stored[0]["declined_reason"] == "too long today"
    saved = fake_supabase.inserted_rows("transcripts")
    assert any(
        row["speaker"] == "system"
        and row["payload"]["kind"] == "lesson_declined"
        and row["payload"]["data"]["title"] == "At the café"
        for row in saved
    )


@pytest.mark.asyncio
async def test_decline_lesson_requires_pending_proposal(client, fake_supabase):
    fake_supabase.results[("sessions", "select")] = [
        active_session_response(lessons=[cafe_lesson(status="active")])
    ]
    response = await client.post(
        "/sessions/lessons/decline", json={"session_id": "sess-1"}, headers=AUTH
    )
    assert response.status_code == 409


# --- Tutor deps assembly -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_proposal_persists_a_proposal(fake_supabase, monkeypatch):
    """The planner round-trip: due cards + recent chat in deps; lesson instance stored."""
    fake_supabase.results[("sessions", "select")] = [
        active_session_response(lessons=[], id="sess-1")
    ]
    fake_supabase.results[("profiles", "select")] = [
        {"id": "user-1", "level": "B1", "goals": "travel"}
    ]
    fake_supabase.results[("cards", "select")] = [
        {"id": "card-1", "front": "quisiera", "back": "I would like"}
    ]
    fake_supabase.results[("transcripts", "select")] = [
        {
            "speaker": "user",
            "text": "Tengo hambre, quiero un café",
            "created_at": "2025-01-01T00:00:01+00:00",
        }
    ]

    from voca.agents.session_planner_agent import LessonProposal

    async def fake_planner_run(_prompt, deps=None):
        assert deps["user_profile"]["level"] == "B1"
        assert deps["recent_transcript"][0]["text"].startswith("Tengo hambre")
        assert deps["due_cards"] == [{"id": "card-1", "front": "quisiera", "back": "I would like"}]
        proposal = LessonProposal(
            **{
                "lesson": {
                    "template": "role_play",
                    "title": "A coffee run",
                    "topic": "café ordering",
                    "objectives": ["order politely"],
                    "minutes": 6,
                },
                "material": [
                    {
                        "type": "scenario",
                        "setting": "a café",
                        "learner_role": "customer",
                        "tutor_role": "barista",
                        "goal": "order",
                    },
                    {
                        "type": "text",
                        "markdown": "# Menú\n| Café | Precio |\n|---|---|\n| espresso | 1,20 € |",
                        "title": "Carta",
                    },
                ],
                "target_card_ids": ["card-1"],
                "intro_line": "¡Hola! Imagina que entramos en la cafetería.",
                "reason": "the learner was just talking about being hungry",
            }
        )
        return type("R", (), {"output": proposal})()

    monkeypatch.setattr(voca_main.session_planner_agent, "run", fake_planner_run)

    lesson = await voca_main.run_proposal("user-1", "sess-1", "es", "a café role play")
    assert lesson is not None
    assert lesson["status"] == "proposed"
    assert lesson["spec"]["template"] == "role_play"
    stored = fake_supabase.updated_rows("sessions")[-1]["values"]["lessons"]
    assert stored[-1]["id"] == lesson["id"]
    assert stored[-1]["target_cards"] == [
        {"id": "card-1", "front": "quisiera", "back": "I would like"}
    ]
    # Material blocks carry their payload through to storage as plain dicts.
    assert stored[-1]["material"][1]["type"] == "text"
    assert "| espresso |" in stored[-1]["material"][1]["markdown"]


@pytest.mark.asyncio
async def test_run_proposal_rejects_missing_required_blocks(fake_supabase, monkeypatch):
    """A proposal missing its template's required blocks is retried once, then refused."""
    fake_supabase.results[("sessions", "select")] = [active_session_response(lessons=[])]
    fake_supabase.results[("profiles", "select")] = [{"id": "user-1"}]
    fake_supabase.results[("cards", "select")] = []

    from voca.agents.session_planner_agent import LessonProposal

    calls = 0

    async def fake_planner_run(_prompt, deps=None):
        nonlocal calls
        calls += 1
        proposal = LessonProposal(
            lesson={"template": "reading_discussion", "title": "T", "objectives": ["x"]},
            material=[{"type": "text", "markdown": "A passage."}],  # questions missing
            target_card_ids=[],
            intro_line="Lee esto.",
            reason="r",
        )
        return type("R", (), {"output": proposal})()

    monkeypatch.setattr(voca_main.session_planner_agent, "run", fake_planner_run)
    lesson = await voca_main.run_proposal("user-1", "sess-1", "es")
    assert lesson is None
    assert calls == 2  # one retry with corrective feedback before giving up


# --- Streamed tool-call leak capture --------------------------------------------------


class LeakyTutorAgent:
    """A fake tutor that embeds a raw, leaked tool call in its streamed text."""

    def __init__(self, chunks: list[str]) -> None:
        self.chunks = chunks

    @contextlib.asynccontextmanager
    async def run_stream(self, _prompt, deps=None, **_kwargs: Any):
        yield FakeStreamResult(self.chunks)


@pytest.mark.asyncio
async def test_chat_captures_leaked_tool_call_into_a_real_event(client, monkeypatch, fake_supabase):
    """`call:propose_lesson{...}` leaking as text becomes a proposal_ready event."""
    fake_supabase.results[("sessions", "select")] = [active_session_response(lessons=[])]
    fake_supabase.results[("profiles", "select")] = [{"id": "user-1"}]
    fake_supabase.results[("cards", "select")] = [
        {"id": "card-1", "front": "quisiera", "back": "I would like"}
    ]
    fake_supabase.results[("transcripts", "select")] = [
        {
            "speaker": "user",
            "text": "cada vez más picante…",
            "created_at": "2025-01-01T00:00:01+00:00",
        }
    ]
    from voca.agents.session_planner_agent import LessonProposal
    from voca.services.lesson_flow import LessonSpec as LessonSpecModel
    from voca.services.lesson_material import ScenarioBlock

    proposal = LessonProposal(
        lesson=LessonSpecModel(
            template="role_play",
            title="At the café",
            objectives=["order"],
            minutes=6,
        ),
        material=[
            ScenarioBlock(
                setting="a café", learner_role="customer", tutor_role="barista", goal="order"
            )
        ],
        target_card_ids=["card-1"],
        intro_line="¡Hola!",
        reason="the picante story",
    )

    async def fake_planner_run(_prompt, deps=None):
        return type("R", (), {"output": proposal})()

    monkeypatch.setattr(voca_main.session_planner_agent, "run", fake_planner_run)

    leak = '¡Qué picante! call:propose_lesson{idea:<|"|>la ciencia del picante<|"|>}<tool_call|>'
    monkeypatch.setattr(voca_main, "tutor_agent", LeakyTutorAgent([leak]))

    response = await client.post(
        "/chat", json={"message": "jaja sí", "session_id": "sess-1"}, headers=AUTH
    )
    events = sse_events(response.text)
    statuses = [event["text"] for event in events if event["type"] == "status"]
    assert statuses == ["Designing your lesson…"]
    structured = [event for event in events if event["type"] == "event"]
    assert structured and structured[0]["kind"] == "proposal_ready"
    assert structured[0]["data"]["lesson"]["spec"]["title"] == "At the café"
    # The leaked call syntax never reaches the visible chat.
    deltas = "".join(event["text"] for event in events if event["type"] == "delta")
    assert "call:propose_lesson" not in deltas
    assert "¡Qué picante!" in deltas
    # The proposal is persisted in the session's lessons array.
    stored = fake_supabase.updated_rows("sessions")[-1]["values"]["lessons"]
    assert stored and stored[0]["status"] == "proposed"


@pytest.mark.asyncio
async def test_chat_leak_without_tool_match_stays_visible_text(client, monkeypatch, fake_supabase):
    """A leaked span for an unknown tool is left as plain text (no crash)."""
    fake_supabase.results[("sessions", "select")] = [active_session_response(lessons=[])]
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
async def test_chat_captures_tool_code_leak(client, monkeypatch, fake_supabase):
    """The `<tool_code>propose_lesson(idea="…")</tool_code>` shape becomes an event."""
    fake_supabase.results[("sessions", "select")] = [active_session_response(lessons=[])]
    fake_supabase.results[("profiles", "select")] = [{"id": "user-1"}]
    fake_supabase.results[("cards", "select")] = []
    fake_supabase.results[("transcripts", "select")] = [
        {"speaker": "user", "text": "hola café", "created_at": "2025-01-01T00:00:01+00:00"}
    ]

    from voca.agents.session_planner_agent import LessonProposal
    from voca.services.lesson_flow import LessonSpec
    from voca.services.lesson_material import ScenarioBlock

    proposal = LessonProposal(
        lesson=LessonSpec(template="role_play", title="Café", objectives=["order"]),
        material=[
            ScenarioBlock(
                setting="a café", learner_role="customer", tutor_role="barista", goal="order"
            )
        ],
        target_card_ids=[],
        intro_line="¡Hola!",
        reason="reason",
    )

    async def fake_planner_run(_prompt, deps=None):
        return type("R", (), {"output": proposal})()

    monkeypatch.setattr(voca_main.session_planner_agent, "run", fake_planner_run)
    leak = '<tool_code>\npropose_lesson(idea="café role play")\n</tool_code>\n'
    monkeypatch.setattr(voca_main, "tutor_agent", LeakyTutorAgent([leak]))

    response = await client.post(
        "/chat", json={"message": "hola", "session_id": "sess-1"}, headers=AUTH
    )
    events = sse_events(response.text)
    structured = [event for event in events if event["type"] == "event"]
    assert structured and structured[0]["kind"] == "proposal_ready"
    deltas = "".join(event["text"] for event in events if event["type"] == "delta")
    assert "tool_code" not in deltas and "propose_lesson(" not in deltas


# --- Backend force-propose safety net -------------------------------------------------


@pytest.mark.asyncio
async def test_chat_force_proposes_after_a_quiet_reply(client, monkeypatch, fake_supabase):
    """A tutor reply with no tool call past the force threshold still yields a card."""
    from voca.agents.session_planner_agent import LessonProposal
    from voca.services.lesson_flow import LessonSpec

    fake_supabase.results[("sessions", "select")] = [active_session_response(lessons=[])]
    fake_supabase.results[("profiles", "select")] = [{"id": "user-1"}]
    fake_supabase.results[("cards", "select")] = []
    fake_supabase.results[("transcripts", "select")] = [
        {"speaker": "user", "text": "hola", "created_at": "2025-01-01T00:00:01+00:00"}
    ]

    from voca.services.lesson_material import ScenarioBlock as _Scenario

    proposal = LessonProposal(
        lesson=LessonSpec(template="role_play", title="At the café", minutes=6),
        material=[
            _Scenario(setting="a café", learner_role="customer", tutor_role="barista", goal="order")
        ],
        target_card_ids=[],
        intro_line="¡Hola!",
        reason="you talked about coffee",
    )

    async def fake_planner_run(_prompt, deps=None):
        return type("R", (), {"output": proposal})()

    monkeypatch.setattr(voca_main.session_planner_agent, "run", fake_planner_run)
    monkeypatch.setattr(voca_main, "tutor_agent", FakeTutorAgent(["Sigamos charlando…"]))

    history = [
        {"role": "user", "content": f"turn {i}"}
        for i in range(12)  # well past the force threshold
    ]
    response = await client.post(
        "/chat",
        json={"message": "sigamos", "session_id": "sess-1", "history": history},
        headers=AUTH,
    )
    events = sse_events(response.text)
    structured = [event for event in events if event["type"] == "event"]
    assert structured and structured[0]["kind"] == "proposal_ready"
    assert structured[0]["data"]["lesson"]["spec"]["title"] == "At the café"
    # The proposal is persisted in the session's lessons array + transcript payload.
    stored = fake_supabase.updated_rows("sessions")[-1]["values"]["lessons"]
    assert stored and stored[0]["status"] == "proposed"
    assert any(
        row.get("payload", {}).get("kind") == "proposal_ready"
        for row in fake_supabase.inserted_rows("transcripts")
    )


@pytest.mark.asyncio
async def test_chat_force_propose_respects_decline_cooldown(client, monkeypatch, fake_supabase):
    """A recent decline keeps the proposal quiet; a pending proposal is never doubled."""
    from voca.services.lesson_flow import LessonSpec, new_lesson

    pending = new_lesson(
        LessonSpec(template="role_play", title="Pending"),
        [],
        [],
        "reason",
        "Intro",
    )
    fake_supabase.results[("sessions", "select")] = [active_session_response(lessons=[pending])]
    fake_supabase.results[("profiles", "select")] = [{"id": "user-1"}]
    fake_supabase.results[("cards", "select")] = []

    async def fail_planner(_prompt, deps=None):
        raise AssertionError("planner must not run while a proposal is pending")

    monkeypatch.setattr(voca_main.session_planner_agent, "run", fail_planner)
    monkeypatch.setattr(voca_main, "tutor_agent", FakeTutorAgent(["hola"]))

    history = [{"role": "user", "content": "t"} for _ in range(20)]
    response = await client.post(
        "/chat", json={"message": "x", "session_id": "sess-1", "history": history}, headers=AUTH
    )
    assert not [event for event in sse_events(response.text) if event["type"] == "event"]
