"""Unit tests for the OpenRouter alert investigator."""

from __future__ import annotations

import copy
import json

import httpx
import pytest

from pypoe.lab.investigator import (
    DEFAULT_OPENROUTER_MODEL,
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
