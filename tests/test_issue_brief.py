import json
from unittest.mock import MagicMock

from osmind.engine.issue_brief import (
    IssueBrief,
    IssueBriefGenerator,
    issue_brief_from_json,
    render_issue_brief_markdown,
)
from osmind.github.models import GHIssue


def _issue() -> GHIssue:
    return GHIssue(
        number=42,
        title="Add Qwen3MoE support",
        body="Need to add Qwen3MoE model support. Follow the existing Qwen2 adapter.",
        labels=["good first issue", "model"],
        url="https://github.com/o/r/issues/42",
        repo="o/r",
        state="open",
        reason="Strong model-adaptation fit.",
    )


def _brief_payload() -> dict:
    return {
        "one_liner": "Add Qwen3MoE support by following the Qwen2 adapter.",
        "plain_explanation": "The issue asks for a new model adapter.",
        "why_it_fits": "It is scoped to model adaptation work.",
        "project_context": ["Existing Qwen2 code is the likely template."],
        "likely_files": ["osmind/models/qwen3_moe.py"],
        "difficulty": "medium",
        "readiness": "ready",
        "background_to_learn": ["Qwen model config mapping"],
        "next_steps": ["Find the Qwen2 adapter", "Add a minimal Qwen3MoE config"],
        "agent_questions": ["Which tests cover model adapter registration?"],
        "risks": ["Architecture differences may need deeper changes."],
    }


def test_issue_brief_generator_parses_structured_json():
    llm = MagicMock()
    llm.chat.return_value = json.dumps(_brief_payload())
    issue = _issue()

    brief = IssueBriefGenerator(llm).generate(issue, reason="Recommended by ranker")

    assert brief == IssueBrief(**_brief_payload())
    llm.chat.assert_called_once()
    system, prompt = llm.chat.call_args.args
    assert "Only return valid JSON" in system
    assert "Repo: o/r" in prompt
    assert "Issue #42" in prompt
    assert "Labels: good first issue, model" in prompt
    assert "Recommendation reason: Recommended by ranker" in prompt
    assert "one_liner" in prompt
    assert llm.chat.call_args.kwargs["max_tokens"] == 1024


def test_issue_brief_generator_falls_back_when_llm_returns_invalid_json():
    llm = MagicMock()
    llm.chat.return_value = "not json"
    issue = _issue()

    brief = IssueBriefGenerator(llm).generate(issue, reason="Good first issue with clear adapter template.")

    assert brief.one_liner == "Add Qwen3MoE support"
    assert "Need to add Qwen3MoE model support" in brief.plain_explanation
    assert "Good first issue with clear adapter template." in brief.why_it_fits
    assert brief.project_context == ["Repo: o/r", "Labels: good first issue, model"]
    assert brief.likely_files == []
    assert brief.difficulty == "unknown"
    assert brief.readiness == "needs review"
    assert "Read the issue body and linked discussion." in brief.next_steps
    assert brief.agent_questions
    assert brief.risks


def test_issue_brief_generator_falls_back_when_list_fields_are_blank():
    llm = MagicMock()
    payload = _brief_payload()
    payload["next_steps"] = ["  "]
    llm.chat.return_value = json.dumps(payload)
    issue = _issue()

    brief = IssueBriefGenerator(llm).generate(issue, reason="Clear fit.")

    assert brief.one_liner == "Add Qwen3MoE support"
    assert "Clear fit." in brief.why_it_fits
    assert "The LLM did not return a valid structured brief." in brief.risks


def test_issue_brief_renders_markdown_sections():
    brief = IssueBrief(**_brief_payload())

    markdown = render_issue_brief_markdown(brief)

    assert markdown.startswith("## Issue Brief")
    assert "### One-Liner" in markdown
    assert "### Difficulty / Readiness" in markdown
    assert "- Difficulty: medium" in markdown
    assert "- Readiness: ready" in markdown
    assert "### Explanation" in markdown
    assert "### Why It Fits" in markdown
    assert "### Project Context" in markdown
    assert "- Existing Qwen2 code is the likely template." in markdown
    assert "### Likely Files" in markdown
    assert "- `osmind/models/qwen3_moe.py`" in markdown
    assert "### Background" in markdown
    assert "### Next Steps" in markdown
    assert "### Agent Questions" in markdown
    assert "### Risks" in markdown


def test_issue_brief_json_roundtrip():
    brief = IssueBrief(**_brief_payload())

    parsed = issue_brief_from_json(brief.to_json())

    assert parsed == brief
