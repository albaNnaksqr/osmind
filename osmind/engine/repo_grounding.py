from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from osmind.github.models import GHIssue


MAX_FILE_BYTES = 350_000
MAX_TERMS = 12
MAX_HITS = 24

SKIP_DIRS = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "target",
}

SEARCH_EXTENSIONS = {
    ".c",
    ".cc",
    ".cfg",
    ".cpp",
    ".cu",
    ".cuh",
    ".go",
    ".h",
    ".hpp",
    ".ini",
    ".java",
    ".js",
    ".json",
    ".md",
    ".py",
    ".rs",
    ".rst",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}

STOP_WORDS = {
    "about",
    "after",
    "against",
    "before",
    "between",
    "bug",
    "call",
    "cannot",
    "code",
    "describe",
    "does",
    "empty",
    "error",
    "expected",
    "fails",
    "from",
    "generate",
    "issue",
    "list",
    "mode",
    "openai",
    "parser",
    "passes",
    "returns",
    "should",
    "the",
    "this",
    "tool",
    "using",
    "when",
    "with",
}


@dataclass(frozen=True)
class RepoHit:
    term: str
    path: str
    line: int
    text: str
    kind: str


@dataclass
class GroundingReport:
    repo: str
    checkout_path: Path | None
    terms: list[str] = field(default_factory=list)
    hits: list[RepoHit] = field(default_factory=list)
    source_files: list[str] = field(default_factory=list)
    test_files: list[str] = field(default_factory=list)
    doc_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def has_hits(self) -> bool:
        return bool(self.hits)


def ground_issue_checkout(issue: GHIssue, checkout_path: Path | str | None) -> GroundingReport:
    """Search a local checkout for concrete issue terms.

    This is deliberately a scout, not an agent: it does not modify files, run tests,
    or try to understand the whole project. It only produces low-cost evidence for
    the packet / future MCP surfaces.
    """
    path = Path(checkout_path).expanduser() if checkout_path else None
    report = GroundingReport(repo=issue.repo, checkout_path=path)
    report.terms = extract_issue_terms(issue)

    if path is None:
        report.warnings.append("No local checkout path configured for this repo.")
        return report
    if not path.exists() or not path.is_dir():
        report.warnings.append(f"Local checkout path is missing or not a directory: {path}")
        return report
    if not report.terms:
        report.warnings.append("No high-signal terms could be extracted from the issue text.")
        return report

    report.hits = _search_checkout(path, report.terms)
    report.source_files = _unique(hit.path for hit in report.hits if hit.kind == "source")
    report.test_files = _unique(hit.path for hit in report.hits if hit.kind == "test")
    report.doc_files = _unique(hit.path for hit in report.hits if hit.kind == "doc")

    if not report.hits:
        report.warnings.append("No local source, test, or doc files matched the extracted issue terms.")
    return report


def extract_issue_terms(issue: GHIssue) -> list[str]:
    text = "\n".join(
        [
            issue.title or "",
            issue.body or "",
            " ".join(issue.labels or []),
            " ".join(str(getattr(comment, "body", "") or "") for comment in issue.comments[:3]),
        ]
    )
    candidates: list[str] = []

    candidates.extend(re.findall(r"`([^`\n]{3,80})`", text))
    candidates.extend(re.findall(r"\B--[a-zA-Z0-9][a-zA-Z0-9_-]{2,}", text))
    candidates.extend(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*(?:[./-][A-Za-z0-9_]+)+\b", text))
    candidates.extend(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{4,}\b", text))

    normalized: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        term = candidate.strip().strip("'\".,:;()[]{}")
        if not _is_useful_term(term):
            continue
        key = term.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(term)
        if len(normalized) >= MAX_TERMS:
            break
    return normalized


def render_repo_grounding(report: GroundingReport) -> str:
    lines: list[str] = []
    checkout = str(report.checkout_path) if report.checkout_path else "not configured"
    lines.extend(["### Scope", f"- Repo: `{report.repo}`", f"- Checkout: `{checkout}`"])

    if report.terms:
        lines.extend(["", "### Search Terms", *[f"- `{term}`" for term in report.terms]])

    if report.warnings:
        lines.extend(["", "### Warnings", *[f"- {warning}" for warning in report.warnings]])

    if report.hits:
        lines.extend(["", "### Highest-Signal Matches"])
        for hit in report.hits[:10]:
            lines.append(f"- `{hit.path}:{hit.line}` matched `{hit.term}` ({hit.kind}): {hit.text}")

    if report.test_files:
        lines.extend(["", "### Likely Test Entry", *[f"- `{path}`" for path in report.test_files[:5]]])
    elif report.has_hits:
        lines.extend(["", "### Likely Test Entry", "- No matched test file; search tests near the matched source paths."])

    lines.extend(["", "### Repo-Grounded First Steps", render_repo_first_steps(report)])
    lines.extend(["", "### Stop If", render_repo_stop_conditions(report)])
    return "\n".join(lines).rstrip()


def render_repo_first_steps(report: GroundingReport, fallback_steps: list[str] | None = None) -> str:
    if report.source_files or report.test_files:
        lines = []
        if report.source_files:
            lines.append(f"1. Read `{report.source_files[0]}` first; it has the strongest local match to the issue terms.")
        else:
            lines.append(f"1. Read `{report.hits[0].path}` first; it has the strongest local match to the issue terms.")
        if report.test_files:
            lines.append(f"2. Open `{report.test_files[0]}` and look for the smallest failing test you can add or adapt.")
        else:
            lines.append("2. Search for tests near the matched source file before touching implementation code.")
        lines.append("3. Use the matched line snippets to restate the suspected code path and validation check.")
        return "\n".join(lines)

    if fallback_steps:
        return "\n".join(f"{index}. {step}" for index, step in enumerate(fallback_steps, 1))

    return "\n".join(
        [
            "1. Restate the issue in one sentence.",
            "2. Search the repository manually for the highest-signal title terms.",
            "3. Do not implement until a likely file and validation path are identified.",
        ]
    )


def render_repo_file_targets(report: GroundingReport, fallback: str = "") -> str:
    lines: list[str] = []
    if report.source_files:
        lines.extend(["### Source", *[f"- `{path}`" for path in report.source_files[:8]]])
    if report.test_files:
        lines.extend(["", "### Tests", *[f"- `{path}`" for path in report.test_files[:8]]])
    if report.doc_files:
        lines.extend(["", "### Docs", *[f"- `{path}`" for path in report.doc_files[:5]]])
    if lines:
        return "\n".join(lines).strip()
    return fallback or "No repo-grounded file targets were identified."


def render_repo_stop_conditions(report: GroundingReport) -> str:
    lines = []
    if report.warnings:
        lines.append("Stop if the local checkout warning cannot be resolved quickly.")
    if not report.test_files:
        lines.append("Stop if no minimal validation path appears after checking nearby tests.")
    if not report.source_files:
        lines.append("Stop if the issue terms do not map to a concrete source module.")
    if not lines:
        lines.append("Stop if the matched files do not explain the reported behavior within 30 minutes.")
    return "\n".join(f"- {line}" for line in lines)


def _search_checkout(root: Path, terms: list[str]) -> list[RepoHit]:
    hits: list[RepoHit] = []
    hits_by_kind: dict[str, int] = {}
    lowered_terms = [(term, term.lower()) for term in terms]

    for path in _iter_searchable_files(root):
        rel = path.relative_to(root).as_posix()
        kind = _classify_path(rel)
        if hits_by_kind.get(kind, 0) >= MAX_HITS:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line_number, line in enumerate(text.splitlines(), 1):
            lowered_line = line.lower()
            for term, lowered_term in lowered_terms:
                if lowered_term not in lowered_line:
                    continue
                hits.append(RepoHit(term=term, path=rel, line=line_number, text=_clean_line(line), kind=kind))
                hits_by_kind[kind] = hits_by_kind.get(kind, 0) + 1
                break
            if hits_by_kind.get(kind, 0) >= MAX_HITS:
                break
    return _rank_hits(hits)


def _iter_searchable_files(root: Path):
    for path in root.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if not path.is_file() or path.suffix.lower() not in SEARCH_EXTENSIONS:
            continue
        try:
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        yield path


def _rank_hits(hits: list[RepoHit]) -> list[RepoHit]:
    kind_rank = {"source": 0, "test": 1, "doc": 2}
    return sorted(hits, key=lambda hit: (kind_rank.get(hit.kind, 3), hit.path, hit.line))


def _classify_path(path: str) -> str:
    lowered = path.lower()
    name = Path(path).name.lower()
    if "test" in name or "/test" in lowered or "tests/" in lowered:
        return "test"
    if lowered.endswith((".md", ".rst", ".txt")) or lowered.startswith("docs/") or "/docs/" in lowered:
        return "doc"
    return "source"


def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", line.strip())[:180]


def _is_useful_term(term: str) -> bool:
    if len(term) < 3 or len(term) > 80:
        return False
    lowered = term.lower()
    if lowered in STOP_WORDS:
        return False
    if lowered.startswith(("http://", "https://")):
        return False
    if lowered.isdigit():
        return False
    return True


def _unique(values) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
