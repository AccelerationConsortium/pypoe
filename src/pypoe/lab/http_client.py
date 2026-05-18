"""Async HTTP client for the AC Organic Self-driving Lab aggregator.

The aggregator (``ac-organic-lab/api`` on port 8001 by default) is the
single source of truth for lab state. This module only wraps its read
endpoints plus the ingest write endpoint used to journal agent
observations. No ``/control/*`` calls — see the module docstring of
``pypoe.lab`` for why.

Endpoints mirror the aggregator's HTTP surface as documented in
``ac-organic-lab/docs/OBSERVABILITY.md`` § 9 and verified against the
live code in ``api/app/main.py`` and ``api/app/history.py``.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Optional

try:
    import httpx
except ImportError as exc:  # pragma: no cover - lab extra not installed
    httpx = None  # type: ignore[assignment]
    _HTTPX_IMPORT_ERROR = exc
else:
    _HTTPX_IMPORT_ERROR = None


DEFAULT_BASE_URL = "http://localhost:8001"
DEFAULT_TIMEOUT_S = 10.0
DEFAULT_AGENT_SOURCE = "claude-agent"


class LabClient:
    """Thin async wrapper over the aggregator's HTTP API."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        *,
        agent_source: Optional[str] = None,
        client: Optional["httpx.AsyncClient"] = None,
    ) -> None:
        if httpx is None and client is None:
            raise ImportError(
                "httpx is required for pypoe.lab.LabClient — install the "
                "lab extra: pip install -e '.[lab]'"
            ) from _HTTPX_IMPORT_ERROR

        self.base_url = (
            base_url
            or os.environ.get("LAB_API_URL")
            or DEFAULT_BASE_URL
        ).rstrip("/")
        self.timeout = (
            timeout
            if timeout is not None
            else float(os.environ.get("LAB_MCP_HTTP_TIMEOUT", DEFAULT_TIMEOUT_S))
        )
        self.agent_source = (
            agent_source
            or os.environ.get("LAB_MCP_AGENT_SOURCE")
            or DEFAULT_AGENT_SOURCE
        )
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self.base_url, timeout=self.timeout
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> "LabClient":
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.aclose()

    # ---------- meta / health ----------

    async def health(self) -> dict:
        return await self._get_json("/api/health")

    async def platforms(self) -> dict:
        return await self._get_json("/api/platforms")

    async def catalog(self) -> dict:
        return await self._get_json("/api/catalog")

    # ---------- equipment ----------

    async def list_equipment(self) -> dict:
        return await self._get_json("/api/equipment")

    async def get_equipment_status(self, equipment_id: str) -> dict:
        return await self._get_json(f"/api/equipment/{equipment_id}/status")

    # ---------- history ----------

    async def recent_events(self, device_id: str, limit: int = 50) -> dict:
        return await self._get_json(
            f"/api/history/events/{device_id}", params={"limit": limit}
        )

    async def uptime(
        self, device_id: Optional[str] = None, days: int = 7
    ) -> dict:
        if device_id:
            return await self._get_json(
                f"/api/history/uptime/{device_id}", params={"days": days}
            )
        return await self._get_json("/api/history/uptime", params={"days": days})

    async def latest_sensors(self) -> dict:
        return await self._get_json("/api/history/sensors/latest")

    async def sensor_history(
        self,
        sensor_id: str,
        metric: str,
        since_hours: float = 1.0,
        limit: int = 2000,
    ) -> dict:
        return await self._get_json(
            f"/api/history/sensors/{sensor_id}/{metric}",
            params={"since_hours": since_hours, "limit": limit},
        )

    async def recent_runs(
        self, limit: int = 20, device_id: Optional[str] = None
    ) -> dict:
        params: dict[str, Any] = {"limit": limit}
        if device_id:
            params["device_id"] = device_id
        return await self._get_json("/api/history/runs", params=params)

    async def run_wells(self, run_id: str) -> dict:
        return await self._get_json(f"/api/history/runs/{run_id}/wells")

    # ---------- ingest (agent observations) ----------

    async def ingest_event(self, device_id: str, record: dict) -> None:
        """POST one IngestEventRecord wrapped in the documented envelope.

        Mirrors ``IngestEventsRequest`` in
        ``ac-organic-lab/api/app/history.py``: ``{device_id, records:[...]}``.
        """
        body = {"device_id": device_id, "records": [record]}
        resp = await self._client.post("/api/ingest/events", json=body)
        resp.raise_for_status()

    async def append_observation(
        self,
        device_id: str,
        summary: str,
        *,
        severity: str = "info",
        extra: Optional[dict] = None,
    ) -> dict:
        """Convenience wrapper that builds the IngestEventRecord shape.

        ``severity`` and ``source`` live under ``extra`` rather than
        ``context`` because the aggregator's ``ingest_events`` collapses
        ``context`` into ``message`` when ``message`` is empty (see
        ``api/app/history.py::ingest_events``). Keeping severity in
        ``extra`` means it survives a round trip via ``/api/history/events``.
        """
        if severity not in ("info", "warning", "error"):
            raise ValueError(
                f"severity must be one of info/warning/error, got {severity!r}"
            )
        record_extra: dict[str, Any] = {
            "source": self.agent_source,
            "severity": severity,
        }
        if extra:
            record_extra.update(extra)

        record = {
            "timestamp": datetime.now(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "event": "agent_observation",
            "message": summary,
            "from_state": None,
            "to_state": None,
            "context": None,
            "extra": record_extra,
        }
        await self.ingest_event(device_id, record)
        return record

    # ---------- internals ----------

    async def _get_json(
        self, path: str, params: Optional[dict] = None
    ) -> dict:
        resp = await self._client.get(path, params=params)
        resp.raise_for_status()
        return resp.json()
