"""Unit tests for the OpenRouter alert investigator."""

from __future__ import annotations

import copy
import json
from dataclasses import replace

import httpx
import pytest

from pypoe.core.providers import ProviderError
from pypoe.lab import investigator
from pypoe.lab.config import load_config
from pypoe.lab.investigator import (
    DEFAULT_OPENROUTER_MODEL,
    RETRY_DELAYS_S,
    _is_retryable,
    investigation_models,
    resolve_investigation_model,
    run_investigation,
)


def test_resolve_investigation_model_prefixes_short_ids():
    assert resolve_investigation_model("gpt-5.6-luna") == "openai/gpt-5.6-luna"
    assert resolve_investigation_model("openai/gpt-5.6-luna") == "openai/gpt-5.6-luna"
    assert resolve_investigation_model("") == DEFAULT_OPENROUTER_MODEL


@pytest.mark.asyncio
async def test_run_investigation_requires_openrouter_key(monkeypatch):
    monkeypatch.setattr(
        "pypoe.lab.investigator.get_config",
        lambda: type("Cfg", (), {"openrouter_api_key": "", "openrouter_max_tokens": 256})(),
    )
    out = await run_investigation("look at ot2_hte", api_key="")
    assert "OPENROUTER_API_KEY" in out


class _Lab:
    async def health(self):
        return {"status": "ok", "equipment_count": 2}

    async def aclose(self):
        return None


class _ScriptedHTTP:
    def __init__(self, replies):
        self.replies = list(replies)
        self.payloads = []

    async def post(self, url, json=None, headers=None, timeout=None):
        self.payloads.append(copy.deepcopy(json))
        reply = self.replies.pop(0)
        return httpx.Response(200, json=reply)

    async def aclose(self):
        return None


@pytest.mark.asyncio
async def test_run_investigation_tool_loop_then_summary(monkeypatch):
    http = _ScriptedHTTP(
        [
            {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "aggregator_health",
                                        "arguments": "{}",
                                    },
                                }
                            ],
                        }
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {
                            "content": "Lead investigator: aggregator is healthy.",
                        }
                    }
                ]
            },
        ]
    )
    monkeypatch.setattr(
        "pypoe.lab.investigator.get_config",
        lambda: type("Cfg", (), {"openrouter_api_key": "sk-or-test", "openrouter_max_tokens": 256})(),
    )

    out = await run_investigation(
        "investigate aggregator",
        lab=_Lab(),  # type: ignore[arg-type]
        api_key="sk-or-test",
        http_client=http,  # type: ignore[arg-type]
    )
    assert out == "Lead investigator: aggregator is healthy."
    first = http.payloads[0]
    assert first["model"] == "openai/gpt-5.6-luna"
    assert first["reasoning"]["effort"] == "max"
    assert first["tools"]
    tool_msg = http.payloads[1]["messages"][-1]
    assert tool_msg["role"] == "tool"
    assert json.loads(tool_msg["content"])["status"] == "ok"


@pytest.mark.asyncio
async def test_run_investigation_reports_provider_error(monkeypatch):
    class _FailHTTP:
        async def post(self, url, json=None, headers=None, timeout=None):
            return httpx.Response(401, text='{"error":{"message":"invalid key"}}')

        async def aclose(self):
            return None

    monkeypatch.setattr(
        "pypoe.lab.investigator.get_config",
        lambda: type("Cfg", (), {"openrouter_api_key": "sk-or-test", "openrouter_max_tokens": 256})(),
    )
    out = await run_investigation(
        "investigate",
        lab=_Lab(),  # type: ignore[arg-type]
        api_key="sk-or-test",
        http_client=_FailHTTP(),  # type: ignore[arg-type]
    )
    assert out.startswith(":x: OpenRouter investigator failed:")


@pytest.mark.asyncio
async def test_run_investigation_unknown_tool_is_reported(monkeypatch):
    http = _ScriptedHTTP(
        [
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": "call_x",
                                    "function": {"name": "explode_reactor", "arguments": "{}"},
                                }
                            ]
                        }
                    }
                ]
            },
            {"choices": [{"message": {"content": "unconfirmed"}}]},
        ]
    )
    monkeypatch.setattr(
        "pypoe.lab.investigator.get_config",
        lambda: type("Cfg", (), {"openrouter_api_key": "sk-or-test", "openrouter_max_tokens": 256})(),
    )
    out = await run_investigation(
        "investigate",
        lab=_Lab(),  # type: ignore[arg-type]
        api_key="sk-or-test",
        http_client=http,  # type: ignore[arg-type]
    )
    assert out == "unconfirmed"
    assert "unknown tool" in http.payloads[1]["messages"][-1]["content"]


class _Alerts:
    """Minimal stand-in for ``LabConfig.alerts``."""

    def __init__(self, model="gpt-5.6-luna", fallbacks=()):
        self.investigation_model = model
        self.investigation_fallback_models = tuple(fallbacks)


def test_investigation_models_appends_deduped_fallbacks():
    models = investigation_models(
        _Alerts(fallbacks=("anthropic/claude-sonnet-5", "gpt-5.6-luna", "z-ai/glm-5.3"))
    )
    assert models == [
        "openai/gpt-5.6-luna",
        "anthropic/claude-sonnet-5",
        "z-ai/glm-5.3",
    ]
    assert investigation_models(_Alerts()) == ["openai/gpt-5.6-luna"]


def test_is_retryable_reads_status_and_body_codes():
    assert _is_retryable(ProviderError("boom", status_code=429))
    assert _is_retryable(ProviderError({"error": {"code": 429}}))
    assert not _is_retryable(ProviderError("bad key", status_code=401))
    assert not _is_retryable(ProviderError({"error": {"code": 404}}))


class _RateLimitedHTTP:
    """429s the named models; answers on anything else."""

    def __init__(self, limited):
        self.limited = set(limited)
        self.models = []

    async def post(self, url, json=None, headers=None, timeout=None):
        model = json["model"]
        self.models.append(model)
        if model in self.limited:
            return httpx.Response(
                200,
                json={
                    "id": "gen-1",
                    "error": {
                        "message": f"{model} is temporarily rate-limited upstream.",
                        "code": 429,
                    },
                },
            )
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "aggregator is healthy."}}]}
        )

    async def aclose(self):
        return None


def _patch_cfg(monkeypatch, fallbacks=("anthropic/claude-sonnet-5",)):
    monkeypatch.setattr(
        "pypoe.lab.investigator.get_config",
        lambda: type(
            "Cfg", (), {"openrouter_api_key": "sk-or-test", "openrouter_max_tokens": 256}
        )(),
    )
    cfg = load_config()
    alerts = replace(cfg.alerts, investigation_fallback_models=tuple(fallbacks))
    monkeypatch.setattr(
        "pypoe.lab.investigator.load_config", lambda: replace(cfg, alerts=alerts)
    )
    # Zero the backoff instead of patching asyncio.sleep: the delays are read
    # from the module at call time, and the event loop keeps its real sleep.
    monkeypatch.setattr(investigator, "RETRY_DELAYS_S", (0.0,) * len(RETRY_DELAYS_S))


@pytest.mark.asyncio
async def test_run_investigation_fails_over_to_next_model(monkeypatch):
    _patch_cfg(monkeypatch)
    http = _RateLimitedHTTP({"openai/gpt-5.6-luna"})

    out = await run_investigation(
        "investigate",
        lab=_Lab(),  # type: ignore[arg-type]
        api_key="sk-or-test",
        http_client=http,  # type: ignore[arg-type]
    )

    # Primary retried (1 + len(RETRY_DELAYS_S)) times, then the fallback answered.
    assert http.models == ["openai/gpt-5.6-luna"] * (len(RETRY_DELAYS_S) + 1) + [
        "anthropic/claude-sonnet-5"
    ]
    assert out.startswith("_Lead investigator fell back to `anthropic/claude-sonnet-5`")
    assert "aggregator is healthy." in out


@pytest.mark.asyncio
async def test_run_investigation_reports_when_every_model_is_limited(monkeypatch):
    _patch_cfg(monkeypatch)
    http = _RateLimitedHTTP({"openai/gpt-5.6-luna", "anthropic/claude-sonnet-5"})

    out = await run_investigation(
        "investigate",
        lab=_Lab(),  # type: ignore[arg-type]
        api_key="sk-or-test",
        http_client=http,  # type: ignore[arg-type]
    )

    assert "every model was rate-limited or unavailable" in out
    assert "`openai/gpt-5.6-luna`" in out and "`anthropic/claude-sonnet-5`" in out


@pytest.mark.asyncio
async def test_run_investigation_does_not_retry_a_bad_key(monkeypatch):
    _patch_cfg(monkeypatch)

    class _BadKeyHTTP:
        def __init__(self):
            self.calls = 0

        async def post(self, url, json=None, headers=None, timeout=None):
            self.calls += 1
            return httpx.Response(401, text='{"error":{"message":"invalid key"}}')

        async def aclose(self):
            return None

    http = _BadKeyHTTP()
    out = await run_investigation(
        "investigate",
        lab=_Lab(),  # type: ignore[arg-type]
        api_key="sk-or-test",
        http_client=http,  # type: ignore[arg-type]
    )
    assert http.calls == 1
    assert out.startswith(":x: OpenRouter investigator failed:")


@pytest.mark.asyncio
async def test_failover_sticks_for_later_tool_rounds(monkeypatch):
    """Once a fallback answers, later rounds must not re-pay the primary's backoff."""
    _patch_cfg(monkeypatch)

    class _ToolThenSummary(_RateLimitedHTTP):
        def __init__(self, limited):
            super().__init__(limited)
            self.answers = 0

        async def post(self, url, json=None, headers=None, timeout=None):
            if json["model"] in self.limited:
                return await super().post(url, json=json)
            self.models.append(json["model"])
            self.answers += 1
            if self.answers == 1:
                return httpx.Response(
                    200,
                    json={
                        "choices": [
                            {
                                "message": {
                                    "tool_calls": [
                                        {
                                            "id": "call_1",
                                            "function": {
                                                "name": "aggregator_health",
                                                "arguments": "{}",
                                            },
                                        }
                                    ]
                                }
                            }
                        ]
                    },
                )
            return httpx.Response(
                200, json={"choices": [{"message": {"content": "healthy."}}]}
            )

    http = _ToolThenSummary({"openai/gpt-5.6-luna"})
    out = await run_investigation(
        "investigate",
        lab=_Lab(),  # type: ignore[arg-type]
        api_key="sk-or-test",
        http_client=http,  # type: ignore[arg-type]
    )

    assert "healthy." in out
    # The primary is tried only in the first round, not again for round two.
    assert http.models.count("openai/gpt-5.6-luna") == len(RETRY_DELAYS_S) + 1
    assert http.models.count("anthropic/claude-sonnet-5") == 2
