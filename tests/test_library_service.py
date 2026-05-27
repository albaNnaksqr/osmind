from __future__ import annotations

from datetime import date

import pytest

from osmind.engine.issue_brief import IssueBrief
from osmind.github.models import GHIssue, GHPR, PRFile
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


def _issue(*, title: str = "Tokenizer memory leak", updated_at: str = "2026-05-15T01:02:03+00:00") -> GHIssue:
    return GHIssue(
        number=7,
        title=title,
        body="Memory grows on long sequences.",
        labels=["bug"],
        url="https://github.com/openai/osmind/issues/7",
        repo="openai/osmind",
        state="open",
        updated_at=updated_at,
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
            "decision": "undecided",
            "decision_resource_hash": "",
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
decision: continue
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
    assert "decision: continue" in markdown
    assert "confidence: high" in markdown
    assert "Old generated content." not in markdown
    assert "Stores generated packs in the notes vault." in markdown
    assert "## Notes\n\nKeep this manual note.\n\n## Follow-up\n\nKeep everything after notes too." in markdown


def test_write_pr_pack_uses_cached_path_when_pr_title_changes(tmp_path):
    notes_vault = tmp_path / "notes"
    cache_path = tmp_path / "cache" / "osmind.db"
    library = PackLibrary(notes_vault, cache_path)
    original_path = library.write_pr_pack(_pr(title="Original Title"))
    original_path.write_text(
        """---
type: osmind-learning-pack
source_type: pr
repo: openai/osmind
number: 42
title: Original Title
url: https://github.com/openai/osmind/pull/42
status: reviewed
decision: defer
confidence: high
generated_at: '2026-05-15'
source_updated_at: '2026-05-15T01:02:03+00:00'
modules:
- osmind
tags:
- osmind
---

# PR #42: Original Title

## Why This Is Worth Reading

Old generated content.

## Notes

Retitle should not move this note.
""",
        encoding="utf-8",
    )

    returned_path = library.write_pr_pack(_pr(title="Retitled Pack", updated_at="2026-05-16T01:02:03+00:00"))

    assert returned_path == original_path
    assert not (notes_vault / "osmind" / "openai_osmind" / "pr-42-retitled-pack.md").exists()
    markdown = original_path.read_text(encoding="utf-8")
    assert "# PR #42: Retitled Pack" in markdown
    assert "title: Retitled Pack" in markdown
    assert "status: reviewed" in markdown
    assert "decision: defer" in markdown
    assert "confidence: high" in markdown
    assert "Old generated content." not in markdown
    assert "## Notes\n\nRetitle should not move this note." in markdown
    packs = library.list_packs()
    assert packs[0]["path"] == str(original_path)
    assert packs[0]["status"] == "reviewed"
    assert packs[0]["decision"] == "defer"
    assert packs[0]["confidence"] == "high"


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


def test_write_issue_pack_creates_markdown_and_cache_record(tmp_path):
    notes_vault = tmp_path / "notes"
    cache_path = tmp_path / "cache" / "osmind.db"
    library = PackLibrary(notes_vault, cache_path)

    path = library.write_issue_pack(_issue())

    assert path == notes_vault / "osmind" / "openai_osmind" / "issue-7-tokenizer-memory-leak.md"
    assert path.exists()
    markdown = path.read_text(encoding="utf-8")
    assert "# Issue #7: Tokenizer memory leak" in markdown
    assert "source_type: issue" in markdown
    assert "Memory grows on long sequences." in markdown

    packs = library.list_packs()
    assert packs[0]["repo"] == "openai/osmind"
    assert packs[0]["source_type"] == "issue"
    assert packs[0]["number"] == 7
    assert packs[0]["path"] == str(path)
    assert packs[0]["status"] == "unread"
    assert packs[0]["decision"] == "undecided"
    assert packs[0]["confidence"] == "unknown"


def test_write_issue_pack_includes_configured_resources_in_recommendation_snapshot(tmp_path):
    notes_vault = tmp_path / "notes"
    cache_path = tmp_path / "cache" / "osmind.db"
    issue = _issue()
    issue.resource_fit = "blocked"
    issue.reason = "主题匹配，但当前 GPU 资源不足以复现"
    library = PackLibrary(notes_vault, cache_path, resources={"gpus": "4x RTX 4090"})

    path = library.write_issue_pack(issue)

    markdown = path.read_text(encoding="utf-8")
    assert "## Recommendation Snapshot" in markdown
    assert "| Resource Fit | Blocked |" in markdown
    assert "| Configured Resources | gpus: 4x RTX 4090 |" in markdown


def test_write_issue_pack_can_include_issue_brief(tmp_path):
    notes_vault = tmp_path / "notes"
    cache_path = tmp_path / "cache" / "osmind.db"
    brief = IssueBrief(
        one_liner="tokenizer cache 泄漏 issue",
        problem_summary="Tokenizer cache may grow due to missing eviction paths.",
        background=["Tokenizer cache path: src/tokenizer/cache.py.", "模型推理路径和 tokenizer cache 初始化。"],
        matched_interests=["SGLang"],
        matched_skills=["Python"],
        resource_assessment="难度中等，已知可复现。",
        evidence=["Tokenizer cache 相关代码在 `src/tokenizer/cache.py`。", "Issue 可能缺少完整复现脚本"],
        risks=["Issue 可能缺少完整复现脚本", "当前 repo 可能缺少 tokenizer 重现数据。"],
        first_steps=["阅读并搜索 tokenizer cache 相关实现", "先执行复现脚本"],
        validation_path=["复现测试先失败", "如何复现该问题"],
        agent_prompt="请在 o/r 中分析 tokenizer cache 泄漏 issue",
    )
    issue = GHIssue(
        number=7,
        title="tokenizer cache 泄漏 issue",
        body="Memory grows on long prompt batches.",
        labels=["bug", "tokenizer"],
        url="https://github.com/o/r/issues/7",
        repo="o/r",
        state="open",
        reason="Interest: SGLang\nSkill: Python",
    )
    library = PackLibrary(notes_vault, cache_path)

    path = library.write_issue_pack(issue, brief=brief)

    markdown = path.read_text(encoding="utf-8")
    rec_snap = markdown.index("## Recommendation Snapshot")
    issue_brief = markdown.index("## Issue Brief")
    fit = markdown.index("## Why It May Fit You")
    risks = markdown.index("## Risks And Missing Evidence")
    first_30 = markdown.index("## First 30 Minutes")
    validation = markdown.index("## Validation Path")
    prompt = markdown.index("## Agent Prompt")
    continue_log = markdown.index("## Continue Or Stop Criteria")

    assert "## Recommendation Snapshot" in markdown
    assert rec_snap < issue_brief < fit < risks < first_30 < validation < prompt < continue_log
    assert "## Issue Brief" in markdown
    issue_brief_section = markdown[issue_brief:fit]
    assert issue_brief_section.index("### One-Liner") < issue_brief_section.index("### Problem Summary")
    assert issue_brief_section.index("### Problem Summary") < issue_brief_section.index("### Background")
    assert "### One-Liner" in issue_brief_section
    assert "Tokenizer cache may grow due to missing eviction paths." in issue_brief_section
    assert "### Problem Summary" in issue_brief_section
    assert "### Background" in issue_brief_section
    assert "- Tokenizer cache path: src/tokenizer/cache.py." in issue_brief_section

    why_section = markdown[fit:risks]
    assert "### Matched Interests" in why_section
    assert "### Matched Skills" in why_section
    assert "### Resource Assessment" in why_section
    assert "### Evidence" in why_section
    assert "Interest: SGLang" in why_section
    assert "Skill: Python" in why_section

    risks_section = markdown[risks:first_30]
    assert "### Risks" in risks_section
    assert "## Risks And Missing Evidence" in markdown
    assert risks_section.count("Issue 可能缺少完整复现脚本") == 1
    assert "Issue 可能缺少完整复现脚本" in markdown
    assert "## First 30 Minutes" in markdown
    assert "阅读并搜索 tokenizer cache 相关实现" in markdown
    assert "## Validation Path" in markdown
    assert "复现测试先失败" in markdown
    assert "## Agent Prompt" in markdown
    assert "请在 o/r 中分析 tokenizer cache 泄漏 issue" in markdown
    assert markdown.count("## Issue Brief") == 1


def test_write_issue_pack_reuses_cached_path_and_preserves_user_content_on_retitle(tmp_path):
    notes_vault = tmp_path / "notes"
    cache_path = tmp_path / "cache" / "osmind.db"
    library = PackLibrary(notes_vault, cache_path)
    original_path = library.write_issue_pack(_issue(title="Original Issue"))
    original_path.write_text(
        """---
type: osmind-learning-pack
source_type: issue
repo: openai/osmind
number: 7
title: Original Issue
url: https://github.com/openai/osmind/issues/7
status: reviewed
decision: discard
confidence: high
generated_at: '2026-05-15'
source_updated_at: '2026-05-15T01:02:03+00:00'
modules: []
tags:
- osmind
---

# Issue #7: Original Issue

## Why This May Fit You

Old generated content.

## Notes

Keep this issue note.
""",
        encoding="utf-8",
    )

    returned_path = library.write_issue_pack(_issue(title="Retitled Issue", updated_at="2026-05-16T01:02:03+00:00"))

    assert returned_path == original_path
    assert not (notes_vault / "osmind" / "openai_osmind" / "issue-7-retitled-issue.md").exists()
    markdown = original_path.read_text(encoding="utf-8")
    assert "# Issue #7: Retitled Issue" in markdown
    assert "title: Retitled Issue" in markdown
    assert "status: reviewed" in markdown
    assert "decision: discard" in markdown
    assert "confidence: high" in markdown
    assert "Old generated content." not in markdown
    assert "## Notes\n\nKeep this issue note." in markdown
    assert library.list_packs()[0]["path"] == str(original_path)


def test_write_issue_pack_preserves_only_final_notes_section_when_body_mentions_notes(tmp_path):
    notes_vault = tmp_path / "notes"
    cache_path = tmp_path / "cache" / "osmind.db"
    library = PackLibrary(notes_vault, cache_path)
    issue = _issue(title="Original Issue")
    issue.body = "Original body\n\n## Notes\n\nThis heading came from upstream."
    path = library.write_issue_pack(issue)
    path.write_text(
        path.read_text(encoding="utf-8")
        + "\nManual user note.\n\n## Follow-up\n\nKeep this user section.\n",
        encoding="utf-8",
    )

    retitled = _issue(title="Retitled Issue", updated_at="2026-05-16T01:02:03+00:00")
    retitled.body = "New body without the old generated content."
    library.write_issue_pack(retitled)

    markdown = path.read_text(encoding="utf-8")

    assert "# Issue #7: Retitled Issue" in markdown
    assert "Original body" not in markdown
    assert "This heading came from upstream." not in markdown
    assert "New body without the old generated content." in markdown
    assert "## Notes\n\nManual user note.\n\n## Follow-up\n\nKeep this user section." in markdown
    assert markdown.count("## Missing Context") == 1


def test_set_pack_decision_updates_markdown_frontmatter_log_and_cache(tmp_path):
    notes_vault = tmp_path / "notes"
    cache_path = tmp_path / "cache" / "osmind.db"
    library = PackLibrary(notes_vault, cache_path)
    path = library.write_issue_pack(_issue())

    returned_path = library.set_pack_decision("openai/osmind", "issue", 7, "continue")

    markdown = path.read_text(encoding="utf-8")
    packs = library.list_packs()
    assert returned_path == path
    assert "decision: continue" in markdown
    assert "## Decision Log" in markdown
    assert f"- {date.today()}: decision=continue" in markdown
    assert packs[0]["decision"] == "continue"


def test_set_pack_decision_rejects_unknown_decision_without_changing_file(tmp_path):
    notes_vault = tmp_path / "notes"
    cache_path = tmp_path / "cache" / "osmind.db"
    library = PackLibrary(notes_vault, cache_path)
    path = library.write_issue_pack(_issue())
    original_markdown = path.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported pack decision"):
        library.set_pack_decision("openai/osmind", "issue", 7, "maybe")

    assert path.read_text(encoding="utf-8") == original_markdown
    assert library.list_packs()[0]["decision"] == "undecided"


def test_open_path_splits_command_args(monkeypatch, tmp_path):
    calls = []
    path = tmp_path / "pack.md"

    monkeypatch.setattr("subprocess.run", lambda args, check: calls.append((args, check)))

    open_path(path, command="code --wait")

    assert calls == [(["code", "--wait", str(path)], True)]


def test_open_path_uses_terminal_pager_when_editor_is_unset(monkeypatch, tmp_path):
    calls = []
    path = tmp_path / "pack.md"

    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setenv("EDITOR", "")
    monkeypatch.setattr("shutil.which", lambda command: "/usr/bin/less" if command == "less" else None)
    monkeypatch.setattr("subprocess.run", lambda args, check: calls.append((args, check)))

    open_path(path)

    assert calls == [(["less", str(path)], True)]
