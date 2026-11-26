"""Logfire (OpenTelemetry) telemetry for the FastAPI backend.

`configure_telemetry(app)` is called once in `voca.main` at import time, before
serving. FastAPI request handling, outgoing httpx calls (Supabase, Ollama), and
Pydantic AI agent runs (tutor, session planner, post-session analyst,
translator) then all appear as spans; Python `logging` records from `voca.*`
loggers are routed through Logfire too.

Content capture: Pydantic AI instrumentation records LLM prompt/completion
content (`include_content=True`), so the conversation text sent to Ollama and
received from it appears on the model-request spans in the Logfire UI. HTTP
request bodies/headers are NOT captured (httpx is instrumented without
`capture_all`). The console exporter is off — the Logfire UI is the view.

The service name comes from `LOGFIRE_SERVICE_NAME` (the Logfire SDK's own env
var; read via pydantic-settings, see `src/voca/.env`; default "voca-backend").

Offline safety: logfire disables sending while running under pytest by default
(`PYTEST_VERSION` guard in the SDK), so the test suite stays hermetic; tests
that assert on spans use the `capfire` fixture (see tests/test_telemetry.py).
"""

import logging

import logfire
from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()


class TelemetrySettings(BaseSettings):
    """Telemetry knobs; env vars are read with a LOGFIRE_ prefix (LOGFIRE_SERVICE_NAME)."""

    model_config = SettingsConfigDict(env_prefix="LOGFIRE_")

    service_name: str = "voca-backend"


SERVICE_NAME = TelemetrySettings().service_name

_configured = False


def configure_telemetry(app: FastAPI) -> None:
    """Configure Logfire once per process and attach every instrumentor.

    Must run before the app starts serving and before any agent runs; a second
    call is a no-op so re-imports (e.g. pytest sessions) never double-instrument.
    """
    global _configured
    if _configured:
        return

    logfire.configure(service_name=SERVICE_NAME, console=False)
    logfire.instrument_fastapi(app)
    # httpx instrumenting is library-wide: covers Supabase REST/auth calls and
    # Ollama requests (pydantic-ai's OpenAI-compatible model transport incl.).
    logfire.instrument_httpx()
    logfire.instrument_pydantic_ai(include_content=True)
    # Route stdlib `logging` records (e.g. logger.exception in voca.main) through.
    logging.getLogger().addHandler(logfire.LogfireLoggingHandler())

    _configured = True
