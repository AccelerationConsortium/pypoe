"""Unit tests for ``pypoe.lab.alert_routes``.

Uses FastAPI's TestClient + monkeypatches the Slack post + claude
subprocess so the test never touches the network or the shell.
"""

from __future__ import annotations

import asyncio
import json

import pytest

fastapi = pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pypoe.lab import alert_routes
from pypoe.lab.config import reload_config
from pypoe.lab.http_client import LabClient


def _mk_app(monkeypatch, *, claude_output: str = "Investigation summary"):
    posted: list[dict] = []
    investigations: list[str] = []

    async def fake_post_slack(channel, text, thread_ts=None):
        posted.append(
            {"channel": channel, "text": text, "thread_ts": thread_ts}
        )
        return f"ts-{len(posted)}"

    async def fake_run_claude(prompt):
        investigations.append(prompt)
        return claude_output

    monkeypatch.setattr(alert_routes, "_post_slack", fake_post_slack)
    monkeypatch.setattr(alert_routes, "_run_claude", fake_run_claude)

    fastapi_app = FastAPI()
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json={}))
    lab = LabClient(
        base_url="http://test",
        client=httpx.AsyncClient(base_url="http://test", transport=transport),
    )
    alert_routes.register_alert_routes(
        fastapi_app, client=lab, max_concurrent=2, slack_channel="#test"
    )
    return fastapi_app, posted, investigations


def test_build_prompt_with_models_lists_each_model():
    """The synthesised prompt MUST mention every configured consult model."""
    prompt = alert_routes._build_investigation_prompt(
        monitor="plateloc",
        msg="No response from COM3",
        consult_models=("GPT-5.5", "Claude-Opus-4.7", "Gemini-3.1-Pro"),
    )
    assert "plateloc" in prompt
    assert "No response from COM3" in prompt
    # Each model name appears in the listed block.
    for m in ("GPT-5.5", "Claude-Opus-4.7", "Gemini-3.1-Pro"):
        assert m in prompt
    # Consult-block instructions present.
    assert "consult_poe" in prompt
    assert "synthesised" in prompt or "synthesis" in prompt.lower()
    # Don't propose calling /control/*.
    assert "do not propose" in prompt.lower()


def test_build_prompt_no_models_uses_solo_block():
    """Empty model list → no consult step, no synthesis block."""
    prompt = alert_routes._build_investigation_prompt(
        monitor="aggregator",
        msg="down",
        consult_models=(),
    )
    assert "Skip Poe consultation" in prompt
    # Solo tail = 2-4 line summary instruction, no synthesis bullet rules.
    assert "consult_poe" not in prompt
    assert "synthesis" not in prompt.lower()


def test_kuma_webhook_down_posts_investigating_then_summary(monkeypatch):
    app, posted, investigations = _mk_app(
        monkeypatch, claude_output="Summary lines here"
    )

    with TestClient(app) as client:
        resp = client.post(
            "/alerts/kuma",
            json={
                "heartbeat": {"status": 0, "msg": "connection refused"},
                "monitor": {"name": "aggregator"},
                "msg": "connection refused",
            },
        )
    assert resp.status_code == 202
    body = resp.json()
    assert body["action"] == "investigating"
    assert body["monitor"] == "aggregator"

    # First post is the rotating-light line.
    assert posted, "expected at least one Slack post"
    assert "Investigating" in posted[0]["text"]
    assert posted[0]["channel"] == "#test"
    assert posted[0]["thread_ts"] is None

    # The background task should have run after the TestClient context
    # closed (which awaits all pending tasks). The captured value is the
    # fully built prompt, which must carry the monitor, the message, and
    # the default consult models (ConsultSection — see pypoe.lab.config).
    assert len(investigations) == 1
    prompt = investigations[0]
    assert "aggregator" in prompt
    assert "connection refused" in prompt
    assert "GPT-5.5" in prompt and "Claude-Opus-4.7" in prompt
    assert len(posted) == 2
    threaded = posted[1]
    assert threaded["thread_ts"] == "ts-1"  # threaded under the first message
    assert "Summary lines here" in threaded["text"]


def test_kuma_webhook_recovery_posts_recovery_only(monkeypatch):
    app, posted, investigations = _mk_app(monkeypatch)

    with TestClient(app) as client:
        resp = client.post(
            "/alerts/kuma",
            json={
                "heartbeat": {"status": 1, "msg": "back up"},
                "monitor": {"name": "aggregator"},
                "msg": "back up",
            },
        )
    assert resp.status_code == 202
    assert resp.json()["action"] == "recovered"
    assert len(posted) == 1
    assert "recovered" in posted[0]["text"]
    # No investigation kicked off on recovery.
    assert investigations == []


def test_kuma_webhook_truncates_long_claude_output(monkeypatch):
    long_text = "x" * 5000
    app, posted, _ = _mk_app(monkeypatch, claude_output=long_text)
    with TestClient(app) as client:
        client.post(
            "/alerts/kuma",
            json={
                "heartbeat": {"status": 0, "msg": "down"},
                "monitor": {"name": "any"},
            },
        )
    # Two posts; second is the threaded reply, which must be truncated.
    threaded = posted[1]
    assert "(truncated)" in threaded["text"]
    assert len(threaded["text"]) <= alert_routes._MAX_CLAUDE_OUTPUT_CHARS


def test_device_alert_down_posts_investigating_then_summary(monkeypatch):
    app, posted, investigations = _mk_app(
        monkeypatch, claude_output="Device diagnosis"
    )

    with TestClient(app) as client:
        resp = client.post(
            "/alerts/device",
            json={
                "device_id": "plateloc",
                "event": "error",
                "state": "error",
                "message": "COM timeout",
                "last_error": {"code": "com_other", "message": "COM timeout"},
            },
        )
    assert resp.status_code == 202
    body = resp.json()
    assert body["action"] == "investigating"
    assert body["device"] == "plateloc"

    assert "plateloc" in posted[0]["text"]
    assert "ERROR" in posted[0]["text"]
    assert "Investigating" in posted[0]["text"]

    # Prompt is device-focused: targets the device, carries last_error.
    assert len(investigations) == 1
    prompt = investigations[0]
    assert 'get_equipment_status("plateloc")' in prompt
    assert "com_other" in prompt

    threaded = posted[1]
    assert threaded["thread_ts"] == "ts-1"
    assert "Device diagnosis" in threaded["text"]


def test_device_alert_storm_mentions_other_devices(monkeypatch):
    app, posted, investigations = _mk_app(monkeypatch)

    with TestClient(app) as client:
        resp = client.post(
            "/alerts/device",
            json={
                "device_id": "ot2_hte",
                "event": "unreachable",
                "message": "3 devices down in one sweep",
                "devices": ["plateloc", "cytation_5"],
            },
        )
    assert resp.status_code == 202
    assert "(+2 more)" in posted[0]["text"]
    prompt = investigations[0]
    assert "plateloc" in prompt and "cytation_5" in prompt


def test_device_alert_recovery_posts_recovery_only(monkeypatch):
    app, posted, investigations = _mk_app(monkeypatch)

    with TestClient(app) as client:
        resp = client.post(
            "/alerts/device",
            json={
                "device_id": "plateloc",
                "event": "recovered",
                "message": "back to ready",
            },
        )
    assert resp.status_code == 202
    assert resp.json()["action"] == "recovered"
    assert len(posted) == 1
    assert "recovered" in posted[0]["text"]
    assert investigations == []


def test_device_alert_rejects_unknown_event(monkeypatch):
    app, posted, investigations = _mk_app(monkeypatch)

    with TestClient(app) as client:
        resp = client.post(
            "/alerts/device",
            json={"device_id": "plateloc", "event": "exploded"},
        )
    assert resp.status_code == 422
    assert posted == []
    assert investigations == []


def test_concurrency_bound_is_respected(monkeypatch):
    """Two simultaneous alerts shouldn't run more than `max_concurrent` claude
    subprocesses in parallel. Verified via observable peak concurrency."""

    async def main():
        peak = {"value": 0, "current": 0, "lock": asyncio.Lock()}
        ready = asyncio.Event()
        release = asyncio.Event()

        async def fake_post_slack(channel, text, thread_ts=None):
            return "ts"

        async def fake_run_claude(prompt):
            async with peak["lock"]:
                peak["current"] += 1
                peak["value"] = max(peak["value"], peak["current"])
                if peak["current"] >= 2:
                    ready.set()
            await release.wait()
            async with peak["lock"]:
                peak["current"] -= 1
            return "done"

        monkeypatch.setattr(alert_routes, "_post_slack", fake_post_slack)
        monkeypatch.setattr(alert_routes, "_run_claude", fake_run_claude)

        fastapi_app = FastAPI()
        transport = httpx.MockTransport(
            lambda r: httpx.Response(200, json={})
        )
        lab = LabClient(
            base_url="http://test",
            client=httpx.AsyncClient(base_url="http://test", transport=transport),
        )
        alert_routes.register_alert_routes(
            fastapi_app, client=lab, max_concurrent=2, slack_channel="#test"
        )

        from fastapi.testclient import TestClient

        with TestClient(fastapi_app) as tc:
            for _ in range(4):
                tc.post(
                    "/alerts/kuma",
                    json={
                        "heartbeat": {"status": 0, "msg": "down"},
                        "monitor": {"name": "x"},
                    },
                )
            # Give the background tasks a moment to start; release them
            # so the TestClient teardown can finish.
            try:
                await asyncio.wait_for(ready.wait(), timeout=2.0)
            finally:
                release.set()
        return peak["value"]

    peak = asyncio.run(main())
    assert peak <= 2, f"peak concurrency {peak} exceeded max_concurrent=2"


# ---------------------------------------------------------------------------
# _run_claude hardening (model pin, strict MCP config, cwd isolation, timeout)
# ---------------------------------------------------------------------------


class _FakeProc:
    def __init__(self, out=b"ok summary", err=b"", returncode=0):
        self._out = out
        self._err = err
        self.returncode = returncode

    async def communicate(self):
        return (self._out, self._err)

    async def wait(self):
        return self.returncode


def test_run_claude_builds_hardened_command(monkeypatch, tmp_path):
    """The investigation subprocess pins a model, injects only the pypoe-lab
    MCP server strictly, runs outside the repo tree, and carries a system
    prompt — matching the dashboard assistant's safeguards."""

    captured: dict = {}

    async def fake_exec(*args, **kwargs):
        captured["args"] = list(args)
        captured["cwd"] = kwargs.get("cwd")
        return _FakeProc(out=b"root cause: air pressure")

    # Deterministic config (no packaged slack.yaml), isolated runtime dir.
    monkeypatch.setenv("PYPOE_LAB_CONFIG", str(tmp_path / "no-such.yaml"))
    monkeypatch.setenv("PYPOE_INVESTIGATOR_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("LAB_INVESTIGATION_MODEL", "sonnet")
    reload_config()
    monkeypatch.setattr(alert_routes, "_claude_binary", lambda: "/usr/bin/claude")
    monkeypatch.setattr(alert_routes.asyncio, "create_subprocess_exec", fake_exec)

    try:
        out = asyncio.run(alert_routes._run_claude("investigate ot2_hte"))
    finally:
        reload_config()

    args = captured["args"]
    assert args[0] == "/usr/bin/claude"
    assert "-p" in args and "investigate ot2_hte" in args
    assert args[args.index("--model") + 1] == "sonnet"
    assert "--strict-mcp-config" in args
    assert "--append-system-prompt" in args
    assert args[args.index("--allowedTools") + 1] == "mcp__pypoe-lab__*"
    # cwd is the isolated runtime dir, not the repo tree.
    assert captured["cwd"] == str(tmp_path)
    # An explicit, strict mcp.json was written for exactly the pypoe-lab server.
    mcp_path = args[args.index("--mcp-config") + 1]
    assert mcp_path == str(tmp_path / "mcp.json")
    cfg = json.loads((tmp_path / "mcp.json").read_text())
    assert list(cfg["mcpServers"].keys()) == ["pypoe-lab"]
    assert cfg["mcpServers"]["pypoe-lab"]["args"] == ["lab-mcp"]
    assert out == "root cause: air pressure"


def test_run_claude_times_out_and_kills(monkeypatch, tmp_path):
    """A hung CLI is killed at the wallclock cap and reported, not left to
    linger against the concurrency budget."""

    killed = {"value": False}

    class _HangProc:
        returncode = None

        async def communicate(self):
            await asyncio.sleep(10)
            return (b"", b"")

        def kill(self):
            killed["value"] = True
            self.returncode = -9

        async def wait(self):
            return -9

    async def fake_exec(*args, **kwargs):
        return _HangProc()

    monkeypatch.setenv("PYPOE_LAB_CONFIG", str(tmp_path / "no-such.yaml"))
    monkeypatch.setenv("PYPOE_INVESTIGATOR_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("LAB_INVESTIGATION_TIMEOUT_S", "0.05")
    reload_config()
    monkeypatch.setattr(alert_routes, "_claude_binary", lambda: "/usr/bin/claude")
    monkeypatch.setattr(alert_routes.asyncio, "create_subprocess_exec", fake_exec)

    try:
        out = asyncio.run(alert_routes._run_claude("investigate"))
    finally:
        reload_config()

    assert "timeout" in out.lower()
    assert killed["value"] is True
