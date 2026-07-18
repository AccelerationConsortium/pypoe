"""``POST /alerts/kuma`` webhook handler.

Mounted onto PyPoe's existing FastAPI app (``interfaces/web/app.py``).
Receives Uptime Kuma's default JSON payload, posts an instant
"Investigating…" message into Slack, and kicks off a background
``claude -p`` invocation against the lab MCP server. The investigation
result is appended as a threaded reply.

Concurrency is bounded by a process-wide semaphore so a flood of alerts
doesn't fork an unbounded number of ``claude`` subprocesses.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
from typing import Optional

try:
    from fastapi import APIRouter, FastAPI, HTTPException, Request, status
    from pydantic import BaseModel
    _FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover - web-ui extra not installed
    APIRouter = None  # type: ignore[assignment]
    FastAPI = None  # type: ignore[assignment]
    HTTPException = None  # type: ignore[assignment]
    Request = None  # type: ignore[assignment]
    BaseModel = object  # type: ignore[misc,assignment]
    status = None  # type: ignore[assignment]
    _FASTAPI_AVAILABLE = False

from .config import load_config
from .http_client import LabClient

logger = logging.getLogger(__name__)

_MAX_CLAUDE_OUTPUT_CHARS = 3000
_DEFAULT_MAX_CONCURRENT = 2


_INVESTIGATION_PROMPT_HEAD = """\
An Uptime Kuma alert just fired for monitor `{monitor}` (msg: {msg}).

You have a `pypoe-lab` MCP server registered. Use it to investigate.

Steps:

1. Call `aggregator_health()` and `list_equipment()`. If the aggregator
   itself is down, say so and stop.
2. For each device whose state is not `ready`/`idle`/`running`/`dry_run`,
   call `get_equipment_status()` and `recent_events(device_id)`. Inspect
   `status.equipment_status`, `status.message`, `status.last_error`, and
   `details.claimed_by`.
"""

_DEVICE_PROMPT_HEAD = """\
A lab device alert just fired: `{device_id}` reported `{event}`
(message: {msg}).{last_error_line}{devices_line}

You have a `pypoe-lab` MCP server registered. Use it to investigate.

Steps:

1. Call `get_equipment_status("{device_id}")` and
   `recent_events("{device_id}")`. Inspect `status.equipment_status`,
   `status.message`, `status.last_error`, and `details.claimed_by`.
2. Call `device_uptime("{device_id}")` and `aggregator_health()` for
   context. If other devices are listed as affected above, check each
   of them briefly with `get_equipment_status()` — simultaneous failures
   usually mean a shared cause (network, gateway, power).
"""

_CONSULT_BLOCK = """\
3. Consult each Poe model below for an independent second opinion.
   For EACH model, call:
       consult_poe(model="<model>", question="<your question>", context="<lab state you gathered>")
   The `context` you pass MUST include the relevant facts you read in
   step 2 — the consulted model has no MCP access of its own, so the
   string you supply is the ONLY information it sees.

   Models to consult (one call per model):
{models_block}

   If a `consult_poe` call returns `returncode != 0` (Poe unreachable,
   bad bot, missing API key, etc.), note the failure in your summary
   but DO NOT abort — continue with the rest of the investigation.
"""

_NO_CONSULT_BLOCK = """\
3. Skip Poe consultation (disabled in slack.yaml). If a human judgment
   call is needed, call `ask_human(...)`.
"""

_INVESTIGATION_PROMPT_TAIL_CONSULT = """\
4. Per affected device, call `append_observation(device_id, summary,
   severity)` to journal your finding.

You CANNOT perform control actions through this server. Do not propose
calling `/control/*` directly. If recovery requires a control action,
recommend it in plain English so a human or workflow can execute it via
`lab-skills`.

End with a synthesised Slack-thread reply that contains, in order:
  - One-line headline of the most likely root cause.
  - 1-2 bullets per consulted model summarising what it said,
    explicitly noting any divergences (e.g. "GPT-5.5 thinks X;
    Claude-Opus-4.7 thinks Y").
  - 1-2 lines of YOUR own diagnosis, citing the lab evidence.
  - If recovery requires a control action, recommend it in plain
    English (NOT as a /control/* call).
Keep the total reply under 2500 characters so it fits in one Slack
message after truncation.
"""

_INVESTIGATION_PROMPT_TAIL_SOLO = """\
4. Per affected device, call `append_observation(device_id, summary,
   severity)` to journal your finding.

You CANNOT perform control actions through this server. Do not propose
calling `/control/*` directly. If recovery requires a control action,
recommend it in plain English so a human or workflow can execute it via
`lab-skills`.

End with a 2-4 line summary suitable for a Slack thread reply.
"""


def _build_investigation_prompt(
    monitor: str, msg: str, consult_models: tuple[str, ...]
) -> str:
    """Compose the investigation prompt with the configured model list.

    If ``consult_models`` is empty, switch to the solo prompt (no Poe
    consultation step, no synthesis instructions).
    """
    head = _INVESTIGATION_PROMPT_HEAD.format(monitor=monitor, msg=msg)
    return _finish_prompt(head, consult_models)


def _build_device_prompt(
    device_id: str,
    event: str,
    msg: str,
    consult_models: tuple[str, ...],
    *,
    last_error: Optional[dict] = None,
    devices: Optional[list[str]] = None,
) -> str:
    """Compose a device-focused investigation prompt (POST /alerts/device)."""
    last_error_line = (
        f"\nDevice-reported last_error: {last_error}" if last_error else ""
    )
    devices_line = (
        f"\nOther devices affected in the same sweep: {', '.join(devices)}"
        if devices
        else ""
    )
    head = _DEVICE_PROMPT_HEAD.format(
        device_id=device_id,
        event=event,
        msg=msg,
        last_error_line=last_error_line,
        devices_line=devices_line,
    )
    return _finish_prompt(head, consult_models)


def _finish_prompt(head: str, consult_models: tuple[str, ...]) -> str:
    if consult_models:
        models_block = "\n".join(f"     - {m}" for m in consult_models)
        return head + _CONSULT_BLOCK.format(models_block=models_block) + _INVESTIGATION_PROMPT_TAIL_CONSULT
    return head + _NO_CONSULT_BLOCK + _INVESTIGATION_PROMPT_TAIL_SOLO


class KumaHeartbeat(BaseModel):  # type: ignore[misc]
    status: int = 0
    msg: Optional[str] = None
    time: Optional[str] = None


class KumaMonitor(BaseModel):  # type: ignore[misc]
    name: Optional[str] = None
    type: Optional[str] = None


class KumaAlert(BaseModel):  # type: ignore[misc]
    heartbeat: Optional[KumaHeartbeat] = None
    monitor: Optional[KumaMonitor] = None
    msg: Optional[str] = None


#: Device-alert events the aggregator-side notifier may send. ``recovered``
#: posts a one-liner; everything else triggers an investigation.
DEVICE_ALERT_EVENTS = ("unreachable", "error", "e_stop", "degraded", "recovered")


class DeviceAlert(BaseModel):  # type: ignore[misc]
    """Payload for ``POST /alerts/device`` (sent by the lab aggregator's
    alert notifier, not by Uptime Kuma)."""

    device_id: str
    event: str  # one of DEVICE_ALERT_EVENTS
    state: Optional[str] = None
    message: Optional[str] = None
    last_error: Optional[dict] = None
    #: For storm-collapsed alerts: the other device ids that tripped in
    #: the same sweep (device_id carries the first one).
    devices: Optional[list[str]] = None


def register_alert_routes(
    app: "FastAPI",
    client: Optional[LabClient] = None,
    *,
    max_concurrent: Optional[int] = None,
    slack_channel: Optional[str] = None,
) -> "APIRouter":
    """Mount ``POST /alerts/kuma`` onto a FastAPI app."""
    if not _FASTAPI_AVAILABLE:
        raise ImportError(
            "FastAPI is required for register_alert_routes — install the "
            "web-ui extra: pip install -e '.[web-ui]'"
        )

    lab = client or LabClient()
    cfg = load_config()
    concurrency = (
        max_concurrent
        if max_concurrent is not None
        else (cfg.alerts.max_concurrent_investigations or _DEFAULT_MAX_CONCURRENT)
    )
    semaphore = asyncio.Semaphore(concurrency)
    channel = slack_channel or cfg.slack.alert_channel

    router = APIRouter(prefix="/alerts", tags=["lab-alerts"])

    @router.post("/kuma", status_code=202)
    async def kuma_webhook(payload: KumaAlert, request: Request) -> dict:
        monitor_name = (payload.monitor.name if payload.monitor else None) or "unknown"
        msg = payload.msg or (payload.heartbeat.msg if payload.heartbeat else "") or ""
        is_down = payload.heartbeat is not None and payload.heartbeat.status == 0

        if not is_down:
            # Recovery — post the recovery line, no investigation.
            try:
                await _post_slack(
                    channel,
                    f":white_check_mark: *{monitor_name}* recovered — {msg}".strip(),
                )
            except Exception as exc:
                logger.error("Failed to post Slack recovery alert: %s", exc)
            return {"action": "recovered", "monitor": monitor_name}

        # Down — post the "investigating" line and kick off a background task.
        try:
            thread_ts = await _post_slack(
                channel,
                f":rotating_light: *{monitor_name}* DOWN — {msg} "
                f":mag: Investigating…",
            )
        except Exception as exc:
            logger.error("Failed to post Slack alert: %s", exc)
            thread_ts = None

        # Investigation runs in the background, bounded by the semaphore.
        # Consult-model list is captured per request (so a slack.yaml edit
        # takes effect on the next alert without a process restart, if the
        # config singleton has been reload_config()-ed).
        consult_models = cfg.consult.models if cfg.consult.enabled else ()
        prompt = _build_investigation_prompt(monitor_name, msg, consult_models)
        asyncio.create_task(
            _investigate(
                prompt=prompt,
                channel=channel,
                thread_ts=thread_ts,
                semaphore=semaphore,
            )
        )
        return {
            "action": "investigating",
            "monitor": monitor_name,
            "thread_ts": thread_ts,
        }

    @router.post("/device", status_code=202)
    async def device_alert(payload: DeviceAlert) -> dict:
        if payload.event not in DEVICE_ALERT_EVENTS:
            raise HTTPException(
                status_code=422,
                detail=f"event must be one of {DEVICE_ALERT_EVENTS}",
            )
        msg = payload.message or ""

        if payload.event == "recovered":
            try:
                await _post_slack(
                    channel,
                    f":white_check_mark: *{payload.device_id}* recovered — {msg}".strip(),
                )
            except Exception as exc:
                logger.error("Failed to post device recovery alert: %s", exc)
            return {"action": "recovered", "device": payload.device_id}

        others = f" (+{len(payload.devices)} more)" if payload.devices else ""
        try:
            thread_ts = await _post_slack(
                channel,
                f":rotating_light: *{payload.device_id}*{others} "
                f"{payload.event.upper()} — {msg} :mag: Investigating…",
            )
        except Exception as exc:
            logger.error("Failed to post device alert: %s", exc)
            thread_ts = None

        consult_models = cfg.consult.models if cfg.consult.enabled else ()
        prompt = _build_device_prompt(
            payload.device_id,
            payload.event,
            msg,
            consult_models,
            last_error=payload.last_error,
            devices=payload.devices,
        )
        asyncio.create_task(
            _investigate(
                prompt=prompt,
                channel=channel,
                thread_ts=thread_ts,
                semaphore=semaphore,
            )
        )
        return {
            "action": "investigating",
            "device": payload.device_id,
            "thread_ts": thread_ts,
        }

    app.include_router(router)
    return router


# ---------------------------------------------------------------------------
# Background investigation
# ---------------------------------------------------------------------------


async def _investigate(
    *,
    prompt: str,
    channel: str,
    thread_ts: Optional[str],
    semaphore: asyncio.Semaphore,
) -> None:
    async with semaphore:
        try:
            output = await _run_claude(prompt)
        except Exception as exc:
            output = f":x: Investigation failed to start: {exc}"
        if len(output) > _MAX_CLAUDE_OUTPUT_CHARS:
            output = output[: _MAX_CLAUDE_OUTPUT_CHARS - 100] + "\n…(truncated)"
        try:
            await _post_slack(channel, output, thread_ts=thread_ts)
        except Exception as exc:
            logger.error("Failed to post investigation reply: %s", exc)


async def _run_claude(prompt: str) -> str:
    """Run ``claude -p <prompt>`` and return stdout (or a useful error)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "claude",
            "-p",
            prompt,
            # Headless -p runs cannot grant permissions interactively, so the
            # lab MCP tools must be pre-allowed or every call is refused.
            "--allowedTools",
            "mcp__pypoe-lab__*",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            return (
                f":x: `claude` exited {proc.returncode}\n"
                f"```\n{stderr.decode(errors='replace').strip()[:1500]}\n```"
            )
        return stdout.decode(errors="replace").strip()
    except FileNotFoundError:
        return (
            ":x: `claude` CLI not on PATH. Install it on the same host as PyPoe "
            "(see https://docs.anthropic.com/en/docs/claude-code) so the webhook "
            "can spawn investigations."
        )


# ---------------------------------------------------------------------------
# Slack posting (kept tiny so tests can monkeypatch it)
# ---------------------------------------------------------------------------


async def _post_slack(
    channel: str, text: str, thread_ts: Optional[str] = None
) -> Optional[str]:
    try:
        from slack_sdk.web.async_client import AsyncWebClient
    except ImportError as exc:
        logger.warning("slack_sdk missing: %s", exc)
        return None

    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        logger.warning("SLACK_BOT_TOKEN unset — not posting to %s", channel)
        return None

    slack = AsyncWebClient(token=token)
    kwargs = {"channel": channel, "text": text}
    if thread_ts:
        kwargs["thread_ts"] = thread_ts
    resp = await slack.chat_postMessage(**kwargs)
    return resp.get("ts")
