"""
PyPoe - Python client for Poe.com using the official API

This package provides a clean, async interface for interacting with Poe bots
including GPT-4, Claude, and more, with optional conversation history management.

Package Structure:
- core: Core API client and functionality (always available)
- interfaces: Web and Slack interfaces (requires pypoe[web-ui])
- examples: Example scripts and demonstrations (always available)
- scripts: Setup and utility scripts (always available)
- tests: Test suites (always available)
"""

from .core.config import Config, get_config

# Core POE functionality (always available)
from .core import PoeChatClient, HistoryManager

# Examples, scripts, and tests (always available)
from . import examples, scripts, tests

__all__ = ["Config", "get_config", "PoeChatClient", "HistoryManager", "examples", "scripts", "tests"]

# Interfaces (optional - requires web-ui dependencies)
try:
    from . import interfaces
    __all__.append("interfaces")
except ImportError:
    # Interfaces not available without [web-ui] dependencies
    pass

__version__ = "2.0.0"