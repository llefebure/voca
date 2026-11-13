"""Shared LLM configuration for all Voca agents (local Ollama, OpenAI-compatible).

Two model lanes:
- `ollama_model` — the fast, local chat model (streaming tutor, simple translate).
- `planning_model` — a cloud reasoning-grade model for the structured-output agents
  (session planner, post-session analyst): small local models are unreliable at
  schema-adherent JSON.
"""

import os

from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.settings import ModelSettings

LLM_MODEL_NAME = os.getenv("LLM_MODEL", "granite4.2:3b")
PLANNING_MODEL_NAME = os.getenv("LLM_PLANNING_MODEL", "gemma4:31b-cloud")
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


ollama_model = OllamaModel(
    LLM_MODEL_NAME,
    provider=_build_provider(),
    settings=ModelSettings(
        # Through the OpenAI-compat endpoint `think: false` is ignored; granite
        # "thinks" unless reasoning_effort=none — verified ~10-100x faster turns.
        extra_body={"reasoning_effort": "none"},
    ),
)

# No granite-specific settings here; gemma4's thinking is left on by default and
# can be tuned (e.g. `extra_body={"reasoning_effort": "none"}`) once proven costly.
planning_model = OllamaModel(
    PLANNING_MODEL_NAME,
    provider=_build_provider(),
)
