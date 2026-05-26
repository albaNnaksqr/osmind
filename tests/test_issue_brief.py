import json
import pytest
from unittest.mock import MagicMock

from osmind.engine.issue_brief import (
    IssueBrief,
    IssueBriefGenerator,
    render_agent_prompt,
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
        "one_liner": "这是一个模型适配问题，可以先沿着 Qwen2 adapter 找入口。",
        "problem_summary": "Issue 要求为 Qwen3MoE 增加模型支持，并参考已有 Qwen2 adapter。",
        "background": [
            "模型适配通常涉及 config mapping、权重加载和注册路径。",
            "Issue 文本给出了 Qwen2 adapter 作为可搜索模板。",
        ],
        "matched_interests": ["SGLang inference optimization"],
        "matched_skills": ["Python"],
        "resource_assessment": "资源风险较低；第一步主要是代码阅读和小范围测试，不依赖大 GPU。",
        "evidence": [
            "Title mentions Qwen3MoE support.",
            "Body says to follow the existing Qwen2 adapter.",
            "Label good first issue suggests scoped external contribution.",
        ],
        "risks": ["Qwen3MoE 架构差异可能导致适配范围超过 config mapping。"],
        "first_steps": [
            "搜索 Qwen2 adapter 和 model registry。",
            "确认 Qwen3MoE config 名称、权重键和 tokenizer 是否已有支持。",
            "找一个最小加载或注册测试作为验证点。",
        ],
        "validation_path": [
            "能定位现有 Qwen2 adapter。",
            "能说明 Qwen3MoE 需要新增或复用哪些注册入口。",
            "能跑一个最小模型配置或相关单测。",
        ],
        "agent_prompt": (
            "在 o/r 仓库中研究 issue #42: Add Qwen3MoE support。"
            "先搜索 Qwen2 adapter、model registry 和 Qwen3MoE 相关符号，"
            "总结最小实现路径和可验证测试；如果找不到注册入口，停止并说明缺失信息。"
        ),
        "metadata": {
            "source_updated_at": "2026-05-15T01:02:03+00:00",
            "recommendation_reason": "Recommended by ranker",
            "profile_hash": "profile-hash",
            "source_hash": "source-hash",
        },
    }


def _legacy_brief_payload() -> dict:
    return {
        "one_liner": "Tokenizer cache grows without bound.",
        "plain_explanation": "The tokenizer cache keeps growing after repeated requests.",
        "why_it_fits": "The cached recommendation says this is actionable for Python work.",
        "project_context": ["Tokenizer code owns request text normalization."],
        "likely_files": ["python/sglang/tokenizer.py"],
        "difficulty": "medium",
        "readiness": "ready",
        "background_to_learn": ["Read the tokenizer cache implementation."],
        "next_steps": ["Add a regression test for repeated tokenization."],
        "agent_questions": ["Which cache key is expected to be bounded?"],
        "risks": ["The cache may be intentionally process-wide."],
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
    assert "Good first issue with clear adapter template." in brief.problem_summary
    assert brief.background == ["Repo: o/r", "Labels: good first issue, model", "Issue URL: https://github.com/o/r/issues/42"]
    assert brief.first_steps[0] == "Read the issue body and linked discussion."
    assert brief.matched_interests == []
    assert brief.risks


def test_issue_brief_generator_falls_back_when_list_fields_are_blank():
    llm = MagicMock()
    payload = _brief_payload()
    payload["first_steps"] = ["  "]
    llm.chat.return_value = json.dumps(payload)
    issue = _issue()

    brief = IssueBriefGenerator(llm).generate(issue, reason="Clear fit.")

    assert brief.one_liner == "这是一个模型适配问题，可以先沿着 Qwen2 adapter 找入口。"
    assert brief.first_steps == []
    assert "Issue 要求为 Qwen3MoE 增加模型支持" in brief.problem_summary


def test_issue_brief_renders_markdown_sections():
    brief = IssueBrief(**_brief_payload())

    markdown = render_issue_brief_markdown(brief)

    assert markdown.startswith("## Issue Brief")
    assert "### One-Liner" in markdown
    assert "这是一个模型适配问题" in markdown
    assert "### Problem Summary" in markdown
    assert "Issue 要求为 Qwen3MoE 增加模型支持" in markdown
    assert "### Background" in markdown
    assert "### Why It May Fit You" in markdown
    assert "- Interest: SGLang inference optimization" in markdown
    assert "- Skill: Python" in markdown
    assert "### Resource Assessment" in markdown
    assert "资源风险较低" in markdown
    assert "### Evidence" in markdown
    assert "### Risks And Missing Evidence" in markdown
    assert "### First 30 Minutes" in markdown
    assert "搜索 Qwen2 adapter" in markdown
    assert "### Validation Path" in markdown
    assert "### Agent Prompt" in markdown
    assert "在 o/r 仓库中研究 issue #42" in markdown
    assert "### Next Steps" not in markdown


def test_render_agent_prompt_returns_saved_prompt_text():
    brief = IssueBrief(**_brief_payload())

    assert render_agent_prompt(brief).startswith("在 o/r 仓库中研究 issue #42")
    assert "停止并说明缺失信息" in render_agent_prompt(brief)


def test_issue_brief_json_roundtrip():
    brief = IssueBrief(**_brief_payload())

    parsed = issue_brief_from_json(brief.to_json())

    assert parsed == brief


def test_issue_brief_supports_legacy_constructor_kwargs():
    legacy = _legacy_brief_payload()
    brief = IssueBrief(**legacy)

    assert brief.one_liner == legacy["one_liner"]
    assert brief.problem_summary == legacy["plain_explanation"]
    assert brief.background == legacy["project_context"]
    assert brief.evidence == legacy["likely_files"]
    assert brief.first_steps == legacy["next_steps"]
    assert brief.validation_path == legacy["agent_questions"]

    assert brief.plain_explanation == legacy["plain_explanation"]
    assert brief.why_it_fits == legacy["why_it_fits"]
    assert brief.project_context == legacy["project_context"]
    assert brief.likely_files == legacy["likely_files"]
    assert brief.difficulty == legacy["difficulty"]
    assert brief.readiness == legacy["readiness"]
    assert brief.background_to_learn == legacy["background_to_learn"]
    assert brief.next_steps == legacy["next_steps"]
    assert brief.agent_questions == legacy["agent_questions"]


def test_issue_brief_roundtrip_preserves_legacy_why_it_fits():
    legacy = _legacy_brief_payload()
    brief = IssueBrief(**legacy)

    parsed = issue_brief_from_json(brief.to_json())

    assert parsed.why_it_fits == legacy["why_it_fits"]
    assert parsed.why_it_fits == parsed.metadata.recommendation_reason


def test_issue_brief_from_json_requires_resource_assessment_for_canonical_payload():
    payload = _brief_payload()
    del payload["resource_assessment"]

    with pytest.raises(ValueError):
        issue_brief_from_json(json.dumps(payload))


def test_issue_brief_from_json_requires_agent_prompt_for_canonical_payload():
    payload = _brief_payload()
    del payload["agent_prompt"]

    with pytest.raises(ValueError):
        issue_brief_from_json(json.dumps(payload))


@pytest.mark.parametrize(
    "missing_field",
    ["problem_summary", "resource_assessment", "agent_prompt"],
)
def test_issue_brief_from_json_does_not_fall_back_to_legacy_fields_for_required_values(missing_field: str):
    payload = {
        "plain_explanation": "Legacy explanation.",
        "why_it_fits": "Legacy fit statement.",
        "one_liner": "Legacy issue.",
        "resource_assessment": "Legacy resource text.",
        "agent_prompt": "Legacy prompt.",
        "problem_summary": "Legacy canonical summary.",
    }
    payload[missing_field] = ""

    with pytest.raises(ValueError):
        issue_brief_from_json(json.dumps(payload))
