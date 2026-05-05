from pypoe.interfaces.slack.bot import PyPoeSlackBot


def _format_slack_response(response: str, *, hide_thinking: bool) -> str:
    bot = PyPoeSlackBot.__new__(PyPoeSlackBot)
    bot.hide_thinking_in_slack = hide_thinking
    return bot._format_response_for_slack(response, "TestBot", "slack_thread")


def test_slack_thinking_visible_by_default():
    response = "<think>private reasoning</think>\n\nVisible answer"

    formatted = _format_slack_response(response, hide_thinking=False)

    assert "<think>private reasoning</think>" in formatted
    assert "Visible answer" in formatted


def test_slack_thinking_hidden_when_enabled():
    response = "<think>private reasoning</think>\n\nVisible answer"

    formatted = _format_slack_response(response, hide_thinking=True)

    assert "private reasoning" not in formatted
    assert "<think>" not in formatted
    assert "Visible answer" in formatted


def test_slack_thinking_hides_multiline_and_multiple_blocks():
    response = """Before
<think>
first private line
second private line
</think>
Middle
<thinking>more private reasoning</thinking>
After"""

    formatted = _format_slack_response(response, hide_thinking=True)

    assert "first private line" not in formatted
    assert "second private line" not in formatted
    assert "more private reasoning" not in formatted
    assert "Before" in formatted
    assert "Middle" in formatted
    assert "After" in formatted


def test_slack_thinking_hides_reasoning_tag_case_insensitively():
    response = "<REASONING>private reasoning</REASONING>\nFinal"

    formatted = _format_slack_response(response, hide_thinking=True)

    assert "private reasoning" not in formatted
    assert "Final" in formatted


def test_slack_thinking_hides_markdown_reasoning_block():
    response = """Thinking...

> The user is asking if I'm still on/here.
> Simple casual response.

Yep, still here!"""

    formatted = _format_slack_response(response, hide_thinking=True)

    assert "Thinking..." not in formatted
    assert "The user is asking" not in formatted
    assert "Simple casual response" not in formatted
    assert "Yep, still here!" in formatted


def test_slack_thinking_only_response_uses_placeholder():
    response = "<think>private reasoning only</think>"

    formatted = _format_slack_response(response, hide_thinking=True)

    assert "private reasoning only" not in formatted
    assert "_(thinking hidden)_" in formatted


def test_slack_thinking_helper_does_not_mutate_original_response():
    response = "<think>private reasoning</think>\nVisible answer"

    redacted = PyPoeSlackBot._hide_thinking_for_slack(response)

    assert response == "<think>private reasoning</think>\nVisible answer"
    assert redacted == "Visible answer"
