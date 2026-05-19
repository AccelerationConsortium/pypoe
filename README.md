# PyPoe

A Python client for Poe.com that exposes Poe's models through three
interfaces — a CLI, a local web UI, and a Slack bot — all sharing a
single SQLite conversation history at `~/.pypoe/single_webchat_history.db`.

## Three interfaces

- **CLI.** Interactive chat from the terminal.

  ```bash
  pypoe cli select          # pick or start a conversation
  pypoe cli chat            # start/continue a chat
  pypoe cli list            # list conversations
  ```

- **Web UI.** Browser chat with a sidebar of past conversations.

  ```bash
  pypoe web                 # http://127.0.0.1:8000
  ```

- **Slack bot.** `/poe` slash command, `@PyPoe` mentions, and DMs, with
  per-thread context.

  ```bash
  pypoe slack
  ```

All three write to and read from the same database, so conversations
started in one interface continue in the others.

### Optional: lab integration

PyPoe also ships a read-only **lab interface layer** for the AC Organic
Self-driving Lab. With `pip install -e ".[lab]"` you additionally get:

- `pypoe lab-mcp` — a read-only MCP server (talk to the lab from
  Claude Desktop / Code).
- `pypoe lab-status` — one-shot aggregator health summary.
- `/lab-*` Slack slash commands (auto-registered on `pypoe slack` when
  `LAB_API_URL` is set).
- `POST /alerts/kuma` webhook (auto-mounted on `pypoe web` under the
  same condition) for Uptime Kuma alert investigation.

The integration is **read-only at the device level**: there is no
`control_action` tool and no `/control/*` calls. Control flows through
the `lab-skills` SDK in `ac-organic-lab/`. See
[docs/LAB_INTEGRATION.md](docs/LAB_INTEGRATION.md) for setup.

## Install

PyPoe is editable-installed from a clone:

```bash
git clone https://github.com/your-username/pypoe.git
cd pypoe
pip install -e .                  # CLI only
pip install -e ".[web-ui]"        # CLI + web + Slack
pip install -e ".[dev]"           # everything + test/lint tools
```

The web UI and Slack bot share the same `web-ui` extra (both depend on
`fastapi`, `slack-bolt`, etc.). Image/video auto-download is a separate
`media` extra and requires `PYPOE_ENABLE_MEDIA=true` at runtime.

## Quickstart

1. Get a Poe API key from [poe.com/api_key](https://poe.com/api_key).
2. Create a `.env` in the repo root:

   ```env
   POE_API_KEY=your-poe-api-key
   ```

3. Pick an interface:

   ```bash
   pypoe cli select   # terminal
   pypoe web          # browser at http://127.0.0.1:8000
   pypoe slack        # requires Slack app + SLACK_* env vars
   ```

For network access, authentication, Slack app setup, or running as a
service, see the topic-specific docs below.

## Documentation

- [docs/README_SETUP.md](docs/README_SETUP.md) — install options, `.env`
  layout, environment variables, basic troubleshooting.
- [docs/README_WEB.md](docs/README_WEB.md) — running the web UI:
  network access, authentication, bot locking.
- [docs/README_SLACK.md](docs/README_SLACK.md) — Slack app creation,
  scopes, slash command and events, per-thread conversation scoping.
- [docs/README_SYSTEMD.md](docs/README_SYSTEMD.md) — running `pypoe-web`
  and `pypoe-slack` as user-level systemd services.
- [docs/README_HISTORY.md](docs/README_HISTORY.md) — history database:
  where it lives, schema, Slack id scheme, sqlite cookbook, cleanup
  commands.
- [docs/LAB_INTEGRATION.md](docs/LAB_INTEGRATION.md) — AC Organic
  Self-driving Lab integration: MCP server, `/lab-*` slash commands,
  Kuma alert webhook, environment variables, and the read-only
  guard-rails (no `/control/*`).

## Project layout

```
pypoe/
  src/pypoe/
    core/          # client, history, config, cli entry point
    interfaces/    # web/, slack/, cli/
    lab/           # optional ac-organic-lab integration (read-only MCP,
                   #   /lab-* Slack commands, /alerts/kuma webhook)
    config/        # slack.yaml + models.yaml (lab + model catalog)
    tests/
  scripts/         # ops + setup helpers
  docs/            # topic-specific documentation
  examples/        # SDK usage samples
```

## License

MIT — see [LICENSE](LICENSE).

## Support

- Issues: <https://github.com/AccelerationConsortium/pypoe/issues>
- Poe API reference: <https://creator.poe.com/docs/quick-start>
