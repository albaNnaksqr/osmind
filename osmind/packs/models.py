from __future__ import annotations

from dataclasses import dataclass, field


PackStatus = str
PackConfidence = str


@dataclass
class SourceRef:
    source_type: str
    repo: str
    number: int
    title: str
    url: str
    updated_at: str


@dataclass
class PackSection:
    title: str
    body: str


@dataclass
class LearningPack:
    source: SourceRef
    status: PackStatus = "unread"
    confidence: PackConfidence = "unknown"
    modules: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=lambda: ["osmind", "open-source"])
    sections: list[PackSection] = field(default_factory=list)
