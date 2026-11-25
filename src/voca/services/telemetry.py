"""Logfire (OpenTelemetry) telemetry for the FastAPI backend.

`configure_telemetry(app)` is called once in `voca.main` at import time, before
serving. FastAPI request handling, outgoing httpx calls (Supabase, Ollama), and
Pydantic AI agent runs (tutor, session planner, post-session analyst,
translator) then all appear as spans; Python `logging` records from `voca.*`
loggers are routed through Logfire too.

Privacy defaults: HTTP request bodies/headers and LLM prompt/completion content
are NOT captured (`include_content=False`), so user chat text stays out of
telemetry. The console exporter is off — the Logfire UI is the view. To capture
model prompts/completions, flip `include_content` to True here.

Offline safety: logfire disables sending while running under pytest by default
(`PYTEST_VERSION` guard in the SDK), so the test suite stays hermetic; tests
that assert on spans use the `capfire` fixture (see tests/test_telemetry.py).
"""

import logging

import logfire
from fastapi import FastAPI

SERVICE_NAME = "voca-backend"

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
    logfire.instrument_pydantic_ai(include_content=False)
    # Route stdlib `logging` records (e.g. logger.exception in voca.main) through.
    logging.getLogger().addHandler(logfire.LogfireLoggingHandler())

    _configured = True
