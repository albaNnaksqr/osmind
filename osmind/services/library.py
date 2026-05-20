from __future__ import annotations

from datetime import date
import os
import re
import tempfile
import unicodedata
from pathlib import Path

import yaml

from osmind.cache.store import CacheStore
from osmind.github.models import GHIssue, GHPR
from osmind.packs.generator import PackGenerator
from osmind.packs.models import VALID_PACK_DECISIONS
from osmind.packs.renderer import render_pack


MAX_SLUG_LENGTH = 80


class PackLibrary:
    def __init__(self, notes_vault: Path, cache_path: Path, resources: dict | None = None):
        self.notes_vault = notes_vault
        self.cache = CacheStore(cache_path)
        self.generator = PackGenerator()
        self.resources = resources or {}

    def write_pr_pack(self, pr: GHPR) -> Path:
        pack = self.generator.from_pr(pr)
        path = self._existing_pack_path(pr.repo, "pr", pr.number) or self._pr_pack_path(pr)
        return self._write_pack(path, pr.repo, "pr", pr.number, pack)

    def write_issue_pack(self, issue: GHIssue) -> Path:
        pack = self.generator.from_issue(issue, resources=self.resources)
        path = self._existing_pack_path(issue.repo, "issue", issue.number) or self._issue_pack_path(issue)
        return self._write_pack(path, issue.repo, "issue", issue.number, pack)

    def _write_pack(
        self,
        path: Path,
        repo: str,
        source_type: str,
        number: int,
        pack,
    ) -> Path:
        if path.exists():
            existing_markdown = path.read_text(encoding="utf-8")
            _preserve_user_frontmatter(pack, existing_markdown)
        else:
            existing_markdown = ""
        markdown = _preserve_notes_section(render_pack(pack), existing_markdown)
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(path, markdown)
        self.cache.upsert_pack(
            repo,
            source_type,
            number,
            path,
            pack.status,
            pack.confidence,
            pack.source.updated_at,
            decision=pack.decision,
        )
        return path

    def list_packs(self) -> list[dict]:
        return self.cache.list_packs()

    def set_pack_decision(
        self,
        repo: str,
        source_type: str,
        number: int,
        decision: str,
        *,
        decision_resource_hash: str = "",
    ) -> Path:
        if decision not in VALID_PACK_DECISIONS:
            raise ValueError(f"Unsupported pack decision: {decision}")

        cached_pack = self.cache.get_pack(repo, source_type, number)
        if cached_pack is None:
            raise FileNotFoundError(f"No Contribution Packet cached for {repo} {source_type} #{number}")

        path = Path(cached_pack["path"])
        if not path.exists():
            raise FileNotFoundError(f"Contribution Packet file does not exist: {path}")

        markdown = path.read_text(encoding="utf-8")
        updated_markdown = _mark_decision(markdown, decision)
        _atomic_write_text(path, updated_markdown)
        if not self.cache.update_pack_decision(
            repo,
            source_type,
            number,
            decision,
            decision_resource_hash=decision_resource_hash,
        ):
            raise FileNotFoundError(f"No Contribution Packet cached for {repo} {source_type} #{number}")
        return path

    def _pr_pack_path(self, pr: GHPR) -> Path:
        repo_dir = pr.repo.replace("/", "_")
        filename = f"pr-{pr.number}-{_slug(pr.title)}.md"
        return self.notes_vault / "osmind" / repo_dir / filename

    def _issue_pack_path(self, issue: GHIssue) -> Path:
        repo_dir = issue.repo.replace("/", "_")
        filename = f"issue-{issue.number}-{_slug(issue.title)}.md"
        return self.notes_vault / "osmind" / repo_dir / filename

    def _existing_pack_path(self, repo: str, source_type: str, number: int) -> Path | None:
        cached_pack = self.cache.get_pack(repo, source_type, number)
        if cached_pack is None:
            return None

        cached_path = Path(cached_pack["path"])
        return cached_path if cached_path.exists() else None


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        return "untitled"
    return slug[:MAX_SLUG_LENGTH].rstrip("-") or "untitled"


def _preserve_user_frontmatter(pack, existing_markdown: str) -> None:
    frontmatter = _read_frontmatter(existing_markdown)
    status = frontmatter.get("status")
    decision = frontmatter.get("decision")
    confidence = frontmatter.get("confidence")
    if status:
        pack.status = str(status)
    if decision:
        pack.decision = str(decision)
    if confidence:
        pack.confidence = str(confidence)


def _mark_decision(markdown: str, decision: str) -> str:
    return _append_decision_log(_replace_frontmatter_field(markdown, "decision", decision), decision)


def _replace_frontmatter_field(markdown: str, field: str, value: str) -> str:
    lines = markdown.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise ValueError("Pack is missing YAML frontmatter")

    for index, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            raw_frontmatter = "".join(lines[1:index])
            loaded = yaml.safe_load(raw_frontmatter) or {}
            if not isinstance(loaded, dict):
                raise ValueError("Pack frontmatter must be a mapping")
            loaded[field] = value
            frontmatter = yaml.dump(loaded, allow_unicode=True, sort_keys=False).strip()
            body = "".join(lines[index + 1 :])
            return f"---\n{frontmatter}\n---\n{body}"
    raise ValueError("Pack is missing YAML frontmatter")


def _append_decision_log(markdown: str, decision: str) -> str:
    entry = f"- {date.today()}: decision={decision}"
    matches = list(re.finditer(r"(?m)^## Decision Log\s*$", markdown))
    if matches:
        match = matches[-1]
        next_heading = re.search(r"(?m)^##\s+", markdown[match.end() :])
        section_end = match.end() + next_heading.start() if next_heading else len(markdown)
        prefix = markdown[:section_end].rstrip()
        suffix = markdown[section_end:].lstrip("\n")
        if suffix:
            return f"{prefix}\n{entry}\n\n{suffix}"
        return f"{prefix}\n{entry}\n"

    section = f"## Decision Log\n\n{entry}\n"
    notes_match = re.search(r"(?m)^## Notes\s*$", markdown)
    if notes_match:
        prefix = markdown[: notes_match.start()].rstrip()
        suffix = markdown[notes_match.start() :].lstrip("\n")
        return f"{prefix}\n\n{section}\n{suffix}"
    return f"{markdown.rstrip()}\n\n{section}"


def _read_frontmatter(markdown: str) -> dict:
    lines = markdown.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}

    for index, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            try:
                loaded = yaml.safe_load("".join(lines[1:index])) or {}
            except yaml.YAMLError:
                return {}
            return loaded if isinstance(loaded, dict) else {}
    return {}


def _preserve_notes_section(generated_markdown: str, existing_markdown: str) -> str:
    existing_notes = _section_from_notes(existing_markdown)
    if existing_notes is None:
        return generated_markdown

    generated_prefix = _section_before_notes(generated_markdown)
    if generated_prefix is None:
        return generated_markdown

    return f"{generated_prefix.rstrip()}\n\n{existing_notes.rstrip()}\n"


def _section_from_notes(markdown: str) -> str | None:
    matches = list(re.finditer(r"(?m)^## Notes\s*$", markdown))
    if not matches:
        return None
    match = matches[-1]
    body = markdown[match.end() :].lstrip()
    return f"## Notes\n\n{body}"


def _section_before_notes(markdown: str) -> str | None:
    matches = list(re.finditer(r"(?m)^## Notes\s*$", markdown))
    if not matches:
        return None
    match = matches[-1]
    return markdown[: match.start()]


def _atomic_write_text(path: Path, text: str) -> None:
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(text)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        _replace_file(temp_path, path)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


def _replace_file(temp_path: Path, destination: Path) -> None:
    temp_path.replace(destination)
