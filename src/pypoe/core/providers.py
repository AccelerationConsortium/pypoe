"""Model providers PyPoe can talk to, and the transport for each.

This is the provider seam CLAUDE.local.md **D6** contemplates, introduced for
a concrete reason: Poe's subscription lapsed and every chat call started
failing, so a second source of models had to be reachable without rewriting
the client.

Two providers ship today:

* **poe** — via ``fastapi_poe``. Kept on its native SDK rather than folded onto
  the OpenAI-compatible path below, because Poe's media bots (image/video
  generation) return markdown media links that :class:`ContentProcessor`
  understands, and that behaviour is worth preserving exactly.
* **openrouter** — via the OpenAI-compatible ``/chat/completions`` SSE stream.

Routing is **per model**, not global: every roster entry carries a provider
(see :mod:`pypoe.core.models`), so a Poe model and an OpenRouter model can be
used side by side — including as the two sides of a debate. The model id stays
the single identity for a conversation, which is what the history DB already
stores, so nothing downstream needs a new column.

Billing note that shapes the code below: Poe is a flat subscription, while
OpenRouter is **pay-per-token**. A runaway loop cannot overspend a
subscription but can drain OpenRouter credits, so the OpenRouter path carries
a ``max_tokens`` ceiling and a credits reading that ``/status`` surfaces.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

POE = "poe"
OPENROUTER = "openrouter"


@dataclass(frozen=True)
class ProviderSpec:
    """Static description of a model source."""

    name: str
    label: str
    #: OpenAI-compatible base URL. Poe has one too (used for health probes even
    #: though chat goes through fastapi_poe).
    base_url: str
    #: Config attribute on :class:`pypoe.core.config.Config` holding the key.
    api_key_field: str
    #: Env var the key comes from, quoted in operator-facing messages.
    api_key_env: str
    #: Where to go when the key is missing or rejected.
    signup_url: str
    #: True when spend is metered per token rather than by flat subscription.
    metered: bool = False
    #: Extra headers (OpenRouter asks callers to identify themselves).
    extra_headers: Dict[str, str] = field(default_factory=dict)


PROVIDERS: Dict[str, ProviderSpec] = {
    POE: ProviderSpec(
        name=POE,
        label="Poe",
        base_url="https://api.poe.com/v1",
        api_key_field="poe_api_key",
        api_key_env="POE_API_KEY",
        signup_url="https://poe.com/api_key",
    ),
    OPENROUTER: ProviderSpec(
        name=OPENROUTER,
        label="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_field="openrouter_api_key",
        api_key_env="OPENROUTER_API_KEY",
        signup_url="https://openrouter.ai/keys",
        metered=True,
        extra_headers={
            # OpenRouter uses these for attribution on its dashboard/leaderboards.
            "HTTP-Referer": "https://github.com/cyrilcaoyang/PyPoe",
            "X-Title": "PyPoe",
        },
    ),
}

DEFAULT_PROVIDER = POE


def get_provider(name: Optional[str]) -> ProviderSpec:
    """Look up a provider, falling back to Poe for unknown/blank names."""
    spec = PROVIDERS.get((name or "").strip().lower())
    return spec or PROVIDERS[DEFAULT_PROVIDER]


def api_key_for(spec: ProviderSpec, config: Any) -> str:
    """The configured key for ``spec``, or ``""`` when unset."""
    return getattr(config, spec.api_key_field, "") or ""


def configured_providers(config: Any) -> List[str]:
    """Provider names that currently have a key, in registry order."""
    return [name for name, spec in PROVIDERS.items() if api_key_for(spec, config)]


def _headers(spec: ProviderSpec, api_key: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        **spec.extra_headers,
    }


class ProviderError(Exception):
    """A provider returned a structured error.

    ``str()`` is the raw JSON body so it classifies through the same path as a
    ``fastapi_poe`` ``BotError`` (see :mod:`pypoe.core.provider_health`).
    """

    def __init__(self, payload: Any, status_code: Optional[int] = None):
        super().__init__(payload if isinstance(payload, str) else json.dumps(payload))
        self.status_code = status_code


async def stream_openai_compatible(
    spec: ProviderSpec,
    *,
    api_key: str,
    model: str,
    messages: List[Dict[str, str]],
    max_tokens: Optional[int] = None,
    timeout_s: float = 300.0,
) -> AsyncGenerator[str, None]:
    """Stream a chat completion over the OpenAI-compatible SSE protocol.

    Yields content deltas as they arrive. Raises :class:`ProviderError` with the
    provider's own JSON body on a non-2xx response, so the caller's existing
    classification path works unchanged for either provider.
    """
    import httpx

    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
    }
    if max_tokens:
        # The spend ceiling for metered providers; harmless elsewhere.
        payload["max_tokens"] = max_tokens

    url = f"{spec.base_url.rstrip('/')}/chat/completions"

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        async with client.stream(
            "POST", url, json=payload, headers=_headers(spec, api_key)
        ) as response:
            if response.status_code >= 400:
                body = await response.aread()
                raise ProviderError(
                    body.decode("utf-8", "replace"), status_code=response.status_code
                )

            async for line in response.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[len("data:") :].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except ValueError:
                    continue

                # An error can arrive mid-stream, after a 200 header.
                if isinstance(chunk, dict) and chunk.get("error"):
                    raise ProviderError(chunk)

                for choice in chunk.get("choices") or []:
                    delta = choice.get("delta") or {}
                    content = delta.get("content")
                    if content:
                        yield content


async def probe(
    spec: ProviderSpec,
    *,
    api_key: str,
    model: str,
    timeout_s: float = 8.0,
) -> Tuple[bool, Optional[int], Optional[Any]]:
    """Cheapest call that proves this provider will actually serve a request.

    Returns ``(ok, status_code, body)``; the caller classifies the body.

    Uses a ``max_tokens=1`` completion because that is the only call that
    exercises entitlement. Listing endpoints are useless for this: Poe's
    ``GET /v1/models`` returns HTTP 200 with the full roster even for an
    unsubscribed account, so it validates the key and nothing more.

    A *failing* probe is rejected before inference and costs nothing, which is
    what lets :mod:`pypoe.core.provider_health` re-check a broken provider
    often while re-checking a healthy one rarely.
    """
    import httpx

    url = f"{spec.base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.post(
                url, json=payload, headers=_headers(spec, api_key)
            )
    except Exception as exc:
        logger.debug("%s probe transport failure: %s", spec.name, exc)
        return False, None, {"__transport_error__": f"Could not reach {url}: {exc}"}

    if response.status_code < 400:
        return True, response.status_code, None

    try:
        body = response.json()
    except ValueError:
        body = None
    return False, response.status_code, body


async def fetch_credits(
    spec: ProviderSpec, *, api_key: str, timeout_s: float = 8.0
) -> Optional[Dict[str, float]]:
    """Remaining balance for a metered provider, or ``None`` if unavailable.

    Only OpenRouter exposes this; a flat-subscription provider has no balance
    to report, and asking would be meaningless rather than merely empty.
    """
    if not spec.metered:
        return None

    import httpx

    url = f"{spec.base_url.rstrip('/')}/credits"
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            response = await client.get(url, headers=_headers(spec, api_key))
        if response.status_code >= 400:
            return None
        body = response.json()
    except Exception as exc:
        logger.debug("%s credits lookup failed: %s", spec.name, exc)
        return None

    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        return None

    # OpenRouter reports cumulative grants and usage; the useful number is the
    # difference. Field names have moved around, so accept the known aliases.
    granted = _first_float(data, "total_credits", "limit", "credits")
    used = _first_float(data, "total_usage", "usage")
    if granted is None and used is None:
        return None

    result: Dict[str, float] = {}
    if granted is not None:
        result["granted"] = granted
    if used is not None:
        result["used"] = used
    if granted is not None and used is not None:
        result["remaining"] = round(granted - used, 4)
    return result or None


def _first_float(data: Dict[str, Any], *keys: str) -> Optional[float]:
    for key in keys:
        value = data.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return None
