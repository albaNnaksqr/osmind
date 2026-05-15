from __future__ import annotations

import os
import re
import tempfile
import unicodedata
from pathlib import Path

import yaml

from osmind.cache.store import CacheStore
from osmind.github.models import GHPR
from osmind.packs.generator import PackGenerator
from osmind.packs.renderer import render_pack


MAX_SLUG_LENGTH = 80


class PackLibrary:
    def __init__(self, notes_vault: Path, cache_path: Path):
        self.notes_vault = notes_vault
        self.cache = CacheStore(cache_path)
        self.generator = PackGenerator()

    def write_pr_pack(self, pr: GHPR) -> Path:
        pack = self.generator.from_pr(pr)
        path = self._existing_pr_pack_path(pr) or self._pr_pack_path(pr)
        if path.exists():
            existing_markdown = path.read_text(encoding="utf-8")
            _preserve_status_and_confidence(pack, existing_markdown)
        else:
            existing_markdown = ""
        markdown = _preserve_notes_section(render_pack(pack), existing_markdown)
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(path, markdown)
        self.cache.upsert_pack(
            pr.repo,
            "pr",
            pr.number,
            path,
            pack.status,
            pack.confidence,
            pack.source.updated_at,
        )
        return path

    def list_packs(self) -> list[dict]:
        return self.cache.list_packs()

    def _pr_pack_path(self, pr: GHPR) -> Path:
        repo_dir = pr.repo.replace("/", "_")
        filename = f"pr-{pr.number}-{_slug(pr.title)}.md"
        return self.notes_vault / "osmind" / repo_dir / filename

    def _existing_pr_pack_path(self, pr: GHPR) -> Path | None:
        cached_pack = self.cache.get_pack(pr.repo, "pr", pr.number)
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


def _preserve_status_and_confidence(pack, existing_markdown: str) -> None:
    frontmatter = _read_frontmatter(existing_markdown)
    status = frontmatter.get("status")
    confidence = frontmatter.get("confidence")
    if status:
        pack.status = str(status)
    if confidence:
        pack.confidence = str(confidence)


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
    match = re.search(r"(?m)^## Notes\s*$", markdown)
    if match is None:
        return None
    return markdown[match.start() :]


def _section_before_notes(markdown: str) -> str | None:
    match = re.search(r"(?m)^## Notes\s*$", markdown)
    if match is None:
        return None
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
