"""Unit tests for the ``/kuma/status`` gateway envelope
(``WebApp._kuma_status_payload``).

The builder is exercised on a stub carrying only the attributes it uses,
so the full WebApp (Poe client, DB, …) never has to be constructed.
Kuma's status-page API is mocked with respx.
"""

from __future__ import annotations

import asyncio

import pytest

pytest.importorskip("fastapi")
httpx = pytest.importorskip("httpx")
respx = pytest.importorskip("respx")

from pypoe.interfaces.web.app import WebApp

KUMA = "http://kuma.test"


def _stub():
    class Stub:
        _kuma_status_cache = None
        _kuma_status_cache_expires_at = 0.0
        _KUMA_BEAT_STATES = WebApp._KUMA_BEAT_STATES
        _now_utc = WebApp._now_utc
        _component = WebApp._component
        _metric = WebApp._metric
        _kuma_status_payload = WebApp._kuma_status_payload

    return Stub()


def _mock_kuma(monitors, heartbeats):
    respx.get(f"{KUMA}/api/status-page/lab").mock(
        return_value=httpx.Response(
            200,
            json={"publicGroupList": [{"name": "Services", "monitorList": monitors}]},
        )
    )
    respx.get(f"{KUMA}/api/status-page/heartbeat/lab").mock(
        return_value=httpx.Response(200, json={"heartbeatList": heartbeats})
    )


@respx.mock
def test_all_monitors_up_is_ready(monkeypatch):
    monkeypatch.setenv("PYPOE_KUMA_URL", KUMA)
    _mock_kuma(
        [{"id": 1, "name": "aggregator"}, {"id": 2, "name": "pypoe web"}],
        {"1": [{"status": 1}], "2": [{"status": 1}]},
    )
    payload = asyncio.run(_stub()._kuma_status_payload())
    assert payload["equipment_id"] == "uptime_kuma"
    assert payload["equipment_status"] == "ready"
    assert payload["components"]["aggregator"]["state"] == "up"
    assert payload["components"]["pypoe_web"]["state"] == "up"
    assert payload["metrics"]["monitors_up"]["value"] == 2
    assert payload["metrics"]["monitors_total"]["value"] == 2


@respx.mock
def test_down_monitor_degrades_and_names_it(monkeypatch):
    monkeypatch.setenv("PYPOE_KUMA_URL", KUMA)
    _mock_kuma(
        [{"id": 1, "name": "aggregator"}, {"id": 2, "name": "AnaliticaDB"}],
        {"1": [{"status": 1}], "2": [{"status": 0}]},
    )
    payload = asyncio.run(_stub()._kuma_status_payload())
    assert payload["equipment_status"] == "degraded"
    assert "AnaliticaDB" in payload["message"]
    assert payload["components"]["analiticadb"]["state"] == "down"
    assert payload["metrics"]["monitors_up"]["value"] == 1


@respx.mock
def test_kuma_unreachable_reports_unknown_not_error(monkeypatch):
    monkeypatch.setenv("PYPOE_KUMA_URL", KUMA)
    respx.get(f"{KUMA}/api/status-page/lab").mock(
        side_effect=httpx.ConnectError("refused")
    )
    payload = asyncio.run(_stub()._kuma_status_payload())
    # STATUS_SPEC §2.1 gateway rule: unreachable backing service → unknown.
    assert payload["equipment_status"] == "unknown"
    assert "unreachable" in payload["message"].lower()
    assert payload["components"] == {}
    assert payload["last_error"] is None


@respx.mock
def test_payload_is_cached(monkeypatch):
    monkeypatch.setenv("PYPOE_KUMA_URL", KUMA)
    route = respx.get(f"{KUMA}/api/status-page/lab").mock(
        return_value=httpx.Response(
            200,
            json={"publicGroupList": [{"monitorList": [{"id": 1, "name": "a"}]}]},
        )
    )
    respx.get(f"{KUMA}/api/status-page/heartbeat/lab").mock(
        return_value=httpx.Response(200, json={"heartbeatList": {"1": [{"status": 1}]}})
    )
    stub = _stub()
    asyncio.run(stub._kuma_status_payload())
    asyncio.run(stub._kuma_status_payload())
    assert route.call_count == 1  # second call served from cache
