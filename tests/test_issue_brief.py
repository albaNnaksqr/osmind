import json
import pytest
from unittest.mock import MagicMock

from osmind.engine.issue_brief import (
    IssueBrief,
    IssueBriefGenerationError,
    IssueBriefGenerator,
    IssueBriefProfileContext,
    is_issue_brief_current,
    render_agent_prompt,
    issue_brief_from_json,
    issue_brief_metadata,
    render_issue_brief_markdown,
)
from osmind.github.models import GHComment, GHIssue


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


def _comment(index: int, body: str) -> GHComment:
    return GHComment(
        author=f"user-{index}",
        body=body,
        url=f"https://github.com/o/r/issues/42#issuecomment-{index}",
        created_at=f"2026-05-{index:02d}T00:00:00+00:00",
    )


def _issue_with_comments(*comment_bodies: str) -> GHIssue:
    issue = _issue()
    issue.updated_at = "2026-05-15T01:02:03+00:00"
    issue.comments = [_comment(index, body) for index, body in enumerate(comment_bodies, 1)]
    return issue


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
    issue = _issue_with_comments(
        "Check the existing registry wiring.",
        "The Qwen2 adapter already covers most config glue.",
        "Please keep tokenizer compatibility in mind.",
        "A minimal loader smoke test would help.",
        "We should verify config aliases before touching weights.",
        "This sixth comment should not appear in the prompt.",
    )
    profile_context = IssueBriefProfileContext(
        interests=["SGLang inference optimization"],
        skills=["Python"],
        resources={
            "zeta": "late",
            "alpha": "first",
            "nested": {"gpu": "4090", "ram_gb": 64},
        },
    )
    expected_metadata = issue_brief_metadata(
        issue,
        "Recommended by ranker",
        profile_context,
    )

    brief = IssueBriefGenerator(llm).generate(
        issue,
        reason="Recommended by ranker",
        profile_context=profile_context,
    )
    expected = IssueBrief(**_brief_payload())
    expected.metadata = expected_metadata

    assert brief == expected
    llm.chat.assert_called_once()
    system, prompt = llm.chat.call_args.args
    assert "Only return valid JSON" in system
    assert "Repo: o/r" in prompt
    assert "Issue #42" in prompt
    assert "Labels: good first issue, model" in prompt
    assert "Recommendation reason: Recommended by ranker" in prompt
    assert "Answer in Chinese" in prompt
    assert "Return strict JSON only" in prompt
    assert "User profile:" in prompt
    assert "Interests: SGLang inference optimization" in prompt
    assert "Skills: Python" in prompt
    assert "Resources: alpha: first, nested: {gpu: 4090, ram_gb: 64}, zeta: late" in prompt
    assert "- user-1: Check the existing registry wiring." in prompt
    assert "- user-5: We should verify config aliases before touching weights." in prompt
    assert "This sixth comment should not appear in the prompt." not in prompt
    assert "one_liner" in prompt
    assert "problem_summary" in prompt
    assert "matched_interests" in prompt
    assert "validation_path" in prompt
    assert "agent_prompt" in prompt
    assert llm.chat.call_args.kwargs["max_tokens"] == 1400


def test_issue_brief_generator_raises_controlled_error_for_invalid_json():
    llm = MagicMock()
    llm.chat.return_value = "not json"
    issue = _issue()
    profile_context = IssueBriefProfileContext(
        interests=["SGLang inference optimization"],
        skills=["Python"],
        resources={"gpus": "4x RTX 4090"},
    )

    with pytest.raises(IssueBriefGenerationError, match="Failed to parse issue brief JSON"):
        IssueBriefGenerator(llm).generate(
            issue,
            reason="Good first issue with clear adapter template.",
            profile_context=profile_context,
        )


def test_issue_brief_cache_metadata_marks_current_brief_valid():
    issue = _issue()
    profile_context = IssueBriefProfileContext(
        interests=["SGLang inference optimization"],
        skills=["Python"],
        resources={"gpus": "4x RTX 4090"},
    )
    brief = IssueBrief(**_brief_payload())
    brief.metadata = issue_brief_metadata(issue, "Recommended by ranker", profile_context)

    assert is_issue_brief_current(brief, issue, "Recommended by ranker", profile_context)


def test_issue_brief_cache_metadata_detects_changed_reason():
    issue = _issue()
    profile_context = IssueBriefProfileContext(
        interests=["SGLang inference optimization"],
        skills=["Python"],
        resources={"gpus": "4x RTX 4090"},
    )
    brief = IssueBrief(**_brief_payload())
    brief.metadata = issue_brief_metadata(issue, "Recommended by ranker", profile_context)

    assert not is_issue_brief_current(brief, issue, "Different reason", profile_context)


def test_issue_brief_profile_prompt_and_hash_are_stable_across_resource_insertion_order():
    issue = _issue()
    first = IssueBriefProfileContext(
        interests=["Infra"],
        skills=["Python"],
        resources={
            "zeta": "late",
            "alpha": "first",
            "nested": {"gpu": "4090", "ram_gb": 64},
        },
    )
    second = IssueBriefProfileContext(
        interests=["Infra"],
        skills=["Python"],
        resources={
            "nested": {"ram_gb": 64, "gpu": "4090"},
            "alpha": "first",
            "zeta": "late",
        },
    )

    first_metadata = issue_brief_metadata(issue, "Recommended by ranker", first)
    second_metadata = issue_brief_metadata(issue, "Recommended by ranker", second)

    assert first_metadata.profile_hash == second_metadata.profile_hash
    assert first.to_prompt() == second.to_prompt()
    assert "Resources: alpha: first, nested: {gpu: 4090, ram_gb: 64}, zeta: late" in first.to_prompt()


def test_issue_brief_cache_metadata_ignores_sixth_comment_body_change():
    issue = _issue_with_comments(
        "first comment",
        "second comment",
        "third comment",
        "fourth comment",
        "fifth comment",
        "sixth comment",
    )
    issue.updated_at = "2026-05-15T01:02:03+00:00"
    profile_context = IssueBriefProfileContext(
        interests=["SGLang inference optimization"],
        skills=["Python"],
        resources={"gpus": "4x RTX 4090"},
    )
    brief = IssueBrief(**_brief_payload())
    brief.metadata = issue_brief_metadata(issue, "Recommended by ranker", profile_context)

    changed_issue = _issue_with_comments(
        "first comment",
        "second comment",
        "third comment",
        "fourth comment",
        "fifth comment",
        "sixth comment changed outside prompt window",
    )
    changed_issue.updated_at = "2026-05-16T01:02:03+00:00"

    assert is_issue_brief_current(brief, changed_issue, "Recommended by ranker", profile_context)


def test_issue_brief_cache_metadata_detects_first_five_comment_body_change():
    issue = _issue_with_comments(
        "first comment",
        "second comment",
        "third comment",
        "fourth comment",
        "fifth comment",
        "sixth comment",
    )
    issue.updated_at = "2026-05-15T01:02:03+00:00"
    profile_context = IssueBriefProfileContext(
        interests=["SGLang inference optimization"],
        skills=["Python"],
        resources={"gpus": "4x RTX 4090"},
    )
    brief = IssueBrief(**_brief_payload())
    brief.metadata = issue_brief_metadata(issue, "Recommended by ranker", profile_context)

    changed_issue = _issue_with_comments(
        "first comment changed inside prompt window",
        "second comment",
        "third comment",
        "fourth comment",
        "fifth comment",
        "sixth comment",
    )
    changed_issue.updated_at = "2026-05-16T01:02:03+00:00"

    assert not is_issue_brief_current(brief, changed_issue, "Recommended by ranker", profile_context)


def test_issue_brief_cache_metadata_detects_issue_body_change():
    issue = _issue_with_comments("first comment")
    issue.updated_at = "2026-05-15T01:02:03+00:00"
    profile_context = IssueBriefProfileContext(
        interests=["SGLang inference optimization"],
        skills=["Python"],
        resources={"gpus": "4x RTX 4090"},
    )
    brief = IssueBrief(**_brief_payload())
    brief.metadata = issue_brief_metadata(issue, "Recommended by ranker", profile_context)

    changed_issue = _issue_with_comments("first comment")
    changed_issue.updated_at = "2026-05-16T01:02:03+00:00"
    changed_issue.body = "Need to add Qwen3MoE model support with a new tokenizer path."

    assert not is_issue_brief_current(brief, changed_issue, "Recommended by ranker", profile_context)


def test_issue_brief_cache_metadata_detects_profile_change():
    issue = _issue_with_comments("first comment")
    profile_context = IssueBriefProfileContext(
        interests=["SGLang inference optimization"],
        skills=["Python"],
        resources={"gpus": "4x RTX 4090"},
    )
    brief = IssueBrief(**_brief_payload())
    brief.metadata = issue_brief_metadata(issue, "Recommended by ranker", profile_context)

    changed_profile = IssueBriefProfileContext(
        interests=["SGLang inference optimization"],
        skills=["Python", "CUDA"],
        resources={"gpus": "4x RTX 4090"},
    )

    assert not is_issue_brief_current(brief, issue, "Recommended by ranker", changed_profile)


def test_issue_brief_generator_normalizes_blank_optional_list_items():
    llm = MagicMock()
    payload = _brief_payload()
    payload["first_steps"] = ["搜索 Qwen2 adapter", "  "]
    llm.chat.return_value = json.dumps(payload)
    issue = _issue()

    brief = IssueBriefGenerator(llm).generate(issue, reason="Clear fit.")

    assert brief.first_steps == ["搜索 Qwen2 adapter"]


def test_issue_brief_generator_sets_missing_recommendation_reason():
    payload = _brief_payload()
    payload.pop("metadata")
    llm = MagicMock()
    llm.chat.return_value = json.dumps(payload)
    issue = _issue()

    brief = IssueBriefGenerator(llm).generate(issue, reason="Clear model-adaptation fit.")

    assert brief.metadata.recommendation_reason == "Clear model-adaptation fit."


def test_issue_brief_parser_normalizes_blank_optional_list_items():
    payload = _brief_payload()
    payload["first_steps"] = ["搜索 Qwen2 adapter", "  "]

    brief = issue_brief_from_json(json.dumps(payload))

    assert brief.first_steps == ["搜索 Qwen2 adapter"]


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


def test_issue_brief_roundtrip_preserves_legacy_compatibility_read_properties():
    legacy = _legacy_brief_payload()
    legacy.pop("background_to_learn", None)
    brief = IssueBrief(**legacy)

    parsed = issue_brief_from_json(brief.to_json())

    assert parsed.difficulty == legacy["difficulty"]
    assert parsed.readiness == legacy["readiness"]
    assert parsed.background_to_learn == legacy["project_context"]


def test_issue_brief_roundtrip_preserves_legacy_background_to_learn():
    brief = IssueBrief(
        one_liner="Tokenizer cache grows without bound.",
        plain_explanation="The tokenizer cache grows.",
        project_context=["ctx"],
        background_to_learn=["learn me"],
    )

    parsed = issue_brief_from_json(brief.to_json())

    assert parsed.background_to_learn == ["learn me"]


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
    ["one_liner", "problem_summary", "resource_assessment", "agent_prompt"],
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


def test_issue_brief_from_json_requires_one_liner_for_canonical_payload():
    payload = _brief_payload()
    del payload["one_liner"]

    with pytest.raises(ValueError):
        issue_brief_from_json(json.dumps(payload))
