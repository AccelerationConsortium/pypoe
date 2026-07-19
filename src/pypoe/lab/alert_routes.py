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
import json
import logging
import os
import shutil
import sys
from pathlib import Path
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
_ALLOWED_TOOL_GLOB = "mcp__pypoe-lab__*"

#: The investigator's role + read-only mandate, injected via
#: ``--append-system-prompt`` so it is enforced as a system instruction rather
#: than buried in the user prompt (the incident-specific steps stay there).
#: Mirrors the dashboard assistant's ``SYSTEM_PROMPT`` pattern.
SYSTEM_PROMPT = """You are the AC Organic Self-driving Lab's automated incident \
investigator. An alert has fired; investigate it using the read-only \
`pypoe-lab` MCP server and report a concise root-cause summary for a Slack \
thread.

You are READ-ONLY. You cannot actuate hardware and must never propose calling \
`/control/*` endpoints directly. If recovery needs a control action, recommend \
it in plain English for a human or a `lab-skills` workflow to carry out.

Ground every conclusion in evidence you actually read via the MCP tools. If the \
data does not support a conclusion, say so plainly rather than speculate."""


def _investigator_runtime_dir() -> Path:
    """Minimal scratch dir for the investigation subprocess.

    Holds the generated ``mcp.json`` and doubles as the subprocess cwd.
    Deliberately *outside* the pypoe repo tree so the spawned ``claude`` finds
    no project ``CLAUDE.md`` / ``CLAUDE.local.md`` to auto-load — that bundle
    would otherwise be re-read on every alert, thrashing the prompt cache and
    burning usage limits (the same reason the dashboard assistant isolates its
    cwd). Override with ``PYPOE_INVESTIGATOR_RUNTIME_DIR``.
    """

    d = Path(
        os.environ.get(
            "PYPOE_INVESTIGATOR_RUNTIME_DIR",
            str(Path.home() / ".cache" / "pypoe-investigator"),
        )
    )
    d.mkdir(parents=True, exist_ok=True)
    return d


def _investigator_cwd() -> str:
    return os.environ.get("PYPOE_INVESTIGATOR_CWD") or str(_investigator_runtime_dir())


def _claude_binary() -> Optional[str]:
    """Resolve the ``claude`` CLI, tolerating a minimal systemd PATH.

    PyPoe's web service runs under systemd with a PATH that usually excludes
    ``~/.local/bin``, so ``shutil.which`` alone often misses a per-user install.
    Honour an explicit override, then fall back to well-known install paths.
    """

    override = os.environ.get("PYPOE_CLAUDE_BIN")
    if override:
        return override
    found = shutil.which("claude")
    if found:
        return found
    candidates = [
        Path.home() / ".local" / "bin" / "claude",
        Path("/usr/local/bin/claude"),
        Path("/opt/claude/bin/claude"),
        Path("/home/sdl2/.local/bin/claude"),
    ]
    for c in candidates:
        if c.is_file() and os.access(c, os.X_OK):
            return str(c)
    return None


def _pypoe_binary() -> str:
    """Resolve the ``pypoe`` console script that launches the lab MCP server.

    Prefers ``PYPOE_BIN``, then PATH, then the script sitting next to the
    running interpreter (the common editable-install layout). Falls back to the
    bare name so a mis-resolved env still produces a legible spawn error.
    """

    override = os.environ.get("PYPOE_BIN")
    if override:
        return override
    found = shutil.which("pypoe")
    if found:
        return found
    sibling = Path(sys.executable).with_name("pypoe")
    if sibling.is_file() and os.access(sibling, os.X_OK):
        return str(sibling)
    return "pypoe"


def _write_mcp_config(cfg) -> Path:
    """Materialise an explicit ``pypoe-lab`` MCP config and return its path.

    Passed via ``--mcp-config`` + ``--strict-mcp-config`` so the investigation
    sees *only* this read-only server regardless of the subprocess cwd or any
    filesystem-discovered ``claude`` MCP config — hermetic, like the dashboard
    assistant. The MCP server subprocess needs a few env vars to reach the
    aggregator and (for ``consult_poe``) Poe; forward just those.
    """

    env: dict[str, str] = {"LAB_API_URL": cfg.api_url}
    for key in (
        "POE_API_KEY",
        "LAB_MCP_AGENT_SOURCE",
        "LAB_MCP_HTTP_TIMEOUT",
        "LAB_CONSULT_ENABLED",
        "LAB_CONSULT_MODELS",
        "PYPOE_LAB_CONFIG",
    ):
        val = os.environ.get(key)
        if val is not None:
            env[key] = val

    config = {
        "mcpServers": {
            "pypoe-lab": {
                "type": "stdio",
                "command": _pypoe_binary(),
                "args": ["lab-mcp"],
                "env": env,
            }
        }
    }
    path = _investigator_runtime_dir() / "mcp.json"
    path.write_text(json.dumps(config, indent=2))
    return path


_INVESTIGATION_PROMPT_HEAD = """\
An Uptime Kuma alert just fired for monitor `{monitor}` (msg: {msg}).

You have a `pypoe-lab` MCP server registered. Use it to investigate.

Steps:

1. Call `aggregator_health()` and `list_equipment()`. If the aggregator
   itself is down, say so and stop.
2. For each device whose state is not `ready`/`idle`/`running`/`dry_run`,
   call `get_equipment_status()`, `recent_events(device_id)`, and
   `recent_observations(device_id)`. Inspect `status.equipment_status`,
   `status.message`, `status.last_error`, and `details.claimed_by`. If a
   device has prior observations, treat a repeat as a RECURRENCE and build on
   the earlier root cause instead of re-deriving it from scratch.
"""

_DEVICE_PROMPT_HEAD = """\
A lab device alert just fired: `{device_id}` reported `{event}`
(message: {msg}).{last_error_line}{devices_line}

You have a `pypoe-lab` MCP server registered. Use it to investigate.

Steps:

1. Call `get_equipment_status("{device_id}")`,
   `recent_events("{device_id}")`, and `recent_observations("{device_id}")`.
   Inspect `status.equipment_status`, `status.message`, `status.last_error`,
   and `details.claimed_by`. If `recent_observations` shows this device was
   investigated before, decide whether this is a NEW issue or a RECURRENCE:
   for a recurrence, build on the prior root cause (cite its date and note the
   occurrence count) rather than starting cold.
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
   severity)` to journal your finding. Lead `summary` with a stable one-line
   root-cause headline so a future `recent_observations` read can match a
   recurrence to this incident.

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
   severity)` to journal your finding. Lead `summary` with a stable one-line
   root-cause headline so a future `recent_observations` read can match a
   recurrence to this incident.

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
    """Run a hardened ``claude`` investigation and return stdout (or an error).

    Adopts the dashboard assistant's safeguards: a pinned ``--model`` (no silent
    tier drift), an explicit ``--mcp-config`` + ``--strict-mcp-config`` (only the
    read-only ``pypoe-lab`` server, independent of cwd), a cwd outside the repo
    tree (no ``CLAUDE.md`` bundle re-read per alert), the role/read-only mandate
    via ``--append-system-prompt``, and a hard wallclock timeout so a hung CLI
    can never linger against the concurrency budget.
    """

    binary = _claude_binary()
    if binary is None:
        return (
            ":x: `claude` CLI not on PATH. Install it on the same host as PyPoe "
            "(see https://docs.anthropic.com/en/docs/claude-code) or set "
            "`PYPOE_CLAUDE_BIN` so the webhook can spawn investigations."
        )

    cfg = load_config()
    mcp_config_path = _write_mcp_config(cfg)
    timeout_s = cfg.alerts.investigation_timeout_s
    args = [
        binary,
        "-p",
        prompt,
        "--model",
        cfg.alerts.investigation_model,
        "--append-system-prompt",
        SYSTEM_PROMPT,
        "--mcp-config",
        str(mcp_config_path),
        "--strict-mcp-config",
        # Headless -p runs cannot grant permissions interactively, so the lab
        # MCP tools must be pre-allowed or every call is refused.
        "--allowedTools",
        _ALLOWED_TOOL_GLOB,
        "--permission-mode",
        "default",
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=_investigator_cwd(),
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return f":x: could not spawn `{binary}` — check the install / `PYPOE_CLAUDE_BIN`."

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        return (
            f":x: investigation exceeded {timeout_s:.0f}s timeout and was killed "
            "before producing a summary."
        )

    if proc.returncode != 0:
        return (
            f":x: `claude` exited {proc.returncode}\n"
            f"```\n{stderr.decode(errors='replace').strip()[:1500]}\n```"
        )
    return stdout.decode(errors="replace").strip()


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
