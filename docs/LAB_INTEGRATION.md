# Lab Integration

PyPoe ships an optional **lab-interface layer** for the AC Organic
Self-driving Lab. With `pip install -e ".[lab]"` PyPoe gains:

- a read-only **MCP server** (`pypoe lab-mcp`) for Claude Desktop /
  Claude Code, so you can ask Claude about lab state in natural
  language;
- **`/lab-*` Slack slash commands** (no LLM, instant response) for
  humans on the team;
- a **`POST /alerts/kuma` webhook** mounted on `pypoe web` for Uptime
  Kuma to trigger autonomous investigations via `claude -p`;
- a **`pypoe lab-status`** one-shot CLI that prints aggregator health
  and any device that needs operator attention.

The layer is intentionally **read-only at the device level**: there is
no `control_action` MCP tool, no `LAB_MCP_ENABLE_CONTROL` knob, and the
HTTP client cannot talk to `/control/*` endpoints. Control belongs to
the `lab-skills` SDK (in the `ac-organic-lab/` repo) and the
forthcoming `lab-skills mcp serve` MCP server, which enforces the
four-layer interlock model documented in `ac-organic-lab/docs/INTERLOCKS.md`.

## Architecture (one diagram)

```
Browser ──► Next.js (web/) ──► FastAPI aggregator (:8001) ──► equipment APIs
                                ▲              ▲
                                │              │  POST /api/ingest/events
                                │              │  (agent observations)
                                │              │
   Claude Code / Desktop ──MCP──┘              │
   (pypoe lab-mcp; READ + OBSERVE)             │
                                               │
   PyPoe Slack bot ──/lab-* commands ──────────┤   (no LLM)
                                               │
   Uptime Kuma ──── /alerts/kuma ──► claude -p ─┘
                                       │
                                       ├─► consult_poe (Poe via PyPoe CLI)
                                       └─► ask_human  (Slack thread reply)
```

The aggregator at `LAB_API_URL` (default `http://localhost:8001`) is
the **single source of truth**. PyPoe never caches lab state.

## Install

```bash
pip install -e ".[lab]"
```

This adds three runtime deps to PyPoe: `mcp`, `httpx`, and
`slack-sdk`. Combine with the existing extras as needed:

```bash
pip install -e ".[web-ui,lab]"   # also runs pypoe web + slack bot
pip install -e ".[dev]"          # everything, including [lab]
```

## Configure

Two files cooperate:

- **`slack.yaml`** at PyPoe project root holds the lab-side knobs
  (aggregator URL, slash-command prefix, alert channel, etc.). This
  file is *gitignored* and site-specific; a template
  (`slack.example.yaml`) is committed for you to copy.
- **`.env`** keeps **secrets only** — `SLACK_BOT_TOKEN`,
  `SLACK_SIGNING_SECRET`, `POE_API_KEY`. Nothing in `.env` controls
  lab behaviour; that all moved to `slack.yaml`.

Either file is optional. With neither present, the loader falls back
to the hardcoded defaults in `pypoe.lab.config.LabConfig` and a
`pypoe lab-mcp` server still starts cleanly against
`http://localhost:8001`.

### `slack.yaml` schema

```yaml
lab:
  api_url: http://localhost:8001        # ac-organic-lab aggregator
  slack:
    alert_channel: "#lab-alerts"        # Kuma alerts + ask_human
    command_prefix: /lab-               # namespace for /lab-* commands
  alerts:
    max_concurrent_investigations: 2    # cap on simultaneous claude -p
  mcp:
    agent_source: claude-agent          # stamped into observations
    http_timeout_s: 10                  # aggregator HTTP read timeout
```

To bring up a second lab in the same Slack workspace, give it a
different prefix and channel:

```yaml
lab:
  slack:
    alert_channel: "#sdl2-lab-alerts"
    command_prefix: /sdl2-lab-
```

### Override precedence

Highest wins:

1. Explicit kwargs in code (rare; tests / advanced wiring).
2. Environment variables:
   `LAB_API_URL`, `LAB_SLACK_CHANNEL`, `LAB_SLACK_COMMAND_PREFIX`,
   `LAB_ALERT_MAX_CONCURRENT`, `LAB_MCP_AGENT_SOURCE`,
   `LAB_MCP_HTTP_TIMEOUT`.
3. Values in `slack.yaml`.
4. Defaults baked into `pypoe.lab.config`.

`PYPOE_LAB_CONFIG=<path>` overrides the file location entirely;
when set, the loader looks only at that path (no fallback to the
project-root file), so tests and one-off configs are easy.

### Secrets stay in `.env`

```
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...
POE_API_KEY=...
```

Optionally, `PYPOE_ENABLE_LAB=1` in `.env` will wire `/lab-*` and
`/alerts/kuma` even when `slack.yaml` is missing.

There is **no** `LAB_MCP_ENABLE_CONTROL` — control is intentionally
not exposed.

## Use it

### From Claude Desktop / Code (MCP)

Register the server once:

```bash
claude mcp add ac-organic-lab -- pypoe lab-mcp
```

…then in any Claude session ask things like:

> List lab equipment and tell me which ones are not ready.

> The `plateloc` has been in `requires_init` for an hour. What does
> its recent event log show, and what should I tell the operator?

> Append an observation to `dose_every_well` saying "post-recovery
> sweep looks clean" with severity `info`.

The MCP server registers exactly these 13 tools — note the absence of
a `control_action`:

| Tool | Kind | Source |
|---|---|---|
| `list_equipment()` | read | `GET /api/equipment` |
| `get_equipment_status(id)` | read | `GET /api/equipment/{id}/status` |
| `aggregator_health()` | read | `GET /api/health` |
| `list_platforms()` | read | `GET /api/platforms` |
| `skill_catalog()` | read | `GET /api/catalog` |
| `recent_events(id, limit)` | read | `GET /api/history/events/{id}` |
| `device_uptime(id?, days)` | read | `GET /api/history/uptime[/{id}]` |
| `latest_sensors()` | read | `GET /api/history/sensors/latest` |
| `recent_runs(limit)` | read | `GET /api/history/runs` |
| `run_wells(run_id)` | read | `GET /api/history/runs/{id}/wells` |
| `append_observation(id, summary, severity, extra?)` | write (journaling) | `POST /api/ingest/events` |
| `consult_poe(model, question, context?)` | other-LLM | shells `pypoe cli chat --bot <model>` |
| `ask_human(question, channel?, timeout_s)` | human-in-the-loop | Slack thread reply with polling |

`append_observation` is the **only** write path. It posts an
`agent_observation` event into the aggregator's history table; the
record shows up in `GET /api/history/events/{device_id}` and on the
dashboard's history sidebar. Severity and source live under `extra` so
they survive the aggregator's `message = rec.message or rec.context`
collapse (see `ac-organic-lab/api/app/history.py::ingest_events`).

### From the Slack bot

`pypoe slack` automatically registers `/lab-*` commands when
`LAB_API_URL` (or `PYPOE_ENABLE_LAB`) is set. No restart needed beyond
`pypoe slack` itself.

Commands below use the default prefix `/lab-`. With
`LAB_SLACK_COMMAND_PREFIX=/sdl2-lab-`, read every `/lab-` as
`/sdl2-lab-`.

| Command | Argument | Output |
|---|---|---|
| `/lab-status` | — | Aggregator health + every device whose state is not `ready/idle/running/dry_run`, with claim holder if any. |
| `/lab-device` | `<equipment_id>` | One device's state, message, allowed actions, last error, and claim. |
| `/lab-runs` | `[limit]` (default 10) | Most recent dosing runs. |
| `/lab-sensors` | — | Latest reading per sensor (capped at 20 lines). |
| `/lab-actions` | `<equipment_id>` | The device's `allowed_actions` per STATUS_SPEC v1.1 — useful for "what could `lab-skills` do right now?". |

> When registering these in the Slack app admin UI, the **Command** field
> takes only the hyphenated name (e.g. `/lab-device` or `/sdl2-lab-device`).
> Arguments are typed by the user when they invoke the command (e.g.
> `/lab-device plateloc`). Put the argument hint into Slack's
> **Usage Hint** field instead, where spaces are allowed. The
> `equipment_id` is the `id:` key from `ac-organic-lab/equipment.yaml`
> (e.g. `plateloc`, `dose_every_well`, `ot2`).

These call the aggregator directly and never invoke an LLM, so they're
instant and free.

### From Uptime Kuma

Once `pypoe web` is running with `LAB_API_URL` set, configure Kuma to
POST its default JSON payload to `http://<host>:8000/alerts/kuma`.
On a "down" alert, PyPoe will:

1. Post `:rotating_light: *<monitor>* DOWN — <msg> :mag: Investigating…`
   to `LAB_SLACK_CHANNEL`, capturing the thread `ts`.
2. Spawn `claude -p` in the background (bounded by
   `LAB_ALERT_MAX_CONCURRENT`). The prompt tells Claude to use the
   `pypoe-lab` MCP server to investigate, optionally `consult_poe` for
   a second opinion, optionally `ask_human` for judgment calls, and
   journal each finding via `append_observation`. It is explicitly
   told it **cannot** perform control actions and to recommend them in
   plain English instead.
3. Post Claude's summary as a threaded reply (truncated to ~3000
   chars).

On a "recovery" alert, PyPoe posts a single recovery line and does not
spawn an investigation.

The `claude` CLI authenticates with **Claude Team** OAuth (run
`claude` once on the host), so no Anthropic API key is needed in the
PyPoe environment.

### From the command line

```bash
# Quick "is the lab healthy?" check, no Slack, no Claude:
pypoe lab-status

# Override base URL for ad-hoc checks against a non-default aggregator:
pypoe lab-status --base-url http://lab-staging:8001

# Run the MCP server interactively (Claude Desktop / Code spawns this):
pypoe lab-mcp
```

## What this is NOT

- **Not a replacement for `lab-skills mcp serve`** (`ac-organic-lab`
  v0.4 milestone). When that ships, register both:
  - `pypoe lab-mcp` for visibility, journaling, and consultation;
  - `lab-skills mcp serve` for skill dispatch with claim semantics and
    interlock enforcement.
- **Not a control surface.** Direct `/control/*` calls would bypass
  Layer 3 (skill preconditions) and Layer 4 (project interlocks) per
  `ac-organic-lab/docs/INTERLOCKS.md`. Control flows through
  `lab-skills`, period.
- **Not a state cache.** PyPoe re-asks the aggregator on every call.
  The aggregator is the source of truth; PyPoe is plumbing.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `pypoe lab-status` says "Aggregator unreachable" | Aggregator service down or `LAB_API_URL` wrong | `curl $LAB_API_URL/api/health`; check `journalctl -u ac-organic-lab-api` on the dashboard host. |
| `/lab-*` commands missing in Slack | `LAB_API_URL` / `PYPOE_ENABLE_LAB` unset, or `[lab]` extra not installed | Set env var and reinstall with `pip install -e ".[lab]"`. Restart `pypoe slack`. |
| `claude` exits 127 in Kuma thread | `claude` CLI not on PATH on the PyPoe host | Install Claude Code locally; run `claude` once to OAuth into Claude Team. |
| `consult_poe` returns "pypoe CLI not on PATH" | The MCP host runs PyPoe from a different venv | Make sure `pypoe` is on PATH of whatever process Claude Desktop spawns. |
| `ask_human` immediately times out | `SLACK_BOT_TOKEN` missing or the bot isn't in `LAB_SLACK_CHANNEL` | Invite the bot to the channel, double-check token. |
| Observations don't appear in the dashboard sidebar | Severity / source ended up in `context` instead of `extra` | This package always uses `extra`. If you wrote a custom MCP tool, port it. |

## Background reading

- `pypoe_upgrade_plan.md` — design document for this work (kept at the
  repo root next to PyPoe and `ac-organic-lab`).
- `ac-organic-lab/docs/STATUS_SPEC.md` — device contract (v1.0 + v1.1).
- `ac-organic-lab/docs/INTERLOCKS.md` — four-layer safety model that
  motivates the read-only constraint here.
- `ac-organic-lab/docs/OBSERVABILITY.md` — aggregator history DB
  schema; `agent_observation` is intended to extend the documented
  `event_type` set (a small docs PR is pending upstream).
- `ac-organic-lab/docs/ROADMAP.md` § v0.4 — the SDK-side MCP server
  that complements this one.
