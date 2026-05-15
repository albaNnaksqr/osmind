from __future__ import annotations

import re
import unicodedata
from pathlib import Path

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
        markdown = render_pack(pack)
        path = self._pr_pack_path(pr)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown, encoding="utf-8")
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


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        return "untitled"
    return slug[:MAX_SLUG_LENGTH].rstrip("-") or "untitled"
