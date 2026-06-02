"""Repo-grounded signals for issue triage.

The ranker scores issues from their text, but text alone produces false
positives: an issue can read like a great match yet already be assigned, have a
linked PR, or be tagged wontfix/duplicate. This module derives cheap,
GitHub-metadata-only signals (no clone, no extra API calls beyond what
``get_issues`` already loads) and turns them into:

- ``facts``: human-readable lines fed into the LLM prompt as context.
- ``flags``: short warnings surfaced in the UI / persisted into the reason.
- deterministic guardrails applied to the score (see ``apply_guardrails``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

# Labels that strongly suggest the issue is not actionable as a contribution.
NEGATIVE_LABELS = {
    "wontfix",
    "won't fix",
    "invalid",
    "duplicate",
    "stale",
    "question",
    "needs-info",
    "needs more info",
    "needs-more-info",
    "cannot reproduce",
    "can't reproduce",
    "cant reproduce",
    "not a bug",
    "by design",
    "spam",
}

# Labels that suggest the maintainers welcome outside contributions.
POSITIVE_LABELS = {
    "good first issue",
    "good-first-issue",
    "help wanted",
    "help-wanted",
    "bug",
    "contributions welcome",
}

# Text patterns suggesting the issue is already resolved / a duplicate.
_RESOLUTION_RE = re.compile(
    r"\b(fixed|fix|resolved|resolve|closed|close|addressed|address|"
    r"duplicate of|dup of|superseded by|done in|merged in|tracked in)\b"
    r"[^\n#]{0,30}#(\d+)",
    re.IGNORECASE,
)

_STALE_THRESHOLD_DAYS = 180


@dataclass
class RepoSignals:
    assigned: bool = False
    assignees: list[str] = field(default_factory=list)
    positive_labels: list[str] = field(default_factory=list)
    negative_labels: list[str] = field(default_factory=list)
    resolution_refs: list[int] = field(default_factory=list)
    comment_count: int = 0
    stale_days: int | None = None
    facts: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    @property
    def has_guardrail(self) -> bool:
        return self.assigned or bool(self.negative_labels) or bool(self.resolution_refs)


def _stale_days(updated_at: str) -> int | None:
    if not updated_at:
        return None
    try:
        dt = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt
    return max(delta.days, 0)


def ground_issue(issue) -> RepoSignals:
    """Derive repo-grounded signals from an already-fetched issue."""
    labels_lower = {str(label).strip().lower() for label in getattr(issue, "labels", []) or []}
    assignees = list(getattr(issue, "assignees", []) or [])
    comment_count = int(getattr(issue, "comment_count", 0) or 0)

    text = " ".join(
        [str(getattr(issue, "body", "") or "")]
        + [str(getattr(c, "body", "") or "") for c in getattr(issue, "comments", []) or []]
    )
    resolution_refs = sorted({int(m.group(2)) for m in _RESOLUTION_RE.finditer(text)})

    signals = RepoSignals(
        assigned=bool(assignees),
        assignees=assignees,
        positive_labels=sorted(labels_lower & POSITIVE_LABELS),
        negative_labels=sorted(labels_lower & NEGATIVE_LABELS),
        resolution_refs=resolution_refs,
        comment_count=comment_count,
        stale_days=_stale_days(str(getattr(issue, "updated_at", "") or "")),
    )
    _populate_facts_and_flags(signals)
    return signals


def _populate_facts_and_flags(s: RepoSignals) -> None:
    if s.assigned:
        who = ", ".join(s.assignees)
        s.facts.append(f"Already assigned to: {who} (someone is likely already working on it).")
        s.flags.append(f"⚠ 已被指派给 {who}")
    if s.resolution_refs:
        refs = ", ".join(f"#{n}" for n in s.resolution_refs)
        s.facts.append(f"Text references a resolving/duplicate PR or issue ({refs}); may already be handled.")
        s.flags.append(f"⚠ 可能已被 {refs} 处理/重复")
    if s.negative_labels:
        labels = ", ".join(s.negative_labels)
        s.facts.append(f"Carries non-actionable labels: {labels}.")
        s.flags.append(f"⚠ 负面标签: {labels}")
    if s.positive_labels:
        s.facts.append(f"Maintainer-friendly labels: {', '.join(s.positive_labels)}.")
    if s.stale_days is not None and s.stale_days >= _STALE_THRESHOLD_DAYS:
        s.facts.append(f"No activity for ~{s.stale_days} days (stale; maintainers may have moved on).")
        s.flags.append(f"⚠ 已 {s.stale_days} 天无活动")
    if s.comment_count:
        s.facts.append(f"Has {s.comment_count} comment(s).")


def grounding_prompt_block(signals: RepoSignals) -> str:
    """Render signals as a 'Repo facts' block for the scoring prompt."""
    if not signals.facts:
        return "Repo facts: none detected."
    lines = "\n".join(f"- {fact}" for fact in signals.facts)
    return (
        "Repo facts (verified from GitHub metadata — weigh these heavily for "
        "actionability):\n" + lines
    )


def apply_guardrails(result: dict, signals: RepoSignals) -> dict:
    """Deterministically clamp the LLM result for the strongest negative signals.

    These override the LLM so a text-only 'Do now' cannot survive when the issue
    is already claimed, resolved, or explicitly non-actionable.
    """
    if not signals.has_guardrail:
        return result

    result = dict(result)
    result["actionability"] = "low"
    if signals.negative_labels:
        result["fit"] = "low"
        result["score"] = min(float(result.get("score", 0.0) or 0.0), 0.3)
    else:
        result["score"] = min(float(result.get("score", 0.0) or 0.0), 0.39)

    prefix = " ".join(signals.flags)
    reason = str(result.get("reason", "") or "").strip()
    result["reason"] = f"{prefix} · {reason}" if reason else prefix
    return result
