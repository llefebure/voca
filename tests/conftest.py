import pytest
from unittest.mock import MagicMock
import src.voca.services.supabase_client as supabase_client

@pytest.fixture
def mock_supabase():
    """Mocks the supabase client to avoid real DB calls during agent tests."""
    original_supabase = supabase_client.supabase
    mock = MagicMock()
    supabase_client.supabase = mock
    yield mock
    supabase_client.supabase = original_supabase
