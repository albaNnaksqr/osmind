from __future__ import annotations
import json
from osmind.engine.llm import LLMClient
from osmind.github.models import GHIssue

_SYSTEM = """\
You are a contribution opportunity scorer. Given a user profile, available resources, and a GitHub issue, return a JSON object:
{
  "score": <float 0-1>,
  "priority": "high" | "medium" | "low",
  "fit": "high" | "medium" | "low",
  "resource_fit": "ok" | "risk" | "blocked",
  "actionability": "high" | "medium" | "low",
  "reason": "<one sentence in Chinese explaining the recommendation and any resource constraint>"
}
Only return valid JSON, no markdown."""

_UNKNOWN = "unknown"
_LEVELS = {"high", "medium", "low", _UNKNOWN}
_RESOURCE_FIT = {"ok", "risk", "blocked", _UNKNOWN}


class Ranker:
    def __init__(
        self,
        llm: LLMClient,
        interests: list[str],
        skills: list[str],
        resources: dict | None = None,
    ):
        self._llm = llm
        self._interests = interests
        self._skills = skills
        self._resources = resources or {}

    def _score_issue(self, issue: GHIssue) -> dict:
        prompt = (
            f"User interests: {', '.join(self._interests)}\n"
            f"User skills: {', '.join(self._skills)}\n\n"
            f"User resources:\n{_format_resources(self._resources)}\n\n"
            f"Issue #{issue.number}: {issue.title}\n"
            f"Labels: {', '.join(issue.labels)}\n"
            f"Body: {issue.body[:400]}"
        )
        raw = self._llm.chat(_SYSTEM, prompt, max_tokens=128)
        try:
            data = json.loads(raw)
            return {
                "score": float(data["score"]),
                "priority": _normalize_level(data.get("priority")),
                "fit": _normalize_level(data.get("fit")),
                "resource_fit": _normalize_resource_fit(data.get("resource_fit")),
                "actionability": _normalize_level(data.get("actionability")),
                "reason": str(data.get("reason", "")),
            }
        except (json.JSONDecodeError, KeyError, ValueError):
            return {
                "score": 0.0,
                "priority": _UNKNOWN,
                "fit": _UNKNOWN,
                "resource_fit": _UNKNOWN,
                "actionability": _UNKNOWN,
                "reason": "",
            }

    def score_one(self, issue: GHIssue) -> GHIssue:
        """Score a single issue in-place and return it."""
        result = self._score_issue(issue)
        issue.score = result["score"]
        issue.reason = result["reason"]
        issue.priority = result["priority"]
        issue.fit = result["fit"]
        issue.resource_fit = result["resource_fit"]
        issue.actionability = result["actionability"]
        return issue

    def rank(self, issues: list[GHIssue]) -> list[GHIssue]:
        for issue in issues:
            self.score_one(issue)
        return sorted(issues, key=lambda i: i.score, reverse=True)


def _format_resources(resources: dict) -> str:
    if not resources:
        return "- unspecified"
    return "\n".join(f"- {key}: {value}" for key, value in resources.items())


def _normalize_level(value) -> str:
    normalized = str(value or _UNKNOWN).strip().lower()
    if normalized == "med":
        normalized = "medium"
    return normalized if normalized in _LEVELS else _UNKNOWN


def _normalize_resource_fit(value) -> str:
    normalized = str(value or _UNKNOWN).strip().lower()
    return normalized if normalized in _RESOURCE_FIT else _UNKNOWN
