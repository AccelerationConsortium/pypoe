"""``/lab-*`` Slack slash commands.

Read-only — no LLM, no token cost. Handlers are async to match PyPoe's
``slack_bolt.async_app.AsyncApp``. Each handler calls ``await ack()``
within the 3-second Slack deadline and posts the response in the same
ack call (no slow ``respond`` followup needed since aggregator reads
are sub-second on a warm cache).
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from .http_client import LabClient

logger = logging.getLogger(__name__)

# State values that mean "everything's fine, no operator attention needed".
# Anything else surfaces in /lab-status.
HEALTHY_STATES: frozenset[str] = frozenset(
    {"ready", "idle", "running", "dry_run"}
)


def register_lab_commands(app: Any, client: LabClient) -> None:
    """Register ``/lab-*`` handlers on an ``AsyncApp``.

    Typed as ``Any`` so importing this module never requires
    ``slack_bolt`` to be installed (the registration call sites do).
    """

    @app.command("/lab-status")
    async def _lab_status(ack: Callable, respond: Callable, command: dict) -> None:
        await ack()
        try:
            health = await client.health()
            eq = await client.list_equipment()
        except Exception as exc:
            await respond(_err(f"Aggregator unreachable: {exc}"))
            return
        await respond(_format_status(health, eq))

    @app.command("/lab-device")
    async def _lab_device(ack: Callable, respond: Callable, command: dict) -> None:
        await ack()
        device_id = (command.get("text") or "").strip().split()[0:1]
        if not device_id:
            await respond(_err("Usage: `/lab-device <equipment_id>`"))
            return
        try:
            snap = await client.get_equipment_status(device_id[0])
        except Exception as exc:
            await respond(_err(f"Could not fetch `{device_id[0]}`: {exc}"))
            return
        await respond(_format_device(snap))

    @app.command("/lab-runs")
    async def _lab_runs(ack: Callable, respond: Callable, command: dict) -> None:
        await ack()
        text = (command.get("text") or "").strip()
        try:
            limit = int(text) if text else 10
        except ValueError:
            limit = 10
        try:
            data = await client.recent_runs(limit=limit)
        except Exception as exc:
            await respond(_err(f"Could not fetch runs: {exc}"))
            return
        await respond(_format_runs(data, limit))

    @app.command("/lab-sensors")
    async def _lab_sensors(ack: Callable, respond: Callable, command: dict) -> None:
        await ack()
        try:
            data = await client.latest_sensors()
        except Exception as exc:
            await respond(_err(f"Could not fetch sensors: {exc}"))
            return
        await respond(_format_sensors(data))

    @app.command("/lab-actions")
    async def _lab_actions(ack: Callable, respond: Callable, command: dict) -> None:
        await ack()
        device_id = (command.get("text") or "").strip().split()[0:1]
        if not device_id:
            await respond(_err("Usage: `/lab-actions <equipment_id>`"))
            return
        try:
            snap = await client.get_equipment_status(device_id[0])
        except Exception as exc:
            await respond(_err(f"Could not fetch `{device_id[0]}`: {exc}"))
            return
        await respond(_format_actions(device_id[0], snap))


# ---------------------------------------------------------------------------
# Formatters (Slack mrkdwn). Kept simple, plain text + backticks.
# ---------------------------------------------------------------------------


def _err(text: str) -> str:
    return f":warning: {text}"


def _format_status(health: dict, eq: dict) -> str:
    equipment = eq.get("equipment", [])
    eq_count = len(equipment)
    health_line = (
        f":white_check_mark: Aggregator healthy "
        f"(version `{health.get('version', '?')}`, "
        f"{health.get('equipment_count', eq_count)} devices registered)"
    )
    unhealthy = [
        e for e in equipment if _state_of(e) not in HEALTHY_STATES
    ]
    if not unhealthy:
        return f"{health_line}\nAll devices in a healthy state."

    lines = [health_line, f"*{len(unhealthy)} device(s) need attention:*"]
    for e in unhealthy:
        state = _state_of(e)
        msg = _message_of(e) or ""
        line = f"• `{e.get('id')}` — `{state}`"
        if msg:
            line += f" — {msg}"
        claimed = _claimed_by(e)
        if claimed:
            line += f"  _claimed by {claimed}_"
        lines.append(line)
    return "\n".join(lines)


def _format_device(snap: dict) -> str:
    state = _state_of(snap)
    name = snap.get("name", snap.get("id"))
    lines = [f"*{name}* (`{snap.get('id')}`) — `{state}`"]
    msg = _message_of(snap)
    if msg:
        lines.append(f"_{msg}_")

    fetch_err = snap.get("fetch_error")
    if fetch_err:
        lines.append(f":x: fetch_error: `{fetch_err}`")

    claimed = _claimed_by(snap)
    if claimed:
        lines.append(f"Claimed by: {claimed}")

    actions = _allowed_actions(snap)
    if actions:
        lines.append("Allowed actions: " + ", ".join(f"`{a}`" for a in actions))

    last_err = _last_error(snap)
    if last_err:
        lines.append(f":exclamation: last_error: {last_err}")
    return "\n".join(lines)


def _format_runs(data: dict, limit: int) -> str:
    runs = data.get("runs", [])
    if not runs:
        return "_No recent runs._"
    lines = [f"*Most recent {min(limit, len(runs))} runs:*"]
    for r in runs[:limit]:
        wells = f"{r.get('n_converged', 0)}/{r.get('n_wells', 0)}"
        lines.append(
            f"• `{r.get('id', '')[:8]}…` `{r.get('device_id', '?')}` "
            f"plate `{r.get('plate_id') or '?'}` — "
            f"{r.get('status', '?')} ({wells} converged)"
        )
    return "\n".join(lines)


def _format_sensors(data: dict) -> str:
    readings = data.get("readings", [])
    if not readings:
        return "_No sensor readings yet._"
    # Cap at 20 lines to stay well under Slack's 4000-char limit.
    capped = readings[:20]
    lines = ["*Latest sensor readings:*"]
    for r in capped:
        lines.append(
            f"• `{r.get('sensor_id')}` · `{r.get('metric')}` = "
            f"{r.get('value')} {r.get('unit', '')}".rstrip()
        )
    if len(readings) > 20:
        lines.append(f"_…and {len(readings) - 20} more (capped at 20)._")
    return "\n".join(lines)


def _format_actions(device_id: str, snap: dict) -> str:
    actions = _allowed_actions(snap)
    if not actions:
        state = _state_of(snap)
        return (
            f"`{device_id}` (state `{state}`) currently lists no "
            f"`allowed_actions`. Either the device is v1.0 (no claim "
            f"semantics) or no actions are dispatchable in this state."
        )
    return (
        f"`{device_id}` currently honors: "
        + ", ".join(f"`{a}`" for a in actions)
    )


# ---------------------------------------------------------------------------
# Snapshot accessors. Defensive — aggregator nests STATUS_SPEC under
# ``snap.status``, but missing/None values are normal during boot and
# during fetch errors, so every getter degrades gracefully.
# ---------------------------------------------------------------------------


def _status(snap: dict) -> dict:
    return snap.get("status") or {}


def _state_of(snap: dict) -> str:
    return _status(snap).get("equipment_status") or (
        "unreachable" if snap.get("fetch_error") else "unknown"
    )


def _message_of(snap: dict) -> str:
    return _status(snap).get("message") or ""


def _allowed_actions(snap: dict) -> list[str]:
    actions = _status(snap).get("allowed_actions") or []
    return [a for a in actions if isinstance(a, str)]


def _claimed_by(snap: dict) -> str:
    details = _status(snap).get("details") or {}
    claim = details.get("claimed_by")
    if not claim:
        return ""
    if isinstance(claim, dict):
        owner = claim.get("owner", "unknown")
        expires = claim.get("expires_at") or claim.get("ts") or ""
        suffix = f" (expires {expires})" if expires else ""
        return f"`{owner}`{suffix}"
    return str(claim)


def _last_error(snap: dict) -> str:
    err = _status(snap).get("last_error")
    if not err:
        return ""
    if isinstance(err, dict):
        code = err.get("code")
        msg = err.get("message", "")
        sev = err.get("severity", "")
        prefix = f"[{sev}] " if sev else ""
        if code:
            return f"{prefix}`{code}` — {msg}"
        return f"{prefix}{msg}"
    return str(err)
