"""Chat-only Poe model catalog used by PyPoe interfaces.

The list lives in ``src/pypoe/config/models.yaml`` (gitignored; copy
from ``models.example.yaml`` next to it). This module loads it at
import time and exposes the same three constants the rest of the
codebase has always imported:

  * ``CHAT_MODELS``
  * ``DEFAULT_CHAT_MODEL``
  * ``MODEL_PRICING_USD_PER_1M_TOKENS``

If the YAML is absent / malformed, the hardcoded fallback below is
used so existing deployments keep working without action.

Override the file location with ``PYPOE_MODELS_CONFIG=<path>``.
"""

import logging
import math
import os
from pathlib import Path

logger = logging.getLogger(__name__)


_FALLBACK_DEFAULT = "Claude-Opus-4.8"

_FALLBACK_CHAT_MODELS = [
    "Claude-Opus-4.8",
    "Claude-Sonnet-4.6",
    "Claude-Opus-4.7",
    "GPT-5.4",
    "GPT-4-Turbo",
    "Grok-4",
    "Gemini-3.1-Pro",
    "Gemini-3-Flash",
    "GLM-5.2",
    "Kimi-K3",
]

# Snapshot from https://models.poecdn.net/models.json on 2026-07-19;
# every priced entry is live on Poe. Keep in step with
# config/models.example.yaml. Kimi-K3 is a live Poe bot not yet in the
# pricing feed, so it ships in the roster but carries no price entry.
_FALLBACK_PRICING = {
    "Claude-Opus-4.8":    {"prompt": 4.2929,  "completion": 21.4646},
    "Claude-Sonnet-4.6":  {"prompt": 2.5758,  "completion": 12.8788},
    "Claude-Opus-4.7":    {"prompt": 4.2929,  "completion": 21.4646},
    "GPT-5.4":            {"prompt": 2.2727,  "completion": 13.6364},
    "GPT-4-Turbo":        {"prompt": 9.0909,  "completion": 27.2727},
    "Grok-4":             {"prompt": 3.0303,  "completion": 15.1515},
    "Gemini-3.1-Pro":     {"prompt": 2.0202,  "completion": 12.1212},
    "Gemini-3-Flash":     {"prompt": 0.4040,  "completion": 2.4242},
    "GLM-5.2":            {"prompt": 1.4141,  "completion": 4.4444},
}


def _config_path() -> Path:
    """``src/pypoe/config/models.yaml`` (sibling of ``core/``)."""
    custom = os.environ.get("PYPOE_MODELS_CONFIG")
    if custom:
        return Path(custom).expanduser().resolve()
    return Path(__file__).resolve().parent.parent / "config" / "models.yaml"


def _load() -> tuple[list[str], str, dict]:
    """Read models.yaml; on any failure fall back to the hardcoded values."""
    path = _config_path()
    if not path.is_file():
        return _FALLBACK_CHAT_MODELS, _FALLBACK_DEFAULT, _FALLBACK_PRICING

    try:
        import yaml  # PyYAML is a transitive dep of pypoe[web-ui]/[lab]
    except ImportError:
        logger.debug("PyYAML not available; using hardcoded model list")
        return _FALLBACK_CHAT_MODELS, _FALLBACK_DEFAULT, _FALLBACK_PRICING

    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except Exception as exc:
        logger.warning("Could not parse %s (%s) — using hardcoded model list", path, exc)
        return _FALLBACK_CHAT_MODELS, _FALLBACK_DEFAULT, _FALLBACK_PRICING

    chat_models = data.get("chat_models")
    if not isinstance(chat_models, list) or not all(isinstance(m, str) for m in chat_models):
        chat_models = _FALLBACK_CHAT_MODELS

    default = data.get("default") if isinstance(data.get("default"), str) else _FALLBACK_DEFAULT
    pricing = data.get("pricing_usd_per_1m_tokens")
    if not isinstance(pricing, dict):
        pricing = _FALLBACK_PRICING

    return list(chat_models), default, pricing


CHAT_MODELS, DEFAULT_CHAT_MODEL, MODEL_PRICING_USD_PER_1M_TOKENS = _load()


def dollar_meter(rate_per_1m_tokens: float) -> str:
    """Return one '$' per $1.00 per 1M tokens."""
    if rate_per_1m_tokens <= 0:
        return "-"
    return "$" * max(1, math.ceil(rate_per_1m_tokens))


def get_model_price_markers(model: str) -> tuple[str, str]:
    """Return prompt/completion dollar-sign markers for a model."""
    pricing = MODEL_PRICING_USD_PER_1M_TOKENS.get(model)
    if not pricing:
        return ("?", "?")

    return (
        dollar_meter(pricing["prompt"]),
        dollar_meter(pricing["completion"]),
    )


def format_model_price_marker(model: str) -> str:
    """Format Slack-friendly prompt/completion price markers."""
    prompt, completion = get_model_price_markers(model)
    if prompt == "?" or completion == "?":
        return "price unknown"
    return f"in {prompt} / out {completion}"
