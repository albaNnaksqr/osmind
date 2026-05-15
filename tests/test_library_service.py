from __future__ import annotations

from osmind.github.models import GHPR, PRFile
from osmind.services.library import PackLibrary


def test_write_pr_pack_creates_markdown_and_cache_record(tmp_path):
    notes_vault = tmp_path / "notes"
    cache_path = tmp_path / "cache" / "osmind.db"
    pr = GHPR(
        number=42,
        title="Add Learning Pack Writer!",
        body="Stores generated packs in the notes vault.",
        url="https://github.com/openai/osmind/pull/42",
        repo="openai/osmind",
        updated_at="2026-05-15T01:02:03+00:00",
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
