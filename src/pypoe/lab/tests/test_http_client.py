"""Unit tests for ``pypoe.lab.http_client``.

Uses ``httpx.MockTransport`` so no real aggregator is needed.
"""

from __future__ import annotations

import json
import re

import pytest

httpx = pytest.importorskip("httpx")

from pypoe.lab.http_client import LabClient


def _mk_client(handler) -> LabClient:
    transport = httpx.MockTransport(handler)
    inner = httpx.AsyncClient(
        base_url="http://test", transport=transport, timeout=5.0
    )
    return LabClient(base_url="http://test", client=inner)


@pytest.mark.asyncio
async def test_health_returns_json():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/health"
        return httpx.Response(200, json={"status": "healthy", "equipment_count": 17})

    async with _mk_client(handler) as client:
        out = await client.health()
        assert out == {"status": "healthy", "equipment_count": 17}


@pytest.mark.asyncio
async def test_get_equipment_status_path():
    async def handler(request):
        assert request.url.path == "/api/equipment/plateloc/status"
        return httpx.Response(200, json={"id": "plateloc"})

    async with _mk_client(handler) as client:
        await client.get_equipment_status("plateloc")


@pytest.mark.asyncio
async def test_uptime_with_and_without_device_id():
    seen_paths: list[str] = []

    async def handler(request):
        seen_paths.append(request.url.path)
        return httpx.Response(200, json={})

    async with _mk_client(handler) as client:
        await client.uptime()
        await client.uptime("plateloc", days=14)

    assert seen_paths == [
        "/api/history/uptime",
        "/api/history/uptime/plateloc",
    ]


@pytest.mark.asyncio
async def test_recent_events_passes_limit():
    async def handler(request):
        assert request.url.params.get("limit") == "25"
        return httpx.Response(200, json={"device_id": "x", "events": []})

    async with _mk_client(handler) as client:
        await client.recent_events("x", limit=25)


@pytest.mark.asyncio
async def test_recent_observations_filters_to_agent_observation():
    async def handler(request):
        assert request.url.path == "/api/history/events/ot2_hte"
        assert request.url.params.get("event_type") == "agent_observation"
        assert request.url.params.get("limit") == "10"
        return httpx.Response(200, json={"device_id": "ot2_hte", "events": []})

    async with _mk_client(handler) as client:
        await client.recent_observations("ot2_hte")


@pytest.mark.asyncio
async def test_append_observation_envelope_shape():
    """The aggregator collapses ``context`` into ``message`` when message is
    empty, so severity/source must live in ``extra``, never in ``context``.
    """
    captured: dict = {}

    async def handler(request):
        captured["path"] = request.url.path
        captured["method"] = request.method
        captured["body"] = json.loads(request.content)
        return httpx.Response(204)

    async with _mk_client(handler) as client:
        record = await client.append_observation(
            "plateloc",
            "All steady",
            severity="info",
            extra={"context_summary": "post-recovery sweep"},
        )

    assert captured["path"] == "/api/ingest/events"
    assert captured["method"] == "POST"
    body = captured["body"]
    assert body["device_id"] == "plateloc"
    assert len(body["records"]) == 1
    rec = body["records"][0]

    # Event type used for the upstream docs PR.
    assert rec["event"] == "agent_observation"
    # Message is the one-liner; context stays None so the aggregator's
    # `message = rec.message or rec.context` quirk leaves message intact.
    assert rec["message"] == "All steady"
    assert rec["context"] is None
    # Severity and source must be in extra so they survive ingest.
    assert rec["extra"]["source"] == "claude-agent"
    assert rec["extra"]["severity"] == "info"
    assert rec["extra"]["context_summary"] == "post-recovery sweep"
    # Caller-visible return matches what was posted.
    assert record["event"] == "agent_observation"

    # Timestamp is a valid ISO 8601 UTC string.
    assert re.match(
        r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$", rec["timestamp"]
    )


@pytest.mark.asyncio
async def test_append_observation_rejects_unknown_severity():
    async def handler(request):  # never called
        return httpx.Response(204)

    async with _mk_client(handler) as client:
        with pytest.raises(ValueError, match="severity"):
            await client.append_observation("plateloc", "x", severity="bogus")


@pytest.mark.asyncio
async def test_get_raises_on_4xx():
    async def handler(request):
        return httpx.Response(404, json={"detail": "no such device"})

    async with _mk_client(handler) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await client.get_equipment_status("nonesuch")


@pytest.mark.asyncio
async def test_base_url_from_env(monkeypatch):
    from pypoe.lab import config as lab_config
    monkeypatch.setenv("LAB_API_URL", "http://override.example:9000")
    lab_config.reload_config()  # autouse fixture cached the empty value
    client = LabClient()
    try:
        assert client.base_url == "http://override.example:9000"
    finally:
        await client.aclose()
