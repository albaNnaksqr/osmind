# Learning Pack Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fragile in-TUI learning chat with cached GitHub analysis and durable Markdown Learning Packs for PRs and issues.

**Architecture:** Add a service layer behind the Textual UI: SQLite cache for GitHub item freshness and pack metadata, pack models/renderers for Markdown output, and generator classes for PR/Issue pack content. Keep the TUI as a thin control console that refreshes, generates, opens, and lists packs.

**Tech Stack:** Python 3.11, Textual, PyGithub, OpenAI-compatible LLM client, PyYAML, SQLite from the Python standard library, pytest.

---

## File Structure

Create these focused modules:

- `osmind/cache/__init__.py`: package marker.
- `osmind/cache/store.py`: SQLite schema, item freshness, analysis metadata, pack metadata.
- `osmind/packs/__init__.py`: package marker.
- `osmind/packs/models.py`: dataclasses for source refs, pack status, pack sections, generated packs.
- `osmind/packs/renderer.py`: Markdown and YAML frontmatter rendering.
- `osmind/packs/opener.py`: open generated pack files through a configured editor or OS opener.
- `osmind/packs/generator.py`: PR and issue Learning Pack generation using GitHub models and optional LLM.
- `osmind/services/__init__.py`: package marker.
- `osmind/services/library.py`: orchestration API used by TUI screens.
- `osmind/tui/screens/packs.py`: new Packs screen for generated pack list and open/regenerate actions.

Modify these existing modules:

- `osmind/github/models.py`: add metadata fields needed for cache staleness.
- `osmind/github/client.py`: populate item `updated_at`, issue comments when available, and PR file hashes.
- `osmind/tui/app.py`: replace Learn tab with Packs tab and wire app-level services.
- `osmind/tui/screens/discover.py`: use service API and cached status instead of embedding GitHub/LLM work directly.
- `osmind/tui/screens/review.py`: read generated pack metadata and unanswered questions from pack files.
- `pyproject.toml`: add no runtime dependency unless tests reveal a need.

Add tests:

- `tests/test_cache_store.py`
- `tests/test_pack_renderer.py`
- `tests/test_pack_generator.py`
- `tests/test_library_service.py`
- Update existing `tests/test_github_client.py`, `tests/test_tui.py`, and fixture files as needed.

## Task 1: Add GitHub Metadata Fields

**Files:**
- Modify: `osmind/github/models.py`
- Modify: `osmind/github/client.py`
- Test: `tests/test_github_client.py`

- [ ] **Step 1: Write failing model/client tests**

Add tests that assert fetched models carry freshness metadata. Use mocks instead of live GitHub.

```python
from datetime import datetime, timezone
from unittest.mock import MagicMock

from osmind.github.client import GitHubClient


def test_get_issues_includes_updated_at_and_comments(monkeypatch):
    updated = datetime(2026, 5, 15, 1, 2, 3, tzinfo=timezone.utc)
    issue = MagicMock()
    issue.number = 42
    issue.title = "Tokenizer leak"
    issue.body = "Long sequences leak memory"
    issue.labels = []
    issue.html_url = "https://github.com/o/r/issues/42"
    issue.state = "open"
    issue.updated_at = updated
    issue.get_comments.return_value = []

    repo = MagicMock()
    repo.get_issues.return_value = [issue]

    gh = MagicMock()
    gh.get_repo.return_value = repo
    monkeypatch.setattr("osmind.github.client.Github", lambda token=None: gh)

    result = GitHubClient("token").get_issues("o/r", limit=1)

    assert result[0].updated_at == "2026-05-15T01:02:03+00:00"
    assert result[0].comments == []


def test_get_pr_includes_updated_at_and_file_status(monkeypatch):
    updated = datetime(2026, 5, 15, 1, 2, 3, tzinfo=timezone.utc)
    file_obj = MagicMock()
    file_obj.filename = "src/a.py"
    file_obj.patch = "@@ -1 +1 @@"
    file_obj.status = "modified"
    file_obj.additions = 2
    file_obj.deletions = 1

    pr = MagicMock()
    pr.number = 7
    pr.title = "Refactor runner"
    pr.body = "Body"
    pr.html_url = "https://github.com/o/r/pull/7"
    pr.updated_at = updated
    pr.get_files.return_value = [file_obj]

    repo = MagicMock()
    repo.get_pull.return_value = pr

    gh = MagicMock()
    gh.get_repo.return_value = repo
    monkeypatch.setattr("osmind.github.client.Github", lambda token=None: gh)

    result = GitHubClient("token").get_pr("o/r", 7)

    assert result.updated_at == "2026-05-15T01:02:03+00:00"
    assert result.files[0].status == "modified"
    assert result.files[0].additions == 2
    assert result.files[0].deletions == 1
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
pytest tests/test_github_client.py -v
```

Expected: FAIL because `updated_at`, `comments`, `status`, `additions`, and `deletions` do not exist.

- [ ] **Step 3: Extend GitHub dataclasses**

Update `osmind/github/models.py`:

```python
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class GHComment:
    author: str
    body: str
    url: str
    created_at: str


@dataclass
class GHIssue:
    number: int
    title: str
    body: str
    labels: list[str]
    url: str
    repo: str
    state: str
    updated_at: str = ""
    comments: list[GHComment] = field(default_factory=list)
    score: float = 0.0
    reason: str = ""


@dataclass
class PRFile:
    filename: str
    patch: str
    status: str = ""
    additions: int = 0
    deletions: int = 0


@dataclass
class GHPR:
    number: int
    title: str
    body: str
    url: str
    repo: str
    files: list[PRFile] = field(default_factory=list)
    updated_at: str = ""
    score: float = 0.0
```

- [ ] **Step 4: Populate metadata in GitHub client**

Update `osmind/github/client.py` helper and model creation:

```python
def _iso(dt) -> str:
    return dt.isoformat() if dt else ""
```

Use `updated_at=_iso(i.updated_at)` for issues, `updated_at=_iso(p.updated_at)` for PRs, and populate `PRFile(status=f.status or "", additions=f.additions or 0, deletions=f.deletions or 0)`.

For issue comments, add:

```python
comments = [
    GHComment(
        author=c.user.login if c.user else "",
        body=c.body or "",
        url=c.html_url,
        created_at=_iso(c.created_at),
    )
    for c in i.get_comments()[:5]
]
```

If PyGithub paginated lists do not support slicing in the installed version, replace with a small loop that breaks after five comments.

- [ ] **Step 5: Run tests**

Run:

```bash
pytest tests/test_github_client.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add osmind/github/models.py osmind/github/client.py tests/test_github_client.py
git commit -m "feat: capture github item freshness metadata"
```

## Task 2: Add SQLite Cache Store

**Files:**
- Create: `osmind/cache/__init__.py`
- Create: `osmind/cache/store.py`
- Test: `tests/test_cache_store.py`

- [ ] **Step 1: Write failing cache tests**

Create `tests/test_cache_store.py`:

```python
from pathlib import Path

from osmind.cache.store import CacheStore


def test_cache_marks_unchanged_item_fresh(tmp_path: Path):
    store = CacheStore(tmp_path / "osmind.db")
    store.upsert_item(
        repo="o/r",
        source_type="pr",
        number=7,
        title="Title",
        body_hash="body1",
        content_hash="files1",
        state="open",
        url="https://github.com/o/r/pull/7",
        updated_at="2026-05-15T01:02:03+00:00",
    )

    assert store.is_item_stale("o/r", "pr", 7, "body1", "files1", "2026-05-15T01:02:03+00:00") is False


def test_cache_marks_changed_hash_stale(tmp_path: Path):
    store = CacheStore(tmp_path / "osmind.db")
    store.upsert_item("o/r", "issue", 42, "Title", "body1", "comments1", "open", "url", "u1")

    assert store.is_item_stale("o/r", "issue", 42, "body2", "comments1", "u1") is True


def test_cache_records_pack_metadata(tmp_path: Path):
    store = CacheStore(tmp_path / "osmind.db")
    pack_path = tmp_path / "pack.md"
    store.upsert_pack(
        repo="o/r",
        source_type="pr",
        number=7,
        path=pack_path,
        status="unread",
        confidence="unknown",
        source_updated_at="u1",
    )

    packs = store.list_packs()

    assert packs[0]["repo"] == "o/r"
    assert packs[0]["source_type"] == "pr"
    assert packs[0]["number"] == 7
    assert packs[0]["path"] == str(pack_path)
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
pytest tests/test_cache_store.py -v
```

Expected: FAIL because `osmind.cache.store` does not exist.

- [ ] **Step 3: Implement cache package**

Create `osmind/cache/__init__.py`:

```python
"""Persistent cache for GitHub item and Learning Pack metadata."""
```

Create `osmind/cache/store.py`:

```python
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class CacheStore:
    def __init__(self, db_path: Path):
        self._path = db_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS github_items (
                repo TEXT NOT NULL,
                source_type TEXT NOT NULL,
                number INTEGER NOT NULL,
                title TEXT NOT NULL,
                body_hash TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                state TEXT NOT NULL,
                url TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (repo, source_type, number)
            );

            CREATE TABLE IF NOT EXISTS analysis (
                repo TEXT NOT NULL,
                source_type TEXT NOT NULL,
                number INTEGER NOT NULL,
                model TEXT NOT NULL,
                prompt_version TEXT NOT NULL,
                input_hash TEXT NOT NULL,
                scores_json TEXT NOT NULL,
                reason TEXT NOT NULL,
                generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                error TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (repo, source_type, number, model, prompt_version, input_hash)
            );

            CREATE TABLE IF NOT EXISTS packs (
                repo TEXT NOT NULL,
                source_type TEXT NOT NULL,
                number INTEGER NOT NULL,
                path TEXT NOT NULL,
                status TEXT NOT NULL,
                confidence TEXT NOT NULL,
                source_updated_at TEXT NOT NULL,
                generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                stale INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (repo, source_type, number)
            );
            """
        )
        self._conn.commit()

    def upsert_item(
        self,
        repo: str,
        source_type: str,
        number: int,
        title: str,
        body_hash: str,
        content_hash: str,
        state: str,
        url: str,
        updated_at: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO github_items
                (repo, source_type, number, title, body_hash, content_hash, state, url, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(repo, source_type, number) DO UPDATE SET
                title=excluded.title,
                body_hash=excluded.body_hash,
                content_hash=excluded.content_hash,
                state=excluded.state,
                url=excluded.url,
                updated_at=excluded.updated_at,
                fetched_at=CURRENT_TIMESTAMP
            """,
            (repo, source_type, number, title, body_hash, content_hash, state, url, updated_at),
        )
        self._conn.commit()

    def is_item_stale(
        self,
        repo: str,
        source_type: str,
        number: int,
        body_hash: str,
        content_hash: str,
        updated_at: str,
    ) -> bool:
        row = self._conn.execute(
            """
            SELECT body_hash, content_hash, updated_at
            FROM github_items
            WHERE repo = ? AND source_type = ? AND number = ?
            """,
            (repo, source_type, number),
        ).fetchone()
        if row is None:
            return True
        return (
            row["body_hash"] != body_hash
            or row["content_hash"] != content_hash
            or row["updated_at"] != updated_at
        )

    def upsert_pack(
        self,
        repo: str,
        source_type: str,
        number: int,
        path: Path,
        status: str,
        confidence: str,
        source_updated_at: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO packs
                (repo, source_type, number, path, status, confidence, source_updated_at, stale)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
            ON CONFLICT(repo, source_type, number) DO UPDATE SET
                path=excluded.path,
                status=excluded.status,
                confidence=excluded.confidence,
                source_updated_at=excluded.source_updated_at,
                generated_at=CURRENT_TIMESTAMP,
                stale=0
            """,
            (repo, source_type, number, str(path), status, confidence, source_updated_at),
        )
        self._conn.commit()

    def list_packs(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT repo, source_type, number, path, status, confidence, source_updated_at, generated_at, stale
            FROM packs
            ORDER BY generated_at DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]
```

- [ ] **Step 4: Run cache tests**

Run:

```bash
pytest tests/test_cache_store.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add osmind/cache tests/test_cache_store.py
git commit -m "feat: add sqlite cache store"
```

## Task 3: Add Pack Models and Markdown Renderer

**Files:**
- Create: `osmind/packs/__init__.py`
- Create: `osmind/packs/models.py`
- Create: `osmind/packs/renderer.py`
- Test: `tests/test_pack_renderer.py`

- [ ] **Step 1: Write failing renderer tests**

Create `tests/test_pack_renderer.py`:

```python
from osmind.packs.models import LearningPack, PackSection, SourceRef
from osmind.packs.renderer import render_pack


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

    assert "type: osmind-learning-pack" in rendered
    assert "source_type: pr" in rendered
    assert "# PR #7: Refactor runner" in rendered
    assert "## Why This Is Worth Reading" in rendered
    assert "Useful design change." in rendered
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
pytest tests/test_pack_renderer.py -v
```

Expected: FAIL because pack modules do not exist.

- [ ] **Step 3: Implement pack models**

Create `osmind/packs/__init__.py`:

```python
"""Learning Pack generation and rendering."""
```

Create `osmind/packs/models.py`:

```python
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
```

- [ ] **Step 4: Implement renderer**

Create `osmind/packs/renderer.py`:

```python
from __future__ import annotations

from datetime import date

import yaml

from osmind.packs.models import LearningPack


def _heading(pack: LearningPack) -> str:
    label = "PR" if pack.source.source_type == "pr" else "Issue"
    return f"# {label} #{pack.source.number}: {pack.source.title}"


def render_pack(pack: LearningPack) -> str:
    frontmatter = {
        "type": "osmind-learning-pack",
        "source_type": pack.source.source_type,
        "repo": pack.source.repo,
        "number": pack.source.number,
        "title": pack.source.title,
        "url": pack.source.url,
        "status": pack.status,
        "confidence": pack.confidence,
        "generated_at": str(date.today()),
        "source_updated_at": pack.source.updated_at,
        "modules": pack.modules,
        "tags": pack.tags,
    }
    lines = [
        "---",
        yaml.dump(frontmatter, allow_unicode=True, sort_keys=False).strip(),
        "---",
        "",
        _heading(pack),
        "",
    ]
    for section in pack.sections:
        lines.append(f"## {section.title}")
        lines.append("")
        lines.append(section.body.strip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
```

- [ ] **Step 5: Run renderer tests**

Run:

```bash
pytest tests/test_pack_renderer.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add osmind/packs tests/test_pack_renderer.py
git commit -m "feat: render learning pack markdown"
```

## Task 4: Generate PR Learning Packs

**Files:**
- Create: `osmind/packs/generator.py`
- Test: `tests/test_pack_generator.py`

- [ ] **Step 1: Write failing PR generator test**

Create or extend `tests/test_pack_generator.py`:

```python
from osmind.github.models import GHPR, PRFile
from osmind.packs.generator import PackGenerator


def test_generate_pr_pack_contains_reading_path_and_agent_prompt():
    pr = GHPR(
        number=7,
        title="Refactor runner",
        body="This refactors model runner setup.",
        url="https://github.com/o/r/pull/7",
        repo="o/r",
        updated_at="2026-05-15T01:02:03+00:00",
        files=[
            PRFile(
                filename="src/runner.py",
                patch="@@ -1 +1 @@\n-old\n+new",
                status="modified",
                additions=1,
                deletions=1,
            )
        ],
    )

    pack = PackGenerator().from_pr(pr)

    section_titles = [s.title for s in pack.sections]
    assert pack.source.source_type == "pr"
    assert pack.modules == ["src"]
    assert "Files To Read First" in section_titles
    assert "Agent Exploration Prompt" in section_titles
    assert "src/runner.py" in "\n".join(s.body for s in pack.sections)
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
pytest tests/test_pack_generator.py -v
```

Expected: FAIL because `PackGenerator` does not exist.

- [ ] **Step 3: Implement PR pack generation**

Create `osmind/packs/generator.py`:

```python
from __future__ import annotations

from osmind.github.models import GHIssue, GHPR
from osmind.packs.models import LearningPack, PackSection, SourceRef


def _modules_from_paths(paths: list[str]) -> list[str]:
    modules = []
    for path in paths:
        head = path.split("/", 1)[0]
        if head and head not in modules:
            modules.append(head)
    return modules


def _bullet_lines(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- No concrete files available."


class PackGenerator:
    def from_pr(self, pr: GHPR) -> LearningPack:
        file_paths = [f.filename for f in pr.files]
        modules = _modules_from_paths(file_paths)
        changed_files = [
            f"`{f.filename}` ({f.status or 'changed'}, +{f.additions}/-{f.deletions})"
            for f in pr.files
        ]
        first_files = changed_files[:8]
        diff_map = []
        for f in pr.files[:8]:
            sample = f.patch[:700].strip() if f.patch else "No patch available from GitHub."
            diff_map.append(f"### `{f.filename}`\n\n```diff\n{sample}\n```")

        source = SourceRef(
            source_type="pr",
            repo=pr.repo,
            number=pr.number,
            title=pr.title,
            url=pr.url,
            updated_at=pr.updated_at,
        )
        return LearningPack(
            source=source,
            modules=modules,
            sections=[
                PackSection(
                    "Why This Is Worth Reading",
                    "This PR is worth reading because it shows how a real change moves through the project. Use it to understand the touched modules, review style, and integration points.",
                ),
                PackSection(
                    "What Changed",
                    pr.body.strip() or "The PR body is empty. Use the changed files and diff map below as the primary source.",
                ),
                PackSection("Files To Read First", _bullet_lines(first_files)),
                PackSection("Diff Map", "\n\n".join(diff_map) if diff_map else "No file diffs were available."),
                PackSection(
                    "Reading Path",
                    "1. Read the PR title and body.\n2. Skim the file list.\n3. Open the first changed file locally or on GitHub.\n4. Compare each diff hunk with the surrounding code.\n5. Write down what behavior changed before reading review comments.",
                ),
                PackSection(
                    "Socratic Questions",
                    "1. Why did this change need to touch these files?\n2. What behavior would break if one changed file were reverted?\n3. Which tests would prove the new behavior is correct?",
                ),
                PackSection(
                    "Agent Exploration Prompt",
                    f"Help me understand PR #{pr.number} in {pr.repo}: {pr.title}. Start by explaining the changed files, then identify the design reason behind the change, and finally suggest what I should manually verify before relying on this PR.",
                ),
                PackSection(
                    "If You Want To Contribute Next",
                    "Look for follow-up issues, missing tests, docs updates, or adjacent modules that use the changed behavior. Do not open a PR until you can explain the existing behavior and the intended new behavior.",
                ),
                PackSection("Review Later", "- [ ] I can explain why each changed file was necessary.\n- [ ] I can identify the highest-risk behavior change.\n- [ ] I know which test would catch a regression."),
                PackSection("Notes", ""),
            ],
        )

    def from_issue(self, issue: GHIssue) -> LearningPack:
        raise NotImplementedError("Issue pack generation is implemented in Task 6.")
```

- [ ] **Step 4: Run PR generator tests**

Run:

```bash
pytest tests/test_pack_generator.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add osmind/packs/generator.py tests/test_pack_generator.py
git commit -m "feat: generate pr learning packs"
```

## Task 5: Write Pack Files and Open Them

**Files:**
- Create: `osmind/packs/opener.py`
- Create: `osmind/services/__init__.py`
- Create: `osmind/services/library.py`
- Test: `tests/test_library_service.py`

- [ ] **Step 1: Write failing service tests**

Create `tests/test_library_service.py`:

```python
from pathlib import Path

from osmind.github.models import GHPR, PRFile
from osmind.services.library import PackLibrary


def test_write_pr_pack_creates_markdown_and_cache_record(tmp_path: Path):
    library = PackLibrary(notes_vault=tmp_path / "vault", cache_path=tmp_path / "cache.db")
    pr = GHPR(
        number=7,
        title="Refactor runner",
        body="Body",
        url="https://github.com/o/r/pull/7",
        repo="o/r",
        updated_at="u1",
        files=[PRFile("src/runner.py", "@@ diff", "modified", 1, 1)],
    )

    path = library.write_pr_pack(pr)

    assert path.exists()
    assert path.name == "pr-7-refactor-runner.md"
    assert "# PR #7: Refactor runner" in path.read_text()
    assert library.list_packs()[0]["path"] == str(path)
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
pytest tests/test_library_service.py -v
```

Expected: FAIL because `PackLibrary` does not exist.

- [ ] **Step 3: Implement pack opener**

Create `osmind/packs/opener.py`:

```python
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def open_path(path: Path, command: str | None = None) -> None:
    if command:
        subprocess.run([command, str(path)], check=False)
        return
    if os.environ.get("EDITOR"):
        subprocess.run([os.environ["EDITOR"], str(path)], check=False)
        return
    subprocess.run(["xdg-open", str(path)], check=False)
```

- [ ] **Step 4: Implement service package**

Create `osmind/services/__init__.py`:

```python
"""Application service layer used by CLI and TUI surfaces."""
```

Create `osmind/services/library.py`:

```python
from __future__ import annotations

import re
from pathlib import Path

from osmind.cache.store import CacheStore
from osmind.github.models import GHPR
from osmind.packs.generator import PackGenerator
from osmind.packs.renderer import render_pack


def _slug(text: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return value[:60] or "untitled"


class PackLibrary:
    def __init__(self, notes_vault: Path, cache_path: Path):
        self._notes_vault = notes_vault
        self._cache = CacheStore(cache_path)
        self._generator = PackGenerator()

    def _repo_dir(self, repo: str) -> Path:
        path = self._notes_vault / "osmind" / repo.replace("/", "_")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_pr_pack(self, pr: GHPR) -> Path:
        pack = self._generator.from_pr(pr)
        path = self._repo_dir(pr.repo) / f"pr-{pr.number}-{_slug(pr.title)}.md"
        path.write_text(render_pack(pack), encoding="utf-8")
        self._cache.upsert_pack(
            repo=pr.repo,
            source_type="pr",
            number=pr.number,
            path=path,
            status=pack.status,
            confidence=pack.confidence,
            source_updated_at=pr.updated_at,
        )
        return path

    def list_packs(self) -> list[dict]:
        return self._cache.list_packs()
```

- [ ] **Step 5: Run service tests**

Run:

```bash
pytest tests/test_library_service.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add osmind/packs/opener.py osmind/services tests/test_library_service.py
git commit -m "feat: write learning packs to vault"
```

## Task 6: Generate Issue Learning Packs

**Files:**
- Modify: `osmind/packs/generator.py`
- Modify: `osmind/services/library.py`
- Test: `tests/test_pack_generator.py`
- Test: `tests/test_library_service.py`

- [ ] **Step 1: Write failing issue generator test**

Append to `tests/test_pack_generator.py`:

```python
from osmind.github.models import GHComment, GHIssue


def test_generate_issue_pack_contains_investigation_path_and_human_checkpoints():
    issue = GHIssue(
        number=42,
        title="Tokenizer memory leak",
        body="Memory grows on long sequences.",
        labels=["bug"],
        url="https://github.com/o/r/issues/42",
        repo="o/r",
        state="open",
        updated_at="u1",
        comments=[GHComment("maintainer", "Likely tokenizer cache.", "url", "u0")],
    )

    pack = PackGenerator().from_issue(issue)

    section_titles = [s.title for s in pack.sections]
    assert pack.source.source_type == "issue"
    assert "Investigation Path" in section_titles
    assert "Agent Exploration Prompt" in section_titles
    assert "Tokenizer memory leak" in pack.sections[0].body
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
pytest tests/test_pack_generator.py -v
```

Expected: FAIL because `from_issue` raises `NotImplementedError`.

- [ ] **Step 3: Implement issue pack generation**

Replace `from_issue` in `osmind/packs/generator.py` with:

```python
    def from_issue(self, issue: GHIssue) -> LearningPack:
        source = SourceRef(
            source_type="issue",
            repo=issue.repo,
            number=issue.number,
            title=issue.title,
            url=issue.url,
            updated_at=issue.updated_at,
        )
        comments = "\n".join(
            f"- {c.author}: {c.body[:300]}" for c in issue.comments[:5]
        ) or "- No issue comments were cached."
        labels = ", ".join(issue.labels) if issue.labels else "none"
        return LearningPack(
            source=source,
            modules=[],
            sections=[
                PackSection(
                    "Why This May Fit You",
                    f"{issue.title}\n\nLabels: {labels}\n\nUse this issue to judge whether the problem is understandable, scoped, and worth deeper exploration.",
                ),
                PackSection(
                    "What Is Known",
                    issue.body.strip() or "The issue body is empty. Use comments and repository search to recover context.",
                ),
                PackSection("Missing Context", comments),
                PackSection(
                    "Investigation Path",
                    "1. Reproduce or restate the bug or request in your own words.\n2. Search the repository for names from the title and issue body.\n3. Identify the smallest module likely involved.\n4. Find existing tests around that module.\n5. Decide whether the next step is reading, reproduction, or implementation.",
                ),
                PackSection(
                    "Files Or Symbols To Search",
                    "- Search exact error messages from the issue body.\n- Search important nouns from the title.\n- Search labels and module names mentioned by maintainers.",
                ),
                PackSection(
                    "Agent Exploration Prompt",
                    f"Help me investigate issue #{issue.number} in {issue.repo}: {issue.title}. First summarize the known facts, then search for likely files or symbols, then propose a minimal reproduction or validation path. Do not implement until the investigation path is clear.",
                ),
                PackSection(
                    "Human Checkpoints",
                    "- [ ] I can explain the issue without copying the issue text.\n- [ ] I know which module is likely involved.\n- [ ] I know what evidence would prove a fix works.\n- [ ] I know whether this is suitable for agent assistance.",
                ),
                PackSection(
                    "Learning Questions",
                    "1. What existing behavior does this issue rely on?\n2. What project convention might constrain the fix?\n3. What would make this issue too risky for a first contribution?",
                ),
                PackSection("Notes", ""),
            ],
        )
```

- [ ] **Step 4: Add service method for issue packs**

Append to `PackLibrary` in `osmind/services/library.py`:

```python
    def write_issue_pack(self, issue) -> Path:
        pack = self._generator.from_issue(issue)
        path = self._repo_dir(issue.repo) / f"issue-{issue.number}-{_slug(issue.title)}.md"
        path.write_text(render_pack(pack), encoding="utf-8")
        self._cache.upsert_pack(
            repo=issue.repo,
            source_type="issue",
            number=issue.number,
            path=path,
            status=pack.status,
            confidence=pack.confidence,
            source_updated_at=issue.updated_at,
        )
        return path
```

- [ ] **Step 5: Add issue service test**

Append to `tests/test_library_service.py`:

```python
from osmind.github.models import GHIssue


def test_write_issue_pack_creates_markdown_and_cache_record(tmp_path: Path):
    library = PackLibrary(notes_vault=tmp_path / "vault", cache_path=tmp_path / "cache.db")
    issue = GHIssue(
        number=42,
        title="Tokenizer memory leak",
        body="Body",
        labels=["bug"],
        url="https://github.com/o/r/issues/42",
        repo="o/r",
        state="open",
        updated_at="u1",
    )

    path = library.write_issue_pack(issue)

    assert path.exists()
    assert path.name == "issue-42-tokenizer-memory-leak.md"
    assert "# Issue #42: Tokenizer memory leak" in path.read_text()
```

- [ ] **Step 6: Run pack and service tests**

Run:

```bash
pytest tests/test_pack_generator.py tests/test_library_service.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add osmind/packs/generator.py osmind/services/library.py tests/test_pack_generator.py tests/test_library_service.py
git commit -m "feat: generate issue learning packs"
```

## Task 7: Replace Learn Tab With Packs Tab

**Files:**
- Create: `osmind/tui/screens/packs.py`
- Modify: `osmind/tui/app.py`
- Test: `tests/test_tui.py`

- [ ] **Step 1: Write failing TUI smoke test**

Update `tests/test_tui.py` with a test that verifies the tab exists. If the existing test uses Textual's pilot, adapt the assertion to the current style in the file.

```python
import pytest

from osmind.tui.app import OsmindApp


@pytest.mark.asyncio
async def test_app_has_packs_tab(test_config):
    app = OsmindApp(test_config)
    async with app.run_test() as pilot:
        tabs = app.query("TabPane")
        ids = {tab.id for tab in tabs}
        assert "packs" in ids
        assert "learn" not in ids
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
pytest tests/test_tui.py -v
```

Expected: FAIL because the app still defines `learn`.

- [ ] **Step 3: Implement Packs screen**

Create `osmind/tui/screens/packs.py`:

```python
from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Label

from osmind.packs.opener import open_path
from osmind.services.library import PackLibrary


class PacksScreen(Vertical):
    BINDINGS = [
        ("o", "open_pack", "Open Pack"),
        ("r", "reload", "Reload"),
    ]

    def compose(self) -> ComposeResult:
        yield Label("[bold]Learning Packs[/bold]", markup=True)
        yield DataTable(id="packs-table", cursor_type="row")
        yield Label("[dim]o: open  r: reload[/dim]", markup=True)

    def on_mount(self) -> None:
        table = self.query_one("#packs-table", DataTable)
        table.add_columns("Type", "#", "Repo", "Status", "Confidence", "Path")
        self._load()

    def _library(self) -> PackLibrary:
        cache_path = self.app.config.notes_vault / "osmind" / ".cache" / "osmind.db"
        return PackLibrary(self.app.config.notes_vault, cache_path)

    def _load(self) -> None:
        self._packs = self._library().list_packs()
        table = self.query_one("#packs-table", DataTable)
        table.clear()
        for idx, pack in enumerate(self._packs):
            table.add_row(
                pack["source_type"],
                str(pack["number"]),
                pack["repo"],
                pack["status"],
                pack["confidence"],
                pack["path"],
                key=str(idx),
            )

    def action_reload(self) -> None:
        self._load()

    def action_open_pack(self) -> None:
        table = self.query_one("#packs-table", DataTable)
        if table.cursor_row is None or not self._packs:
            self.notify("No pack selected", severity="warning")
            return
        pack = self._packs[table.cursor_row]
        open_path(Path(pack["path"]))
```

- [ ] **Step 4: Wire Packs tab in app**

Modify `osmind/tui/app.py`:

```python
from osmind.tui.screens.packs import PacksScreen
```

Replace the Learn tab:

```python
            with TabPane("Packs", id="packs"):
                yield PacksScreen()
```

Update key bindings:

```python
        ("p", "switch_tab('packs')", "Packs"),
```

- [ ] **Step 5: Run TUI tests**

Run:

```bash
pytest tests/test_tui.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add osmind/tui/app.py osmind/tui/screens/packs.py tests/test_tui.py
git commit -m "feat: add learning packs tui screen"
```

## Task 8: Wire Discover Generate/Open Pack Actions

**Files:**
- Modify: `osmind/tui/screens/discover.py`
- Test: `tests/test_tui.py`

- [ ] **Step 1: Add service seam for testability**

In `DiscoverScreen.__init__`, add selected-pack tracking:

```python
        self._pack_paths_by_number: dict[str, str] = {}
```

Add helper:

```python
    def _library(self):
        from osmind.services.library import PackLibrary
        cache_path = self.app.config.notes_vault / "osmind" / ".cache" / "osmind.db"
        return PackLibrary(self.app.config.notes_vault, cache_path)
```

- [ ] **Step 2: Add generate action**

Add binding:

```python
        ("g", "generate_pack", "Generate Pack"),
        ("o", "open_pack", "Open Pack"),
```

Add action methods:

```python
    async def action_generate_pack(self) -> None:
        issue = self._get_selected_issue()
        if not issue:
            self.notify("先选中一个 issue", severity="warning")
            return
        path = await asyncio.to_thread(self._library().write_issue_pack, issue)
        self._pack_paths_by_number[str(issue.number)] = str(path)
        self.notify(f"Learning Pack saved: {path}", timeout=5)

    def action_open_pack(self) -> None:
        issue = self._get_selected_issue()
        if not issue:
            self.notify("先选中一个 issue", severity="warning")
            return
        path = self._pack_paths_by_number.get(str(issue.number))
        if not path:
            self.notify("No pack generated for selected issue", severity="warning")
            return
        from pathlib import Path
        from osmind.packs.opener import open_path
        open_path(Path(path))
```

This task wires issue pack generation first because Discover currently displays issues. PR pack generation is available through the service and will be surfaced from the Packs/PR workflow in a later task.

- [ ] **Step 3: Run focused tests**

Run:

```bash
pytest tests/test_tui.py tests/test_library_service.py -v
```

Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add osmind/tui/screens/discover.py tests/test_tui.py
git commit -m "feat: generate learning packs from discover"
```

## Task 9: Update Review To Read Learning Packs

**Files:**
- Modify: `osmind/tui/screens/review.py`
- Modify: `osmind/packs/renderer.py`
- Test: `tests/test_pack_renderer.py`

- [ ] **Step 1: Add pack parser test**

Append to `tests/test_pack_renderer.py`:

```python
from osmind.packs.renderer import parse_pack_frontmatter


def test_parse_pack_frontmatter_reads_status_and_confidence():
    text = """---
type: osmind-learning-pack
source_type: pr
repo: o/r
number: 7
title: Refactor runner
url: https://github.com/o/r/pull/7
status: reading
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
    assert data["confidence"] == "low"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
pytest tests/test_pack_renderer.py -v
```

Expected: FAIL because `parse_pack_frontmatter` does not exist.

- [ ] **Step 3: Implement frontmatter parser**

Append to `osmind/packs/renderer.py`:

```python
def parse_pack_frontmatter(text: str) -> dict:
    if not text.startswith("---\n"):
        raise ValueError("Pack is missing YAML frontmatter")
    _, raw, _body = text.split("---", 2)
    data = yaml.safe_load(raw) or {}
    if data.get("type") != "osmind-learning-pack":
        raise ValueError("Not an osmind Learning Pack")
    return data
```

- [ ] **Step 4: Update Review screen data source**

In `osmind/tui/screens/review.py`, replace `NotesVault` usage in `_load_notes_list` with pack cache:

```python
        from osmind.services.library import PackLibrary
        cache_path = self.app.config.notes_vault / "osmind" / ".cache" / "osmind.db"
        library = PackLibrary(self.app.config.notes_vault, cache_path)
        self._notes = library.list_packs()
```

Update table rows to use dict keys:

```python
        for idx, note in enumerate(self._notes):
            table.add_row(
                f"#{note['number']}",
                note["repo"].split("/")[-1],
                key=str(idx),
            )
```

In `_start_note_review`, read the pack path:

```python
            content = Path(note["path"]).read_text(encoding="utf-8")
```

Also update the label text from “Saved Notes” to “Learning Packs”.

- [ ] **Step 5: Run tests**

Run:

```bash
pytest tests/test_pack_renderer.py tests/test_tui.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add osmind/packs/renderer.py osmind/tui/screens/review.py tests/test_pack_renderer.py
git commit -m "feat: review learning packs"
```

## Task 10: Full Verification and Documentation Update

**Files:**
- Modify: `README.md`
- Modify: `profile.yaml.example` if cache/editor config is added during implementation.

- [ ] **Step 1: Update README product positioning**

Replace the opening description with:

```markdown
**osmind** is a local-first Learning Pack generator for developers who want to understand and contribute to open-source projects.

It watches GitHub repositories you care about, recommends PRs and issues that match your interests, and turns selected items into Markdown Learning Packs in your Obsidian vault. Each pack gives you a reading path, key files, questions, and an optional Codex or Claude prompt so learning can compound over time.
```

- [ ] **Step 2: Update README workflow**

Document:

```markdown
## Workflow

1. Configure watched repositories in `profile.yaml`.
2. Run `osmind`.
3. Use Discover to refresh issues and choose an item.
4. Press `g` to generate a Learning Pack.
5. Press `o` to open the pack in your editor or Obsidian.
6. Read the pack alongside GitHub or a local checkout.
7. Use Packs and Review to revisit generated material.
```

- [ ] **Step 3: Run the full test suite**

Run:

```bash
pytest -v
```

Expected: PASS.

- [ ] **Step 4: Run import smoke test**

Run:

```bash
python -c "from osmind.tui.app import OsmindApp; from osmind.services.library import PackLibrary; print('ok')"
```

Expected output:

```text
ok
```

- [ ] **Step 5: Commit**

```bash
git add README.md profile.yaml.example
git commit -m "docs: describe learning pack workflow"
```

## Execution Notes

- Keep each task commit separate.
- Do not keep the old Learn chat as a second path unless a later spec explicitly asks for it.
- Avoid live GitHub or live LLM calls in tests.
- If Textual tests are brittle, prefer service-layer tests and keep TUI tests to smoke coverage.
- If a task reveals unrelated pre-existing failures, stop and document the failing command before changing unrelated code.

## Self-Review

Spec coverage:

- Cached analysis and staleness are covered by Tasks 1 and 2.
- Markdown Learning Pack generation is covered by Tasks 3, 4, 5, and 6.
- TUI as a control console is covered by Tasks 7 and 8.
- Review over generated packs is covered by Task 9.
- Documentation and verification are covered by Task 10.

No unresolved markers are intentionally left in the plan. Function and class names are consistent across tasks: `CacheStore`, `LearningPack`, `PackGenerator`, `PackLibrary`, `render_pack`, and `parse_pack_frontmatter`.
