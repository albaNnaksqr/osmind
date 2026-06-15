from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class GHComment:
    author: str
    body: str
    url: str
    created_at: str


@dataclass
class GHIssue:
    number: int
    title: str
    body: str
    labels: list[str]
    url: str
    repo: str          # "owner/name"
    state: str         # "open" | "closed"
    score: float = 0.0  # filled by ranker
    reason: str = ""
    updated_at: str = ""
    comments: list[GHComment] = field(default_factory=list)
    priority: str = "unknown"
    fit: str = "unknown"
    resource_fit: str = "unknown"
    actionability: str = "unknown"
    assignees: list[str] = field(default_factory=list)
    comment_count: int = 0
    grounding: list[str] = field(default_factory=list)  # repo-verified flags


@dataclass
class IssueSignals:
    """Objective, contribution-relevant facts fetched live at report time."""
    number: int
    labels: list[str] = field(default_factory=list)
    assignees: list[str] = field(default_factory=list)
    comment_count: int = 0
    participant_count: int = 0
    linked_open_prs: list[int] = field(default_factory=list)
    updated_at: str = ""

    @property
    def has_open_pr(self) -> bool:
        return bool(self.linked_open_prs)

    @property
    def is_claimed(self) -> bool:
        return bool(self.assignees) or self.has_open_pr


@dataclass
class PRFile:
    filename: str
    patch: str          # raw unified diff
    status: str = ""
    additions: int = 0
    deletions: int = 0


@dataclass
class GHPR:
    number: int
    title: str
    body: str
    url: str
    repo: str
    files: list[PRFile] = field(default_factory=list)
    score: float = 0.0
    updated_at: str = ""
