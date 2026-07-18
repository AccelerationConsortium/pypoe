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
Browser ──► Next.js (web/, :8000) ──► FastAPI aggregator (:8001) ──► equipment APIs
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
                                       ├─► consult_poe (PoeChatClient → Poe API)
                                       └─► ask_human  (Slack thread reply)
```

The dashboard at `LAB_API_URL` (default `http://localhost:8000`) — the
Next.js front door, which proxies `/api/*` to the FastAPI aggregator on
`:8001` — is the **single source of truth**. PyPoe never caches lab state.

## Install

```bash
pip install -e ".[lab]"
```

This adds four runtime deps to PyPoe: `mcp`, `httpx`, `slack-sdk`,
`pyyaml`. Combine with the existing extras as needed:

```bash
pip install -e ".[web-ui,lab]"   # also runs pypoe web + slack bot
pip install -e ".[dev]"          # everything, including [lab]
```

## Configure

Three files cooperate, all under **`src/pypoe/config/`**:

- **`slack.yaml`** holds the lab-side knobs (aggregator URL,
  slash-command prefix, alert channel, consult model list, …).
  *Gitignored*. Copy `slack.example.yaml` next to it as a starting
  point.
- **`models.yaml`** is the Poe model catalog used by every PyPoe
  interface (CLI/web/slack/lab). *Gitignored*. Copy
  `models.example.yaml` next to it. The `consult.models` entries in
  `slack.yaml` MUST exist in this file's `chat_models` list.
- **`.env`** at the project root keeps **secrets only** —
  `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, `POE_API_KEY`. Nothing in
  `.env` controls lab behaviour; that all lives in the YAMLs.

All three files are optional. With none present, both loaders fall
back to baked-in defaults: an 8-model `CHAT_MODELS` snapshot and the
defaults inside `pypoe.lab.config.LabConfig`. `pypoe lab-mcp` and
`pypoe lab-status` start cleanly against `http://localhost:8000` in
that mode.

### `slack.yaml` schema

```yaml
lab:
  api_url: http://localhost:8000        # ac-organic-lab dashboard (proxies /api/* to :8001)
  slack:
    alert_channel: "#lab-alerts"        # Kuma alerts + ask_human
    command_prefix: /lab-               # namespace for /lab-* commands
  alerts:
    max_concurrent_investigations: 2    # cap on simultaneous claude -p
  mcp:
    agent_source: claude-agent          # stamped into observations
    http_timeout_s: 10                  # aggregator HTTP read timeout
  consult:
    enabled: true                       # ask Poe models for second opinions
    models:                             # one consult_poe call per entry
      - GPT-5.5                         # names must match an entry in
      - Claude-Opus-4.7                 # config/models.yaml::chat_models
```

When `consult.enabled` is true (default), every `/alerts/kuma`
investigation requires Claude to call `consult_poe` once per model
listed under `consult.models`. Claude then synthesises all responses
into a Slack thread reply that includes a headline, per-model
bullets (with divergences flagged explicitly), and Claude's own
diagnosis. Failures of individual `consult_poe` calls are noted in
the summary, never aborts.

Set `consult.enabled: false` (or leave `consult.models` empty) to
keep Claude solo — the old prompt that suggested consultation only
"if a failure looks ambiguous."

To bring up a second lab in the same Slack workspace, give it a
different prefix and channel:

```yaml
lab:
  slack:
    alert_channel: "#sdl2-lab-alerts"
    command_prefix: /sdl2-lab-
```

### `models.yaml` schema

```yaml
default: Claude-Sonnet-4.6           # used wherever DEFAULT_CHAT_MODEL is needed
chat_models:                         # the list PyPoe's UIs offer to users
  - Claude-Opus-4.7
  - Claude-Sonnet-4.6
  - GPT-5.5
  - GPT-5.5-Pro
  - GPT-4-Turbo
  - Grok-4
  - Gemini-3.1-Pro
  - Gemini-3-Flash
pricing_usd_per_1m_tokens:           # Poe pricing snapshot; controls
  Claude-Opus-4.7:    { prompt: 4.2929,  completion: 21.4646  }   # the
  Claude-Sonnet-4.6:  { prompt: 2.5758,  completion: 12.8788  }   # $-meter
  # ... (etc — see config/models.example.yaml)
```

Run `scripts/utils/update_models.py` to test which entries in
`chat_models` are currently live on Poe before editing the list.

### Override precedence

Highest wins:

1. Explicit kwargs in code (rare; tests / advanced wiring).
2. Environment variables:
   `LAB_API_URL`, `LAB_SLACK_CHANNEL`, `LAB_SLACK_COMMAND_PREFIX`,
   `LAB_ALERT_MAX_CONCURRENT`, `LAB_MCP_AGENT_SOURCE`,
   `LAB_MCP_HTTP_TIMEOUT`, `LAB_CONSULT_ENABLED`,
   `LAB_CONSULT_MODELS` (comma-separated).
3. Values in `slack.yaml`.
4. Defaults baked into `pypoe.lab.config`.

`PYPOE_LAB_CONFIG=<path>` overrides the file location entirely;
when set, the loader looks only at that path (no fallback to the
packaged location), so tests and one-off configs are easy. The
same pattern applies to `PYPOE_MODELS_CONFIG=<path>` for the model
catalog.

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
| `consult_poe(model, question, context?)` | other-LLM | `pypoe.core.client.PoeChatClient.send_message` (ephemeral; no DB write) |
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
POST its default JSON payload to `http://<host>:<port>/alerts/kuma`
(a webhook-type notification; on the current deployment that is
`http://100.64.254.6:8006/alerts/kuma`).

**On a DOWN alert** (`heartbeat.status == 0`):

1. PyPoe posts `:rotating_light: *<monitor>* DOWN — <msg>
   :mag: Investigating…` to `LAB_SLACK_CHANNEL` and captures the
   thread `ts`.
2. A background task (bounded by `consult.max_concurrent_investigations`)
   spawns `claude -p` with a prompt that tells Claude to:
   - call `aggregator_health()` + `list_equipment()` first;
   - for each non-healthy device, call `get_equipment_status()` +
     `recent_events()`;
   - call `consult_poe(model=…)` once per entry in `consult.models`
     (if `consult.enabled`) for an independent second opinion;
   - optionally call `ask_human(...)` for judgment calls;
   - call `append_observation(device_id, ...)` per affected device;
   - synthesize a Slack reply: headline → per-model bullets with
     divergences explicit → Claude's own diagnosis → plain-English
     recovery recommendation (no `/control/*` calls).
3. The synthesised summary lands as a **threaded reply** under the
   original `:rotating_light:` post (truncated to ~3000 chars).

**On a RECOVERY alert** (`heartbeat.status == 1`): PyPoe posts a
single `:white_check_mark: recovered` line. **No investigation, no
Claude, no Poe.** This keeps the alert loop quiet for normal
flap recoveries.

**Choosing the Kuma monitor name matters.** The `monitor.name` you
typed in Kuma is the first signal Claude has for *which device the
alert is about*. Naming Kuma monitors after the `equipment.yaml` id
(e.g. `plateloc`, `dose_every_well`, `aggregator`) lets Claude map
directly without guesswork. Otherwise Claude falls back to scanning
all non-healthy devices via `list_equipment()`.

**Auth:** the `claude` CLI authenticates with **Claude Team** OAuth
(run `claude` once on the host), so no Anthropic API key is needed in
the PyPoe environment. `consult_poe` uses your `POE_API_KEY`.

**Headless permissions (load-bearing).** Two things must be true on
the host or every investigation replies "my tools are unavailable":

1. The `pypoe-lab` MCP server is registered for the `claude` CLI in
   the directory `pypoe web` runs from (its `WorkingDirectory`):

   ```bash
   cd /path/to/pypoe
   claude mcp add pypoe-lab -e LAB_API_URL=http://127.0.0.1:8001 -- \
       /path/to/pypoe/.venv/bin/pypoe lab-mcp
   ```

2. The spawned `claude -p` is pre-allowed to call those tools —
   headless runs cannot grant permissions interactively. The webhook
   passes `--allowedTools "mcp__pypoe-lab__*"` for exactly this
   reason; if you rename the MCP server, update that flag in
   `lab/alert_routes.py` to match.

### From the lab aggregator (device alerts)

Uptime Kuma watches the *platform services*; the *devices* are
watched by the lab aggregator itself, which already polls every
device. Its `alert_notifier` (in `ac-organic-lab`, `api/app/
alert_notifier.py`, enabled by `PYPOE_ALERT_URL` in that repo's
`.env`) POSTs to PyPoe's second webhook:

```
POST /alerts/device
{"device_id": "plateloc", "event": "error",
 "state": "error", "message": "...", "last_error": {...},
 "devices": ["cytation_5", ...]}        # only on storm-collapsed alerts
```

Events: `unreachable` | `error` | `e_stop` | `degraded` | `recovered`.
Same Slack channel and investigation machinery as the Kuma path, but
the prompt is **device-focused** — Claude goes straight to
`get_equipment_status("<device_id>")`, `recent_events`, and
`device_uptime` instead of a fleet-wide sweep, and the device's
`last_error` rides along in the prompt. `recovered` posts a
`:white_check_mark:` one-liner, no investigation.

The debounce/cooldown/storm rules (2-sweep sustained unreachable,
immediate error/e_stop, 30-min per-device cooldown, ≥3 devices in one
sweep collapse into a single alert) all live on the aggregator side —
PyPoe just renders and investigates whatever arrives.

### Kuma tile on the lab dashboard (`/kuma/status`)

PyPoe also **gateway-fronts Uptime Kuma** for the dashboard (the same
pattern kasa-tapo-services uses for cameras): `GET /kuma/status`
serves a STATUS_SPEC v1.0 envelope with one component per Kuma
monitor, built from Kuma's public status-page API
(`PYPOE_KUMA_URL`, slug `PYPOE_KUMA_STATUS_SLUG`, default `lab`) and
cached for 15 s. Any monitor down → `degraded` (message names them);
Kuma unreachable → `unknown` per STATUS_SPEC §2.1. The lab's
`equipment.yaml` registers this as `uptime_kuma` under Services.

Related: when `PYPOE_KUMA_URL` is set, PyPoe's own `/status` gains a
required `uptime_kuma` component — Kuma alerts when PyPoe dies, the
dashboard shows when Kuma dies; neither can die silently.

Kuma deployment notes (dashboard host): docker, **host networking**
(`--network host -e UPTIME_KUMA_PORT=8005`, volume `uptime-kuma`) —
bridge networking cannot reach the loopback/Tailscale-bound services.
Admin credentials live in `~/.pypoe/uptime-kuma-admin.credentials`.
When adding monitors for auth-gated services, probe an endpoint that
answers plainly (e.g. the auth sidecar's `/status`) — Kuma's checks
send browser-style `Accept` headers, so login-redirecting endpoints
302 → 404 and flap the monitor.

### From the command line

```bash
# Quick "is the lab healthy?" check, no Slack, no Claude:
pypoe lab-status

# Override base URL for ad-hoc checks against a non-default aggregator:
pypoe lab-status --base-url http://lab-staging:8000

# Run the MCP server interactively (Claude Desktop / Code spawns this):
pypoe lab-mcp
```

## What gets stored where

A common question: does the Slack thread / Claude's report / the
human's reply get persisted anywhere?

| Artifact | Stored where? | Queryable? |
|---|---|---|
| `:rotating_light:` alert post, `:white_check_mark:` recovery line, threaded investigation summary | **Slack only** | yes — Slack thread is the audit log |
| `ask_human(...)` `:question:` post + the human's reply | **Slack only** | yes — same thread |
| `consult_poe(...)` round-trip with Poe | **Ephemeral** (no DB write) | no |
| `append_observation(...)` per-device finding | **Aggregator's `lab.db`** (`equipment_events` table) | yes — `GET /api/history/events/{device_id}` + dashboard history sidebar |
| PyPoe chat conversations (`/poe ...`, web UI, `pypoe cli`) | `~/.pypoe/single_webchat_history.db` | yes — `pypoe cli list` / web UI |

Deliberate design: PyPoe's chat DB is for **Poe conversations**.
Operational signals (alerts, summaries, second opinions) live in
Slack where multiple humans can audit. Per-device findings live in
the aggregator's DB so they render alongside `state_transition`,
`error`, `startup`, etc. for the same device.

### What does an `agent_observation` row look like?

```json
{
  "ts": "2026-05-19T22:32:06.361461Z",
  "device_id": "plateloc",
  "event_type": "agent_observation",
  "from_state": null,
  "to_state": null,
  "message": "<one-line summary from Claude>",
  "payload": {
    "source": "claude-agent",           // from cfg.mcp.agent_source
    "severity": "info | warning | error",
    "<anything Claude passed in extra>": "..."
  }
}
```

Severity and source live in `payload`, not `context`, so the
aggregator's `message = rec.message or rec.context` collapse leaves
the message field intact when read back via `recent_events()`.

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
| `consult_poe` returns `returncode: 2` with "not accessible" | `POE_API_KEY` unset, expired, or the model name isn't in `models.yaml::chat_models` | Set `POE_API_KEY` in `.env`; double-check `consult.models` entries match `chat_models`. |
| `consult_poe` returns `returncode: 1` | Transient network error or Poe API blip | Investigation continues; Claude notes the failure in the summary. Retry next alert. |
| `ask_human` immediately times out | `SLACK_BOT_TOKEN` missing or the bot isn't in `LAB_SLACK_CHANNEL` | Invite the bot to the channel, double-check token. |
| Observations don't appear in the dashboard sidebar | Severity / source ended up in `context` instead of `extra` | This package always uses `extra`. If you wrote a custom MCP tool, port it. |
| `/sdl2-lab-status` says "did not respond" in Slack | Slack app config doesn't declare that command name | Each `/lab-*` (or `/<prefix>-…`) must be added in the Slack app admin UI before the bot can receive it. Reinstall the app after adding. |

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
