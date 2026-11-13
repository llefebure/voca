"""Endpoint tests for /chat: auth, ownership, and SSE framing — fully offline."""

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


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=voca_main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


def active_session_response() -> dict[str, Any]:
    return {"id": "sess-1", "user_id": "user-1", "status": "active"}


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
    # Point auth lookups at a fake that rejects unknown tokens.
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
async def test_chat_streams_json_frames(client, monkeypatch, fake_supabase):
    """Every SSE frame is a single-line JSON object; deltas keep their newlines."""
    fake_supabase.results[("sessions", "select")] = [active_session_response()]
    fake_supabase.results[("profiles", "select")] = [{"id": "user-1", "level": "A2"}]
    chunks = ["¡Hola! ", "¿Cómo\nestás?\n", "Bien."]
    monkeypatch.setattr(voca_main, "tutor_agent", FakeTutorAgent(chunks))

    response = await client.post(
        "/chat", json={"message": "hola", "session_id": "sess-1"}, headers=AUTH
    )
    assert response.status_code == 200

    events = []
    for line in response.text.strip().splitlines():
        if not line:
            continue
        assert line.startswith("data: "), f"non-JSON SSE line: {line!r}"
        events.append(json.loads(line[len("data: ") :]))  # fails if framing broke

    deltas = [event["text"] for event in events if event["type"] == "delta"]
    assert "".join(deltas) == "".join(chunks)
    assert "".join(deltas).count("\n") == 2, "deltas must not lose their newlines"
    assert events[-1]["type"] == "done"

    # Both turns were persisted: the user's message, then the tutor's full reply.
    saved = fake_supabase.inserted_rows("transcripts")
    assert [row["speaker"] for row in saved] == ["user", "tutor"]
    assert saved[1]["text"] == "".join(chunks)


@pytest.mark.asyncio
async def test_chat_yields_error_event_on_backend_failure(client, monkeypatch, fake_supabase):
    fake_supabase.results[("sessions", "select")] = [active_session_response()]
    fake_supabase.results[("profiles", "select")] = [{"id": "user-1"}]

    class ExplodingTutor(FakeTutorAgent):
        @contextlib.asynccontextmanager
        async def run_stream(self, *_args: Any, **_kwargs: Any):
            raise RuntimeError("model exploded")
            yield  # pragma: no cover

    monkeypatch.setattr(voca_main, "tutor_agent", ExplodingTutor([]))

    response = await client.post(
        "/chat", json={"message": "hola", "session_id": "sess-1"}, headers=AUTH
    )
    events = [
        json.loads(line[len("data: ") :]) for line in response.text.strip().splitlines() if line
    ]
    assert events[-1]["type"] == "done"
    assert events[-2]["type"] == "error"
    assert "exploded" in events[-2]["message"]
    assert events[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_chat_saves_partial_reply_after_failure(client, monkeypatch, fake_supabase):
    fake_supabase.results[("sessions", "select")] = [active_session_response()]
    fake_supabase.results[("profiles", "select")] = [{"id": "user-1"}]

    class PartialTutor(FakeTutorAgent):
        @contextlib.asynccontextmanager
        async def run_stream(self, *_args: Any, **_kwargs: Any) -> AsyncIterator[FakeStreamResult]:
            # Stream a little text, then blow up mid-tur…
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
