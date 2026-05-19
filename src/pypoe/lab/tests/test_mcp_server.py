"""Unit tests for ``pypoe.lab.mcp_server``.

Focused on the tool helpers that have non-trivial wiring:
``_consult_poe`` (calls PoeChatClient directly) and the surface
shape of the FastMCP server itself (tool list, no control_action).
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import AsyncIterator

import pytest

mcp_module = pytest.importorskip("mcp.server.fastmcp")

from pypoe.lab import mcp_server


async def _yield_chunks(*chunks: str) -> AsyncIterator[str]:
    for c in chunks:
        yield c


class _FakePoeChatClient:
    """Minimal PoeChatClient stand-in for testing ``_consult_poe``."""

    def __init__(
        self,
        *,
        chunks: tuple[str, ...] = (),
        raises: Exception | None = None,
        recorded: dict | None = None,
    ):
        self._chunks = chunks
        self._raises = raises
        self._recorded = recorded if recorded is not None else {}

    def __call__(self, *args, **kwargs):
        # Constructor; we record the kwargs the production code passes.
        self._recorded["init_kwargs"] = kwargs
        return self

    async def send_message(self, message, *, bot_name, save_history=True):
        self._recorded["prompt"] = message
        self._recorded["bot_name"] = bot_name
        self._recorded["save_history"] = save_history
        if self._raises:
            raise self._raises
        async for c in _yield_chunks(*self._chunks):
            yield c


def _install_fake_client(monkeypatch, fake: _FakePoeChatClient):
    """Replace ``from ..core.client import PoeChatClient`` for the duration."""
    fake_module = SimpleNamespace(PoeChatClient=fake)
    monkeypatch.setitem(sys.modules, "pypoe.core.client", fake_module)


@pytest.mark.asyncio
async def test_consult_poe_returns_concatenated_chunks(monkeypatch):
    recorded: dict = {}
    fake = _FakePoeChatClient(chunks=("Sounds ", "like ", "a COM driver bug."), recorded=recorded)
    _install_fake_client(monkeypatch, fake)

    result = await mcp_server._consult_poe(
        "Claude-Sonnet-4.6",
        "Is the plateloc failure a hardware or software issue?",
        "plateloc reports last_error.code='startup'",
    )

    assert result["model"] == "Claude-Sonnet-4.6"
    assert result["answer"] == "Sounds like a COM driver bug."
    assert result["returncode"] == 0
    assert result["stderr"] == ""

    # Prompt is context + blank line + question, per the documented shape.
    prompt = recorded["prompt"]
    assert prompt.startswith("plateloc reports")
    assert prompt.endswith("Is the plateloc failure a hardware or software issue?")
    assert "\n\n" in prompt
    # save_history MUST be False so a consult never pollutes PyPoe's chat DB.
    assert recorded["save_history"] is False
    assert recorded["bot_name"] == "Claude-Sonnet-4.6"
    # The lab integration owns its own ephemeral client.
    assert recorded["init_kwargs"].get("enable_history") is False


@pytest.mark.asyncio
async def test_consult_poe_no_context_passes_bare_question(monkeypatch):
    recorded: dict = {}
    fake = _FakePoeChatClient(chunks=("answer",), recorded=recorded)
    _install_fake_client(monkeypatch, fake)

    await mcp_server._consult_poe("GPT-5.5", "How safe?", None)
    assert recorded["prompt"] == "How safe?"


@pytest.mark.asyncio
async def test_consult_poe_surfaces_value_error_as_returncode_2(monkeypatch):
    """ValueError = caller-fixable (bad bot name, missing API key, quota)."""
    fake = _FakePoeChatClient(raises=ValueError("Bot 'NotARealBot' is not accessible"))
    _install_fake_client(monkeypatch, fake)

    result = await mcp_server._consult_poe("NotARealBot", "ping", None)
    assert result["answer"] == ""
    assert result["returncode"] == 2
    assert "NotARealBot" in result["stderr"]


@pytest.mark.asyncio
async def test_consult_poe_surfaces_unexpected_error_as_returncode_1(monkeypatch):
    fake = _FakePoeChatClient(raises=RuntimeError("network blip"))
    _install_fake_client(monkeypatch, fake)
    result = await mcp_server._consult_poe("GPT-5.5", "ping", None)
    assert result["answer"] == ""
    assert result["returncode"] == 1
    assert "RuntimeError" in result["stderr"]
    assert "network blip" in result["stderr"]


def test_build_server_registers_no_control_action():
    """Architectural guarantee: PyPoe MCP is read-only at the device level.

    Loading PoeChatClient requires its real dependencies, so we patch the
    LabClient with a no-op (only the catalog matters here, not real I/O).
    """
    import asyncio

    class _DummyLab:
        async def __aexit__(self, *a): return None
        async def aclose(self): return None

    server = mcp_server.build_server(client=_DummyLab())  # type: ignore[arg-type]
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert "control_action" not in names
    # Spot-check the documented surface.
    assert {"list_equipment", "get_equipment_status", "append_observation",
            "consult_poe", "ask_human"}.issubset(names)
