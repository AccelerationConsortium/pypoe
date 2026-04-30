"""
PyTest configuration and shared fixtures for PyPoe tests.
"""
import pytest
import os
from unittest.mock import patch

# Configure pytest for async tests
pytest_plugins = ['pytest_asyncio']

@pytest.fixture(scope="session")
def test_api_key():
    """Fixture providing a test API key."""
    return "test_api_key_12345"

@pytest.fixture
def mock_env_with_api_key(test_api_key):
    """Fixture that mocks environment with a valid API key."""
    with patch.dict(os.environ, {"POE_API_KEY": test_api_key}, clear=False):
        yield

@pytest.fixture
def mock_env_without_api_key():
    """Fixture that mocks environment without an API key."""
    # Create a copy of environment without POE_API_KEY
    env_copy = {k: v for k, v in os.environ.items() if k != "POE_API_KEY"}
    
    with patch.dict(os.environ, env_copy, clear=True), \
         patch('pypoe.core.config.load_dotenv') as mock_load_dotenv:
        # Mock load_dotenv to do nothing
        mock_load_dotenv.return_value = None
        yield 