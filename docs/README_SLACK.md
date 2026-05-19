# PyPoe Slack Bot

How to create the Slack app, configure it, run the bot, and how PyPoe
scopes Slack conversations into the shared history database.

The bot connects via Slack Socket Mode and is implemented in
[src/pypoe/interfaces/slack/bot.py](../src/pypoe/interfaces/slack/bot.py).
For service management (start/stop/logs as systemd) see
[README_SYSTEMD.md](README_SYSTEMD.md). For the underlying history
schema see [README_HISTORY.md](README_HISTORY.md).

## Create the Slack app

1. Visit <https://api.slack.com/apps>, click **Create New App** →
   **From scratch**.
2. Name the app `PyPoe`; pick your workspace.

### Enable Socket Mode

Socket Mode lets the bot connect outbound, so no public callback URL is
required.

1. **Settings → Socket Mode**: turn on **Enable Socket Mode**.
2. Generate an app-level token with the scope `connections:write`.
3. Save the token (starts with `xapp-`) — this becomes `SLACK_APP_TOKEN`.

### OAuth scopes

**Features → OAuth & Permissions → Bot Token Scopes**:

```text
app_mentions:read
channels:history
chat:write
commands
groups:history
im:history
im:read
im:write
mpim:history
```

- `commands` enables `/poe`.
- `app_mentions:read` enables `@PyPoe`.
- `im:*` covers DMs; `mpim:history` and `groups:history` cover group
  DMs and private channels.

### Slash command

**Features → Slash Commands → Create New Command**:

```text
Command:           /poe
Request URL:       https://example.com/slack/events    (unused in Socket Mode but required)
Short Description: Chat with Poe models through PyPoe
```

### Event subscriptions

**Features → Event Subscriptions → Subscribe to bot events**:

```text
app_mention
message.im
```

### App Home

**Features → App Home → Show Tabs**:

1. Enable the **Messages Tab**.
2. Tick **Allow users to send Slash commands and messages from the
   messages tab**.

Without this, Slack reports "Sending messages to this app has been
turned off" when users try to DM the bot.

### Install to the workspace

**Features → OAuth & Permissions → Install to Workspace**. After
approving, copy:

- **Bot User OAuth Token** (starts with `xoxb-`) → `SLACK_BOT_TOKEN`.
- **Basic Information → Signing Secret** → `SLACK_SIGNING_SECRET`.

Reinstall the app whenever you change scopes, slash commands, event
subscriptions, or App Home settings.

## `.env` configuration

Add these to the repo-root `.env`:

```env
POE_API_KEY=your-poe-api-key
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_SIGNING_SECRET=your-signing-secret
SLACK_APP_TOKEN=xapp-your-app-token
SLACK_SOCKET_MODE=true
PYPOE_SLACK_HIDE_THINKING=true  # optional: hide model reasoning blocks in Slack
```

`PYPOE_SLACK_HIDE_THINKING=true` removes model reasoning blocks such as
`<think>...</think>` and Slack-rendered `Thinking...` quote blocks from
Slack-visible replies. The full model response is still saved in conversation
history.

Install the dependencies (the same extra ships both the web UI and
Slack stack):

```bash
pip install -e ".[web-ui]"
```

## Run it

Foreground (good for iteration):

```bash
pypoe slack
```

As a systemd service: see [README_SYSTEMD.md](README_SYSTEMD.md). Quick
recap:

```bash
systemctl --user start pypoe-slack
journalctl --user -u pypoe-slack -f
```

If you're editing bot code, stop the service first so there's only one
Socket Mode connection:

```bash
systemctl --user stop pypoe-slack
# ...edit, run python -m compileall -q src/pypoe and your tests...
systemctl --user start pypoe-slack
```

## How conversation context is scoped

Each Slack interaction maps to one stable conversation id in
`~/.pypoe/single_webchat_history.db`. **Thread always wins when
present**:

- Any message inside a Slack thread (channel, private channel, group,
  mpim, *or DM thread*) is one isolated conversation, keyed
  `slack_thread_<channel_id>_<thread_ts>`.
- A DM at the top level (no thread) maps to one persistent
  per-user conversation, keyed `slack_dm_<user_id>`.

Concrete entry points:

- `/poe chat <message>` at the top level of a channel — the bot posts a
  public placeholder; that message's `ts` becomes the thread root, and
  the model's response replaces the placeholder via `chat.update`.
  Continue with `@PyPoe …` in the thread.
- `/poe chat <message>` from inside an existing thread — the existing
  thread is reused.
- `@PyPoe <message>` mentioned inside a thread — that thread continues.
- `@PyPoe <message>` mentioned at the top level — a new thread starts
  rooted at the user's mention.
- A DM message sent as a thread reply — the bot's reply lands in that
  same DM thread; that thread is its own context, separate from your
  top-level DM history.

Per-thread commands (`/poe reset`, `/poe context`, `/poe stats`,
`/poe set-model`) need an active thread. Run them from a DM, or from
inside an existing PyPoe thread. The bot will explain when there's no
thread to act on.

### `/poe` autocomplete in threads

Slack hides slash-command autocomplete inside threads of private
channels and mpim/group DMs. The command still works if you type
`/poe chat hello` and submit, but the autocomplete-friendly path inside
a thread is to **@-mention** the bot:

```text
@PyPoe what's next?
```

For private channels and mpims, the bot has to be in the conversation;
run `/invite @PyPoe` once. After that, both mentions and slash commands
work.

## Testing in Slack

Slash commands:

```text
/poe help
/poe models
/poe chat hello
/poe set-model Claude-Sonnet-4.6   # only valid in DM or inside a thread
/poe usage
/poe reset                         # only valid in DM or inside a thread
```

Mentions:

```text
@PyPoe hello                       # starts (or continues) a thread
```

Direct messages: just type to the bot.

## One-shot history cleanup

A guarded cleanup deletes Slack-scoped rows from the history db on
startup. Use it once after upgrading from older versions that produced
orphan rows:

```bash
PYPOE_SLACK_WIPE_ON_START=1 systemctl --user restart pypoe-slack
# unset the variable (or restart again) so future restarts don't wipe
systemctl --user restart pypoe-slack
```

This deletes only:

- `conversations` whose `chat_mode LIKE 'slack_%'`.
- `messages` whose `conversation_id LIKE 'slack_%'` or whose parent
  conversation has `chat_mode LIKE 'slack_%'`.

Web/CLI history is not touched.

## Optional: `/lab-*` commands for the AC Organic Self-driving Lab

If you've installed PyPoe with `pip install -e ".[lab]"` and set
`LAB_API_URL` (or `PYPOE_ENABLE_LAB=1`) in `.env`, `pypoe slack`
auto-registers a second set of read-only slash commands that query
the lab dashboard's aggregator: `/lab-status`, `/lab-device`,
`/lab-runs`, `/lab-sensors`, `/lab-actions`. These are namespaced via
`LAB_SLACK_COMMAND_PREFIX` (default `/lab-`); set it to
`/sdl2-lab-` (or similar) when multiple labs share one Slack workspace.

You still need to declare each command in the Slack app admin UI
before Slack will forward it to the bot. See
[docs/LAB_INTEGRATION.md](LAB_INTEGRATION.md) for the full list and
the per-command argument hints.

## Troubleshooting

```bash
systemctl --user status pypoe-slack
journalctl --user -u pypoe-slack -n 100 --no-pager
```

Validate that `.env` is being picked up without printing secrets:

```bash
python - <<'PY'
from dotenv import load_dotenv
from pathlib import Path
import os

load_dotenv(Path.cwd() / ".env")
for name in ("POE_API_KEY", "SLACK_BOT_TOKEN", "SLACK_SIGNING_SECRET", "SLACK_APP_TOKEN"):
    value = os.getenv(name, "")
    print(f"{name}:", "set" if value else "missing")
PY
```

| Symptom | First thing to check |
|---------|----------------------|
| Bot ignores DMs | App Home → Messages Tab + "Allow Slash commands and messages" must be on; reinstall if you just toggled it. |
| `/poe` not recognised | Slash command exists in the app config; reinstall the app; restart `pypoe-slack`. |
| `@PyPoe` ignored | `app_mention` event subscription enabled; bot invited to the channel (`/invite @PyPoe`). |
| "Sending messages to this app has been turned off" | App Home messages tab disabled; enable + reinstall + reload Slack. |
| Bot replies at the channel top level instead of in a thread | Older code or stale process; `systemctl --user restart pypoe-slack` and confirm with `systemctl --user status pypoe-slack` (Active line should be a recent timestamp). |
| Many duplicate "tabs" appearing in history | Pre-thread-scoping data; run the `PYPOE_SLACK_WIPE_ON_START=1` cleanup. |
