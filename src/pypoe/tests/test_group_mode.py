"""Tests for Phase 1 group/debate fan-out: schema, validation, history round-trip.

These tests cover:
  * HistoryManager round-trips ``bot_names`` (conversations) and
    ``model_name`` (messages) cleanly, including the no-op migration.
  * POST /api/conversation/new validates the participant list when
    chat_mode in ('group','debate') and accepts the legacy 'chatbot' path.
  * POST /api/conversation/{id}/send rejects group conversations (they
    must use the WebSocket fan-out endpoint).
  * The bot-locking branch in the WS handler is gated on chat_mode='chatbot'.

Network-touching paths (actual ``fastapi_poe.get_bot_response`` calls and the
WebSocket fan-out itself) are exercised manually; here we only verify shape.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import List
from unittest.mock import patch

import pytest

from pypoe.core.history import HistoryManager


@pytest.fixture
def temp_db():
    """Per-test SQLite path; never touches the user's real DB."""
    with tempfile.TemporaryDirectory() as tmp:
        yield str(Path(tmp) / "test_pypoe.db")


@pytest.mark.asyncio
async def test_history_round_trips_group_metadata(temp_db):
    history = HistoryManager(db_path=temp_db)
    await history.initialize()

    cid = await history.create_conversation(
        title="round trip",
        bot_name="Claude-Opus-4.7",
        chat_mode="group",
        bot_names=["Claude-Opus-4.7", "GPT-5.5", "Gemini-2.5-Pro"],
    )
    await history.add_message(cid, "user", "Hi all")
    await history.add_message(cid, "assistant", "A reply", model_name="Claude-Opus-4.7")
    await history.add_message(cid, "assistant", "B reply", model_name="GPT-5.5")
    await history.add_message(cid, "assistant", "C reply", model_name="Gemini-2.5-Pro")

    conv = next(c for c in await history.get_conversations() if c["id"] == cid)
    assert conv["chat_mode"] == "group"
    assert conv["bot_names"] == ["Claude-Opus-4.7", "GPT-5.5", "Gemini-2.5-Pro"]

    msgs = await history.get_conversation_messages(cid)
    assert [m["role"] for m in msgs] == ["user", "assistant", "assistant", "assistant"]
    assert [m["model_name"] for m in msgs] == [None, "Claude-Opus-4.7", "GPT-5.5", "Gemini-2.5-Pro"]
    assert [m["content"] for m in msgs[1:]] == ["A reply", "B reply", "C reply"]


@pytest.mark.asyncio
async def test_history_chatbot_mode_keeps_bot_names_null(temp_db):
    """Single-bot conversations leave bot_names NULL (back-compat)."""
    history = HistoryManager(db_path=temp_db)
    await history.initialize()

    cid = await history.create_conversation(
        title="solo",
        bot_name="Claude-Opus-4.7",
        chat_mode="chatbot",
    )
    conv = next(c for c in await history.get_conversations() if c["id"] == cid)
    assert conv["chat_mode"] == "chatbot"
    assert conv["bot_names"] is None


@pytest.mark.asyncio
async def test_history_migration_is_idempotent(temp_db):
    history = HistoryManager(db_path=temp_db)
    await history.initialize()
    # Re-running initialize() must not error nor duplicate columns.
    await history.initialize()
    await history.initialize()
    # Schema is healthy enough to round-trip again.
    cid = await history.create_conversation(
        title="t", bot_name="x", chat_mode="group", bot_names=["a", "b"]
    )
    assert cid


# --- HTTP endpoint validation --------------------------------------------------

@pytest.fixture
def web_app_client(monkeypatch, tmp_path):
    """Spin up a WebApp pointed at a throwaway SQLite file. Avoids touching
    ``~/.pypoe/single_webchat_history.db`` and avoids network calls."""
    monkeypatch.setenv("POE_API_KEY", "test-key-12345")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))

    # Re-import so the Config picks up the env override.
    from fastapi.testclient import TestClient
    from pypoe.core.config import Config
    from pypoe.interfaces.web.app import create_app

    app = create_app(Config())
    return TestClient(app)


def test_create_conversation_chatbot_back_compat(web_app_client):
    r = web_app_client.post(
        "/api/conversation/new",
        json={"title": "t", "bot_name": "Claude-Opus-4.7", "chat_mode": "chatbot"},
    )
    assert r.status_code == 200, r.text
    assert "conversation_id" in r.json()


def test_create_group_requires_bot_names(web_app_client):
    r = web_app_client.post(
        "/api/conversation/new",
        json={"title": "g", "bot_name": "Claude-Opus-4.7", "chat_mode": "group"},
    )
    assert r.status_code == 400
    assert "bot_names" in r.json()["detail"]


def test_create_group_rejects_solo_participant(web_app_client):
    r = web_app_client.post(
        "/api/conversation/new",
        json={
            "title": "g",
            "bot_name": "Claude-Opus-4.7",
            "chat_mode": "group",
            "bot_names": ["Claude-Opus-4.7"],
        },
    )
    assert r.status_code == 400
    assert "exactly 2" in r.json()["detail"]


def test_create_group_rejects_three_participants(web_app_client):
    """Phase 2.6: max-2 cap. Three is now over the limit."""
    from pypoe.core.models import CHAT_MODELS
    picks = list(CHAT_MODELS)[:3]
    if len(picks) < 3:
        pytest.skip("Need 3+ models in CHAT_MODELS for this test")
    r = web_app_client.post(
        "/api/conversation/new",
        json={
            "title": "g",
            "bot_name": picks[0],
            "chat_mode": "group",
            "bot_names": picks,
        },
    )
    assert r.status_code == 400
    assert "exactly 2" in r.json()["detail"]


def test_create_group_rejects_unknown_bot(web_app_client):
    r = web_app_client.post(
        "/api/conversation/new",
        json={
            "title": "g",
            "bot_name": "Claude-Opus-4.7",
            "chat_mode": "group",
            "bot_names": ["Claude-Opus-4.7", "FakeBot-9000"],
        },
    )
    assert r.status_code == 400
    assert "FakeBot-9000" in r.json()["detail"]


def test_create_group_rejects_duplicate_bots(web_app_client):
    r = web_app_client.post(
        "/api/conversation/new",
        json={
            "title": "g",
            "bot_name": "Claude-Opus-4.7",
            "chat_mode": "group",
            "bot_names": ["Claude-Opus-4.7", "Claude-Opus-4.7"],
        },
    )
    assert r.status_code == 400
    assert "unique" in r.json()["detail"]


def test_create_group_accepts_two_valid_bots(web_app_client):
    from pypoe.core.models import CHAT_MODELS
    picks = list(CHAT_MODELS)[:2]
    r = web_app_client.post(
        "/api/conversation/new",
        json={
            "title": "g",
            "bot_name": picks[0],
            "chat_mode": "group",
            "bot_names": picks,
        },
    )
    assert r.status_code == 200, r.text
    cid = r.json()["conversation_id"]

    # The created conversation reports the participants back via /api/conversations.
    convs = web_app_client.get("/api/conversations").json()
    me = next(c for c in convs if c["id"] == cid)
    assert me["chat_mode"] == "group"
    assert me["bot_names"] == picks


def test_send_endpoint_rejects_group_conversations(web_app_client):
    """Non-streaming /send must refuse group mode (use WS instead)."""
    from pypoe.core.models import CHAT_MODELS
    picks = list(CHAT_MODELS)[:2]
    r = web_app_client.post(
        "/api/conversation/new",
        json={
            "title": "g",
            "bot_name": picks[0],
            "chat_mode": "group",
            "bot_names": picks,
        },
    )
    cid = r.json()["conversation_id"]

    r2 = web_app_client.post(
        f"/api/conversation/{cid}/send",
        json={"message": "hi", "bot_name": picks[0], "chat_mode": "group"},
    )
    assert r2.status_code == 400
    assert "WebSocket" in r2.json()["detail"]


# --- Debate (Phase 2) ---------------------------------------------------------

def _debate_payload(picks, **overrides):
    base = {
        "title": "d",
        "bot_name": picks[0],
        "chat_mode": "debate",
        "bot_names": picks,
        "debate_topic": "Is 170C/3s the right seal for compound X?",
        "bot_assignments": {
            picks[0]: {"role": "defend"},
            picks[1]: {"role": "critique"},
        },
    }
    base.update(overrides)
    return base


def test_create_debate_requires_topic(web_app_client):
    from pypoe.core.models import CHAT_MODELS
    picks = list(CHAT_MODELS)[:2]
    r = web_app_client.post(
        "/api/conversation/new",
        json=_debate_payload(picks, debate_topic=""),
    )
    assert r.status_code == 400
    assert "debate_topic" in r.json()["detail"]


def test_create_debate_requires_assignments(web_app_client):
    from pypoe.core.models import CHAT_MODELS
    picks = list(CHAT_MODELS)[:2]
    payload = _debate_payload(picks)
    del payload["bot_assignments"]
    r = web_app_client.post("/api/conversation/new", json=payload)
    assert r.status_code == 400
    assert "bot_assignments" in r.json()["detail"]


def test_create_debate_assignment_keys_must_match_bot_names(web_app_client):
    from pypoe.core.models import CHAT_MODELS
    picks = list(CHAT_MODELS)[:2]
    payload = _debate_payload(picks)
    # Replace one key with a name that isn't in bot_names.
    payload["bot_assignments"] = {
        picks[0]: {"role": "defend"},
        "SomeOtherBot": {"role": "critique"},
    }
    r = web_app_client.post("/api/conversation/new", json=payload)
    assert r.status_code == 400
    assert "must exactly match" in r.json()["detail"]


def test_create_debate_rejects_unknown_role(web_app_client):
    from pypoe.core.models import CHAT_MODELS
    picks = list(CHAT_MODELS)[:2]
    payload = _debate_payload(picks)
    payload["bot_assignments"][picks[0]] = {"role": "yelling"}
    r = web_app_client.post("/api/conversation/new", json=payload)
    assert r.status_code == 400
    assert "Unknown role" in r.json()["detail"]


def test_create_debate_custom_role_requires_label(web_app_client):
    from pypoe.core.models import CHAT_MODELS
    picks = list(CHAT_MODELS)[:2]
    payload = _debate_payload(picks)
    payload["bot_assignments"][picks[0]] = {"role": "custom"}  # missing custom_label
    r = web_app_client.post("/api/conversation/new", json=payload)
    assert r.status_code == 400
    assert "custom_label" in r.json()["detail"]


def test_create_debate_round_trip(web_app_client):
    from pypoe.core.models import CHAT_MODELS
    picks = list(CHAT_MODELS)[:2]
    r = web_app_client.post("/api/conversation/new", json=_debate_payload(picks))
    assert r.status_code == 200, r.text
    cid = r.json()["conversation_id"]

    convs = web_app_client.get("/api/conversations").json()
    me = next(c for c in convs if c["id"] == cid)
    assert me["chat_mode"] == "debate"
    assert me["bot_names"] == picks
    assert me["debate_topic"] == "Is 170C/3s the right seal for compound X?"
    assert me["bot_assignments"][picks[0]] == {"role": "defend", "custom_label": None}
    assert me["bot_assignments"][picks[1]] == {"role": "critique", "custom_label": None}


def test_patch_debate_updates_topic_and_assignments(web_app_client):
    from pypoe.core.models import CHAT_MODELS
    picks = list(CHAT_MODELS)[:2]
    cid = web_app_client.post(
        "/api/conversation/new", json=_debate_payload(picks)
    ).json()["conversation_id"]

    # Edit just the topic.
    r = web_app_client.patch(
        f"/api/conversation/{cid}",
        json={"debate_topic": "Should we change to 165C/4s instead?"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["debate_topic"].startswith("Should we change")

    # Edit just the assignments.
    r = web_app_client.patch(
        f"/api/conversation/{cid}",
        json={
            "bot_assignments": {
                picks[0]: {"role": "critique"},
                picks[1]: {"role": "synthesizer"},
            }
        },
    )
    assert r.status_code == 200, r.text
    convs = web_app_client.get("/api/conversations").json()
    me = next(c for c in convs if c["id"] == cid)
    assert me["bot_assignments"][picks[0]]["role"] == "critique"
    assert me["bot_assignments"][picks[1]]["role"] == "synthesizer"


def test_patch_rejects_non_debate_conversations(web_app_client):
    from pypoe.core.models import CHAT_MODELS
    picks = list(CHAT_MODELS)[:2]
    cid = web_app_client.post(
        "/api/conversation/new",
        json={
            "title": "g",
            "bot_name": picks[0],
            "chat_mode": "group",
            "bot_names": picks,
        },
    ).json()["conversation_id"]
    r = web_app_client.patch(
        f"/api/conversation/{cid}",
        json={"debate_topic": "x"},
    )
    assert r.status_code == 400
    assert "Only debate" in r.json()["detail"]


def test_debate_prompt_includes_topic_and_role_blurbs():
    from pypoe.interfaces.web.app import WebApp, DEBATE_ROLE_PRESETS

    prompt = WebApp._build_debate_system_prompt(
        topic="Is X safer than Y?",
        this_bot="A",
        bot_names=["A", "B", "C"],
        bot_assignments={
            "A": {"role": "defend"},
            "B": {"role": "critique"},
            "C": {"role": "custom", "custom_label": "summariser who picks one"},
        },
    )
    # Topic appears verbatim.
    assert "Is X safer than Y?" in prompt
    # This bot's role uses the preset blurb, not the bare key.
    assert DEBATE_ROLE_PRESETS["defend"] in prompt
    # Other participants are listed by name and described.
    assert "B:" in prompt
    assert DEBATE_ROLE_PRESETS["critique"] in prompt
    # Custom labels override the preset.
    assert "summariser who picks one" in prompt
    # This bot does not appear in "OTHER PARTICIPANTS:".
    assert prompt.count("A:") == 0  # A isn't in the others-block


def test_debate_prompt_handles_same_role_on_multiple_bots():
    """2v1 debates: two bots can share the 'critique' role."""
    from pypoe.interfaces.web.app import WebApp

    prompt = WebApp._build_debate_system_prompt(
        topic="t",
        this_bot="A",
        bot_names=["A", "B", "C"],
        bot_assignments={
            "A": {"role": "defend"},
            "B": {"role": "critique"},
            "C": {"role": "critique"},
        },
    )
    # B and C are both listed with the critique blurb.
    assert prompt.count("flaws, edge cases") == 2
