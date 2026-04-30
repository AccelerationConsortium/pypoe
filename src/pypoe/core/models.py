"""Chat-only Poe model catalog used by PyPoe interfaces."""

import math

CHAT_MODELS = [
    "Claude-Opus-4.7",
    "Claude-Sonnet-4.6",
    "GPT-5.5",
    "GPT-5.5-Pro",
    "GPT-4-Turbo",
    "Grok-4",
    "Gemini-3.1-Pro",
    "Gemini-3-Flash",
]

DEFAULT_CHAT_MODEL = "Claude-Sonnet-4.6"

# Static snapshot from https://models.poecdn.net/models.json, displayed by
# https://poe.com/api/models. Values are USD per 1M tokens.
MODEL_PRICING_USD_PER_1M_TOKENS = {
    "Claude-Opus-4.7": {"prompt": 4.2929, "completion": 21.4646},
    "Claude-Sonnet-4.6": {"prompt": 2.5758, "completion": 12.8788},
    "GPT-5.5": {"prompt": 4.5455, "completion": 27.2727},
    "GPT-5.5-Pro": {"prompt": 27.2727, "completion": 163.6364},
    "GPT-4-Turbo": {"prompt": 9.0909, "completion": 27.2727},
    "Grok-4": {"prompt": 3.0303, "completion": 15.1515},
    "Gemini-3.1-Pro": {"prompt": 2.0202, "completion": 12.1212},
    "Gemini-3-Flash": {"prompt": 0.4040, "completion": 2.4242},
}


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
