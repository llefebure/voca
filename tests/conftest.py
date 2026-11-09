import pytest
import httpx
import logging
from unittest.mock import MagicMock
import src.voca.services.supabase_client as supabase_client

# Set up logging for HTTP requests
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("httpx_instrumentation")

@pytest.fixture(autouse=True)
def instrument_httpx(monkeypatch):
    """Logs all httpx requests and responses."""
    original_send_async = httpx.AsyncClient.send

    async def patched_send_async(self, request, **kwargs):
        logger.info(f"--- HTTP Request ---")
        logger.info(f"Method: {request.method}")
        logger.info(f"URL: {request.url}")
        if request.content:
            logger.info(f"Body: {request.content.decode(errors='replace')}")
        else:
            logger.info(f"Body: None")

        response = await original_send_async(self, request, **kwargs)

        logger.info(f"--- HTTP Response ---")
        logger.info(f"Status: {response.status_code}")
        try:
            # Accessing .text reads the response body
            logger.info(f"Body: {response.text}")
        except Exception as e:
            logger.info(f"Could not log body: {e}")

        return response

    monkeypatch.setattr(httpx.AsyncClient, "send", patched_send_async)

    original_send_sync = httpx.Client.send

    def patched_send_sync(self, request, **kwargs):
        logger.info(f"--- HTTP Request ---")
        logger.info(f"Method: {request.method}")
        logger.info(f"URL: {request.url}")
        if request.content:
            logger.info(f"Body: {request.content.decode(errors='replace')}")

        response = original_send_sync(self, request, **kwargs)

        logger.info(f"--- HTTP Response ---")
        logger.info(f"Status: {response.status_code}")
        try:
            logger.info(f"Body: {response.text}")
        except Exception as e:
            logger.info(f"Could not log body: {e}")

        return response

    monkeypatch.setattr(httpx.Client, "send", patched_send_sync)

@pytest.fixture
def mock_supabase():
    """Mocks the supabase client to avoid real DB calls during agent tests."""
    original_supabase = supabase_client.supabase
    mock = MagicMock()
    supabase_client.supabase = mock
    yield mock
    supabase_client.supabase = original_supabase
