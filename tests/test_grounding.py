from unittest.mock import MagicMock

import pytest

from osmind.decision import recommended_action
from osmind.engine.grounding import apply_guardrails, ground_issue
from osmind.engine.ranker import Ranker
from osmind.github.models import GHIssue


def _issue(**kwargs) -> GHIssue:
    base = dict(
        number=1,
        title="Something",
        body="A normal bug report with a traceback.",
        labels=[],
        url="https://github.com/x/y/issues/1",
        repo="x/y",
        state="open",
    )
    base.update(kwargs)
    return GHIssue(**base)


def test_ground_issue_detects_assignee():
    signals = ground_issue(_issue(assignees=["alice"]))
    assert signals.assigned is True
    assert signals.has_guardrail is True
    assert any("alice" in f for f in signals.flags)


def test_ground_issue_detects_negative_labels():
    signals = ground_issue(_issue(labels=["wontfix", "bug"]))
    assert signals.negative_labels == ["wontfix"]
    assert signals.positive_labels == ["bug"]
    assert signals.has_guardrail is True


def test_ground_issue_detects_resolution_reference():
    signals = ground_issue(_issue(body="This was already fixed in #123, closing soon."))
    assert signals.resolution_refs == [123]
    assert signals.has_guardrail is True


def test_ground_issue_positive_only_has_no_guardrail():
    signals = ground_issue(_issue(labels=["good first issue"]))
    assert signals.positive_labels == ["good first issue"]
    assert signals.has_guardrail is False


def test_apply_guardrails_negative_label_clamps_score_and_fit():
    signals = ground_issue(_issue(labels=["duplicate"]))
    result = apply_guardrails(
        {"score": 0.9, "priority": "high", "fit": "high",
         "resource_fit": "ok", "actionability": "high", "reason": "looks great"},
        signals,
    )
    assert result["actionability"] == "low"
    assert result["fit"] == "low"
    assert result["score"] <= 0.3
    assert result["reason"].startswith("⚠")


def test_apply_guardrails_noop_without_signals():
    signals = ground_issue(_issue(labels=["good first issue"]))
    original = {"score": 0.8, "priority": "high", "fit": "high",
                "resource_fit": "ok", "actionability": "high", "reason": "ok"}
    assert apply_guardrails(dict(original), signals) == original


def test_ranker_guardrail_demotes_assigned_issue_from_do_now():
    mock_llm = MagicMock()
    mock_llm.chat.return_value = (
        '{"score": 0.92, "priority": "high", "fit": "high", '
        '"resource_fit": "ok", "actionability": "high", "reason": "perfect match"}'
    )
    ranker = Ranker(llm=mock_llm, interests=["x"], skills=["Python"])
    issue = _issue(assignees=["bob"], labels=["good first issue"])

    scored = ranker.score_one(issue)

    # Without grounding this would be "Do now"; the assignee guardrail forces Defer.
    assert scored.actionability == "low"
    assert recommended_action(scored) == "Defer"
    assert scored.grounding  # flag surfaced for the UI
    # Repo facts were fed into the prompt.
    assert "Repo facts" in mock_llm.chat.call_args.args[1]
    assert "assigned" in mock_llm.chat.call_args.args[1].lower()
