# Issue Brief Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade Discover from a scored issue list into an Issue Brief workflow that helps the user understand, judge, save, and optionally act on an issue without immediately leaving osmind.

**Architecture:** Keep GitHub fetching, scoring, and pack generation intact. Add a structured `IssueBrief` domain object and an LLM-backed `IssueBriefGenerator`, then render that object in Discover detail and embed it into Learning Packs. The UI stays TUI-first, while long-term reading remains Markdown/Obsidian.

**Tech Stack:** Python dataclasses, Textual TUI, existing `LLMClient`, existing `GHIssue`, existing SQLite cache and pack generator, pytest.

---

## File Structure

- Create `osmind/engine/issue_brief.py`
  - Owns `IssueBrief`, prompt formatting, JSON parsing, fallback behavior, and markdown rendering helpers.
- Modify `osmind/tui/screens/discover.py`
  - Replace the one-paragraph summary detail with a structured Issue Brief view.
  - Keep `Enter/v` as the detail entry point.
  - Keep `g` pack generation and `o` pack opening.
- Modify `osmind/packs/generator.py`
  - Include the Issue Brief sections in generated Learning Packs when available.
- Modify `osmind/cache/store.py`
  - Persist the latest brief JSON per issue so repeated detail views do not call the LLM again.
- Modify `osmind/github/models.py`
  - Add an optional `brief_json: str = ""` field to `GHIssue` or keep brief persistence cache-only. Prefer cache-only unless UI code becomes cleaner with the field.
- Add `tests/test_issue_brief.py`
  - Unit tests for prompt parsing, fallback output, and markdown rendering.
- Modify `tests/test_tui.py`
  - TUI tests for detail rendering, cache reuse, and pack generation with brief context.
- Modify `tests/test_cache_store.py`
  - Cache round-trip tests for issue briefs.
- Modify `tests/test_pack_generator.py`
  - Pack content tests for the new brief sections.

---

## Task 1: Add Structured Issue Brief Domain

**Files:**
- Create: `osmind/engine/issue_brief.py`
- Test: `tests/test_issue_brief.py`

- [ ] **Step 1: Write failing tests for parsing valid brief JSON**

```python
def test_issue_brief_generator_parses_structured_json():
    from osmind.engine.issue_brief import IssueBriefGenerator
    from osmind.github.models import GHIssue

    class DummyLLM:
        def chat(self, system, prompt, max_tokens=1024):
            return """
            {
              "one_liner": "修复 tokenizer cache 持续增长的问题。",
              "plain_explanation": "这个 issue 说 tokenizer 缓存没有被正确释放，长时间运行会导致内存增长。",
              "why_it_fits": "你关注推理服务和缓存问题，且这个问题可以先从复现测试切入。",
              "project_context": ["tokenizer", "cache", "server runtime"],
              "likely_files": ["python/sglang/srt/"],
              "difficulty": "medium",
              "readiness": "learn-first",
              "background_to_learn": ["tokenizer cache 生命周期", "服务进程内存观测"],
              "next_steps": ["读 issue 原文", "搜索 tokenizer cache", "补一个最小复现"],
              "agent_questions": ["请定位 tokenizer cache 的创建和释放路径。"],
              "risks": ["issue 可能缺少复现步骤"]
            }
            """

    issue = GHIssue(42, "Tokenizer cache leak", "Body", ["bug"], "url", "o/r", "open")

    brief = IssueBriefGenerator(DummyLLM()).generate(issue, reason="推荐理由")

    assert brief.one_liner == "修复 tokenizer cache 持续增长的问题。"
    assert brief.difficulty == "medium"
    assert brief.readiness == "learn-first"
    assert "tokenizer" in brief.project_context
    assert "补一个最小复现" in brief.next_steps
```

- [ ] **Step 2: Run the test and verify it fails**

Run:

```bash
python -m pytest tests/test_issue_brief.py::test_issue_brief_generator_parses_structured_json -q
```

Expected: fail with `ModuleNotFoundError: No module named 'osmind.engine.issue_brief'`.

- [ ] **Step 3: Implement minimal domain object and generator**

Create `osmind/engine/issue_brief.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass, asdict
import json

from osmind.github.models import GHIssue


_SYSTEM = """\
你是一个开源贡献学习助手。请把 GitHub issue 转成中文 Issue Brief。
目标是帮助用户判断是否值得学习、是否适合生成 Learning Pack、下一步看什么。
只返回 JSON，不要 markdown。
"""


@dataclass
class IssueBrief:
    one_liner: str
    plain_explanation: str
    why_it_fits: str
    project_context: list[str]
    likely_files: list[str]
    difficulty: str
    readiness: str
    background_to_learn: list[str]
    next_steps: list[str]
    agent_questions: list[str]
    risks: list[str]

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class IssueBriefGenerator:
    def __init__(self, llm):
        self._llm = llm

    def generate(self, issue: GHIssue, reason: str = "") -> IssueBrief:
        raw = self._llm.chat(_SYSTEM, _format_prompt(issue, reason), max_tokens=1024)
        data = json.loads(raw)
        return IssueBrief(
            one_liner=str(data.get("one_liner", "")),
            plain_explanation=str(data.get("plain_explanation", "")),
            why_it_fits=str(data.get("why_it_fits", "")),
            project_context=_string_list(data.get("project_context")),
            likely_files=_string_list(data.get("likely_files")),
            difficulty=str(data.get("difficulty", "unknown")),
            readiness=str(data.get("readiness", "unknown")),
            background_to_learn=_string_list(data.get("background_to_learn")),
            next_steps=_string_list(data.get("next_steps")),
            agent_questions=_string_list(data.get("agent_questions")),
            risks=_string_list(data.get("risks")),
        )


def _string_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _format_prompt(issue: GHIssue, reason: str) -> str:
    labels = ", ".join(issue.labels) or "none"
    return (
        f"Repo: {issue.repo}\n"
        f"Issue #{issue.number}: {issue.title}\n"
        f"URL: {issue.url}\n"
        f"Labels: {labels}\n"
        f"Recommendation reason: {reason or issue.reason or 'none'}\n\n"
        f"Body:\n{issue.body[:4000] or '(empty)'}\n\n"
        "请返回字段: one_liner, plain_explanation, why_it_fits, "
        "project_context, likely_files, difficulty, readiness, "
        "background_to_learn, next_steps, agent_questions, risks。"
    )
```

- [ ] **Step 4: Run the test and verify it passes**

Run:

```bash
python -m pytest tests/test_issue_brief.py::test_issue_brief_generator_parses_structured_json -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add osmind/engine/issue_brief.py tests/test_issue_brief.py
git commit -m "feat: add structured issue brief generator"
```

---

## Task 2: Add Robust Fallback and Markdown Rendering

**Files:**
- Modify: `osmind/engine/issue_brief.py`
- Test: `tests/test_issue_brief.py`

- [ ] **Step 1: Write failing fallback and rendering tests**

```python
def test_issue_brief_generator_falls_back_when_llm_returns_invalid_json():
    from osmind.engine.issue_brief import IssueBriefGenerator
    from osmind.github.models import GHIssue

    class BadLLM:
        def chat(self, system, prompt, max_tokens=1024):
            return "not json"

    issue = GHIssue(7, "Crash on startup", "Stack trace here", ["bug"], "url", "o/r", "open", reason="启动路径相关")

    brief = IssueBriefGenerator(BadLLM()).generate(issue)

    assert brief.one_liner == "Crash on startup"
    assert "启动路径相关" in brief.why_it_fits
    assert brief.difficulty == "unknown"


def test_issue_brief_renders_markdown_sections():
    from osmind.engine.issue_brief import IssueBrief, render_issue_brief_markdown

    brief = IssueBrief(
        one_liner="修复启动崩溃",
        plain_explanation="服务启动时因为配置缺失崩溃。",
        why_it_fits="适合先读启动路径。",
        project_context=["startup", "config"],
        likely_files=["osmind/tui/app.py"],
        difficulty="medium",
        readiness="learn-first",
        background_to_learn=["Textual lifecycle"],
        next_steps=["读启动入口"],
        agent_questions=["请解释启动链路。"],
        risks=["复现条件不完整"],
    )

    markdown = render_issue_brief_markdown(brief)

    assert "## Issue Brief" in markdown
    assert "修复启动崩溃" in markdown
    assert "- startup" in markdown
    assert "readiness: learn-first" in markdown
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
python -m pytest tests/test_issue_brief.py -q
```

Expected: fail because fallback and `render_issue_brief_markdown` do not exist.

- [ ] **Step 3: Implement fallback and renderer**

Add to `osmind/engine/issue_brief.py`:

```python
def render_issue_brief_markdown(brief: IssueBrief) -> str:
    return "\n".join(
        [
            "## Issue Brief",
            "",
            f"**一句话:** {brief.one_liner}",
            "",
            f"**难度:** {brief.difficulty}",
            f"**readiness:** {brief.readiness}",
            "",
            "### 这个 issue 在说什么",
            brief.plain_explanation,
            "",
            "### 为什么可能适合你",
            brief.why_it_fits,
            "",
            "### 项目上下文",
            _markdown_list(brief.project_context),
            "",
            "### 可能涉及的文件或模块",
            _markdown_list(brief.likely_files),
            "",
            "### 需要补的背景",
            _markdown_list(brief.background_to_learn),
            "",
            "### 下一步",
            _markdown_list(brief.next_steps),
            "",
            "### 可以问 agent 的问题",
            _markdown_list(brief.agent_questions),
            "",
            "### 风险",
            _markdown_list(brief.risks),
        ]
    )


def _markdown_list(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) if items else "- unknown"
```

Update `IssueBriefGenerator.generate()` to catch `json.JSONDecodeError`, `TypeError`, and `ValueError`:

```python
    def generate(self, issue: GHIssue, reason: str = "") -> IssueBrief:
        raw = self._llm.chat(_SYSTEM, _format_prompt(issue, reason), max_tokens=1024)
        try:
            data = json.loads(raw)
            return IssueBrief(
                one_liner=str(data.get("one_liner", "")),
                plain_explanation=str(data.get("plain_explanation", "")),
                why_it_fits=str(data.get("why_it_fits", "")),
                project_context=_string_list(data.get("project_context")),
                likely_files=_string_list(data.get("likely_files")),
                difficulty=str(data.get("difficulty", "unknown")),
                readiness=str(data.get("readiness", "unknown")),
                background_to_learn=_string_list(data.get("background_to_learn")),
                next_steps=_string_list(data.get("next_steps")),
                agent_questions=_string_list(data.get("agent_questions")),
                risks=_string_list(data.get("risks")),
            )
        except (json.JSONDecodeError, TypeError, ValueError):
            fit_reason = reason or issue.reason or "暂无推荐理由。"
            return IssueBrief(
                one_liner=issue.title,
                plain_explanation=(issue.body or "暂无 issue 原文。")[:500],
                why_it_fits=fit_reason,
                project_context=[],
                likely_files=[],
                difficulty="unknown",
                readiness="learn-first",
                background_to_learn=[],
                next_steps=["阅读 issue 原文", "确认是否有复现步骤", "搜索相关模块和历史 PR"],
                agent_questions=[f"请解释 {issue.repo} issue #{issue.number} 的背景和可能涉及的代码路径。"],
                risks=["LLM 未能生成结构化 Brief"],
            )
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```bash
python -m pytest tests/test_issue_brief.py -q
```

Expected: all `tests/test_issue_brief.py` tests pass.

- [ ] **Step 5: Commit**

```bash
git add osmind/engine/issue_brief.py tests/test_issue_brief.py
git commit -m "feat: render issue briefs with fallback"
```

---

## Task 3: Cache Issue Briefs

**Files:**
- Modify: `osmind/cache/store.py`
- Test: `tests/test_cache_store.py`

- [ ] **Step 1: Write failing cache round-trip test**

```python
def test_cache_round_trips_issue_brief(tmp_path):
    from osmind.cache.store import CacheStore
    from osmind.github.models import GHIssue

    store = CacheStore(tmp_path / "osmind.db")
    issue = GHIssue(42, "Tokenizer cache", "Body", [], "url", "o/r", "open")
    store.upsert_issue(issue)

    brief_json = '{"one_liner": "解释 tokenizer cache"}'
    store.update_issue_brief("o/r", 42, brief_json)

    assert store.get_issue_brief("o/r", 42) == brief_json
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
python -m pytest tests/test_cache_store.py::test_cache_round_trips_issue_brief -q
```

Expected: fail because `update_issue_brief` and `get_issue_brief` do not exist.

- [ ] **Step 3: Add `brief_json` column migration**

In `CacheStore._migrate_github_items()` or the existing column migration helper, add:

```python
"brief_json": "TEXT NOT NULL DEFAULT ''",
```

- [ ] **Step 4: Add cache methods**

Add to `CacheStore`:

```python
def update_issue_brief(self, repo: str, number: int, brief_json: str) -> None:
    try:
        self._conn.execute(
            """
            UPDATE github_items
            SET brief_json = ?
            WHERE repo = ? AND source_type = 'issue' AND number = ?
            """,
            (brief_json, repo, number),
        )
        self._conn.commit()
    except Exception:
        self._conn.rollback()
        raise


def get_issue_brief(self, repo: str, number: int) -> str:
    row = self._conn.execute(
        """
        SELECT brief_json
        FROM github_items
        WHERE repo = ? AND source_type = 'issue' AND number = ?
        """,
        (repo, number),
    ).fetchone()
    if row is None:
        return ""
    return str(row["brief_json"] or "")
```

- [ ] **Step 5: Run test and verify it passes**

Run:

```bash
python -m pytest tests/test_cache_store.py::test_cache_round_trips_issue_brief -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add osmind/cache/store.py tests/test_cache_store.py
git commit -m "feat: cache issue briefs"
```

---

## Task 4: Render Issue Brief in Discover Detail

**Files:**
- Modify: `osmind/tui/screens/discover.py`
- Test: `tests/test_tui.py`

- [ ] **Step 1: Write failing TUI test for structured detail**

```python
@pytest.mark.asyncio
async def test_discover_view_issue_renders_structured_issue_brief(temp_config, monkeypatch):
    from osmind.engine.issue_brief import IssueBrief
    from osmind.github.models import GHIssue
    from osmind.tui.screens.discover import DiscoverScreen
    from osmind.tui.widgets.issue_list import IssueTable
    from textual.widgets import Static
    import osmind.engine.issue_brief
    import osmind.engine.llm

    issue = GHIssue(
        42,
        "Tokenizer cache leak",
        "The tokenizer cache grows forever.",
        ["bug"],
        "https://github.com/o/r/issues/42",
        "o/r",
        "open",
        score=0.9,
        reason="与你的推理服务兴趣匹配。",
    )

    class DummyLLMClient:
        def __init__(self, cfg):
            pass

    class DummyBriefGenerator:
        def __init__(self, llm):
            pass

        def generate(self, issue, reason=""):
            return IssueBrief(
                one_liner="修复 tokenizer cache 泄漏",
                plain_explanation="缓存生命周期没有被正确控制。",
                why_it_fits=reason,
                project_context=["tokenizer", "runtime cache"],
                likely_files=["python/sglang/srt/"],
                difficulty="medium",
                readiness="learn-first",
                background_to_learn=["缓存生命周期"],
                next_steps=["搜索 tokenizer cache"],
                agent_questions=["请定位 cache 创建路径。"],
                risks=["复现条件可能不足"],
            )

    monkeypatch.setattr(osmind.engine.llm, "LLMClient", DummyLLMClient)
    monkeypatch.setattr(osmind.engine.issue_brief, "IssueBriefGenerator", DummyBriefGenerator)

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        discover = app.query_one(DiscoverScreen)
        table = app.query_one(IssueTable)
        table.populate([issue])
        table.cursor_coordinate = (0, 0)
        discover._issues_by_number = {str(issue.number): issue}

        await discover.action_view_issue()

        detail = str(app.query_one("#issue-detail-panel", Static).content)

    assert "Issue Brief" in detail
    assert "修复 tokenizer cache 泄漏" in detail
    assert "缓存生命周期没有被正确控制" in detail
    assert "与你的推理服务兴趣匹配" in detail
    assert "搜索 tokenizer cache" in detail
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
python -m pytest tests/test_tui.py::test_discover_view_issue_renders_structured_issue_brief -q
```

Expected: fail because Discover still uses `IssueExplainer` short summary.

- [ ] **Step 3: Replace detail summary path with Issue Brief path**

In `osmind/tui/screens/discover.py`, change `action_view_issue()`:

```python
from osmind.engine.issue_brief import IssueBriefGenerator, render_issue_brief_markdown
from osmind.engine.llm import LLMClient

cached = self._cache().get_issue_brief(issue.repo, issue.number)
if cached:
    brief = issue_brief_from_json(cached)
else:
    llm = LLMClient(llm_cfg)
    brief = IssueBriefGenerator(llm).generate(issue, reason=issue.reason)
    self._cache().update_issue_brief(issue.repo, issue.number, brief.to_json())
detail.update(_format_issue_detail(issue, render_issue_brief_markdown(brief)))
```

Also add `issue_brief_from_json()` to `osmind/engine/issue_brief.py`:

```python
def issue_brief_from_json(value: str) -> IssueBrief:
    data = json.loads(value)
    return IssueBrief(
        one_liner=str(data.get("one_liner", "")),
        plain_explanation=str(data.get("plain_explanation", "")),
        why_it_fits=str(data.get("why_it_fits", "")),
        project_context=_string_list(data.get("project_context")),
        likely_files=_string_list(data.get("likely_files")),
        difficulty=str(data.get("difficulty", "unknown")),
        readiness=str(data.get("readiness", "unknown")),
        background_to_learn=_string_list(data.get("background_to_learn")),
        next_steps=_string_list(data.get("next_steps")),
        agent_questions=_string_list(data.get("agent_questions")),
        risks=_string_list(data.get("risks")),
    )
```

Update `_format_issue_detail(issue, summary)` parameter name to `_format_issue_detail(issue, brief_markdown)` and render:

```python
f"{brief_markdown}\n\n"
f"[bold]原文[/bold]\n{(issue.body or '(empty)').strip()}\n\n"
```

- [ ] **Step 4: Run test and verify it passes**

Run:

```bash
python -m pytest tests/test_tui.py::test_discover_view_issue_renders_structured_issue_brief -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add osmind/tui/screens/discover.py osmind/engine/issue_brief.py tests/test_tui.py
git commit -m "feat: show issue briefs in discover"
```

---

## Task 5: Reuse Cached Briefs in Discover

**Files:**
- Modify: `osmind/tui/screens/discover.py`
- Test: `tests/test_tui.py`

- [ ] **Step 1: Write failing cache reuse test**

```python
@pytest.mark.asyncio
async def test_discover_view_issue_uses_cached_brief_without_llm(temp_config, monkeypatch):
    from osmind.cache.store import CacheStore
    from osmind.github.models import GHIssue
    from osmind.tui.screens.discover import DiscoverScreen
    from osmind.tui.widgets.issue_list import IssueTable
    from textual.widgets import Static
    import osmind.engine.issue_brief

    issue = GHIssue(42, "Cached brief issue", "Body", [], "url", "o/r", "open")
    cache = CacheStore(temp_config.notes_vault / "osmind" / ".cache" / "osmind.db")
    cache.upsert_issue(issue)
    cache.update_issue_brief(
        "o/r",
        42,
        '{"one_liner":"缓存 Brief","plain_explanation":"来自缓存","why_it_fits":"缓存理由","project_context":[],"likely_files":[],"difficulty":"low","readiness":"ready","background_to_learn":[],"next_steps":["直接阅读"],"agent_questions":[],"risks":[]}',
    )

    class FailingBriefGenerator:
        def __init__(self, llm):
            raise AssertionError("LLM should not be used when cached brief exists")

    monkeypatch.setattr(osmind.engine.issue_brief, "IssueBriefGenerator", FailingBriefGenerator)

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        discover = app.query_one(DiscoverScreen)
        table = app.query_one(IssueTable)
        table.populate([issue])
        table.cursor_coordinate = (0, 0)
        discover._issues_by_number = {"42": issue}

        await discover.action_view_issue()

        detail = str(app.query_one("#issue-detail-panel", Static).content)

    assert "缓存 Brief" in detail
    assert "来自缓存" in detail
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
python -m pytest tests/test_tui.py::test_discover_view_issue_uses_cached_brief_without_llm -q
```

Expected: fail if Task 4 did not already implement cache reuse fully.

- [ ] **Step 3: Implement cache-first behavior**

In `action_view_issue()`, make the detail flow exactly:

```python
cached = self._cache().get_issue_brief(issue.repo, issue.number)
if cached:
    brief = issue_brief_from_json(cached)
else:
    brief = IssueBriefGenerator(LLMClient(llm_cfg)).generate(issue, reason=issue.reason)
    self._cache().update_issue_brief(issue.repo, issue.number, brief.to_json())
```

- [ ] **Step 4: Run test and verify it passes**

Run:

```bash
python -m pytest tests/test_tui.py::test_discover_view_issue_uses_cached_brief_without_llm -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add osmind/tui/screens/discover.py tests/test_tui.py
git commit -m "feat: reuse cached issue briefs"
```

---

## Task 6: Put Issue Brief into Learning Packs

**Files:**
- Modify: `osmind/packs/generator.py`
- Test: `tests/test_pack_generator.py`

- [ ] **Step 1: Write failing pack content test**

```python
def test_from_issue_includes_issue_brief_when_present():
    from osmind.engine.issue_brief import IssueBrief
    from osmind.github.models import GHIssue
    from osmind.packs.generator import from_issue

    issue = GHIssue(
        42,
        "Tokenizer cache leak",
        "Body",
        [],
        "url",
        "o/r",
        "open",
        reason="推荐理由",
    )
    brief = IssueBrief(
        one_liner="修复 tokenizer cache 泄漏",
        plain_explanation="缓存生命周期异常。",
        why_it_fits="适合用户。",
        project_context=["tokenizer"],
        likely_files=["python/sglang/srt/"],
        difficulty="medium",
        readiness="learn-first",
        background_to_learn=["cache lifecycle"],
        next_steps=["搜索 tokenizer cache"],
        agent_questions=["请解释 cache 路径"],
        risks=["复现不足"],
    )

    markdown = from_issue(issue, brief=brief)

    assert "## Issue Brief" in markdown
    assert "修复 tokenizer cache 泄漏" in markdown
    assert "搜索 tokenizer cache" in markdown
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
python -m pytest tests/test_pack_generator.py::test_from_issue_includes_issue_brief_when_present -q
```

Expected: fail because `from_issue()` does not accept `brief`.

- [ ] **Step 3: Update pack generator function signature**

In `osmind/packs/generator.py`, change:

```python
def from_issue(issue: GHIssue) -> str:
```

to:

```python
def from_issue(issue: GHIssue, brief=None) -> str:
```

Import renderer:

```python
from osmind.engine.issue_brief import render_issue_brief_markdown
```

Insert after the metadata or "Why This May Fit You" section:

```python
if brief is not None:
    parts.append(render_issue_brief_markdown(brief))
```

- [ ] **Step 4: Thread brief through library write path only when available**

If `PackLibrary.write_issue_pack(issue)` only receives a `GHIssue`, keep it unchanged for now. In Discover, when generating a pack from a detail view with cached brief, call a new optional method or pass `brief` only if the library already supports forwarding. Prefer the minimal change:

```python
def write_issue_pack(self, issue: GHIssue, brief=None) -> Path:
    markdown = generator.from_issue(issue, brief=brief)
```

Update call sites that call `write_issue_pack(issue)` to keep working because `brief` defaults to `None`.

- [ ] **Step 5: Run pack tests**

Run:

```bash
python -m pytest tests/test_pack_generator.py tests/test_library_service.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add osmind/packs/generator.py osmind/services/library.py tests/test_pack_generator.py tests/test_library_service.py
git commit -m "feat: include issue briefs in learning packs"
```

---

## Task 7: Tighten Discover Copy and Navigation

**Files:**
- Modify: `osmind/tui/screens/discover.py`
- Test: `tests/test_tui.py`

- [ ] **Step 1: Write failing copy test**

```python
def test_discover_visible_copy_centers_issue_brief_not_agent_launchers():
    from osmind.tui.screens.discover import DiscoverScreen

    source = DiscoverScreen.__dict__
    bindings = " ".join(f"{binding[0]} {binding[1]} {binding[2]}" for binding in DiscoverScreen.BINDINGS)

    assert "Claude" not in bindings
    assert "Codex" not in bindings
    assert "view_issue" in bindings
```

- [ ] **Step 2: Run test and verify state**

Run:

```bash
python -m pytest tests/test_tui.py::test_discover_visible_copy_centers_issue_brief_not_agent_launchers -q
```

Expected: pass if previous hidden agent work is present; otherwise fail and then remove visible `c/x` bindings.

- [ ] **Step 3: Update detail hints**

In `DiscoverScreen.compose()` and `_show_detail()`, use:

```python
"Esc 返回列表。g 生成 Learning Pack。o 打开已有 Pack。"
```

and:

```python
"  Esc: Back  g: Generate Pack  o: Open Pack"
```

- [ ] **Step 4: Run TUI tests**

Run:

```bash
python -m pytest tests/test_tui.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add osmind/tui/screens/discover.py tests/test_tui.py
git commit -m "chore: center discover copy on issue briefs"
```

---

## Task 8: Final Verification

**Files:**
- No source changes unless tests expose an issue.

- [ ] **Step 1: Run complete test suite**

Run:

```bash
python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Manual TUI smoke test**

Run:

```bash
python -m osmind.tui.app
```

Expected manual path:

1. Open Discover.
2. Press `f` to fetch or load cached issues.
3. Select a high-scored issue.
4. Press `Enter`.
5. Confirm detail shows `Issue Brief`, Chinese explanation, why it fits, background to learn, next steps, risks, and original text.
6. Press `Esc`.
7. Press `g`.
8. Open the generated pack and confirm the same brief appears in Markdown.

- [ ] **Step 3: Commit any final fixes**

```bash
git status --short
git add <changed-files>
git commit -m "test: verify issue brief workflow"
```

Only commit if Step 2 required fixes.

---

## Self-Review

- Spec coverage: The plan covers structured understanding, Chinese explanation, fit reason, modules/files, difficulty/readiness, background learning, next steps, agent questions, risks, caching, TUI rendering, and Learning Pack persistence.
- Placeholder scan: No `TBD`, `TODO`, or vague "add tests" steps remain.
- Type consistency: The plan uses `IssueBrief`, `IssueBriefGenerator.generate(issue, reason="")`, `render_issue_brief_markdown(brief)`, `issue_brief_from_json(value)`, `CacheStore.update_issue_brief(repo, number, brief_json)`, and `CacheStore.get_issue_brief(repo, number)` consistently.
