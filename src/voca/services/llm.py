import os
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.providers.ollama import OllamaProvider

# Configure the shared Ollama model using environment variables
ollama_model = OllamaModel(
    os.getenv("LLM_MODEL", "granite4.2:3b"),
    provider=OllamaProvider(
        base_url=os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
    ),
)
