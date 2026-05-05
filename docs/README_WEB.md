# PyPoe Web UI

Canonical guide for running and operating the PyPoe web interface.
"Bot locking" is one section below.

The web UI is a FastAPI app at [src/pypoe/interfaces/web/app.py](../src/pypoe/interfaces/web/app.py)
that serves a sidebar of past conversations on the left and an active
chat panel on the right. It reads from and writes to the same SQLite
history as the CLI and Slack bot.

## Run it

```bash
pypoe web                                   # binds 127.0.0.1:8000
pypoe web --host 0.0.0.0 --port 8000        # bind everywhere
pypoe web --host "$(tailscale ip -4)"       # bind only the Tailscale IP
```

The corresponding env vars (loaded from `.env`) are `PYPOE_HOST` and
`PYPOE_PORT`. Command-line flags override the env.

When the server is up, open `http://<host>:<port>/` in a browser. There
is also a JSON health endpoint at `/api/health`.

## Network access

| Goal | Recommended setup |
|------|-------------------|
| Local-only chat | Default `pypoe web` — bound to `127.0.0.1`. |
| Access from another device on a tailnet | `pypoe web --host "$(tailscale ip -4)"`. No auth required if the tailnet itself is the trust boundary. |
| Access from your LAN | `pypoe web --host 0.0.0.0` **plus** auth (see below). |
| Access from the public internet | Don't expose directly; tunnel through Tailscale, an SSH `-L`, or a reverse proxy with TLS + auth. |

If you bind to `0.0.0.0` or any non-loopback IP, set credentials.
Without them the UI is open to anyone who can reach the port.

## Authentication

Set both env vars (or pass the matching flags) and the UI requires HTTP
Basic auth on every request:

```env
PYPOE_WEB_USERNAME=admin
PYPOE_WEB_PASSWORD=use-a-strong-password
```

```bash
pypoe web --web-username admin --web-password 'use-a-strong-password'
```

If only one of the two is set, auth is treated as misconfigured and
disabled — set both, or neither.

## Bot locking

Once a conversation has at least one user message, the AI model
attached to that conversation is locked. Any subsequent request that
specifies a different `bot_name` for the same conversation is rejected.

### Why

The history table stores one `bot_name` per conversation row. Allowing
the model to change mid-conversation produces messages from mixed
backends in the same thread, which makes context-replay confusing for
both the user and the model.

### Where it's enforced

Both transports check before delegating to the model:

- REST: `POST /api/conversation/{conversation_id}/send` —
  see [src/pypoe/interfaces/web/app.py](../src/pypoe/interfaces/web/app.py) around line 612.
- WebSocket: `/ws/chat/{conversation_id}` — see the same file
  around line 1401.

The validation rule is the same in both places:

```python
if user_messages and message_data.bot_name and message_data.bot_name != conversation_bot:
    raise HTTPException(
        status_code=400,
        detail=f"Cannot change bot mid-conversation. This conversation is locked to {conversation_bot}. "
               f"Current conversation has {len(user_messages)} user messages.",
    )
```

### Error shapes

REST returns HTTP 400:

```json
{
  "detail": "Cannot change bot mid-conversation. This conversation is locked to Claude-Sonnet-4.6. Current conversation has 3 user messages."
}
```

WebSocket sends an error frame and keeps the socket open:

```json
{
  "type": "error",
  "content": "Cannot change bot mid-conversation. This conversation is locked to Claude-Sonnet-4.6. Current conversation has 3 user messages."
}
```

### Manual repro

```bash
# 1. Create a conversation pinned to one bot
curl -sX POST http://localhost:8000/api/conversation/new \
     -H 'Content-Type: application/json' \
     -d '{"title": "Test", "bot_name": "Claude-Sonnet-4.6"}'

# 2. First message succeeds
curl -sX POST http://localhost:8000/api/conversation/<id>/send \
     -H 'Content-Type: application/json' \
     -d '{"message": "Hello", "bot_name": "Claude-Sonnet-4.6"}'

# 3. Same conversation, different bot — rejected with HTTP 400
curl -sX POST http://localhost:8000/api/conversation/<id>/send \
     -H 'Content-Type: application/json' \
     -d '{"message": "Hello", "bot_name": "GPT-5.5"}'
```

### Bypassing

There is no flag to disable the lock; that's a deliberate data-integrity
guarantee. To use a different bot, start a new conversation.

## Troubleshooting

| Symptom | Check |
|---------|-------|
| `[Errno 98] Address already in use` | `lsof -i :<port>`; pick another port or stop the existing process. |
| Browser shows the login dialog repeatedly | Both `PYPOE_WEB_USERNAME` and `PYPOE_WEB_PASSWORD` must be set; restart the server after editing `.env`. |
| `Cannot change bot mid-conversation` 400 | Expected; either keep the original bot, or create a new conversation. |
| 500 on `/api/conversation/.../send` | `journalctl --user -u pypoe-web -n 100` (if running under systemd) or run `pypoe web` in the foreground for a traceback. |
| Web UI shows zero conversations but Slack does | Different `DATABASE_PATH` between the two processes; confirm both load the same `.env`. |

For background-service operation see [README_SYSTEMD.md](README_SYSTEMD.md).
