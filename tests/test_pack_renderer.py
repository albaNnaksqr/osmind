import re

import yaml

from osmind.packs.models import LearningPack, PackSection, SourceRef
from osmind.packs.renderer import parse_pack_frontmatter, render_pack


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

    assert frontmatter["type"] == "osmind-contribution-packet"
    assert frontmatter["source_type"] == "pr"
    assert frontmatter["repo"] == "o/r"
    assert frontmatter["number"] == 7
    assert frontmatter["title"] == "Refactor runner"
    assert frontmatter["url"] == "https://github.com/o/r/pull/7"
    assert frontmatter["status"] == "unread"
    assert frontmatter["decision"] == "undecided"
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
    assert frontmatter["decision"] == "undecided"
    assert frontmatter["confidence"] == "unknown"
    assert frontmatter["modules"] == []
    assert frontmatter["tags"] == ["osmind", "open-source"]
    assert "# Issue #42: Tokenizer leak" in rendered
    assert "## Context\n\nMemory grows under load." in rendered


def test_parse_pack_frontmatter_reads_status_decision_and_confidence():
    text = """---
type: osmind-contribution-packet
source_type: pr
repo: o/r
number: 7
title: Refactor runner
url: https://github.com/o/r/pull/7
status: reading
decision: continue
confidence: low
generated_at: 2026-05-15
source_updated_at: u1
modules: []
tags: []
---

# PR #7: Refactor runner
"""

    data = parse_pack_frontmatter(text)

    assert data["status"] == "reading"
    assert data["decision"] == "continue"
    assert data["confidence"] == "low"


def test_parse_pack_frontmatter_accepts_legacy_learning_pack_type():
    text = """---
type: osmind-learning-pack
source_type: issue
repo: o/r
number: 42
title: Tokenizer leak
url: https://github.com/o/r/issues/42
status: reading
confidence: low
generated_at: 2026-05-15
source_updated_at: u1
modules: []
tags: []
---

# Issue #42: Tokenizer leak
"""

    data = parse_pack_frontmatter(text)

    assert data["type"] == "osmind-learning-pack"
    assert data["status"] == "reading"
