from __future__ import annotations
from dataclasses import dataclass, field


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


@dataclass
class PRFile:
    filename: str
    patch: str          # raw unified diff


@dataclass
class GHPR:
    number: int
    title: str
    body: str
    url: str
    repo: str
    files: list[PRFile] = field(default_factory=list)
    score: float = 0.0
