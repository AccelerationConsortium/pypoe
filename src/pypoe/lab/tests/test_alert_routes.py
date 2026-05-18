"""Unit tests for ``pypoe.lab.alert_routes``.

Uses FastAPI's TestClient + monkeypatches the Slack post + claude
subprocess so the test never touches the network or the shell.
"""

from __future__ import annotations

import asyncio

import pytest

fastapi = pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from pypoe.lab import alert_routes
from pypoe.lab.http_client import LabClient


def _mk_app(monkeypatch, *, claude_output: str = "Investigation summary"):
    posted: list[dict] = []
    investigations: list[str] = []

    async def fake_post_slack(channel, text, thread_ts=None):
        posted.append(
            {"channel": channel, "text": text, "thread_ts": thread_ts}
        )
        return f"ts-{len(posted)}"

    async def fake_run_claude(monitor, msg):
        investigations.append(f"{monitor}|{msg}")
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
    # closed (which awaits all pending tasks).
    assert investigations == ["aggregator|connection refused"]
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


def test_concurrency_bound_is_respected(monkeypatch):
    """Two simultaneous alerts shouldn't run more than `max_concurrent` claude
    subprocesses in parallel. Verified via observable peak concurrency."""

    async def main():
        peak = {"value": 0, "current": 0, "lock": asyncio.Lock()}
        ready = asyncio.Event()
        release = asyncio.Event()

        async def fake_post_slack(channel, text, thread_ts=None):
            return "ts"

        async def fake_run_claude(monitor, msg):
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
