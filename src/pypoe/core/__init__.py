"""
PyPoe Core Module

Contains the main POE client, history management, and database functionality.
"""

from .client import PoeChatClient
from .history import HistoryManager
from .config import Config, get_config
from .models import (
    CHAT_MODELS,
    DEFAULT_CHAT_MODEL,
    MODEL_PRICING_USD_PER_1M_TOKENS,
    format_model_price_marker,
    get_model_price_markers,
)
from .cli import main as cli_main

__all__ = [
    "PoeChatClient",
    "HistoryManager",
    "Config",
    "get_config",
    "CHAT_MODELS",
    "DEFAULT_CHAT_MODEL",
    "MODEL_PRICING_USD_PER_1M_TOKENS",
    "format_model_price_marker",
    "get_model_price_markers",
    "cli_main",
]