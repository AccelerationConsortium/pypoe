# PyPoe Conversation History

PyPoe stores every chat from every interface — CLI, web, Slack — in
one SQLite database. This page documents where it lives, the schema,
how Slack maps its threads onto that schema, and how to inspect or
clean up the data.

The implementation lives in [src/pypoe/core/history.py](../src/pypoe/core/history.py).
The Slack-specific id derivation is in [src/pypoe/interfaces/slack/bot.py](../src/pypoe/interfaces/slack/bot.py).

## Where the data lives

| Item | Default | Override |
|------|---------|----------|
| Database file | `~/.pypoe/single_webchat_history.db` | `DATABASE_PATH` env var |
| Media directory | `<db parent>/media` (e.g. `~/.pypoe/media`) | `media_dir` arg to `HistoryManager` |
| Slack media subdir | `<db parent>/slack_media` | hard-coded in [src/pypoe/interfaces/slack/bot.py](../src/pypoe/interfaces/slack/bot.py) |

The directory is created on first run by [src/pypoe/core/config.py](../src/pypoe/core/config.py).
Media is only downloaded when `PYPOE_ENABLE_MEDIA=true` and the
`[media]` extra is installed.

## Schema

Created/migrated in `HistoryManager.initialize()`
([src/pypoe/core/history.py](../src/pypoe/core/history.py) line ~85).
Three tables plus one index:

```sql
CREATE TABLE IF NOT EXISTS conversations (
    id          TEXT PRIMARY KEY,
    title       TEXT,
    topic       TEXT,
    bot_name    TEXT,
    chat_mode   TEXT DEFAULT 'chatbot',
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    role            TEXT NOT NULL,                -- 'user' | 'assistant'
    content         TEXT NOT NULL,
    content_type    TEXT DEFAULT 'text',          -- 'text' | 'media' | 'mixed'
    media_data      TEXT,                         -- JSON metadata (when present)
    timestamp       DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(conversation_id) REFERENCES conversations(id)
);

CREATE TABLE IF NOT EXISTS media_files (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id    INTEGER NOT NULL,
    file_hash     TEXT UNIQUE,
    original_url  TEXT,
    local_path    TEXT,
    media_type    TEXT,
    file_size     INTEGER,
    width         INTEGER,
    height        INTEGER,
    duration      REAL,                            -- videos / audio
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(message_id) REFERENCES messages(id)
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_id
    ON messages(conversation_id);
```

Older databases that pre-date the `chat_mode`, `updated_at`, `topic`,
`content_type`, and `media_data` columns are migrated in place by
`_migrate_basic_to_enhanced` on the next start (best-effort `ALTER
TABLE`s).

## Conversation continuity model

Two methods on `PoeChatClient` cover all three interfaces. Both stream
the model output one chunk at a time:

- `send_message(message, bot_name, conversation_id=None)` — when
  `conversation_id` is set, history is loaded from SQLite, the new
  message is appended, the full array is sent to Poe, and both turns
  are persisted. Used by the web UI and `pypoe cli chat`.
- `send_conversation(messages, bot_name, conversation_id=None)` — the
  caller passes the full message array explicitly. Used by the Slack
  bot, which manages context truncation per-model and writes both
  turns itself so it can attach Slack-specific metadata (thread ts,
  user, etc.).

In both paths the model receives the whole conversation, so it can
reference earlier turns naturally.

Each conversation is isolated by `conversations.id`. Two different
ids never share context, even when started by the same user.

## Slack id scheme

Slack does not just use a UUID — it builds a stable, externally
meaningful id from the Slack event so the same DM or thread always
maps to the same conversation row. The rules (thread always wins when
present):

| Slack location | `chat_mode` | `conversations.id` |
|----------------|-------------|--------------------|
| Direct message at top level | `slack_dm` | `slack_dm_<user_id>` |
| Anything inside a Slack thread (channel, private channel, group, mpim, or DM thread) | `slack_thread` | `slack_thread_<channel_id>_<thread_ts>` |

Where `thread_ts` comes from:

- `@PyPoe` mention inside an existing thread: `event["thread_ts"]`.
- `@PyPoe` mention at the top level: `event["ts"]` (a new thread is
  rooted at the user's mention).
- `/poe chat …` at the top level of a channel: the bot posts a
  placeholder message and uses *its* `ts` as the thread root.
- DM message sent as a thread reply: `event["thread_ts"]` for that
  thread, scoped separately from the top-level DM context.

`HistoryManager.create_conversation(..., conversation_id=...)` is
idempotent (`INSERT OR IGNORE`), so the Slack bot can call it on every
cold lookup and a row exists exactly once per scope.

For the user-facing semantics (which slash commands need a thread,
how to start vs continue a thread, etc.) see
[README_SLACK.md](README_SLACK.md).

## Inspecting your history

The fastest way to look at the data is plain `sqlite3`:

```bash
DB=~/.pypoe/single_webchat_history.db

# How many turns per conversation, top 10
sqlite3 "$DB" \
  "SELECT conversation_id, COUNT(*) AS n
     FROM messages
     GROUP BY conversation_id
     ORDER BY n DESC
     LIMIT 10;"

# All Slack DM conversations
sqlite3 "$DB" \
  "SELECT id, title, bot_name, updated_at
     FROM conversations
     WHERE chat_mode = 'slack_dm'
     ORDER BY updated_at DESC;"

# Messages in a specific conversation, with timestamps
sqlite3 -header -column "$DB" \
  "SELECT timestamp, role, substr(content, 1, 80) AS preview
     FROM messages
     WHERE conversation_id = 'slack_thread_C0123_1700000000.000100'
     ORDER BY timestamp;"

# Total media files and bytes
sqlite3 "$DB" \
  "SELECT media_type, COUNT(*) AS files, SUM(file_size) AS bytes
     FROM media_files
     GROUP BY media_type;"
```

The CLI also exposes inspection commands that read the same db:

```bash
pypoe cli list      # list conversations
pypoe cli show      # show a specific conversation
pypoe cli select    # interactive picker
```

The web UI is the most ergonomic browser: start it (`pypoe web`) and
the sidebar lists every conversation across all three interfaces.

## Cleanup

Clean up Slack rows produced by older buggy bot versions (orphan
messages keyed by Slack ids whose parent conversation was a random
UUID). The bot supports a guarded one-shot wipe on startup:

```bash
PYPOE_SLACK_WIPE_ON_START=1 systemctl --user restart pypoe-slack
# then unset and restart again so future restarts don't wipe
systemctl --user restart pypoe-slack
```

This runs the equivalent of:

```sql
DELETE FROM messages
 WHERE conversation_id IN (
       SELECT id FROM conversations WHERE chat_mode LIKE 'slack_%')
    OR conversation_id LIKE 'slack_%';
DELETE FROM conversations WHERE chat_mode LIKE 'slack_%';
```

Web/CLI history is untouched.

To delete a single conversation by hand:

```bash
sqlite3 ~/.pypoe/single_webchat_history.db <<SQL
DELETE FROM messages WHERE conversation_id = '<id>';
DELETE FROM conversations WHERE id = '<id>';
SQL
```

To start completely fresh, stop the services and delete the file:

```bash
systemctl --user stop pypoe-web pypoe-slack
rm ~/.pypoe/single_webchat_history.db
systemctl --user start pypoe-web pypoe-slack
```

## Media storage

Disabled by default. Enable with the `[media]` extra and
`PYPOE_ENABLE_MEDIA=true`; downloaded files land under the media
directory, are de-duplicated by `file_hash`, and are linked to their
originating message via `media_files.message_id`. The detection,
download, and metadata logic is in [src/pypoe/core/history.py](../src/pypoe/core/history.py)
(`_detect_media_content`, `_download_media`, `add_message`).
