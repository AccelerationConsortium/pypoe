"""Per-model provider routing: roster parsing, transport choice, spend cap."""

from __future__ import annotations

import json

import pytest

from pypoe.core import models as models_mod
from pypoe.core.client import PoeChatClient
from pypoe.core.models import _parse_chat_models
from pypoe.core.provider_health import HealthRegistry
from pypoe.core.providers import (
    OPENROUTER,
    POE,
    PROVIDERS,
    ProviderError,
    configured_providers,
    stream_openai_compatible,
)


# --------------------------------------------------------------------------
# roster parsing
# --------------------------------------------------------------------------

def test_bare_strings_stay_poe():
    """Existing rosters keep working untouched."""
    ids, providers = _parse_chat_models(["Claude-Opus-4.8", "GPT-5.4"])
    assert ids == ["Claude-Opus-4.8", "GPT-5.4"]
    assert providers == {}          # unlisted => default provider (Poe)


def test_mapping_entries_carry_a_provider():
    ids, providers = _parse_chat_models(
        [
            "Claude-Opus-4.8",
            {"id": "anthropic/claude-opus-4.8", "provider": "openrouter"},
            {"id": "meta/llama-4", "provider": "OpenRouter"},   # case-insensitive
        ]
    )
    assert ids == ["Claude-Opus-4.8", "anthropic/claude-opus-4.8", "meta/llama-4"]
    assert providers == {
        "anthropic/claude-opus-4.8": OPENROUTER,
        "meta/llama-4": OPENROUTER,
    }


def test_malformed_entries_are_skipped_not_fatal():
    """A bad roster line must not take the whole process down at import."""
    ids, providers = _parse_chat_models(
        ["Good-Model", {"provider": "openrouter"}, 42, {"id": "", "provider": "x"}]
    )
    assert ids == ["Good-Model"]
    assert providers == {}


def test_empty_roster_falls_back(monkeypatch):
    ids, _ = _parse_chat_models([])
    assert ids == models_mod._FALLBACK_CHAT_MODELS


def test_provider_for_defaults_to_poe(monkeypatch):
    monkeypatch.setattr(
        models_mod, "MODEL_PROVIDERS", {"anthropic/claude-opus-4.8": OPENROUTER}
    )
    assert models_mod.provider_for("anthropic/claude-opus-4.8") == OPENROUTER
    # Free-text callers (CLI --bot, lab MCP consult_poe) still resolve.
    assert models_mod.provider_for("Something-Unlisted") == POE


# --------------------------------------------------------------------------
# transport selection
# --------------------------------------------------------------------------

def _client(monkeypatch, *, poe_key="poe-key", openrouter_key="sk-or", max_tokens=4096):
    client = object.__new__(PoeChatClient)
    client.config = type(
        "Cfg",
        (),
        {
            "poe_api_key": poe_key,
            "openrouter_api_key": openrouter_key,
            "openrouter_max_tokens": max_tokens,
        },
    )()
    client.api_key = poe_key
    client.content_processor = type("CP", (), {"should_filter_chunk": lambda self, t: False})()
    return client


@pytest.mark.asyncio
async def test_openrouter_model_uses_the_openai_compatible_path(monkeypatch):
    import pypoe.core.client as clientmod

    monkeypatch.setattr(clientmod, "provider_for", lambda m: OPENROUTER)
    monkeypatch.setattr(clientmod, "health", HealthRegistry())

    seen = {}

    async def _stream(spec, *, api_key, model, messages, max_tokens=None):
        seen.update(
            provider=spec.name, api_key=api_key, model=model,
            messages=messages, max_tokens=max_tokens,
        )
        for chunk in ("Hel", "lo"):
            yield chunk

    monkeypatch.setattr(clientmod, "stream_openai_compatible", _stream)

    client = _client(monkeypatch)
    out = [c async for c in client._stream(
        "anthropic/claude-opus-4.8", [{"role": "user", "content": "hi"}]
    )]

    assert "".join(out) == "Hello"
    assert seen["provider"] == OPENROUTER
    assert seen["api_key"] == "sk-or"
    # The spend ceiling is applied, not left to the provider's default.
    assert seen["max_tokens"] == 4096
    # OpenAI-compatible providers use "assistant" natively; the assistant->bot
    # rename is a Poe protocol quirk that must not leak here.
    assert seen["messages"] == [{"role": "user", "content": "hi"}]


@pytest.mark.asyncio
async def test_assistant_role_is_not_renamed_for_openrouter(monkeypatch):
    import pypoe.core.client as clientmod

    monkeypatch.setattr(clientmod, "provider_for", lambda m: OPENROUTER)
    monkeypatch.setattr(clientmod, "health", HealthRegistry())

    seen = {}

    async def _stream(spec, *, api_key, model, messages, max_tokens=None):
        seen["messages"] = messages
        return
        yield  # pragma: no cover

    monkeypatch.setattr(clientmod, "stream_openai_compatible", _stream)

    client = _client(monkeypatch)
    [c async for c in client._stream(
        "some/model",
        [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}],
    )]

    assert [m["role"] for m in seen["messages"]] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_max_tokens_cap_can_be_disabled(monkeypatch):
    import pypoe.core.client as clientmod

    monkeypatch.setattr(clientmod, "provider_for", lambda m: OPENROUTER)
    monkeypatch.setattr(clientmod, "health", HealthRegistry())

    seen = {}

    async def _stream(spec, *, api_key, model, messages, max_tokens=None):
        seen["max_tokens"] = max_tokens
        return
        yield  # pragma: no cover

    monkeypatch.setattr(clientmod, "stream_openai_compatible", _stream)

    client = _client(monkeypatch, max_tokens=0)
    [c async for c in client._stream("some/model", [{"role": "user", "content": "hi"}])]
    assert seen["max_tokens"] is None


@pytest.mark.asyncio
async def test_missing_key_for_a_routed_model_is_a_clear_error(monkeypatch):
    import pypoe.core.client as clientmod

    monkeypatch.setattr(clientmod, "provider_for", lambda m: OPENROUTER)
    monkeypatch.setattr(clientmod, "health", HealthRegistry())

    client = _client(monkeypatch, openrouter_key="")
    with pytest.raises(ValueError) as excinfo:
        [c async for c in client._stream("some/model", [{"role": "user", "content": "hi"}])]

    assert "OPENROUTER_API_KEY" in str(excinfo.value)
    assert "some/model" in str(excinfo.value)


@pytest.mark.asyncio
async def test_success_is_recorded_against_the_right_provider(monkeypatch):
    """A healthy OpenRouter call must not mark Poe healthy."""
    import pypoe.core.client as clientmod

    registry = HealthRegistry()
    monkeypatch.setattr(clientmod, "provider_for", lambda m: OPENROUTER)
    monkeypatch.setattr(clientmod, "health", registry)

    async def _stream(spec, **kwargs):
        yield "ok"

    monkeypatch.setattr(clientmod, "stream_openai_compatible", _stream)

    client = _client(monkeypatch)
    [c async for c in client._stream("some/model", [{"role": "user", "content": "hi"}])]

    assert registry.for_provider(OPENROUTER).snapshot().ok is True
    assert registry.for_provider(POE).snapshot().state == "unknown"


@pytest.mark.asyncio
async def test_failure_is_recorded_against_the_right_provider(monkeypatch):
    import pypoe.core.client as clientmod

    registry = HealthRegistry()
    monkeypatch.setattr(clientmod, "provider_for", lambda m: OPENROUTER)
    monkeypatch.setattr(clientmod, "health", registry)

    client = _client(monkeypatch)
    error = ProviderError(json.dumps({"error": {"message": "User not found.", "code": 401}}), 401)
    translated = await client._provider_error(error, "some/model")

    assert registry.for_provider(OPENROUTER).snapshot().code == "openrouter_auth_failed"
    assert registry.for_provider(POE).snapshot().state == "unknown"
    assert "OPENROUTER_API_KEY" in str(translated)


# --------------------------------------------------------------------------
# provider config
# --------------------------------------------------------------------------

def test_configured_providers_tracks_keys():
    cfg = type("Cfg", (), {"poe_api_key": "a", "openrouter_api_key": ""})()
    assert configured_providers(cfg) == [POE]

    cfg = type("Cfg", (), {"poe_api_key": "", "openrouter_api_key": "b"})()
    assert configured_providers(cfg) == [OPENROUTER]

    cfg = type("Cfg", (), {"poe_api_key": "a", "openrouter_api_key": "b"})()
    assert configured_providers(cfg) == [POE, OPENROUTER]


def test_only_openrouter_is_metered():
    """Drives whether a balance is even meaningful to ask for."""
    assert PROVIDERS[OPENROUTER].metered is True
    assert PROVIDERS[POE].metered is False


# --------------------------------------------------------------------------
# SSE parsing
# --------------------------------------------------------------------------

class _FakeStreamResponse:
    def __init__(self, lines, status_code=200, body=b""):
        self.status_code = status_code
        self._lines = lines
        self._body = body

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self):
        return self._body


class _FakeStreamClient:
    def __init__(self, response):
        self._response = response

    def __call__(self, *args, **kwargs):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def stream(self, *args, **kwargs):
        response = self._response

        class _Ctx:
            async def __aenter__(self):
                return response

            async def __aexit__(self, *exc):
                return False

        return _Ctx()


@pytest.mark.asyncio
async def test_sse_stream_yields_content_deltas(monkeypatch):
    import httpx

    lines = [
        'data: {"choices":[{"delta":{"role":"assistant"}}]}',
        'data: {"choices":[{"delta":{"content":"Hel"}}]}',
        "",
        'data: {"choices":[{"delta":{"content":"lo"}}]}',
        "data: [DONE]",
        'data: {"choices":[{"delta":{"content":"ignored after DONE"}}]}',
    ]
    monkeypatch.setattr(httpx, "AsyncClient", _FakeStreamClient(_FakeStreamResponse(lines)))

    chunks = [
        c
        async for c in stream_openai_compatible(
            PROVIDERS[OPENROUTER], api_key="k", model="m", messages=[]
        )
    ]
    assert "".join(chunks) == "Hello"


@pytest.mark.asyncio
async def test_sse_stream_raises_provider_error_on_http_error(monkeypatch):
    import httpx

    body = b'{"error": {"message": "User not found.", "code": 401}}'
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        _FakeStreamClient(_FakeStreamResponse([], status_code=401, body=body)),
    )

    with pytest.raises(ProviderError) as excinfo:
        [
            c
            async for c in stream_openai_compatible(
                PROVIDERS[OPENROUTER], api_key="k", model="m", messages=[]
            )
        ]
    assert excinfo.value.status_code == 401
    # str() is the raw JSON so it classifies through the shared path.
    assert json.loads(str(excinfo.value))["error"]["code"] == 401


@pytest.mark.asyncio
async def test_mid_stream_error_is_raised(monkeypatch):
    """An error can arrive after a 200 header; it must not look like success."""
    import httpx

    lines = [
        'data: {"choices":[{"delta":{"content":"partial"}}]}',
        'data: {"error":{"message":"rate limit","code":429}}',
    ]
    monkeypatch.setattr(httpx, "AsyncClient", _FakeStreamClient(_FakeStreamResponse(lines)))

    collected = []
    with pytest.raises(ProviderError):
        async for chunk in stream_openai_compatible(
            PROVIDERS[OPENROUTER], api_key="k", model="m", messages=[]
        ):
            collected.append(chunk)
    assert collected == ["partial"]
