from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from osmind.engine.llm import LLMClient
from osmind.github.models import GHIssue


_SYSTEM = """\
You write structured issue briefs for developers evaluating open-source work.
Only return valid JSON with exactly the requested fields. Do not include markdown."""


@dataclass
class IssueBriefMetadata:
    source_updated_at: str = ""
    recommendation_reason: str = ""
    profile_hash: str = ""
    source_hash: str = ""


@dataclass
class IssueBrief:
    one_liner: str
    problem_summary: str
    background: list[str]
    matched_interests: list[str]
    matched_skills: list[str]
    resource_assessment: str
    evidence: list[str]
    risks: list[str]
    first_steps: list[str]
    validation_path: list[str]
    agent_prompt: str
    metadata: IssueBriefMetadata | dict[str, str] | None = None

    def __post_init__(self) -> None:
        if self.metadata is None:
            self.metadata = IssueBriefMetadata()
        elif isinstance(self.metadata, dict):
            self.metadata = IssueBriefMetadata(
                source_updated_at=str(self.metadata.get("source_updated_at", "")),
                recommendation_reason=str(self.metadata.get("recommendation_reason", "")),
                profile_hash=str(self.metadata.get("profile_hash", "")),
                source_hash=str(self.metadata.get("source_hash", "")),
            )

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class IssueBriefGenerator:
    def __init__(self, llm: LLMClient):
        self._llm = llm

    def generate(self, issue: GHIssue, reason: str = "") -> IssueBrief:
        raw = self._llm.chat(_SYSTEM, _format_prompt(issue, reason), max_tokens=1024)
        try:
            return issue_brief_from_json(raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            return _fallback_brief(issue, reason)


def issue_brief_from_json(value: str) -> IssueBrief:
    data = json.loads(value)
    if not isinstance(data, dict):
        raise ValueError("Issue brief JSON must be an object.")
    metadata = data.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    return IssueBrief(
        one_liner=_required_str(data, "one_liner"),
        problem_summary=_required_str(data, "problem_summary"),
        background=_optional_str_list(data, "background"),
        matched_interests=_optional_str_list(data, "matched_interests"),
        matched_skills=_optional_str_list(data, "matched_skills"),
        resource_assessment=_required_str(data, "resource_assessment"),
        evidence=_optional_str_list(data, "evidence"),
        risks=_optional_str_list(data, "risks"),
        first_steps=_optional_str_list(data, "first_steps"),
        validation_path=_optional_str_list(data, "validation_path"),
        agent_prompt=_required_str(data, "agent_prompt"),
        metadata=IssueBriefMetadata(
            source_updated_at=str(metadata.get("source_updated_at", "")),
            recommendation_reason=str(metadata.get("recommendation_reason", "")),
            profile_hash=str(metadata.get("profile_hash", "")),
            source_hash=str(metadata.get("source_hash", "")),
        ),
    )


def render_issue_brief_markdown(brief: IssueBrief) -> str:
    sections = [
        "## Issue Brief",
        "",
        "### One-Liner",
        brief.one_liner,
        "",
        "### Problem Summary",
        brief.problem_summary,
        "",
        "### Background",
        _render_list(brief.background),
        "",
        "### Why It May Fit You",
        _render_profile_fit(brief),
        "",
        "### Resource Assessment",
        brief.resource_assessment,
        "",
        "### Evidence",
        _render_list(brief.evidence),
        "",
        "### Risks And Missing Evidence",
        _render_list(brief.risks),
        "",
        "### First 30 Minutes",
        _render_numbered(brief.first_steps),
        "",
        "### Validation Path",
        _render_list(brief.validation_path),
        "",
        "### Agent Prompt",
        render_agent_prompt(brief),
    ]
    return "\n".join(sections).rstrip() + "\n"


def render_agent_prompt(brief: IssueBrief) -> str:
    return brief.agent_prompt.strip()


def _render_profile_fit(brief: IssueBrief) -> str:
    lines: list[str] = []
    lines.extend(f"- Interest: {item}" for item in brief.matched_interests)
    lines.extend(f"- Skill: {item}" for item in brief.matched_skills)
    return "\n".join(lines) if lines else "- No direct profile match identified."


def _render_numbered(items: list[str]) -> str:
    if not items:
        return "1. No first step identified."
    return "\n".join(f"{index}. {item}" for index, item in enumerate(items, 1))


def _format_prompt(issue: GHIssue, reason: str) -> str:
    labels = ", ".join(issue.labels) or "none"
    recommendation_reason = reason or issue.reason or "(none)"
    expected_fields = "\n".join(
        [
            '- "one_liner": string',
            '- "problem_summary": string',
            '- "background": array of strings',
            '- "matched_interests": array of strings',
            '- "matched_skills": array of strings',
            '- "resource_assessment": string',
            '- "evidence": array of strings',
            '- "risks": array of strings',
            '- "first_steps": array of strings',
            '- "validation_path": array of strings',
            '- "agent_prompt": string',
            '- "metadata": object with optional keys',
        ]
    )
    return (
        f"Repo: {issue.repo}\n"
        f"Issue #{issue.number}: {issue.title}\n"
        f"URL: {issue.url}\n"
        f"Labels: {labels}\n"
        f"Recommendation reason: {recommendation_reason}\n\n"
        f"Issue body:\n{issue.body[:4000] or '(empty)'}\n\n"
        "Return a JSON object with these expected fields:\n"
        f"{expected_fields}\n\n"
        "Keep the brief concrete, useful to an implementation agent, and grounded in the issue text."
    )


def _fallback_brief(issue: GHIssue, reason: str) -> IssueBrief:
    body_excerpt = _excerpt(issue.body)
    labels = ", ".join(issue.labels) or "none"
    problem_summary = reason or issue.reason or (
        body_excerpt
        or "The issue body is empty; the brief is based on the title and metadata."
    )
    return IssueBrief(
        one_liner=issue.title.strip() or f"Issue #{issue.number}",
        problem_summary=problem_summary,
        background=[
            f"Repo: {issue.repo}",
            f"Labels: {labels}",
            f"Issue URL: {issue.url}",
        ],
        matched_interests=[],
        matched_skills=[],
        resource_assessment="Not enough context to assess risk; inspect source files first.",
        evidence=[
            f"Title: {issue.title}",
            f"Body excerpt: {body_excerpt or '(empty)'}",
        ],
        risks=[
            "The LLM did not return a valid structured brief.",
            "The fallback may miss project-specific files or hidden constraints.",
        ],
        first_steps=[
            "Read the issue body and linked discussion.",
            "Search the repository for symbols from the title and body.",
            "Identify the smallest reproducible change before editing.",
        ],
        validation_path=[
            "Confirm which files own the issue behavior.",
            "Find an existing test or add one covering the intended behavior.",
            "Run focused checks and record the results.",
        ],
        agent_prompt=(
            f"In {issue.repo}, investigate issue #{issue.number}: {issue.title}. "
            "Inspect related code paths, summarize concrete changes and validation checks, "
            "then confirm whether the repository context is sufficient for implementation."
        ),
    )


def _required_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Missing or invalid string field: {key}")
    return value


def _optional_str_list(data: dict[str, Any], key: str) -> list[str]:
    value = data.get(key, [])
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"Invalid list field: {key}")
    return [str(item).strip() for item in value if isinstance(item, str) and item.strip()]


def _render_list(items: list[str], *, code: bool = False) -> str:
    if not items:
        return "- None identified."
    if code:
        return "\n".join(f"- `{item}`" for item in items)
    return "\n".join(f"- {item}" for item in items)


def _excerpt(value: str, limit: int = 500) -> str:
    cleaned = " ".join(value.split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."

