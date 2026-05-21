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
class IssueBrief:
    one_liner: str
    plain_explanation: str
    why_it_fits: str
    project_context: list[str]
    likely_files: list[str]
    difficulty: str
    readiness: str
    background_to_learn: list[str]
    next_steps: list[str]
    agent_questions: list[str]
    risks: list[str]

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
    return IssueBrief(
        one_liner=_required_str(data, "one_liner"),
        plain_explanation=_required_str(data, "plain_explanation"),
        why_it_fits=_required_str(data, "why_it_fits"),
        project_context=_required_str_list(data, "project_context"),
        likely_files=_required_str_list(data, "likely_files"),
        difficulty=_required_str(data, "difficulty"),
        readiness=_required_str(data, "readiness"),
        background_to_learn=_required_str_list(data, "background_to_learn"),
        next_steps=_required_str_list(data, "next_steps"),
        agent_questions=_required_str_list(data, "agent_questions"),
        risks=_required_str_list(data, "risks"),
    )


def render_issue_brief_markdown(brief: IssueBrief) -> str:
    sections = [
        "## Issue Brief",
        "",
        "### One-Liner",
        brief.one_liner,
        "",
        "### Difficulty / Readiness",
        f"- Difficulty: {brief.difficulty}",
        f"- Readiness: {brief.readiness}",
        "",
        "### Explanation",
        brief.plain_explanation,
        "",
        "### Why It Fits",
        brief.why_it_fits,
        "",
        "### Project Context",
        _render_list(brief.project_context),
        "",
        "### Likely Files",
        _render_list(brief.likely_files, code=True),
        "",
        "### Background",
        _render_list(brief.background_to_learn),
        "",
        "### Next Steps",
        _render_list(brief.next_steps),
        "",
        "### Agent Questions",
        _render_list(brief.agent_questions),
        "",
        "### Risks",
        _render_list(brief.risks),
    ]
    return "\n".join(sections).rstrip() + "\n"


def _format_prompt(issue: GHIssue, reason: str) -> str:
    labels = ", ".join(issue.labels) or "none"
    recommendation_reason = reason or issue.reason or "(none)"
    expected_fields = "\n".join(
        [
            '- "one_liner": string',
            '- "plain_explanation": string',
            '- "why_it_fits": string',
            '- "project_context": array of strings',
            '- "likely_files": array of strings',
            '- "difficulty": string',
            '- "readiness": string',
            '- "background_to_learn": array of strings',
            '- "next_steps": array of strings',
            '- "agent_questions": array of strings',
            '- "risks": array of strings',
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
    why_it_fits = reason or issue.reason or "No recommendation reason was provided; review the issue against current goals."
    explanation = body_excerpt or "The issue body is empty, so the brief is based on the title and metadata."
    return IssueBrief(
        one_liner=issue.title.strip() or f"Issue #{issue.number}",
        plain_explanation=explanation,
        why_it_fits=why_it_fits,
        project_context=[f"Repo: {issue.repo}", f"Labels: {labels}"],
        likely_files=[],
        difficulty="unknown",
        readiness="needs review",
        background_to_learn=[
            "Read the issue body, labels, and linked discussion.",
            "Inspect nearby code before choosing an implementation path.",
        ],
        next_steps=[
            "Read the issue body and linked discussion.",
            "Search the repository for terms from the title and body.",
            "Identify the smallest reproducible change before editing.",
        ],
        agent_questions=[
            "Which files own the behavior described by this issue?",
            "What test would fail before the intended fix?",
        ],
        risks=[
            "The LLM did not return a valid structured brief.",
            "The fallback may miss project-specific files or hidden constraints.",
        ],
    )


def _required_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Missing or invalid string field: {key}")
    return value


def _required_str_list(data: dict[str, Any], key: str) -> list[str]:
    value = data.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"Missing or invalid list field: {key}")
    return value


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
