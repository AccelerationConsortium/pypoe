"""Owner-scoped per-user history + web cookie-verify auth (CLAUDE.local.md §4.8/§4.9).

Each test wraps its async body in ``asyncio.run`` so the suite needs no
async-pytest plugin. Uses tmp SQLite DBs so it is hermetic.
"""

from __future__ import annotations

import asyncio
import sqlite3
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("aiosqlite")

from pypoe.core.history import HistoryManager, owner_ctx, _UNSCOPED


def _db() -> str:
    return str(Path(tempfile.mkdtemp()) / "h.db")


def test_migration_adds_owner_column_and_index():
    async def go():
        # Realistic pre-`owner` enhanced schema (everything except owner).
        db = _db()
        con = sqlite3.connect(db)
        con.executescript(
            """
            CREATE TABLE conversations (id TEXT PRIMARY KEY, title TEXT, topic TEXT,
                bot_name TEXT, bot_names TEXT, bot_assignments TEXT, debate_topic TEXT,
                chat_mode TEXT DEFAULT 'chatbot',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE messages (id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL, role TEXT, content TEXT,
                content_type TEXT DEFAULT 'text', media_data TEXT, model_name TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP);
            INSERT INTO conversations (id, title, bot_name) VALUES ('old1', 'Old', 'Bot');
            """
        )
        con.commit(); con.close()

        await HistoryManager(db_path=db).initialize()

        cols = [r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(conversations)")]
        assert "owner" in cols
        idx = [r[0] for r in sqlite3.connect(db).execute(
            "SELECT name FROM sqlite_master WHERE type='index'")]
        assert "idx_conversations_owner" in idx

        h = HistoryManager(db_path=db)
        # legacy NULL-owner row: admin sees it, a normal user does not
        assert {c["id"] for c in await h.get_conversations(is_admin=True)} == {"old1"}
        assert await h.get_conversations(owner="someone") == []

    asyncio.run(go())


def test_explicit_owner_scoping_and_admin_bypass():
    async def go():
        h = HistoryManager(db_path=_db())
        await h.initialize()
        a = await h.create_conversation("A", "Bot", owner="alice")
        b = await h.create_conversation("B", "Bot", owner="bob")
        legacy = await h.create_conversation("L", "Bot")  # owner NULL
        await h.add_message(b, "user", "hi", owner="bob")

        assert {c["id"] for c in await h.get_conversations(owner="alice")} == {a}
        assert {c["id"] for c in await h.get_conversations(is_admin=True)} == {a, b, legacy}
        assert {c["id"] for c in await h.get_conversations()} == {a, b, legacy}  # unscoped
        assert {c["id"] for c in await h.get_conversations(owner=None)} == {legacy}

        # cross-owner read denied; owner/admin allowed
        assert await h.get_conversation_messages(b, owner="alice") == []
        assert len(await h.get_conversation_messages(b, owner="bob")) == 1
        assert len(await h.get_conversation_messages(b, is_admin=True)) == 1

        # cross-owner mutation raises
        with pytest.raises(PermissionError):
            await h.add_message(a, "user", "x", owner="bob")
        with pytest.raises(PermissionError):
            await h.delete_conversation(b, owner="alice")
        await h.delete_conversation(b, owner="bob")
        assert {c["id"] for c in await h.get_conversations(is_admin=True)} == {a, legacy}
        # deleting a non-existent conversation scoped is a harmless no-op
        await h.delete_conversation("nope", owner="alice")

    asyncio.run(go())


def test_instance_default_owner_cli_pattern():
    async def go():
        db = _db()
        cli = HistoryManager(db_path=db, default_owner="cli-user")
        await cli.initialize()
        c1 = await cli.create_conversation("A", "Bot")  # no explicit owner
        everyone = await cli.get_conversations(is_admin=True)
        assert next(c for c in everyone if c["id"] == c1)["owner"] == "cli-user"
        assert {c["id"] for c in await cli.get_conversations()} == {c1}  # auto-scoped

        other = HistoryManager(db_path=db, default_owner="other-user")
        await other.initialize()
        assert await other.get_conversations() == []

    asyncio.run(go())


def test_contextvar_owner_web_pattern():
    async def go():
        h = HistoryManager(db_path=_db())  # web-style: default_owner UNSCOPED
        await h.initialize()
        t = owner_ctx.set("alice")
        a = await h.create_conversation("A", "Bot")
        assert [c["id"] for c in await h.get_conversations()] == [a]
        owner_ctx.reset(t)
        t = owner_ctx.set("bob")
        assert await h.get_conversation_messages(a) == []  # bob can't read alice's
        owner_ctx.reset(t)
        assert len(await h.get_conversations(is_admin=True)) == 1

    asyncio.run(go())


def test_slack_namespaced_owners():
    async def go():
        h = HistoryManager(db_path=_db())
        await h.initialize()
        dm = await h.create_conversation("DM", "Bot",
                                         conversation_id="slack_dm_U1", owner="slack-dm:U1")
        th = await h.create_conversation("TH", "Bot",
                                         conversation_id="slack_thread_C1", owner="slack-channel:C1")
        assert {c["id"] for c in await h.get_conversations(owner="slack-dm:U1")} == {dm}
        assert {c["id"] for c in await h.get_conversations(owner="slack-channel:C1")} == {th}
        assert await h.get_conversation_messages(dm, owner="slack-dm:U2") == []

    asyncio.run(go())
