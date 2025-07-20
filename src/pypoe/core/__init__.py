"""
PyPoe Core Module

Contains the main POE client, history management, and database functionality.
"""

from .client import PoeChatClient
from .history import HistoryManager
from .config import Config, get_config
from .cli import main as cli_main

__all__ = ["PoeChatClient", "HistoryManager", "Config", "get_config", "cli_main"] 