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

    def __init__(
        self,
        one_liner: str,
        problem_summary: str | None = None,
        background: list[str] | None = None,
        matched_interests: list[str] | None = None,
        matched_skills: list[str] | None = None,
        resource_assessment: str | None = None,
        evidence: list[str] | None = None,
        risks: list[str] | None = None,
        first_steps: list[str] | None = None,
        validation_path: list[str] | None = None,
        agent_prompt: str | None = None,
        metadata: IssueBriefMetadata | dict[str, str] | None = None,
        *,
        plain_explanation: str | None = None,
        why_it_fits: str | None = None,
        project_context: list[str] | None = None,
        likely_files: list[str] | None = None,
        difficulty: str | None = None,
        readiness: str | None = None,
        background_to_learn: list[str] | None = None,
        next_steps: list[str] | None = None,
        agent_questions: list[str] | None = None,
    ) -> None:
        if not isinstance(one_liner, str) or not one_liner.strip():
            raise ValueError("Missing or invalid string field: one_liner")
        self.one_liner = one_liner.strip()

        if not isinstance(problem_summary, str) or not problem_summary.strip():
            if isinstance(plain_explanation, str) and plain_explanation.strip():
                problem_summary = plain_explanation
            elif isinstance(why_it_fits, str) and why_it_fits.strip():
                problem_summary = why_it_fits
            else:
                raise ValueError("Missing or invalid string field: problem_summary")
        self.problem_summary = problem_summary.strip()

        self.background = _coerce_str_list(background)
        self._project_context = _coerce_str_list(project_context)
        if not self.background:
            self.background = self._project_context
        if not self.background:
            self.background = _coerce_str_list(background_to_learn)

        self.matched_interests = _coerce_str_list(matched_interests)
        self.matched_skills = _coerce_str_list(matched_skills)

        if isinstance(resource_assessment, str) and resource_assessment.strip():
            self.resource_assessment = resource_assessment.strip()
        else:
            difficulty_text = _coerce_scalar_string(difficulty) or "unknown"
            readiness_text = _coerce_scalar_string(readiness) or "needs review"
            self.resource_assessment = f"Difficulty: {difficulty_text}; Readiness: {readiness_text}."

        self.evidence = _coerce_str_list(evidence)
        self._likely_files = _coerce_str_list(likely_files)
        if not self.evidence:
            self.evidence = self._likely_files

        self.risks = _coerce_str_list(risks)

        self.first_steps = _coerce_str_list(first_steps)
        self._next_steps = _coerce_str_list(next_steps)
        if not self.first_steps:
            self.first_steps = self._next_steps

        self.validation_path = _coerce_str_list(validation_path)
        self._agent_questions = _coerce_str_list(agent_questions)
        if not self.validation_path:
            self.validation_path = self._agent_questions

        self._background_to_learn = _coerce_str_list(background_to_learn) or self._project_context

        if not isinstance(agent_prompt, str) or not agent_prompt.strip():
            why_text = _coerce_scalar_string(why_it_fits)
            if why_text:
                self.agent_prompt = why_text
            else:
                self.agent_prompt = f"Investigate issue: {self.one_liner}"
        else:
            self.agent_prompt = agent_prompt.strip()

        self._plain_explanation = _coerce_scalar_string(plain_explanation, default="")
        self._why_it_fits = _coerce_scalar_string(why_it_fits, default="")
        self._difficulty = _coerce_scalar_string(difficulty, default="unknown")
        self._readiness = _coerce_scalar_string(readiness, default="needs review")
        if metadata is None:
            self.metadata = IssueBriefMetadata()
        elif isinstance(metadata, dict):
            self.metadata = IssueBriefMetadata(
                source_updated_at=str(metadata.get("source_updated_at", "")),
                recommendation_reason=str(metadata.get("recommendation_reason", "")),
                profile_hash=str(metadata.get("profile_hash", "")),
                source_hash=str(metadata.get("source_hash", "")),
            )
        elif isinstance(metadata, IssueBriefMetadata):
            self.metadata = metadata
        else:
            raise TypeError("metadata must be an IssueBriefMetadata instance, dict, or None")

        if not self.metadata.recommendation_reason and self._why_it_fits:
            self.metadata.recommendation_reason = self._why_it_fits

    @property
    def plain_explanation(self) -> str:
        return self._plain_explanation or self.problem_summary

    @property
    def why_it_fits(self) -> str:
        return self._why_it_fits or self.metadata.recommendation_reason or self.problem_summary

    @property
    def project_context(self) -> list[str]:
        return self.background

    @property
    def likely_files(self) -> list[str]:
        return self._likely_files if self._likely_files else self.evidence

    @property
    def difficulty(self) -> str:
        return self._difficulty

    @property
    def readiness(self) -> str:
        return self._readiness

    @property
    def background_to_learn(self) -> list[str]:
        return self._background_to_learn

    @property
    def next_steps(self) -> list[str]:
        return self._next_steps if self._next_steps else self.first_steps

    @property
    def agent_questions(self) -> list[str]:
        return self._agent_questions if self._agent_questions else self.validation_path

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
        validation_path=_optional_str_list(
            data,
            "validation_path",
        ),
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


def _required_str(data: dict[str, Any], key: str, *fallback_keys: str) -> str:
    value = data.get(key)
    if isinstance(value, str) and value.strip():
        return value
    for fallback_key in fallback_keys:
        candidate = data.get(fallback_key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    raise ValueError(f"Missing or invalid string field: {key}")


def _optional_str(data: dict[str, Any], key: str) -> str | None:
    value = data.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _optional_str_list(data: dict[str, Any], key: str) -> list[str]:
    sentinel = object()
    value = data.get(key, sentinel)
    if value is None or value is sentinel:
        return []
    if not isinstance(value, list):
        raise ValueError(f"Invalid list field: {key}")
    return [str(item).strip() for item in value if isinstance(item, str) and item.strip()]


def _coerce_scalar_string(value: Any, *, default: str = "") -> str:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    return default


def _coerce_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        return []
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
