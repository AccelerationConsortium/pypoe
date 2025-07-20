"""
Tests for PyPoe optional integrations.
"""
import pytest
from unittest.mock import patch

def test_slack_bot_import_available():
    """Test that Slack bot can be imported when dependencies are available."""
    try:
        from pypoe.interfaces import slack
        # Should always be importable, even without dependencies
        assert hasattr(slack, 'SLACK_AVAILABLE')
        assert slack.SLACK_AVAILABLE is not None  # Could be True or False
    except ImportError:
        pytest.fail("slack interface module should always be importable, even without slack dependencies")

def test_slack_bot_import_graceful_failure():
    """Test that Slack bot handles missing dependencies gracefully."""
    with patch.dict('sys.modules', {'slack_bolt': None, 'slack_sdk': None}):
        from pypoe.interfaces import slack
        # Should be False when dependencies are missing
        
        # Should be able to import the module but accessing SlackBot should fail gracefully
        if hasattr(slack, 'SlackBot'):
            with pytest.raises(ImportError, match="Slack interface dependencies missing"):
                slack.SlackBot()

def test_cli_slack_command_import():
    """Test that CLI can be imported without errors."""
    try:
        from pypoe.core.cli import main
        # Should not raise import errors
    except ImportError:
        pytest.fail("CLI should always be importable") 