"""Shared LLM configuration for all Voca agents (local Ollama server, OpenAI-compatible).

One lane, one model: every agent — the streaming tutor included — runs the same
cloud model. Native tool calling is what makes tutor-driven canvas panels
dependable, and the strong model does the tutor's job better too. Model settings
stay at their defaults; any "too slow" concern is raised from real use and
handled then, not pre-tuned here.
"""

import os

from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.providers.ollama import OllamaProvider

LLM_MODEL_NAME = os.getenv("LLM_MODEL", "gemma4:31b-cloud")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")


def _build_provider() -> OllamaProvider:
    kwargs: dict = {"base_url": LLM_BASE_URL}
    if os.getenv("VOCA_LLM_LOG") == "1":
        # Optional verbose request logging for debugging (also silences nothing
        # otherwise; the default client has no hooks).
        import httpx

        async def log_request(request: httpx.Request) -> None:
            body = (await request.aread()).decode(errors="replace")
            print(f"[llm] {request.method} {request.url}\n[llm] body: {body}")

        kwargs["http_client"] = httpx.AsyncClient(event_hooks={"request": [log_request]})
    return OllamaProvider(**kwargs)


# The single model every Voca agent speaks through.
voca_model = OllamaModel(
    LLM_MODEL_NAME,
    provider=_build_provider(),
)
