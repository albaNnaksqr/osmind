from __future__ import annotations

from osmind.github.models import GHIssue


def recommended_action(issue: GHIssue) -> str:
    resource_fit = _normalized(getattr(issue, "resource_fit", "unknown"))
    actionability = _normalized(getattr(issue, "actionability", "unknown"))
    priority = _normalized(getattr(issue, "priority", "unknown"))
    score = float(getattr(issue, "score", 0.0) or 0.0)

    if resource_fit in {"blocked", "risk"} or actionability == "low":
        return "Defer"
    if priority == "low" or (priority == "unknown" and 0 < score < 0.4):
        return "Skip"
    if priority == "high" or score >= 0.7:
        return "Do now"
    if priority == "medium" or score >= 0.4:
        return "Review"
    return "--"


def action_reason(issue: GHIssue) -> str:
    resource_fit = _normalized(getattr(issue, "resource_fit", "unknown"))
    actionability = _normalized(getattr(issue, "actionability", "unknown"))
    priority = _normalized(getattr(issue, "priority", "unknown"))
    fit = _normalized(getattr(issue, "fit", "unknown"))
    score = float(getattr(issue, "score", 0.0) or 0.0)

    if resource_fit == "blocked":
        return "resource blocked"
    if resource_fit == "risk":
        return "resource risk"
    if actionability == "low":
        return "low actionability"
    if priority == "high" or score >= 0.7:
        if fit == "high" and resource_fit == "ok":
            return "strong fit + resources OK"
        if fit == "high":
            return "strong fit"
        return "high score"
    if priority == "medium" or score >= 0.4:
        return "worth review"
    if priority == "low" or (0 < score < 0.4):
        return "low priority"
    return "not ranked yet"


def action_why(issue: GHIssue, *, limit: int = 96) -> str:
    prefix = action_reason(issue)
    reason = str(getattr(issue, "reason", "") or "").strip()
    if not reason:
        return prefix
    text = f"{prefix}: {reason}"
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def next_step_for_action(action: str) -> str:
    if action == "Do now":
        return "Generate a packet, then inspect the suggested code path before editing."
    if action == "Review":
        return "Open details and generate a packet only if the validation path is clear."
    if action == "Defer":
        return "Defer until the required environment is available."
    if action == "Skip":
        return "Discard unless new evidence makes it relevant."
    return "Update from GitHub or re-rank with the current profile."


def action_from_score(score: float) -> str:
    if score >= 0.7:
        return "Do now"
    if score >= 0.4:
        return "Review"
    if score > 0:
        return "Skip"
    return "--"


def _normalized(value: str) -> str:
    return str(value or "unknown").lower()
