"""Tests proving rule-based pre-filter handles simple replies WITHOUT calling the LLM.

Requirement: done/yes/no/not_sure/skip/wants_human must never hit _call_llm.
Goal: known step reply under 300ms (moot here, but verified by no LLM call).
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.llm_service import (
    _rule_based_interpret,
    interpret_step_response,
)
from app.models.schemas import InterpretResult


# ── Unit tests for _rule_based_interpret ────────────────────────────────────

@pytest.mark.parametrize("text,expected_label", [
    ("done",          "done"),
    ("Done",          "done"),
    ("DONE",          "done"),
    ("ok",            "done"),
    ("okay",          "done"),
    ("it worked",     "done"),
    ("fixed",         "done"),
    ("yes",           "yes"),
    ("Yeah",          "yes"),
    ("yep",           "yes"),
    ("correct",       "yes"),
    ("no",            "no"),
    ("nope",          "no"),
    ("not working",   "no"),
    ("didn't work",   "no"),
    ("not sure",      "not_sure"),
    ("idk",           "not_sure"),
    ("i don't know",  "not_sure"),
    ("skip",          "skip"),
    ("next",          "skip"),
    ("move on",       "skip"),
    ("human",         "wants_human"),
    ("i want a human","wants_human"),
    ("live agent",    "wants_human"),
    ("talk to someone","wants_human"),
])
def test_rule_based_recognises_simple_replies(text, expected_label):
    result = _rule_based_interpret(text)
    assert result is not None, f"Expected rule match for '{text}' but got None"
    assert result.mapped_response == expected_label


@pytest.mark.parametrize("text", [
    "the light is blinking rapidly",
    "I tried but it shows an error code 502",
    "not entirely sure what happened next",
    "could you explain step 3 again please",
])
def test_rule_based_returns_none_for_ambiguous(text):
    result = _rule_based_interpret(text)
    assert result is None, f"Expected no rule match for '{text}' but got {result}"


# ── Integration: confirm no LLM call for simple replies ─────────────────────

@pytest.mark.parametrize("simple_reply", [
    "done", "yes", "no", "not sure", "skip", "i want a human",
    "ok", "yep", "nope", "fixed", "it worked", "next",
])
def test_simple_reply_does_not_call_llm(simple_reply):
    with patch("app.services.llm_service._call_llm", new_callable=AsyncMock) as mock_llm:
        result = asyncio.run(
            interpret_step_response(simple_reply, {})
        )
        mock_llm.assert_not_called(), (
            f"LLM was called for simple reply '{simple_reply}' — rule-based pre-filter failed"
        )
        assert result.mapped_response != "other"


def test_wants_human_sets_should_escalate():
    result = _rule_based_interpret("i want a human")
    assert result is not None
    assert result.should_escalate is True


def test_done_does_not_escalate():
    result = _rule_based_interpret("done")
    assert result is not None
    assert result.should_escalate is False


def test_rule_based_confidence_is_max():
    for text in ["done", "yes", "no", "skip"]:
        result = _rule_based_interpret(text)
        assert result is not None
        assert result.confidence == 1.0


def test_ambiguous_reply_calls_llm():
    """Ambiguous free-text DOES call LLM — verify the fallback path works."""
    mock_raw = '{"mapped_response":"yes","confidence":0.85,"extracted_observation":"","should_escalate":false,"reason":"test"}'
    with patch("app.services.llm_service._call_llm", new_callable=AsyncMock, return_value=mock_raw):
        result = asyncio.run(
            interpret_step_response("seems to be working now after the reboot", {"id": "step_1"})
        )
        assert result.mapped_response == "yes"
