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

from .http_client import LabClient

logger = logging.getLogger(__name__)

_MAX_CLAUDE_OUTPUT_CHARS = 3000
_DEFAULT_MAX_CONCURRENT = 2


_INVESTIGATION_PROMPT = """\
An Uptime Kuma alert just fired for monitor `{monitor}` (msg: {msg}).

You have a `pypoe-lab` MCP server registered. Use it to investigate.

Steps:

1. Call `aggregator_health()` and `list_equipment()`. If the aggregator
   itself is down, say so and stop.
2. For each device whose state is not `ready`/`idle`/`running`/`dry_run`,
   call `get_equipment_status()` and `recent_events(device_id)`. Inspect
   `status.equipment_status`, `status.message`, `status.last_error`, and
   `details.claimed_by`.
3. If a failure looks ambiguous, call `consult_poe('GPT-4', ...)` for a
   second opinion. If a human judgment call is needed, call
   `ask_human(...)`.
4. Per affected device, call `append_observation(device_id, summary,
   severity)` to journal your finding.

You CANNOT perform control actions through this server. Do not propose
calling `/control/*` directly. If recovery requires a control action,
recommend it in plain English so a human or workflow can execute it via
`lab-skills`.

End with a 2–4 line summary suitable for a Slack thread reply.
"""


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
    concurrency = (
        max_concurrent
        if max_concurrent is not None
        else int(os.environ.get("LAB_ALERT_MAX_CONCURRENT", _DEFAULT_MAX_CONCURRENT))
    )
    semaphore = asyncio.Semaphore(concurrency)
    channel = slack_channel or os.environ.get("LAB_SLACK_CHANNEL", "#lab-alerts")

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
        asyncio.create_task(
            _investigate(
                monitor_name=monitor_name,
                msg=msg,
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

    app.include_router(router)
    return router


# ---------------------------------------------------------------------------
# Background investigation
# ---------------------------------------------------------------------------


async def _investigate(
    *,
    monitor_name: str,
    msg: str,
    channel: str,
    thread_ts: Optional[str],
    semaphore: asyncio.Semaphore,
) -> None:
    async with semaphore:
        try:
            output = await _run_claude(monitor_name, msg)
        except Exception as exc:
            output = f":x: Investigation failed to start: {exc}"
        if len(output) > _MAX_CLAUDE_OUTPUT_CHARS:
            output = output[: _MAX_CLAUDE_OUTPUT_CHARS - 100] + "\n…(truncated)"
        try:
            await _post_slack(channel, output, thread_ts=thread_ts)
        except Exception as exc:
            logger.error("Failed to post investigation reply: %s", exc)


async def _run_claude(monitor: str, msg: str) -> str:
    """Run ``claude -p <prompt>`` and return stdout (or a useful error)."""
    prompt = _INVESTIGATION_PROMPT.format(monitor=monitor, msg=msg)
    try:
        proc = await asyncio.create_subprocess_exec(
            "claude",
            "-p",
            prompt,
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
