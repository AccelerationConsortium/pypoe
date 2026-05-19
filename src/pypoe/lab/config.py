"""Lab-integration config loader.

Loads runtime knobs for the ``pypoe.lab.*`` modules from a single YAML
file at ``src/pypoe/config/slack.yaml`` (gitignored; copy from
``slack.example.yaml`` next to it). Env vars take precedence so quick
overrides and CI don't require editing the YAML.

Why YAML instead of just ``.env``? The lab integration grew enough
knobs (api_url, alert_channel, command_prefix, mcp settings, alert
concurrency, consult model list) that a single typed config file is
easier to read and share than a flat env-var soup. ``.env`` keeps
secrets only (Slack bot token, signing secret, Poe API key).

Precedence (highest wins):
  1. Explicit kwargs in code (e.g. ``LabClient(base_url=...)``).
  2. Environment variables (``LAB_API_URL``, ``LAB_SLACK_CHANNEL``,
     ``LAB_SLACK_COMMAND_PREFIX``, ``LAB_ALERT_MAX_CONCURRENT``,
     ``LAB_MCP_AGENT_SOURCE``, ``LAB_MCP_HTTP_TIMEOUT``).
  3. Values in the YAML config.
  4. Hardcoded defaults below.

The YAML file is **optional**. Existing deployments that only set
env vars keep working unchanged.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


# Resolution order for finding the YAML file.
DEFAULT_FILENAME = "slack.yaml"
EXAMPLE_FILENAME = "slack.example.yaml"


@dataclass(frozen=True)
class SlackSection:
    alert_channel: str = "#lab-alerts"
    command_prefix: str = "/lab-"


@dataclass(frozen=True)
class AlertsSection:
    max_concurrent_investigations: int = 2


@dataclass(frozen=True)
class McpSection:
    agent_source: str = "claude-agent"
    http_timeout_s: float = 10.0


@dataclass(frozen=True)
class LabConfig:
    """Effective config used by every ``pypoe.lab.*`` module."""

    api_url: str = "http://localhost:8001"
    slack: SlackSection = field(default_factory=SlackSection)
    alerts: AlertsSection = field(default_factory=AlertsSection)
    mcp: McpSection = field(default_factory=McpSection)

    # Where the YAML actually came from (None if no file was found).
    source_path: Optional[Path] = None


# ---------------------------------------------------------------------------


def _package_config_dir() -> Path:
    """Return the directory holding the lab-integration YAML configs.

    Lives next to ``pypoe.lab.config`` inside the installed package, at
    ``src/pypoe/config/`` in an editable install. Keeps user-edited
    config tucked away from the project root.
    """
    return Path(__file__).resolve().parent.parent / "config"


def _candidate_paths() -> list[Path]:
    """All YAML locations to try, in priority order.

    If ``PYPOE_LAB_CONFIG`` is set, it is **authoritative** — we do not
    fall back to the packaged location, so tests can disable YAML
    loading by pointing this env var at a non-existent path.
    """
    custom = os.environ.get("PYPOE_LAB_CONFIG")
    if custom:
        return [Path(custom).expanduser().resolve()]
    return [_package_config_dir() / DEFAULT_FILENAME]


def _load_yaml_file() -> tuple[dict, Optional[Path]]:
    """Load the first YAML file that exists. Returns ``({}, None)`` if none."""
    try:
        import yaml  # noqa: WPS433 — optional at lab-extra level
    except ImportError as exc:
        logger.debug("PyYAML not installed; skipping slack.yaml: %s", exc)
        return {}, None

    for path in _candidate_paths():
        if not path.is_file():
            continue
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
        except Exception as exc:
            logger.warning("Failed to parse %s: %s — falling back to env/defaults", path, exc)
            return {}, None
        if not isinstance(data, dict):
            logger.warning("%s did not parse to a mapping (got %s)", path, type(data).__name__)
            return {}, None
        return data, path
    return {}, None


def _dig(d: dict, *keys: str, default: Any = None) -> Any:
    """Walk a nested dict; return ``default`` for missing branches."""
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def _env_float(name: str) -> Optional[float]:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except ValueError:
        logger.warning("Ignoring non-numeric %s=%r", name, raw)
        return None


def _env_int(name: str) -> Optional[int]:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        logger.warning("Ignoring non-integer %s=%r", name, raw)
        return None


def load_config() -> LabConfig:
    """Return the effective :class:`LabConfig` for this process.

    Reads ``slack.yaml`` (if present) and applies env-var overrides.
    Safe to call from any module — cached on first call.
    """
    if _LOADED["cfg"] is not None:
        return _LOADED["cfg"]

    raw, src = _load_yaml_file()

    lab_root = raw.get("lab") if isinstance(raw.get("lab"), dict) else raw

    api_url = (
        os.environ.get("LAB_API_URL")
        or _dig(lab_root, "api_url")
        or "http://localhost:8001"
    )

    slack = SlackSection(
        alert_channel=(
            os.environ.get("LAB_SLACK_CHANNEL")
            or _dig(lab_root, "slack", "alert_channel")
            or SlackSection.__dataclass_fields__["alert_channel"].default
        ),
        command_prefix=(
            os.environ.get("LAB_SLACK_COMMAND_PREFIX")
            or _dig(lab_root, "slack", "command_prefix")
            or SlackSection.__dataclass_fields__["command_prefix"].default
        ),
    )

    alerts = AlertsSection(
        max_concurrent_investigations=(
            _env_int("LAB_ALERT_MAX_CONCURRENT")
            or _dig(lab_root, "alerts", "max_concurrent_investigations")
            or AlertsSection.__dataclass_fields__["max_concurrent_investigations"].default
        ),
    )

    mcp = McpSection(
        agent_source=(
            os.environ.get("LAB_MCP_AGENT_SOURCE")
            or _dig(lab_root, "mcp", "agent_source")
            or McpSection.__dataclass_fields__["agent_source"].default
        ),
        http_timeout_s=(
            _env_float("LAB_MCP_HTTP_TIMEOUT")
            or _dig(lab_root, "mcp", "http_timeout_s")
            or McpSection.__dataclass_fields__["http_timeout_s"].default
        ),
    )

    cfg = LabConfig(api_url=api_url, slack=slack, alerts=alerts, mcp=mcp, source_path=src)
    _LOADED["cfg"] = cfg
    return cfg


def reload_config() -> LabConfig:
    """Force re-read of the YAML + env. Useful in tests and in long-lived
    services that want to pick up a hot-edit without restarting.
    """
    _LOADED["cfg"] = None
    return load_config()


# Lazy singleton storage. A dict (not a module-level Optional[LabConfig])
# so tests can monkeypatch through `_LOADED["cfg"] = None`.
_LOADED: dict[str, Optional[LabConfig]] = {"cfg": None}
