"""
Tests for PyPoe PoeChatClient core functionality.
"""
import pytest
import os
from unittest.mock import patch

from pypoe import PoeChatClient
from pypoe.core.models import DEFAULT_CHAT_MODEL
from .test_conf import test_api_key, mock_env_with_api_key, mock_env_without_api_key

def test_client_initialization_with_api_key(mock_env_with_api_key, test_api_key):
    """Test that PoeChatClient initializes correctly with API key."""
    client = PoeChatClient()
    assert client is not None
    assert client.config.poe_api_key == test_api_key

def test_client_initialization_missing_api_key(mock_env_without_api_key):
    """Test that client raises error when no provider is configured at all."""
    with pytest.raises(ValueError, match="No model provider is configured"):
        PoeChatClient()


def test_openrouter_alone_is_enough(mock_env_without_api_key):
    """A Poe-less deployment must start.

    Config() used to demand POE_API_KEY unconditionally, so every interface
    failed at startup even with OpenRouter configured — which is exactly the
    situation a lapsed Poe subscription creates.
    """
    with patch.dict(os.environ, {"OPENROUTER_API_KEY": "sk-or-test"}):
        client = PoeChatClient(enable_history=False)

    assert client.config.openrouter_api_key == "sk-or-test"
    assert client.config.poe_api_key == ""

def test_client_enable_history_flag(mock_env_with_api_key):
    """Test that history can be enabled/disabled during initialization."""
    client_with_history = PoeChatClient(enable_history=True)
    client_without_history = PoeChatClient(enable_history=False)
    
    # History availability depends on whether HistoryManager is available
    assert client_without_history.enable_history is False

@pytest.mark.asyncio
async def test_get_available_bots(mock_env_with_api_key):
    """Test getting available bots list."""
    client = PoeChatClient()
    
    bots = await client.get_available_bots()
    
    assert isinstance(bots, list)
    assert len(bots) > 0
    assert DEFAULT_CHAT_MODEL in bots

@pytest.mark.asyncio
async def test_client_close(mock_env_with_api_key):
    """Test that client can be closed properly."""
    client = PoeChatClient()
    
    # Should not raise any exceptions
    await client.close()
    
    # Multiple closes should be safe
    await client.close()

def test_client_api_key_property(mock_env_with_api_key, test_api_key):
    """Test that client exposes API key property correctly."""
    client = PoeChatClient()
    assert client.api_key == test_api_key 