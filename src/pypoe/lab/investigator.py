"""OpenRouter-backed alert investigator.

The lead model is GPT-5.6 Luna on OpenRouter. Lab reads, journaling, and
``consult_poe`` run in-process through :class:`LabClient`. PyPoe talks to
OpenRouter or Poe only — no local CLI investigator.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import httpx

from ..core.config import get_config
from ..core.providers import OPENROUTER, PROVIDERS, ProviderError, _headers
from .config import load_config
from .http_client import LabClient

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 12
MAX_TOOL_RESULT_CHARS = 8000
DEFAULT_OPENROUTER_MODEL = "openai/gpt-5.6-luna"

SYSTEM_PROMPT = """You are the AC Organic Self-driving Lab's automated incident \
investigator. An alert has fired; investigate it using the read-only lab \
tools and report a concise root-cause summary for a Slack thread.

You are READ-ONLY. You cannot actuate hardware and must never propose calling \
`/control/*` endpoints directly. If recovery needs a control action, recommend \
it in plain English for a human or a `lab-skills` workflow to carry out.

Ground every conclusion in evidence you actually read via the tools. If the \
data does not support a conclusion, say so plainly rather than speculate.

Keep the final Slack reply concise, with a short labelled paragraph for each
consulted model and a final Lead investigator paragraph. Each model's section,
including your own, must be 100 words or fewer; this is a ceiling, not a target.
Summarise each model's diagnosis, supporting evidence, and recommended action.
In your conclusion, resolve meaningful disagreement and state the next action.
Say "unconfirmed" when the evidence is insufficient. If a consultation fails,
use a single short line under that model's name; never invent its opinion.
If no models were consulted, provide only your conclusion in 100 words or fewer.
Avoid tool-call narration, raw logs, repeated alert details, and repeated
arguments. Keep detailed findings in the journal observation."""

TOOL_DEFS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_equipment",
            "description": "Every registered device with its latest status.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_equipment_status",
            "description": (
                "One device's full STATUS_SPEC envelope. Inspect "
                "status.equipment_status, status.message, status.last_error, "
                "and details.claimed_by."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "equipment_id": {"type": "string"},
                },
                "required": ["equipment_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "aggregator_health",
            "description": "Aggregator service health and equipment count.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_platforms",
            "description": "Dashboard section layout (Overview groupings).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "skill_catalog",
            "description": "Static catalog of skills the SDK can dispatch.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recent_events",
            "description": "State transitions and errors for one device.",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {"type": "string"},
                    "limit": {"type": "integer", "default": 50},
                },
                "required": ["device_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recent_observations",
            "description": (
                "Prior agent findings for one device, newest first. Read "
                "these before diagnosing so a recurrence builds on the last "
                "root cause."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {"type": "string"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["device_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "device_uptime",
            "description": "Uptime percent over the last N days.",
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {"type": "string"},
                    "days": {"type": "integer", "default": 7},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "latest_sensors",
            "description": "Most recent reading per sensor/metric.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recent_runs",
            "description": "Most recent dosing runs, newest first.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 20},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_wells",
            "description": "Per-well dispense results for one run.",
            "parameters": {
                "type": "object",
                "properties": {"run_id": {"type": "string"}},
                "required": ["run_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "append_observation",
            "description": (
                "Journal a finding to the aggregator's history. Lead summary "
                "with a stable one-line root-cause headline."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "device_id": {"type": "string"},
                    "summary": {"type": "string"},
                    "severity": {
                        "type": "string",
                        "enum": ["info", "warning", "error"],
                        "default": "info",
                    },
                },
                "required": ["device_id", "summary"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consult_poe",
            "description": (
                "Ask another catalog model for a second opinion. Pass the "
                "lab facts you already read as context — the consulted "
                "model has no tools of its own."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "model": {"type": "string"},
                    "question": {"type": "string"},
                    "context": {"type": "string"},
                },
                "required": ["model", "question"],
            },
        },
    },
]


def resolve_investigation_model(name: str) -> str:
    """Map a short id such as ``gpt-5.6-luna`` to an OpenRouter slug."""
    model = (name or "").strip() or DEFAULT_OPENROUTER_MODEL
    if "/" not in model:
        return f"openai/{model}"
    return model


def _truncate(value: Any) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    if len(text) > MAX_TOOL_RESULT_CHARS:
        return text[: MAX_TOOL_RESULT_CHARS - 20] + "\n…(truncated)"
    return text


async def _dispatch_tool(lab: LabClient, name: str, args: dict[str, Any]) -> Any:
    if name == "list_equipment":
        return await lab.list_equipment()
    if name == "get_equipment_status":
        return await lab.get_equipment_status(args["equipment_id"])
    if name == "aggregator_health":
        return await lab.health()
    if name == "list_platforms":
        return await lab.platforms()
    if name == "skill_catalog":
        return await lab.catalog()
    if name == "recent_events":
        return await lab.recent_events(args["device_id"], limit=int(args.get("limit") or 50))
    if name == "recent_observations":
        return await lab.recent_observations(
            args["device_id"], limit=int(args.get("limit") or 10)
        )
    if name == "device_uptime":
        return await lab.uptime(
            device_id=args.get("device_id"),
            days=int(args.get("days") or 7),
        )
    if name == "latest_sensors":
        return await lab.latest_sensors()
    if name == "recent_runs":
        return await lab.recent_runs(limit=int(args.get("limit") or 20))
    if name == "run_wells":
        return await lab.run_wells(args["run_id"])
    if name == "append_observation":
        return await lab.append_observation(
            args["device_id"],
            args["summary"],
            severity=args.get("severity") or "info",
        )
    if name == "consult_poe":
        from .mcp_server import _consult_poe

        return await _consult_poe(
            args["model"], args["question"], args.get("context")
        )
    return {"error": f"unknown tool {name!r}"}


def _assistant_message(message: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "role": "assistant",
        "content": message.get("content") or "",
    }
    tool_calls = message.get("tool_calls") or []
    if tool_calls:
        out["tool_calls"] = [
            {
                "id": tc.get("id") or f"call_{i}",
                "type": tc.get("type") or "function",
                "function": {
                    "name": (tc.get("function") or {}).get("name") or "",
                    "arguments": (tc.get("function") or {}).get("arguments") or "{}",
                },
            }
            for i, tc in enumerate(tool_calls)
        ]
    return out


async def _complete(
    http: httpx.AsyncClient,
    *,
    api_key: str,
    model: str,
    messages: list[dict[str, Any]],
    reasoning_effort: str,
    max_tokens: Optional[int],
    timeout_s: float,
) -> dict[str, Any]:
    spec = PROVIDERS[OPENROUTER]
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "tools": TOOL_DEFS,
        "tool_choice": "auto",
    }
    if max_tokens:
        payload["max_tokens"] = max_tokens
    if reasoning_effort:
        payload["reasoning"] = {"effort": reasoning_effort}
        payload["reasoning_effort"] = reasoning_effort

    url = f"{spec.base_url.rstrip('/')}/chat/completions"
    response = await http.post(
        url,
        json=payload,
        headers=_headers(spec, api_key),
        timeout=timeout_s,
    )
    if response.status_code >= 400:
        raise ProviderError(
            response.text, status_code=response.status_code
        )
    body = response.json()
    if isinstance(body, dict) and body.get("error"):
        raise ProviderError(body)
    choices = body.get("choices") or []
    if not choices:
        raise ProviderError("OpenRouter returned no choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ProviderError("OpenRouter returned an empty message")
    return message


async def run_investigation(
    prompt: str,
    *,
    lab: Optional[LabClient] = None,
    api_key: Optional[str] = None,
    http_client: Optional[httpx.AsyncClient] = None,
) -> str:
    """Run one alert investigation against OpenRouter and return Slack prose."""
    cfg = load_config()
    app_cfg = get_config()
    key = api_key if api_key is not None else app_cfg.openrouter_api_key
    if not key:
        return (
            ":x: `OPENROUTER_API_KEY` is unset — cannot run the GPT-5.6 Luna "
            "investigator."
        )

    model = resolve_investigation_model(cfg.alerts.investigation_model)
    timeout_s = float(cfg.alerts.investigation_timeout_s)
    max_tokens = getattr(app_cfg, "openrouter_max_tokens", 0) or None
    owns_lab = lab is None
    owns_http = http_client is None
    lab_client = lab or LabClient()
    http = http_client or httpx.AsyncClient()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    try:
        for _round in range(MAX_TOOL_ROUNDS):
            message = await _complete(
                http,
                api_key=key,
                model=model,
                messages=messages,
                reasoning_effort=cfg.alerts.investigation_reasoning_effort,
                max_tokens=max_tokens,
                timeout_s=timeout_s,
            )
            messages.append(_assistant_message(message))
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                text = (message.get("content") or "").strip()
                if text:
                    return text
                return ":x: OpenRouter returned an empty investigator reply."

            for i, tc in enumerate(tool_calls):
                fn = tc.get("function") or {}
                name = fn.get("name") or ""
                raw_args = fn.get("arguments") or "{}"
                try:
                    args = json.loads(raw_args) if raw_args else {}
                    if not isinstance(args, dict):
                        raise ValueError("tool arguments must be an object")
                    result = await _dispatch_tool(lab_client, name, args)
                except Exception as exc:
                    logger.warning("investigator tool %s failed: %s", name, exc)
                    result = {"error": f"{type(exc).__name__}: {exc}"}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id") or f"call_{i}",
                        "content": _truncate(result),
                    }
                )

        return (
            ":x: investigation used the maximum number of tool rounds "
            f"({MAX_TOOL_ROUNDS}) without a final summary."
        )
    except ProviderError as exc:
        return f":x: OpenRouter investigator failed: {exc}"[:1500]
    except httpx.HTTPError as exc:
        return f":x: OpenRouter investigator request failed: {exc}"
    finally:
        if owns_http:
            await http.aclose()
        if owns_lab:
            await lab_client.aclose()
