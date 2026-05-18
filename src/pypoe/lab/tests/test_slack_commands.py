"""Unit tests for ``pypoe.lab.slack_commands``.

A minimal fake ``AsyncApp`` records registered handlers; tests invoke
them directly without ever touching slack_bolt.
"""

from __future__ import annotations

from typing import Any, Callable

import pytest

from pypoe.lab import slack_commands


class _FakeApp:
    """Captures slash-command handlers without needing slack_bolt."""

    def __init__(self) -> None:
        self.handlers: dict[str, Callable] = {}

    def command(self, name: str):
        def deco(fn):
            self.handlers[name] = fn
            return fn
        return deco


class _FakeClient:
    """LabClient stand-in returning canned aggregator responses."""

    def __init__(
        self,
        *,
        health: dict | None = None,
        equipment: dict | None = None,
        device_status: dict | None = None,
        runs: dict | None = None,
        sensors: dict | None = None,
        raise_health: Exception | None = None,
    ) -> None:
        self._health = health or {"version": "0.1", "equipment_count": 0}
        self._equipment = equipment or {"equipment": []}
        self._device_status = device_status or {}
        self._runs = runs or {"runs": []}
        self._sensors = sensors or {"readings": []}
        self._raise_health = raise_health
        self.calls: list[tuple[str, tuple, dict]] = []

    async def health(self):
        self.calls.append(("health", (), {}))
        if self._raise_health:
            raise self._raise_health
        return self._health

    async def list_equipment(self):
        self.calls.append(("list_equipment", (), {}))
        return self._equipment

    async def get_equipment_status(self, device_id: str):
        self.calls.append(("get_equipment_status", (device_id,), {}))
        return self._device_status

    async def recent_runs(self, limit: int = 20):
        self.calls.append(("recent_runs", (), {"limit": limit}))
        return self._runs

    async def latest_sensors(self):
        self.calls.append(("latest_sensors", (), {}))
        return self._sensors


async def _invoke(handler, *, text: str = "") -> tuple[bool, str]:
    """Call a slash-command handler with mocked ack/respond. Returns
    (ack_called, response_text)."""
    ack_called = False
    response: list[str] = []

    async def ack():
        nonlocal ack_called
        ack_called = True

    async def respond(text: str):
        response.append(text)

    await handler(ack=ack, respond=respond, command={"text": text})
    return ack_called, "\n".join(response)


def _setup() -> tuple[_FakeApp, _FakeClient]:
    app = _FakeApp()
    return app, _FakeClient()


@pytest.mark.asyncio
async def test_registers_all_five_commands():
    app, client = _setup()
    registered = slack_commands.register_lab_commands(app, client)
    assert set(app.handlers.keys()) == {
        "/lab-status", "/lab-device", "/lab-runs", "/lab-sensors", "/lab-actions",
    }
    assert set(registered) == set(app.handlers.keys())


@pytest.mark.asyncio
async def test_custom_prefix_namespaces_commands():
    """Org with multiple labs can prefix each lab's commands separately."""
    app, client = _setup()
    registered = slack_commands.register_lab_commands(
        app, client, command_prefix="/sdl2-lab-"
    )
    assert set(app.handlers.keys()) == {
        "/sdl2-lab-status", "/sdl2-lab-device", "/sdl2-lab-runs",
        "/sdl2-lab-sensors", "/sdl2-lab-actions",
    }
    assert set(registered) == set(app.handlers.keys())


@pytest.mark.asyncio
async def test_prefix_from_env(monkeypatch):
    monkeypatch.setenv("LAB_SLACK_COMMAND_PREFIX", "/sdl3-lab-")
    app, client = _setup()
    registered = slack_commands.register_lab_commands(app, client)
    assert all(c.startswith("/sdl3-lab-") for c in registered)


@pytest.mark.asyncio
async def test_prefix_must_start_with_slash():
    app, client = _setup()
    with pytest.raises(ValueError, match="start with '/'"):
        slack_commands.register_lab_commands(app, client, command_prefix="lab-")


@pytest.mark.asyncio
async def test_custom_prefix_in_usage_hint():
    """When /lab-device is missing its arg, the usage message echoes the prefix."""
    app, client = _setup()
    slack_commands.register_lab_commands(app, client, command_prefix="/sdl2-lab-")
    _, resp = await _invoke(app.handlers["/sdl2-lab-device"])
    assert "/sdl2-lab-device" in resp
    assert "<equipment_id>" in resp


@pytest.mark.asyncio
async def test_lab_status_all_healthy():
    app = _FakeApp()
    client = _FakeClient(
        health={"version": "1.2.3", "equipment_count": 2},
        equipment={
            "equipment": [
                {"id": "a", "status": {"equipment_status": "ready"}},
                {"id": "b", "status": {"equipment_status": "idle"}},
            ]
        },
    )
    slack_commands.register_lab_commands(app, client)
    acked, resp = await _invoke(app.handlers["/lab-status"])
    assert acked
    assert "Aggregator healthy" in resp
    assert "1.2.3" in resp
    assert "All devices in a healthy state" in resp


@pytest.mark.asyncio
async def test_lab_status_lists_unhealthy_devices():
    app = _FakeApp()
    client = _FakeClient(
        health={"version": "1.0", "equipment_count": 3},
        equipment={
            "equipment": [
                {"id": "ok", "status": {"equipment_status": "ready"}},
                {
                    "id": "broken",
                    "status": {
                        "equipment_status": "error",
                        "message": "COM driver lost",
                        "details": {
                            "claimed_by": {
                                "owner": "agent:solubility",
                                "expires_at": "2026-05-18T12:00:00Z",
                            }
                        },
                    },
                },
                {"id": "init", "status": {"equipment_status": "requires_init"}},
            ]
        },
    )
    slack_commands.register_lab_commands(app, client)
    _, resp = await _invoke(app.handlers["/lab-status"])
    assert "2 device(s) need attention" in resp
    assert "broken" in resp and "error" in resp
    assert "COM driver lost" in resp
    assert "agent:solubility" in resp
    assert "init" in resp and "requires_init" in resp
    # The ready device "ok" should NOT be listed under "need attention".
    # Match the backticked id form `\`ok\`` so we don't false-positive on
    # substrings like "broken".
    assert "`ok`" not in resp.split("need attention")[1]


@pytest.mark.asyncio
async def test_lab_status_aggregator_unreachable():
    app = _FakeApp()
    client = _FakeClient(raise_health=RuntimeError("connect refused"))
    slack_commands.register_lab_commands(app, client)
    _, resp = await _invoke(app.handlers["/lab-status"])
    assert "Aggregator unreachable" in resp
    assert "connect refused" in resp


@pytest.mark.asyncio
async def test_lab_device_renders_status_and_actions():
    app = _FakeApp()
    client = _FakeClient(
        device_status={
            "id": "plateloc",
            "name": "Agilent PlateLoc",
            "status": {
                "equipment_status": "requires_init",
                "message": "Awaiting startup",
                "allowed_actions": ["startup"],
                "details": {"claimed_by": None},
                "last_error": {
                    "severity": "error",
                    "code": "startup",
                    "message": "No response from PlateLoc",
                },
            },
        }
    )
    slack_commands.register_lab_commands(app, client)
    _, resp = await _invoke(app.handlers["/lab-device"], text="plateloc")
    assert "Agilent PlateLoc" in resp
    assert "requires_init" in resp
    assert "Awaiting startup" in resp
    assert "startup" in resp  # allowed_actions
    assert "No response from PlateLoc" in resp


@pytest.mark.asyncio
async def test_lab_device_missing_arg():
    app, client = _setup()
    slack_commands.register_lab_commands(app, client)
    _, resp = await _invoke(app.handlers["/lab-device"])
    assert "Usage" in resp


@pytest.mark.asyncio
async def test_lab_runs_with_custom_limit():
    app = _FakeApp()
    client = _FakeClient(
        runs={
            "runs": [
                {
                    "id": "12345678abcdef",
                    "device_id": "dose_every_well",
                    "plate_id": "plate-007",
                    "status": "complete",
                    "n_converged": 90,
                    "n_wells": 96,
                }
            ]
        },
    )
    slack_commands.register_lab_commands(app, client)
    _, resp = await _invoke(app.handlers["/lab-runs"], text="5")
    assert "12345678" in resp
    assert "90/96" in resp
    assert client.calls[-1] == ("recent_runs", (), {"limit": 5})


@pytest.mark.asyncio
async def test_lab_runs_default_limit_on_bad_input():
    app, client = _setup()
    slack_commands.register_lab_commands(app, client)
    await _invoke(app.handlers["/lab-runs"], text="not-a-number")
    assert client.calls[-1] == ("recent_runs", (), {"limit": 10})


@pytest.mark.asyncio
async def test_lab_sensors_caps_at_20_lines():
    readings = [
        {"sensor_id": f"s{i}", "metric": "temperature_c", "value": 20.0, "unit": "°C"}
        for i in range(25)
    ]
    app = _FakeApp()
    client = _FakeClient(sensors={"readings": readings})
    slack_commands.register_lab_commands(app, client)
    _, resp = await _invoke(app.handlers["/lab-sensors"])
    # 20 reading lines + 1 header + 1 "…and 5 more" line
    assert resp.count("temperature_c") == 20
    assert "5 more" in resp


@pytest.mark.asyncio
async def test_lab_actions_v10_device_with_no_allowed_actions():
    """STATUS_SPEC v1.0 devices omit allowed_actions — surface that to the user."""
    app = _FakeApp()
    client = _FakeClient(
        device_status={"status": {"equipment_status": "ready"}},
    )
    slack_commands.register_lab_commands(app, client)
    _, resp = await _invoke(app.handlers["/lab-actions"], text="legacy_device")
    assert "no" in resp.lower() and "allowed_actions" in resp


@pytest.mark.asyncio
async def test_lab_actions_lists_v11_actions():
    app = _FakeApp()
    client = _FakeClient(
        device_status={
            "status": {
                "equipment_status": "ready",
                "allowed_actions": ["seal.start", "stage.in"],
            }
        },
    )
    slack_commands.register_lab_commands(app, client)
    _, resp = await _invoke(app.handlers["/lab-actions"], text="plateloc")
    assert "seal.start" in resp
    assert "stage.in" in resp
