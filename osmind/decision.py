from __future__ import annotations

from dataclasses import dataclass

from osmind.github.models import GHIssue


@dataclass(frozen=True)
class DecisionExplanation:
    action: str
    why: str
    next_step: str
    priority: str
    fit: str
    resource_fit: str
    actionability: str
    resources: str
    evidence: list[str]


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
        return "Inspect"
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
        return "needs inspection"
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
    if action == "Inspect":
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
        return "Inspect"
    if score > 0:
        return "Skip"
    return "--"


def explain_issue_decision(issue: GHIssue, resources: dict | None = None) -> DecisionExplanation:
    action = recommended_action(issue)
    return DecisionExplanation(
        action=action,
        why=action_reason(issue),
        next_step=next_step_for_action(action),
        priority=_display_dimension(
            getattr(issue, "priority", "unknown"),
            kind="priority",
            score=getattr(issue, "score", 0.0),
        ),
        fit=_display_dimension(getattr(issue, "fit", "unknown")),
        resource_fit=_display_dimension(getattr(issue, "resource_fit", "unknown"), kind="resource"),
        actionability=_display_dimension(getattr(issue, "actionability", "unknown")),
        resources=_format_resources(resources or {}),
        evidence=_decision_evidence(issue),
    )


def format_decision_panel(issue: GHIssue, resources: dict | None = None) -> str:
    explanation = explain_issue_decision(issue, resources)
    evidence = "\n".join(f"- {item}" for item in explanation.evidence)
    return "\n".join(
        [
            "[bold]Recommendation[/bold]",
            f"Action: {explanation.action}",
            f"Why: {explanation.why}",
            f"Next Step: {explanation.next_step}",
            "",
            "[bold]Decision Factors[/bold]",
            f"Priority: {explanation.priority}",
            f"Fit: {explanation.fit}",
            f"Resource Fit: {explanation.resource_fit}",
            f"Actionability: {explanation.actionability}",
            f"Configured Resources: {explanation.resources}",
            "",
            "[bold]Evidence[/bold]",
            evidence,
        ]
    )


def format_decision_markdown(issue: GHIssue, resources: dict | None = None) -> str:
    explanation = explain_issue_decision(issue, resources)
    rows = [
        ("Action", explanation.action),
        ("Why", explanation.why),
        ("Next Step", explanation.next_step),
        ("Priority", explanation.priority),
        ("Fit", explanation.fit),
        ("Resource Fit", explanation.resource_fit),
        ("Actionability", explanation.actionability),
        ("Configured Resources", explanation.resources),
    ]
    table = ["| Factor | Value |", "| --- | --- |"]
    table.extend(f"| {_markdown_cell(label)} | {_markdown_cell(value)} |" for label, value in rows)
    evidence = "\n".join(f"- {item}" for item in explanation.evidence)
    return "\n".join([*table, "", "### Evidence", evidence])


def _decision_evidence(issue: GHIssue) -> list[str]:
    evidence: list[str] = []
    reason = str(getattr(issue, "reason", "") or "").strip()
    if reason:
        evidence.append(f"LLM: {reason}")
    else:
        evidence.append("LLM: no generated recommendation reason yet.")

    grounding = getattr(issue, "grounding", []) or []
    for flag in grounding:
        evidence.append(f"Repo: {flag}")

    labels = ", ".join(getattr(issue, "labels", []) or [])
    if labels:
        evidence.append(f"Labels: {labels}")
    else:
        evidence.append("Labels: none")

    body = str(getattr(issue, "body", "") or "").lower()
    if any(word in body for word in ("reproduce", "repro", "steps", "error", "traceback", "stack", "test")):
        evidence.append("Source: issue text mentions reproduction, error, or test clues.")
    else:
        evidence.append("Source: no reproduction, error, or test clues detected in the issue text.")
    return evidence


def _format_resources(resources: dict) -> str:
    if not resources:
        return "unspecified"
    return ", ".join(f"{key}: {value}" for key, value in resources.items())


def _display_dimension(value: str, *, kind: str = "level", score: float = 0.0) -> str:
    normalized = _normalized(value)
    if kind == "priority" and normalized == "unknown":
        if score >= 0.7:
            normalized = "high"
        elif score >= 0.4:
            normalized = "medium"
    labels = {
        "high": "High",
        "medium": "Medium",
        "low": "Low",
        "ok": "OK",
        "risk": "Risk",
        "blocked": "Blocked",
        "unknown": "--",
    }
    return labels.get(normalized, "--")


def _markdown_cell(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _normalized(value: str) -> str:
    return str(value or "unknown").lower()
