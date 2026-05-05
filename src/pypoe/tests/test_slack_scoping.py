"""
Tests for Slack conversation scoping.

These tests cover the per-thread / per-DM id derivation that drives
``slack_thread_<chan>_<thread_ts>`` and ``slack_dm_<user_id>``.
``_determine_conversation_strategy`` is a ``@staticmethod`` so the tests
don't need to instantiate the bot (which would require Slack/Poe creds).
"""
import pytest

from pypoe.interfaces.slack.bot import PyPoeSlackBot


def test_dm_uses_per_user_id():
    conv_id, chat_mode, title = PyPoeSlackBot._determine_conversation_strategy(
        channel_type="im",
        user_id="U123",
        channel_id="D456",
    )
    assert conv_id == "slack_dm_U123"
    assert chat_mode == "slack_dm"
    assert "U123" in title


def test_dm_in_thread_uses_thread_scope():
    """When a DM message lives inside a thread, scoping switches to that
    thread so different DM threads stay isolated even with one user."""
    conv_id, chat_mode, _ = PyPoeSlackBot._determine_conversation_strategy(
        channel_type="im",
        user_id="U123",
        channel_id="D456",
        thread_ts="9999.0001",
    )
    assert conv_id == "slack_thread_D456_9999.0001"
    assert chat_mode == "slack_thread"


def test_dm_top_level_and_thread_are_isolated():
    """Top-level DM messages and DM-thread replies are different conversations."""
    top, _, _ = PyPoeSlackBot._determine_conversation_strategy(
        channel_type="im",
        user_id="U123",
        channel_id="D456",
        thread_ts=None,
    )
    threaded, _, _ = PyPoeSlackBot._determine_conversation_strategy(
        channel_type="im",
        user_id="U123",
        channel_id="D456",
        thread_ts="42.0",
    )
    assert top != threaded


def test_channel_mention_in_existing_thread():
    """@PyPoe inside a thread keys by event['thread_ts']."""
    conv_id, chat_mode, _ = PyPoeSlackBot._determine_conversation_strategy(
        channel_type="public_channel",
        user_id="U123",
        channel_id="C999",
        thread_ts="1700000000.000100",
    )
    assert conv_id == "slack_thread_C999_1700000000.000100"
    assert chat_mode == "slack_thread"


def test_channel_mention_at_top_level():
    """Top-level @PyPoe uses event['ts'] as the new thread root."""
    event_ts = "1700000123.456789"
    conv_id, chat_mode, _ = PyPoeSlackBot._determine_conversation_strategy(
        channel_type="public_channel",
        user_id="U123",
        channel_id="C999",
        thread_ts=event_ts,
    )
    assert conv_id == f"slack_thread_C999_{event_ts}"
    assert chat_mode == "slack_thread"


def test_slash_command_synthesized_thread_root():
    """/poe chat in a channel: the bot's placeholder ts is the thread root."""
    placeholder_ts = "1700000999.111222"
    conv_id, chat_mode, _ = PyPoeSlackBot._determine_conversation_strategy(
        channel_type="public_channel",
        user_id="U123",
        channel_id="C42",
        thread_ts=placeholder_ts,
    )
    assert conv_id == f"slack_thread_C42_{placeholder_ts}"
    assert chat_mode == "slack_thread"


def test_private_channel_and_mpim_use_thread_scoping():
    for channel_type in ("private_channel", "group", "mpim"):
        conv_id, chat_mode, _ = PyPoeSlackBot._determine_conversation_strategy(
            channel_type=channel_type,
            user_id="U1",
            channel_id="C1",
            thread_ts="1.0",
        )
        assert conv_id == "slack_thread_C1_1.0"
        assert chat_mode == "slack_thread"


def test_non_dm_without_thread_ts_raises():
    """Non-DM contexts must always supply a thread_ts."""
    with pytest.raises(ValueError):
        PyPoeSlackBot._determine_conversation_strategy(
            channel_type="public_channel",
            user_id="U1",
            channel_id="C1",
            thread_ts=None,
        )


def test_two_users_same_thread_share_one_conversation():
    """Per-thread scoping is shared across users in that thread by design."""
    a = PyPoeSlackBot._determine_conversation_strategy(
        channel_type="public_channel",
        user_id="UAlice",
        channel_id="C1",
        thread_ts="1.0",
    )
    b = PyPoeSlackBot._determine_conversation_strategy(
        channel_type="public_channel",
        user_id="UBob",
        channel_id="C1",
        thread_ts="1.0",
    )
    assert a[0] == b[0] == "slack_thread_C1_1.0"


def test_two_threads_in_same_channel_are_isolated():
    a = PyPoeSlackBot._determine_conversation_strategy(
        channel_type="public_channel",
        user_id="U1",
        channel_id="C1",
        thread_ts="1.0",
    )
    b = PyPoeSlackBot._determine_conversation_strategy(
        channel_type="public_channel",
        user_id="U1",
        channel_id="C1",
        thread_ts="2.0",
    )
    assert a[0] != b[0]
