import re

import yaml

from osmind.packs.models import LearningPack, PackSection, SourceRef
from osmind.packs.renderer import render_pack


def _frontmatter(rendered: str) -> dict:
    match = re.match(r"---\n(.*?)\n---\n", rendered, re.DOTALL)
    assert match is not None
    return yaml.safe_load(match.group(1))


def test_render_pack_includes_frontmatter_and_sections():
    pack = LearningPack(
        source=SourceRef(
            source_type="pr",
            repo="o/r",
            number=7,
            title="Refactor runner",
            url="https://github.com/o/r/pull/7",
            updated_at="2026-05-15T01:02:03+00:00",
        ),
        status="unread",
        confidence="unknown",
        modules=["src"],
        tags=["osmind", "open-source"],
        sections=[
            PackSection("Why This Is Worth Reading", "Useful design change."),
            PackSection("Notes", ""),
        ],
    )

    rendered = render_pack(pack)
    frontmatter = _frontmatter(rendered)

    assert frontmatter["type"] == "osmind-learning-pack"
    assert frontmatter["source_type"] == "pr"
    assert frontmatter["repo"] == "o/r"
    assert frontmatter["number"] == 7
    assert frontmatter["title"] == "Refactor runner"
    assert frontmatter["url"] == "https://github.com/o/r/pull/7"
    assert frontmatter["status"] == "unread"
    assert frontmatter["confidence"] == "unknown"
    assert frontmatter["source_updated_at"] == "2026-05-15T01:02:03+00:00"
    assert frontmatter["modules"] == ["src"]
    assert frontmatter["tags"] == ["osmind", "open-source"]
    assert "generated_at" in frontmatter
    assert "# PR #7: Refactor runner" in rendered
    assert "## Why This Is Worth Reading\n\nUseful design change." in rendered
    assert "## Notes\n\n" in rendered


def test_render_pack_uses_issue_heading_and_default_tags():
    pack = LearningPack(
        source=SourceRef(
            source_type="issue",
            repo="o/r",
            number=42,
            title="Tokenizer leak",
            url="https://github.com/o/r/issues/42",
            updated_at="2026-05-15T04:05:06+00:00",
        ),
        sections=[PackSection("Context", "Memory grows under load.")],
    )

    rendered = render_pack(pack)
    frontmatter = _frontmatter(rendered)

    assert frontmatter["status"] == "unread"
    assert frontmatter["confidence"] == "unknown"
    assert frontmatter["modules"] == []
    assert frontmatter["tags"] == ["osmind", "open-source"]
    assert "# Issue #42: Tokenizer leak" in rendered
    assert "## Context\n\nMemory grows under load." in rendered
