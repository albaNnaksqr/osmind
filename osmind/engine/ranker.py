from __future__ import annotations
import json
from osmind.engine.llm import LLMClient
from osmind.github.models import GHIssue

_SYSTEM = """\
You are a relevance scorer. Given a user profile and a GitHub issue, return a JSON object:
{"score": <float 0-1>, "reason": "<one sentence in Chinese explaining the match>"}
Only return valid JSON, no markdown."""


class Ranker:
    def __init__(self, llm: LLMClient, interests: list[str], skills: list[str]):
        self._llm = llm
        self._interests = interests
        self._skills = skills

    def _score_issue(self, issue: GHIssue) -> tuple[float, str]:
        prompt = (
            f"User interests: {', '.join(self._interests)}\n"
            f"User skills: {', '.join(self._skills)}\n\n"
            f"Issue #{issue.number}: {issue.title}\n"
            f"Labels: {', '.join(issue.labels)}\n"
            f"Body: {issue.body[:400]}"
        )
        raw = self._llm.chat(_SYSTEM, prompt, max_tokens=128)
        try:
            data = json.loads(raw)
            return float(data["score"]), str(data.get("reason", ""))
        except (json.JSONDecodeError, KeyError, ValueError):
            return 0.0, ""

    def score_one(self, issue: GHIssue) -> GHIssue:
        """Score a single issue in-place and return it."""
        score, reason = self._score_issue(issue)
        issue.score = score
        issue.reason = reason
        return issue

    def rank(self, issues: list[GHIssue]) -> list[GHIssue]:
        for issue in issues:
            self.score_one(issue)
        return sorted(issues, key=lambda i: i.score, reverse=True)
