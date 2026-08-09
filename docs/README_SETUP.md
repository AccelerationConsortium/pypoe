# PyPoe Setup

Install, configure, and verify a PyPoe install. Interface-specific guides
live in [README_SLACK.md](README_SLACK.md) (Slack), [README_WEB.md](README_WEB.md) (web UI),
and [README_SYSTEMD.md](README_SYSTEMD.md) (systemd).

## Prerequisites

- Python 3.8 or newer (3.10+ recommended).
- A Poe API key from <https://poe.com/api_key> (requires a Poe subscription).
- Git, to clone the repo.
- Optional: Slack workspace with admin access (for the Slack bot),
  Tailscale (for remote web access), Linux + systemd (for always-on
  services).

## Install options

PyPoe is installed editable from a clone:

```bash
git clone https://github.com/your-username/pypoe.git
cd pypoe
```

| Command | What it ships |
|---------|---------------|
| `pip install -e .` | Core SDK + CLI |
| `pip install -e ".[web-ui]"` | + web UI and Slack bot (`fastapi`, `slack-bolt`, etc.) |
| `pip install -e ".[media]"` | + image/video auto-download deps (`aiohttp`); also set `PYPOE_ENABLE_MEDIA=true` |
| `pip install -e ".[lab]"` | + AC Organic Self-driving Lab integration: read-only MCP server, `/lab-*` Slack commands, Kuma alert webhook, `pypoe lab-status` / `lab-mcp` CLI. See [LAB_INTEGRATION.md](LAB_INTEGRATION.md). |
| `pip install -e ".[dev]"` | Everything + `pytest`, `black`, `isort`, `flake8`, `mypy` |

There is no `[all]` extra; `[dev]` is the closest analogue.

## API keys and `.env`

`.env` is the recommended way to keep provider keys out of your shell
history. PyPoe loads the first file it finds, in this order (see
`_load_env_files` in [src/pypoe/core/config.py](../src/pypoe/core/config.py)):

1. `<repo-root>/.env`
2. `~/.pypoe/.env`
3. `./.env` (current working directory)

A minimal `.env`:

```env
POE_API_KEY=your-poe-api-key
```

### Model providers

PyPoe talks to two providers, and routing is **per model** — a Poe model and
an OpenRouter model can be used side by side, including as the two sides of a
debate. Which provider serves which model is declared in
[`src/pypoe/config/models.yaml`](../src/pypoe/config/models.example.yaml);
a bare string is a Poe model, a `{id: ..., provider: openrouter}` mapping is
an OpenRouter one.

**At least one** key must be set — it need not be Poe:

```env
POE_API_KEY=your-poe-api-key            # https://poe.com/api_key
OPENROUTER_API_KEY=sk-or-...            # https://openrouter.ai/keys
```

Poe is a flat subscription; **OpenRouter bills per token**, so a runaway loop
can actually spend money there. Two guards, both optional:

```env
# Ceiling on every OpenRouter completion (0 disables the cap).
PYPOE_OPENROUTER_MAX_TOKENS=4096

# Report OpenRouter degraded on /status once the remaining balance falls
# below this many USD — before requests start failing (0 disables).
PYPOE_OPENROUTER_MIN_CREDITS=1.0
```

`GET /status` carries one component per configured provider
(`poe_api`, `openrouter_api`) with a provider-qualified error code such as
`poe_subscription_required` or `openrouter_auth_failed`, plus the remaining
OpenRouter balance. A provider with no key is omitted rather than reported
unhealthy. The service reads `ready` as long as **one** provider can answer,
so a lapsed Poe subscription alongside a working OpenRouter key is not an
outage.

Add Slack and/or web variables only if you use those interfaces:

```env
# Web UI auth and binding (all optional)
PYPOE_HOST=127.0.0.1
PYPOE_PORT=8000
PYPOE_WEB_USERNAME=admin
PYPOE_WEB_PASSWORD=change-me

# Slack (all required if running pypoe slack)
SLACK_BOT_TOKEN=xoxb-...
SLACK_SIGNING_SECRET=...
SLACK_APP_TOKEN=xapp-...
SLACK_SOCKET_MODE=true

# History DB (defaults to ~/.pypoe/single_webchat_history.db)
DATABASE_PATH=/custom/path/history.db

# Media auto-download (off by default; needs the [media] extra)
PYPOE_ENABLE_MEDIA=false

# Slack one-shot db cleanup; see README_SLACK.md
PYPOE_SLACK_WIPE_ON_START=
```

Restrict permissions: `chmod 600 .env`. Never commit it.

## Database

Default location: `~/.pypoe/single_webchat_history.db`. The directory is
created on first run by [src/pypoe/core/config.py](../src/pypoe/core/config.py).
Override with `DATABASE_PATH`. Schema and inspection commands are
documented in [README_HISTORY.md](README_HISTORY.md).

## Verify the install

Each interface has its own smoke test:

```bash
# CLI
pypoe cli list                    # should print "No conversations" or a list

# Web UI (requires the [web-ui] extra)
pypoe web                         # then open http://127.0.0.1:8000

# Slack bot (requires the [web-ui] extra and SLACK_* env vars)
pypoe slack
```

Optional helper scripts in `scripts/setup/`:

- `setup_credentials.py` — interactive `.env` creation.
- `setup_webui.py` — guided web UI configuration.
- `setup_tailscale.py` — bind the web UI to your Tailscale IP.
- `install_system_services.sh` — install hardened system-level
  systemd units under a dedicated `pypoe` user. Ignore if you're
  using the user-level units in [README_SYSTEMD.md](README_SYSTEMD.md).

Plus one in `scripts/utils/`:

- `update_models.py` — interactive Poe model availability checker.
  Edit `src/pypoe/config/models.yaml` based on what reports as live.

## Troubleshooting

| Symptom | First thing to check |
|---------|----------------------|
| `No model provider is configured` | Set `POE_API_KEY` and/or `OPENROUTER_API_KEY`; check the `.env` location matches the precedence list above (`cat ~/.pypoe/.env` or `cat .env`). |
| `requires an active Poe subscription` | Poe API access needs a live subscription. Renew at <https://poe.com/subscription_plans>, or add `OPENROUTER_API_KEY` and OpenRouter models to `models.yaml` to keep working meanwhile. |
| `pypoe web` fails to import | You need the `[web-ui]` extra: `pip install -e ".[web-ui]"`. |
| `pypoe slack` fails to import | Same — `[web-ui]` ships `slack-bolt`. |
| Port 8000 already in use | `lsof -i :8000`; pass `--port 8001` to `pypoe web`. |
| Image/video URLs not downloaded | Install `[media]` and set `PYPOE_ENABLE_MEDIA=true`. |
| Database file missing or 0 bytes | First run creates it; check write permission on `~/.pypoe/`. |

For interface-specific issues, jump to the relevant guide:

- Web UI auth/bot-locking: [README_WEB.md](README_WEB.md)
- Slack app config / scopes / scoping: [README_SLACK.md](README_SLACK.md)
- systemd unit failures: [README_SYSTEMD.md](README_SYSTEMD.md)
