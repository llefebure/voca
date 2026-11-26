"""Telemetry wiring tests: FastAPI request handling emits Logfire spans.

Fully offline — logfire never sends under pytest; the `capfire` fixture
captures spans in-process via its in-memory exporter. `LOGFIRE_SERVICE_NAME`
is set because capfire's own `configure()` build re-builds the resource.
"""

import httpx
import pytest
from logfire.testing import CaptureLogfire
from pydantic_ai.models.test import TestModel

from voca import main as voca_main
from voca.agents.tutor_agent import tutor_agent
from voca.services.telemetry import SERVICE_NAME, TelemetrySettings

AUTH = {"Authorization": "Bearer valid-token"}


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=voca_main.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


@pytest.fixture
def logfire_service_name(monkeypatch):
    monkeypatch.setenv("LOGFIRE_SERVICE_NAME", SERVICE_NAME)


@pytest.mark.asyncio
async def test_fastapi_request_emits_logfire_span(
    client, logfire_service_name, capfire: CaptureLogfire
):
    response = await client.get("/health")
    assert response.status_code == 200

    spans = capfire.exporter.exported_spans_as_dict(include_resources=True)
    health_spans = [span for span in spans if span["attributes"].get("http.route") == "/health"]
    assert health_spans, f"no /health spans among: {[span['name'] for span in spans]}"
    span = health_spans[0]
    assert span["name"] == "GET /health"
    assert span["attributes"]["http.method"] == "GET"
    assert span["resource"]["attributes"]["service.name"] == SERVICE_NAME


@pytest.mark.asyncio
async def test_chat_agent_run_span_carries_conversation_id(
    client, logfire_service_name, fake_supabase, capfire: CaptureLogfire
):
    """The tutor's agent run span is stamped with the DB session id as
    `gen_ai.conversation.id` — Logfire's conversation grouping contract."""
    fake_supabase.results[("sessions", "select")] = [
        {"id": "sess-42", "user_id": "user-1", "status": "active", "language": "es"}
    ]
    fake_supabase.results[("profiles", "select")] = [{"id": "user-1"}]

    with tutor_agent.override(model=TestModel(call_tools=[])):
        response = await client.post(
            "/chat", json={"message": "hola", "session_id": "sess-42"}, headers=AUTH
        )
    assert response.status_code == 200

    spans = capfire.exporter.exported_spans_as_dict(include_resources=True)
    run_spans = [
        span
        for span in spans
        if span["attributes"].get("logfire.msg").endswith(" run")
        and "gen_ai.conversation.id" in span["attributes"]
    ]
    assert run_spans, f"no agent run spans among: {[span['name'] for span in spans]}"
    conversation_ids = {span["attributes"]["gen_ai.conversation.id"] for span in run_spans}
    assert conversation_ids == {"sess-42"}
    # The id is also spread to nested spans via OTel baggage.
    stamped = {
        span["attributes"]["gen_ai.conversation.id"]
        for span in spans
        if span["attributes"].get("gen_ai.conversation.id")
    }
    assert stamped == {"sess-42"}


def test_service_name_reads_env(monkeypatch):
    """TelemetrySettings reads LOGFIRE_SERVICE_NAME (the SDK's own env var)."""
    monkeypatch.setenv("LOGFIRE_SERVICE_NAME", "other-name")
    assert TelemetrySettings().service_name == "other-name"


def test_service_name_default(monkeypatch):
    """Without the env var the former hard-coded default applies."""
    monkeypatch.delenv("LOGFIRE_SERVICE_NAME", raising=False)
    assert TelemetrySettings().service_name == "voca-backend"


@pytest.mark.asyncio
async def test_model_request_spans_capture_content(
    client, logfire_service_name, fake_supabase, capfire: CaptureLogfire
):
    """`include_content=True`: model-request spans expose the LLM messages
    (`gen_ai.input.messages`), so prompts/completions show in the Logfire UI."""
    fake_supabase.results[("sessions", "select")] = [
        {"id": "sess-42", "user_id": "user-1", "status": "active", "language": "es"}
    ]
    fake_supabase.results[("profiles", "select")] = [{"id": "user-1"}]

    with tutor_agent.override(model=TestModel(call_tools=[])):
        response = await client.post(
            "/chat", json={"message": "hola", "session_id": "sess-42"}, headers=AUTH
        )
    assert response.status_code == 200

    spans = capfire.exporter.exported_spans_as_dict(include_resources=True)
    content = [span for span in spans if span["attributes"].get("gen_ai.input.messages")]
    assert content, (
        f"no content-carrying spans among: "
        f"{[(span['name'], sorted(span['attributes'])) for span in spans]}"
    )
