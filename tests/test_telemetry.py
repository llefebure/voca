"""Telemetry wiring tests: FastAPI request handling emits Logfire spans.

Fully offline — logfire never sends under pytest; the `capfire` fixture
captures spans in-process via its in-memory exporter. `LOGFIRE_SERVICE_NAME`
is set because capfire's own `configure()` build re-builds the resource.
"""

import httpx
import pytest
from logfire.testing import CaptureLogfire

from voca import main as voca_main
from voca.services.telemetry import SERVICE_NAME


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
