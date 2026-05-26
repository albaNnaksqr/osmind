from __future__ import annotations

import json
import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any

from osmind.engine.llm import LLMClient
from osmind.github.models import GHIssue


_SYSTEM = """\
You write structured issue briefs for developers evaluating open-source work.
Only return valid JSON with exactly the requested fields. Do not include markdown."""

_ISSUE_BODY_LIMIT = 4000
_COMMENT_BODY_LIMIT = 800
_COMMENT_PROMPT_LIMIT = 5


@dataclass
class IssueBriefMetadata:
    source_updated_at: str = ""
    recommendation_reason: str = ""
    profile_hash: str = ""
    source_hash: str = ""
    legacy_background_to_learn: list[str] = field(default_factory=list)


class IssueBriefGenerationError(Exception):
    pass


@dataclass
class IssueBriefProfileContext:
    interests: list[str]
    skills: list[str]
    resources: dict[str, Any]

    def to_prompt(self) -> str:
        return "\n".join(
            [
                f"Interests: {', '.join(self.interests) or 'none'}",
                f"Skills: {', '.join(self.skills) or 'none'}",
                f"Resources: {_format_mapping(self.resources)}",
            ]
        )


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
        self._difficulty = _coerce_scalar_string(difficulty)
        self._readiness = _coerce_scalar_string(readiness)
        if metadata is None:
            self.metadata = IssueBriefMetadata()
        elif isinstance(metadata, dict):
            legacy_background_to_learn = _coerce_str_list(
                metadata.get("legacy_background_to_learn", [])
            )
            self.metadata = IssueBriefMetadata(
                source_updated_at=str(metadata.get("source_updated_at", "")),
                recommendation_reason=str(metadata.get("recommendation_reason", "")),
                profile_hash=str(metadata.get("profile_hash", "")),
                source_hash=str(metadata.get("source_hash", "")),
                legacy_background_to_learn=legacy_background_to_learn,
            )
        elif isinstance(metadata, IssueBriefMetadata):
            self.metadata = metadata
        else:
            raise TypeError("metadata must be an IssueBriefMetadata instance, dict, or None")

        self._background_to_learn = _coerce_str_list(background_to_learn)
        if not self._background_to_learn:
            self._background_to_learn = self._project_context
        if not self._background_to_learn:
            self._background_to_learn = _coerce_str_list(
                self.metadata.legacy_background_to_learn
            )
        if background_to_learn is not None:
            self.metadata.legacy_background_to_learn = list(self._background_to_learn)

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
        if self._difficulty:
            return self._difficulty
        parsed_difficulty = _parse_profile_value_from_assessment(
            self.resource_assessment,
            "difficulty",
        )
        return parsed_difficulty or "unknown"

    @property
    def readiness(self) -> str:
        if self._readiness:
            return self._readiness
        parsed_readiness = _parse_profile_value_from_assessment(
            self.resource_assessment,
            "readiness",
        )
        return parsed_readiness or "needs review"

    @property
    def background_to_learn(self) -> list[str]:
        return self._background_to_learn or self.background

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

    def generate(
        self,
        issue: GHIssue,
        reason: str = "",
        profile_context: IssueBriefProfileContext | None = None,
    ) -> IssueBrief:
        profile_context = profile_context or IssueBriefProfileContext(
            interests=[],
            skills=[],
            resources={},
        )
        raw = self._llm.chat(
            _SYSTEM,
            _format_prompt(issue, reason, profile_context),
            max_tokens=1400,
        )
        try:
            brief = issue_brief_from_json(raw)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise IssueBriefGenerationError("Failed to parse issue brief JSON") from exc
        brief.metadata = issue_brief_metadata(issue, reason, profile_context)
        return brief


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
            legacy_background_to_learn=_coerce_str_list(
                metadata.get("legacy_background_to_learn", [])
            ),
        ),
    )


def issue_brief_metadata(
    issue: GHIssue,
    reason: str,
    profile_context: IssueBriefProfileContext,
) -> IssueBriefMetadata:
    normalized_profile = _normalized_profile_payload(profile_context)
    return IssueBriefMetadata(
        source_updated_at=issue.updated_at or "",
        recommendation_reason=reason or issue.reason or "",
        profile_hash=_hash_json(normalized_profile),
        source_hash=_hash_json(_normalized_issue_source_payload(issue)),
    )


def is_issue_brief_current(
    brief: IssueBrief,
    issue: GHIssue,
    reason: str,
    profile_context: IssueBriefProfileContext,
) -> bool:
    expected = issue_brief_metadata(issue, reason, profile_context)
    metadata = brief.metadata if isinstance(brief.metadata, IssueBriefMetadata) else IssueBriefMetadata()
    return (
        metadata.source_updated_at == expected.source_updated_at
        and metadata.recommendation_reason == expected.recommendation_reason
        and metadata.profile_hash == expected.profile_hash
        and metadata.source_hash == expected.source_hash
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


def _format_prompt(
    issue: GHIssue, reason: str, profile_context: IssueBriefProfileContext
) -> str:
    labels = ", ".join(issue.labels) or "none"
    recommendation_reason = reason or issue.reason or "(none)"
    comments = _format_comments(issue.comments)
    expected_fields = "\n".join(
        [
            '- "one_liner": string, Chinese',
            '- "problem_summary": string, Chinese',
            '- "background": array of strings, Chinese',
            '- "matched_interests": array of strings copied from user profile when supported by evidence',
            '- "matched_skills": array of strings copied from user profile when supported by evidence',
            '- "resource_assessment": string, Chinese',
            '- "evidence": array of strings grounded in title, labels, body, comments, score reason, or profile',
            '- "risks": array of strings, Chinese',
            '- "first_steps": array of strings, Chinese, first 30 minutes',
            '- "validation_path": array of strings, Chinese',
            '- "agent_prompt": string, Chinese, ready to give to Codex or Claude',
        ]
    )
    return (
        "Answer in Chinese. Return strict JSON only; no markdown fence.\n"
        "Ground every recommendation in the issue text, comments, score reason, or user profile. "
        "If evidence is missing, say so in risks instead of inventing repository internals.\n\n"
        f"Repo: {issue.repo}\n"
        f"Issue #{issue.number}: {issue.title}\n"
        f"URL: {issue.url}\n"
        f"Labels: {labels}\n"
        f"Recommendation reason: {recommendation_reason}\n\n"
        f"User profile:\n{profile_context.to_prompt()}\n\n"
        f"Issue body:\n{_normalize_issue_body(issue.body) or '(empty)'}\n\n"
        f"Comments:\n{comments}\n\n"
        "Return a JSON object with these expected fields:\n"
        f"{expected_fields}\n\n"
        "Keep the brief concrete, useful to an implementation agent, and grounded in the issue text."
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


def _parse_profile_value_from_assessment(resource_assessment: str, key: str) -> str:
    target = key.strip().lower()
    for chunk in resource_assessment.split(";"):
        if ":" not in chunk:
            continue
        chunk_key, chunk_value = chunk.split(":", 1)
        if chunk_key.strip().lower() != target:
            continue
        return chunk_value.strip().strip(".")
    return ""


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


def _format_mapping(values: dict[str, Any]) -> str:
    if not values:
        return "none"
    return ", ".join(
        f"{key}: {_format_prompt_value(values[key])}" for key in sorted(values)
    )


def _hash_json(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _format_prompt_value(value: Any) -> str:
    if isinstance(value, dict):
        return "{" + _format_mapping(value) + "}"
    if isinstance(value, list):
        return "[" + ", ".join(_format_prompt_value(item) for item in value) + "]"
    return str(value)


def _normalize_issue_body(body: str) -> str:
    return body[:_ISSUE_BODY_LIMIT]


def _normalize_comment_body(body: str) -> str:
    return body[:_COMMENT_BODY_LIMIT]


def _normalized_comment_payload(comment: Any) -> dict[str, str]:
    return {
        "author": comment.author,
        "body": _normalize_comment_body(comment.body),
    }


def _normalized_issue_source_payload(issue: GHIssue) -> dict[str, Any]:
    return {
        "title": issue.title,
        "body": _normalize_issue_body(issue.body),
        "labels": list(issue.labels),
        "comments": [
            _normalized_comment_payload(comment)
            for comment in issue.comments[:_COMMENT_PROMPT_LIMIT]
        ],
    }


def _normalized_profile_payload(profile_context: IssueBriefProfileContext) -> dict[str, Any]:
    return {
        "interests": list(profile_context.interests),
        "skills": list(profile_context.skills),
        "resources": _normalize_json_value(profile_context.resources),
    }


def _normalize_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _normalize_json_value(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_normalize_json_value(item) for item in value]
    return value


def _format_comments(comments: list[Any]) -> str:
    normalized_comments = [
        _normalized_comment_payload(comment)
        for comment in comments[:_COMMENT_PROMPT_LIMIT]
    ]
    return (
        "\n".join(
            f"- {comment['author']}: {comment['body']}" for comment in normalized_comments
        )
        or "- No cached comments."
    )


def _render_list(items: list[str], *, code: bool = False) -> str:
    if not items:
        return "- None identified."
    if code:
        return "\n".join(f"- `{item}`" for item in items)
    return "\n".join(f"- {item}" for item in items)
