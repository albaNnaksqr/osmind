from __future__ import annotations

import pytest

from osmind.github.models import GHPR, PRFile
from osmind.packs.opener import open_path
from osmind.services.library import PackLibrary


def _pr(*, title: str = "Add Learning Pack Writer!", updated_at: str = "2026-05-15T01:02:03+00:00") -> GHPR:
    return GHPR(
        number=42,
        title=title,
        body="Stores generated packs in the notes vault.",
        url="https://github.com/openai/osmind/pull/42",
        repo="openai/osmind",
        updated_at=updated_at,
        files=[
            PRFile(
                filename="osmind/services/library.py",
                patch="@@ -0,0 +1 @@\n+service layer",
                status="added",
                additions=1,
                deletions=0,
            )
        ],
    )


def test_write_pr_pack_creates_markdown_and_cache_record(tmp_path):
    notes_vault = tmp_path / "notes"
    cache_path = tmp_path / "cache" / "osmind.db"
    pr = _pr()

    library = PackLibrary(notes_vault, cache_path)

    path = library.write_pr_pack(pr)

    assert path == notes_vault / "osmind" / "openai_osmind" / "pr-42-add-learning-pack-writer.md"
    assert path.exists()
    markdown = path.read_text(encoding="utf-8")
    assert "# PR #42: Add Learning Pack Writer!" in markdown
    assert "repo: openai/osmind" in markdown
    assert "source_updated_at: '2026-05-15T01:02:03+00:00'" in markdown
    assert "Stores generated packs in the notes vault." in markdown

    packs = library.list_packs()
    assert packs == [
        {
            "repo": "openai/osmind",
            "source_type": "pr",
            "number": 42,
            "path": str(path),
            "status": "unread",
            "confidence": "unknown",
            "source_updated_at": "2026-05-15T01:02:03+00:00",
            "generated_at": packs[0]["generated_at"],
            "stale": 0,
        }
    ]


def test_write_pr_pack_preserves_notes_and_user_status_frontmatter(tmp_path):
    notes_vault = tmp_path / "notes"
    cache_path = tmp_path / "cache" / "osmind.db"
    library = PackLibrary(notes_vault, cache_path)
    path = library.write_pr_pack(_pr())
    path.write_text(
        """---
type: osmind-learning-pack
source_type: pr
repo: openai/osmind
number: 42
title: Add Learning Pack Writer!
url: https://github.com/openai/osmind/pull/42
status: reviewed
confidence: high
generated_at: '2026-05-15'
source_updated_at: '2026-05-15T01:02:03+00:00'
modules:
- osmind
tags:
- osmind
---

# PR #42: Add Learning Pack Writer!

## Why This Is Worth Reading

Old generated content.

## Notes

Keep this manual note.

## Follow-up

Keep everything after notes too.
""",
        encoding="utf-8",
    )

    library.write_pr_pack(_pr(updated_at="2026-05-16T01:02:03+00:00"))

    markdown = path.read_text(encoding="utf-8")
    assert "status: reviewed" in markdown
    assert "confidence: high" in markdown
    assert "Old generated content." not in markdown
    assert "Stores generated packs in the notes vault." in markdown
    assert "## Notes\n\nKeep this manual note.\n\n## Follow-up\n\nKeep everything after notes too." in markdown


def test_write_pr_pack_replace_failure_preserves_existing_file_and_cache(tmp_path, monkeypatch):
    notes_vault = tmp_path / "notes"
    cache_path = tmp_path / "cache" / "osmind.db"
    library = PackLibrary(notes_vault, cache_path)
    path = library.write_pr_pack(_pr())
    original_markdown = path.read_text(encoding="utf-8")
    original_cache = library.list_packs()

    def fail_replace(temp_path, destination):
        raise OSError("replace failed")

    monkeypatch.setattr("osmind.services.library._replace_file", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        library.write_pr_pack(_pr(updated_at="2026-05-16T01:02:03+00:00"))

    assert path.read_text(encoding="utf-8") == original_markdown
    assert library.list_packs() == original_cache
    assert not list(path.parent.glob(".*.tmp"))


def test_open_path_splits_command_args(monkeypatch, tmp_path):
    calls = []
    path = tmp_path / "pack.md"

    monkeypatch.setattr("subprocess.run", lambda args, check: calls.append((args, check)))

    open_path(path, command="code --wait")

    assert calls == [(["code", "--wait", str(path)], False)]


def test_open_path_ignores_empty_editor(monkeypatch, tmp_path):
    calls = []
    path = tmp_path / "pack.md"

    monkeypatch.setenv("EDITOR", "")
    monkeypatch.setattr("subprocess.run", lambda args, check: calls.append((args, check)))

    open_path(path)

    assert calls == [(["xdg-open", str(path)], False)]
