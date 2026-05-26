# Opportunity Detail 2.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a richer Discover issue detail and learning-pack flow that explains an issue in Chinese, names profile fit and risks, provides first validation steps, and saves an agent-ready prompt.

**Architecture:** Extend the existing `IssueBrief` boundary instead of adding a parallel explanation object. `osmind.engine.issue_brief` owns structured LLM output, cache metadata, markdown rendering, and prompt rendering; `DiscoverScreen` only loads or generates briefs and renders panes; `PackGenerator` and `PackLibrary` persist the same structured brief into learning packs.

**Tech Stack:** Python dataclasses, JSON, Textual TUI, SQLite-backed `CacheStore`, existing OpenAI-compatible `LLMClient`, pytest and pytest-asyncio.

---

## File Map

- Modify `osmind/engine/issue_brief.py`: define the new `IssueBrief` schema, profile context, cache metadata helpers, strict JSON parsing, prompt formatting, and markdown rendering.
- Modify `osmind/tui/screens/discover.py`: build profile context from app config, validate cached briefs, generate missing/stale briefs, render enhanced detail panes, and preserve fallback behavior.
- Modify `osmind/packs/generator.py`: use structured brief fields to produce learning-pack sections including `Why It May Fit You`, `Risks And Missing Evidence`, `First 30 Minutes`, `Validation Path`, and `Agent Prompt`.
- Modify `osmind/services/library.py`: keep passing optional `IssueBrief` to `PackGenerator`; no new persistence abstraction is needed.
- Modify `tests/test_issue_brief.py`: update and expand unit coverage for schema, rendering, prompt, strict parsing, and cache metadata.
- Modify `tests/test_library_service.py`: assert packs contain structured brief sections and agent prompt.
- Modify `tests/test_pack_generator.py`: assert section ordering and generated issue pack content.
- Modify `tests/test_tui.py`: assert Discover detail uses cache, regenerates stale briefs, handles generation failure, and shows enhanced detail content.
- Optional docs touch: update `README.md` only if the keybinding or visible behavior wording becomes stale.

## Task 1: Expand IssueBrief Schema And Rendering

**Files:**
- Modify: `osmind/engine/issue_brief.py`
- Test: `tests/test_issue_brief.py`

- [ ] **Step 1: Replace the existing brief fixture with the new schema in tests**

Edit `tests/test_issue_brief.py` so `_brief_payload()` returns the new schema:

```python
def _brief_payload() -> dict:
    return {
        "one_liner": "这是一个模型适配问题，可以先沿着 Qwen2 adapter 找入口。",
        "problem_summary": "Issue 要求为 Qwen3MoE 增加模型支持，并参考已有 Qwen2 adapter。",
        "background": [
            "模型适配通常涉及 config mapping、权重加载和注册路径。",
            "Issue 文本给出了 Qwen2 adapter 作为可搜索模板。",
        ],
        "matched_interests": ["SGLang inference optimization"],
        "matched_skills": ["Python"],
        "resource_assessment": "资源风险较低；第一步主要是代码阅读和小范围测试，不依赖大 GPU。",
        "evidence": [
            "Title mentions Qwen3MoE support.",
            "Body says to follow the existing Qwen2 adapter.",
            "Label good first issue suggests scoped external contribution.",
        ],
        "risks": ["Qwen3MoE 架构差异可能导致适配范围超过 config mapping。"],
        "first_steps": [
            "搜索 Qwen2 adapter 和 model registry。",
            "确认 Qwen3MoE config 名称、权重键和 tokenizer 是否已有支持。",
            "找一个最小加载或注册测试作为验证点。",
        ],
        "validation_path": [
            "能定位现有 Qwen2 adapter。",
            "能说明 Qwen3MoE 需要新增或复用哪些注册入口。",
            "能跑一个最小模型配置或相关单测。",
        ],
        "agent_prompt": (
            "在 o/r 仓库中研究 issue #42: Add Qwen3MoE support。"
            "先搜索 Qwen2 adapter、model registry 和 Qwen3MoE 相关符号，"
            "总结最小实现路径和可验证测试；如果找不到注册入口，停止并说明缺失信息。"
        ),
        "metadata": {
            "source_updated_at": "2026-05-15T01:02:03+00:00",
            "recommendation_reason": "Recommended by ranker",
            "profile_hash": "profile-hash",
            "source_hash": "source-hash",
        },
    }
```

- [ ] **Step 2: Update the round-trip and markdown rendering tests to fail against current code**

Replace the old rendering assertions in `test_issue_brief_renders_markdown_sections` with:

```python
def test_issue_brief_renders_markdown_sections():
    brief = IssueBrief(**_brief_payload())

    markdown = render_issue_brief_markdown(brief)

    assert markdown.startswith("## Issue Brief")
    assert "### One-Liner" in markdown
    assert "这是一个模型适配问题" in markdown
    assert "### Problem Summary" in markdown
    assert "Issue 要求为 Qwen3MoE 增加模型支持" in markdown
    assert "### Background" in markdown
    assert "- 模型适配通常涉及 config mapping" in markdown
    assert "### Why It May Fit You" in markdown
    assert "- Interest: SGLang inference optimization" in markdown
    assert "- Skill: Python" in markdown
    assert "### Resource Assessment" in markdown
    assert "资源风险较低" in markdown
    assert "### Evidence" in markdown
    assert "### Risks And Missing Evidence" in markdown
    assert "### First 30 Minutes" in markdown
    assert "搜索 Qwen2 adapter" in markdown
    assert "### Validation Path" in markdown
    assert "### Agent Prompt" in markdown
    assert "在 o/r 仓库中研究 issue #42" in markdown
```

Add a prompt-specific rendering test:

```python
def test_render_agent_prompt_returns_saved_prompt_text():
    brief = IssueBrief(**_brief_payload())

    assert render_agent_prompt(brief).startswith("在 o/r 仓库中研究 issue #42")
    assert "停止并说明缺失信息" in render_agent_prompt(brief)
```

Update `test_issue_brief_json_roundtrip` so it still asserts `parsed == brief`.

- [ ] **Step 3: Run the focused tests and confirm they fail**

Run:

```bash
python -m pytest tests/test_issue_brief.py -q
```

Expected: failures mentioning unexpected keyword arguments such as `problem_summary`, or missing `render_agent_prompt`.

- [ ] **Step 4: Implement the new dataclasses and renderers**

In `osmind/engine/issue_brief.py`, replace the existing `IssueBrief` dataclass with:

```python
@dataclass
class IssueBriefMetadata:
    source_updated_at: str = ""
    recommendation_reason: str = ""
    profile_hash: str = ""
    source_hash: str = ""


@dataclass
class IssueBrief:
    one_liner: str
    problem_summary: str
    background: list[str]
    matched_interests: list[str]
    matched_skills: list[str]
    resource_assessment: str
    evidence: list[str]
    risks: list[str]
    first_steps: list[str]
    validation_path: list[str]
    agent_prompt: str
    metadata: IssueBriefMetadata | dict[str, str] | None = None

    def __post_init__(self) -> None:
        if self.metadata is None:
            self.metadata = IssueBriefMetadata()
        elif isinstance(self.metadata, dict):
            self.metadata = IssueBriefMetadata(
                source_updated_at=str(self.metadata.get("source_updated_at", "")),
                recommendation_reason=str(self.metadata.get("recommendation_reason", "")),
                profile_hash=str(self.metadata.get("profile_hash", "")),
                source_hash=str(self.metadata.get("source_hash", "")),
            )

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)
```

Replace `issue_brief_from_json()` with:

```python
def issue_brief_from_json(value: str) -> IssueBrief:
    data = json.loads(value)
    if not isinstance(data, dict):
        raise ValueError("Issue brief JSON must be an object.")
    metadata = data.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    return IssueBrief(
        one_liner=_required_str(data, "one_liner"),
        problem_summary=_required_str(data, "problem_summary"),
        background=_optional_str_list(data, "background"),
        matched_interests=_optional_str_list(data, "matched_interests"),
        matched_skills=_optional_str_list(data, "matched_skills"),
        resource_assessment=_required_str(data, "resource_assessment"),
        evidence=_optional_str_list(data, "evidence"),
        risks=_optional_str_list(data, "risks"),
        first_steps=_optional_str_list(data, "first_steps"),
        validation_path=_optional_str_list(data, "validation_path"),
        agent_prompt=_required_str(data, "agent_prompt"),
        metadata=IssueBriefMetadata(
            source_updated_at=str(metadata.get("source_updated_at", "")),
            recommendation_reason=str(metadata.get("recommendation_reason", "")),
            profile_hash=str(metadata.get("profile_hash", "")),
            source_hash=str(metadata.get("source_hash", "")),
        ),
    )
```

Add the optional list helper:

```python
def _optional_str_list(data: dict[str, Any], key: str) -> list[str]:
    value = data.get(key, [])
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"Invalid list field: {key}")
    return [str(item).strip() for item in value if isinstance(item, str) and item.strip()]
```

Replace `render_issue_brief_markdown()` with:

```python
def render_issue_brief_markdown(brief: IssueBrief) -> str:
    sections = [
        "## Issue Brief",
        "",
        "### One-Liner",
        brief.one_liner,
        "",
        "### Problem Summary",
        brief.problem_summary,
        "",
        "### Background",
        _render_list(brief.background),
        "",
        "### Why It May Fit You",
        _render_profile_fit(brief),
        "",
        "### Resource Assessment",
        brief.resource_assessment,
        "",
        "### Evidence",
        _render_list(brief.evidence),
        "",
        "### Risks And Missing Evidence",
        _render_list(brief.risks),
        "",
        "### First 30 Minutes",
        _render_numbered(brief.first_steps),
        "",
        "### Validation Path",
        _render_list(brief.validation_path),
        "",
        "### Agent Prompt",
        render_agent_prompt(brief),
    ]
    return "\n".join(sections).rstrip() + "\n"
```

Add:

```python
def render_agent_prompt(brief: IssueBrief) -> str:
    return brief.agent_prompt.strip()


def _render_profile_fit(brief: IssueBrief) -> str:
    lines: list[str] = []
    lines.extend(f"- Interest: {item}" for item in brief.matched_interests)
    lines.extend(f"- Skill: {item}" for item in brief.matched_skills)
    return "\n".join(lines) if lines else "- No direct profile match identified."


def _render_numbered(items: list[str]) -> str:
    if not items:
        return "1. No first step identified."
    return "\n".join(f"{index}. {item}" for index, item in enumerate(items, 1))
```

- [ ] **Step 5: Run the focused tests and confirm they pass**

Run:

```bash
python -m pytest tests/test_issue_brief.py -q
```

Expected: all `tests/test_issue_brief.py` tests pass after updating old tests that still reference removed fields.

- [ ] **Step 6: Commit Task 1**

```bash
git add osmind/engine/issue_brief.py tests/test_issue_brief.py
git commit -m "feat: expand issue brief schema"
```

## Task 2: Add Profile Context, Cache Metadata, And Strict Generation Errors

**Files:**
- Modify: `osmind/engine/issue_brief.py`
- Test: `tests/test_issue_brief.py`

- [ ] **Step 1: Add tests for profile context hashing and stale checks**

Append to `tests/test_issue_brief.py`:

```python
def test_issue_brief_cache_metadata_marks_current_brief_valid():
    issue = _issue()
    profile_context = IssueBriefProfileContext(
        interests=["SGLang inference optimization"],
        skills=["Python"],
        resources={"gpus": "4x RTX 4090"},
    )
    brief = IssueBrief(**_brief_payload())
    brief.metadata = issue_brief_metadata(issue, "Recommended by ranker", profile_context)

    assert is_issue_brief_current(brief, issue, "Recommended by ranker", profile_context)


def test_issue_brief_cache_metadata_detects_changed_reason():
    issue = _issue()
    profile_context = IssueBriefProfileContext(
        interests=["SGLang inference optimization"],
        skills=["Python"],
        resources={"gpus": "4x RTX 4090"},
    )
    brief = IssueBrief(**_brief_payload())
    brief.metadata = issue_brief_metadata(issue, "Recommended by ranker", profile_context)

    assert not is_issue_brief_current(brief, issue, "Different reason", profile_context)


def test_issue_brief_generator_raises_controlled_error_for_invalid_json():
    llm = MagicMock()
    llm.chat.return_value = "not json"
    issue = _issue()
    profile_context = IssueBriefProfileContext(
        interests=["SGLang inference optimization"],
        skills=["Python"],
        resources={"gpus": "4x RTX 4090"},
    )

    try:
        IssueBriefGenerator(llm).generate(issue, reason="Recommended by ranker", profile_context=profile_context)
    except IssueBriefGenerationError as exc:
        assert "Failed to parse issue brief JSON" in str(exc)
    else:
        raise AssertionError("IssueBriefGenerationError was not raised")
```

Update imports in the same file:

```python
from osmind.engine.issue_brief import (
    IssueBrief,
    IssueBriefGenerationError,
    IssueBriefGenerator,
    IssueBriefProfileContext,
    is_issue_brief_current,
    issue_brief_from_json,
    issue_brief_metadata,
    render_agent_prompt,
    render_issue_brief_markdown,
)
```

- [ ] **Step 2: Run tests and confirm they fail**

Run:

```bash
python -m pytest tests/test_issue_brief.py -q
```

Expected: import errors for the new symbols and signature mismatch for `generate(..., profile_context=...)`.

- [ ] **Step 3: Implement profile context and metadata helpers**

In `osmind/engine/issue_brief.py`, add imports:

```python
import hashlib
```

Add dataclasses and exception near the existing dataclasses:

```python
class IssueBriefGenerationError(Exception):
    pass


@dataclass
class IssueBriefProfileContext:
    interests: list[str]
    skills: list[str]
    resources: dict[str, Any]

    def to_prompt(self) -> str:
        return "\n".join(
            [
                f"Interests: {', '.join(self.interests) or 'none'}",
                f"Skills: {', '.join(self.skills) or 'none'}",
                f"Resources: {_format_mapping(self.resources)}",
            ]
        )
```

Add metadata helpers:

```python
def issue_brief_metadata(issue: GHIssue, reason: str, profile_context: IssueBriefProfileContext) -> IssueBriefMetadata:
    return IssueBriefMetadata(
        source_updated_at=issue.updated_at or "",
        recommendation_reason=reason or issue.reason or "",
        profile_hash=_hash_json(
            {
                "interests": profile_context.interests,
                "skills": profile_context.skills,
                "resources": profile_context.resources,
            }
        ),
        source_hash=_hash_json(
            {
                "title": issue.title,
                "body": issue.body,
                "labels": issue.labels,
                "comments": [
                    {
                        "author": comment.author,
                        "body": comment.body,
                        "created_at": comment.created_at,
                        "url": comment.url,
                    }
                    for comment in issue.comments
                ],
            }
        ),
    )


def is_issue_brief_current(
    brief: IssueBrief,
    issue: GHIssue,
    reason: str,
    profile_context: IssueBriefProfileContext,
) -> bool:
    expected = issue_brief_metadata(issue, reason, profile_context)
    metadata = brief.metadata if isinstance(brief.metadata, IssueBriefMetadata) else IssueBriefMetadata()
    return (
        metadata.source_updated_at == expected.source_updated_at
        and metadata.recommendation_reason == expected.recommendation_reason
        and metadata.profile_hash == expected.profile_hash
        and metadata.source_hash == expected.source_hash
    )
```

Add helpers:

```python
def _hash_json(value: dict[str, Any]) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _format_mapping(values: dict[str, Any]) -> str:
    if not values:
        return "none"
    return ", ".join(f"{key}: {value}" for key, value in values.items())
```

- [ ] **Step 4: Update generator signature and strict error behavior**

Replace `IssueBriefGenerator.generate` with:

```python
def generate(
    self,
    issue: GHIssue,
    reason: str = "",
    profile_context: IssueBriefProfileContext | None = None,
) -> IssueBrief:
    profile_context = profile_context or IssueBriefProfileContext(interests=[], skills=[], resources={})
    raw = self._llm.chat(_SYSTEM, _format_prompt(issue, reason, profile_context), max_tokens=1400)
    try:
        brief = issue_brief_from_json(raw)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise IssueBriefGenerationError("Failed to parse issue brief JSON") from exc
    brief.metadata = issue_brief_metadata(issue, reason, profile_context)
    return brief
```

Update `_format_prompt` signature and content:

```python
def _format_prompt(issue: GHIssue, reason: str, profile_context: IssueBriefProfileContext) -> str:
    labels = ", ".join(issue.labels) or "none"
    recommendation_reason = reason or issue.reason or "(none)"
    comments = "\n".join(
        f"- {comment.author}: {comment.body[:800]}"
        for comment in issue.comments[:5]
    ) or "- No cached comments."
    expected_fields = "\n".join(
        [
            '- "one_liner": string, Chinese',
            '- "problem_summary": string, Chinese',
            '- "background": array of strings, Chinese',
            '- "matched_interests": array of strings copied from user profile when supported by evidence',
            '- "matched_skills": array of strings copied from user profile when supported by evidence',
            '- "resource_assessment": string, Chinese',
            '- "evidence": array of strings grounded in title, labels, body, comments, score reason, or profile',
            '- "risks": array of strings, Chinese',
            '- "first_steps": array of strings, Chinese, first 30 minutes',
            '- "validation_path": array of strings, Chinese',
            '- "agent_prompt": string, Chinese, ready to give to Codex or Claude',
        ]
    )
    return (
        "Answer in Chinese. Return strict JSON only; no markdown fence.\n"
        "Ground every recommendation in the issue text, comments, score reason, or user profile. "
        "If evidence is missing, say so in risks instead of inventing repository internals.\n\n"
        f"Repo: {issue.repo}\n"
        f"Issue #{issue.number}: {issue.title}\n"
        f"URL: {issue.url}\n"
        f"Labels: {labels}\n"
        f"Recommendation reason: {recommendation_reason}\n"
        f"User profile:\n{profile_context.to_prompt()}\n\n"
        f"Issue body:\n{issue.body[:4000] or '(empty)'}\n\n"
        f"Comments:\n{comments}\n\n"
        "Return a JSON object with these expected fields:\n"
        f"{expected_fields}\n"
    )
```

- [ ] **Step 5: Update old invalid JSON tests to match controlled error**

Remove or rewrite old tests that asserted fallback brief generation on invalid JSON. Keep one test asserting that optional list fields normalize blanks:

```python
def test_issue_brief_parser_normalizes_blank_optional_list_items():
    payload = _brief_payload()
    payload["first_steps"] = ["搜索 Qwen2 adapter", "  "]

    brief = issue_brief_from_json(json.dumps(payload))

    assert brief.first_steps == ["搜索 Qwen2 adapter"]
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
python -m pytest tests/test_issue_brief.py -q
```

Expected: all issue brief tests pass.

- [ ] **Step 7: Commit Task 2**

```bash
git add osmind/engine/issue_brief.py tests/test_issue_brief.py
git commit -m "feat: add issue brief cache metadata"
```

## Task 3: Wire Enhanced Brief Loading Into Discover

**Files:**
- Modify: `osmind/tui/screens/discover.py`
- Test: `tests/test_tui.py`

- [ ] **Step 1: Add TUI tests for enhanced detail and cache invalidation**

Update `tests/test_tui.py` helper `_issue_brief_payload` so it returns the new schema. Use the same fields from Task 1, but override values through keyword arguments:

```python
def _issue_brief_payload(**overrides):
    payload = {
        "one_liner": "这是 tokenizer cache 泄漏问题，适合先补复现测试。",
        "problem_summary": "Issue 描述 tokenizer cache 会持续增长，需要定位缓存释放或 key 策略。",
        "background": ["Tokenizer cache 可能影响长序列请求的内存占用。"],
        "matched_interests": ["SGLang"],
        "matched_skills": ["Python"],
        "resource_assessment": "可以先用小输入和单测验证，不需要大 GPU。",
        "evidence": ["Label bug.", "Body mentions cache keeps growing."],
        "risks": ["Issue 可能缺少完整复现脚本。"],
        "first_steps": ["搜索 tokenizer cache。", "补一个最小内存增长复现。"],
        "validation_path": ["复现测试先失败。", "修复后缓存数量不再随长序列无限增长。"],
        "agent_prompt": "请在 o/r 中分析 tokenizer cache 泄漏 issue，先找缓存实现和最小复现测试。",
    }
    payload.update(overrides)
    return payload
```

In `test_discover_view_issue_separates_analysis_from_source`, add assertions:

```python
assert "Problem Summary" in str(source)
assert "Why It May Fit You" in str(source)
assert "Risks And Missing Evidence" in str(source)
assert "First 30 Minutes" in str(source)
assert "Validation Path" in str(source)
assert "Agent Prompt" in str(source)
assert "请在 o/r 中分析 tokenizer cache 泄漏 issue" in str(source)
```

Add a stale-cache test:

```python
@pytest.mark.asyncio
async def test_discover_view_issue_regenerates_cached_brief_when_profile_context_changes(temp_config, monkeypatch):
    from osmind.cache.store import CacheStore
    from osmind.github.models import GHIssue
    from osmind.tui.screens.discover import DiscoverScreen
    from osmind.tui.widgets.issue_list import IssueTable
    from textual.widgets import Static
    from osmind.engine.issue_brief import IssueBrief, IssueBriefProfileContext, issue_brief_metadata
    import osmind.engine.issue_brief
    import osmind.engine.llm

    issue = GHIssue(42, "Tokenizer leak", "Original body.", ["bug"], "u", "o/r", "open", reason="same reason")
    stale_context = IssueBriefProfileContext(interests=["Other"], skills=["Python"], resources={"gpus": "none"})
    cached_brief = IssueBrief(**_issue_brief_payload(one_liner="Old brief."))
    cached_brief.metadata = issue_brief_metadata(issue, "same reason", stale_context)
    cache = CacheStore(temp_config.notes_vault / "osmind" / ".cache" / "osmind.db")
    cache.upsert_issue(issue)
    cache.update_issue_brief(issue.repo, issue.number, cached_brief.to_json())
    calls = []

    class DummyLLMClient:
        def __init__(self, cfg):
            pass

    class RecordingIssueBriefGenerator:
        def __init__(self, llm):
            pass

        def generate(self, issue, reason="", profile_context=None):
            calls.append((issue.number, profile_context.interests))
            return IssueBrief(**_issue_brief_payload(one_liner="Fresh brief."))

    monkeypatch.setattr(osmind.engine.llm, "LLMClient", DummyLLMClient)
    monkeypatch.setattr(osmind.engine.issue_brief, "IssueBriefGenerator", RecordingIssueBriefGenerator)

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        discover = app.query_one(DiscoverScreen)
        table = app.query_one(IssueTable)
        table.populate([issue])
        table.cursor_coordinate = (0, 0)
        discover._issues_by_number = {str(issue.number): issue}

        await discover.action_view_issue()

        source = app.query_one("#issue-source-panel", Static).renderable

    assert calls == [(42, ["SGLang"])]
    assert "Fresh brief." in str(source)
    assert "Old brief." not in str(source)
```

- [ ] **Step 2: Run the TUI tests and confirm failure**

Run:

```bash
python -m pytest tests/test_tui.py::test_discover_view_issue_separates_analysis_from_source tests/test_tui.py::test_discover_view_issue_regenerates_cached_brief_when_profile_context_changes -q
```

Expected: failures because Discover still calls `generate(issue, reason=...)` without `profile_context` and cached brief validation only compares `why_it_fits`.

- [ ] **Step 3: Add profile-context helpers to Discover**

In `osmind/tui/screens/discover.py`, update imports inside `action_view_issue` to include:

```python
from osmind.engine.issue_brief import (
    IssueBriefGenerator,
    IssueBriefGenerationError,
    IssueBriefProfileContext,
    is_issue_brief_current,
    issue_brief_from_json,
    render_issue_brief_markdown,
)
```

Add a method on `DiscoverScreen`:

```python
def _issue_brief_profile_context(self):
    from osmind.engine.issue_brief import IssueBriefProfileContext

    return IssueBriefProfileContext(
        interests=list(self.app.config.interests),
        skills=list(self.app.config.skills),
        resources=dict(self.app.config.resources or {}),
    )
```

Replace `_cached_issue_brief` with:

```python
def _cached_issue_brief(self, issue):
    from osmind.engine.issue_brief import is_issue_brief_current, issue_brief_from_json

    cached_json = self._cache().get_issue_brief(issue.repo, issue.number)
    if not cached_json:
        return None
    try:
        brief = issue_brief_from_json(cached_json)
    except Exception:
        return None
    if not is_issue_brief_current(
        brief,
        issue,
        issue.reason,
        self._issue_brief_profile_context(),
    ):
        return None
    return brief
```

- [ ] **Step 4: Update generation call to pass profile context**

Inside `action_view_issue`, replace:

```python
brief = IssueBriefGenerator(llm).generate(issue, reason=issue.reason)
```

with:

```python
brief = IssueBriefGenerator(llm).generate(
    issue,
    reason=issue.reason,
    profile_context=self._issue_brief_profile_context(),
)
```

Keep the existing `except Exception` block so `IssueBriefGenerationError` logs and leaves original issue visible.

- [ ] **Step 5: Run focused TUI tests**

Run:

```bash
python -m pytest tests/test_tui.py::test_discover_view_issue_separates_analysis_from_source tests/test_tui.py::test_discover_view_issue_uses_cached_issue_brief_without_llm tests/test_tui.py::test_discover_view_issue_regenerates_cached_brief_when_reason_changes tests/test_tui.py::test_discover_view_issue_regenerates_cached_brief_when_profile_context_changes -q
```

Expected: all selected tests pass. If old tests construct `IssueBrief` with removed fields, update their fixtures to the new `_issue_brief_payload`.

- [ ] **Step 6: Commit Task 3**

```bash
git add osmind/tui/screens/discover.py tests/test_tui.py
git commit -m "feat: show enhanced issue brief in discover"
```

## Task 4: Persist Structured Brief Sections Into Learning Packs

**Files:**
- Modify: `osmind/packs/generator.py`
- Modify: `tests/test_library_service.py`
- Modify: `tests/test_pack_generator.py`

- [ ] **Step 1: Update pack tests to assert structured sections**

In `tests/test_library_service.py`, update `test_write_issue_pack_can_include_issue_brief` to construct the new `IssueBrief` schema and assert:

```python
assert "## Issue Brief" in markdown
assert "## Why It May Fit You" in markdown
assert "Interest: SGLang" in markdown
assert "Skill: Python" in markdown
assert "## Risks And Missing Evidence" in markdown
assert "Issue 可能缺少完整复现脚本" in markdown
assert "## First 30 Minutes" in markdown
assert "搜索 tokenizer cache" in markdown
assert "## Validation Path" in markdown
assert "复现测试先失败" in markdown
assert "## Agent Prompt" in markdown
assert "请在 o/r 中分析 tokenizer cache 泄漏 issue" in markdown
assert markdown.index("## Recommendation Snapshot") < markdown.index("## Issue Brief")
assert markdown.index("## Issue Brief") < markdown.index("## Why It May Fit You")
```

In `tests/test_pack_generator.py`, add:

```python
def test_issue_pack_uses_structured_brief_sections():
    issue = _issue()
    brief = IssueBrief(
        one_liner="这是 tokenizer cache 泄漏问题。",
        problem_summary="缓存随长序列增长。",
        background=["Tokenizer cache 影响长序列内存。"],
        matched_interests=["SGLang"],
        matched_skills=["Python"],
        resource_assessment="可先用单测验证。",
        evidence=["Body mentions cache keeps growing."],
        risks=["缺少完整复现脚本。"],
        first_steps=["搜索 tokenizer cache。"],
        validation_path=["复现测试先失败。"],
        agent_prompt="请分析 tokenizer cache 泄漏 issue。",
    )

    pack = PackGenerator.from_issue(issue, resources={"gpus": "4x RTX 4090"}, brief=brief)
    sections = {section.title: section.content for section in pack.sections}

    assert "Issue Brief" in sections
    assert "这是 tokenizer cache 泄漏问题。" in sections["Issue Brief"]
    assert "Why It May Fit You" in sections
    assert "Interest: SGLang" in sections["Why It May Fit You"]
    assert "Risks And Missing Evidence" in sections
    assert "缺少完整复现脚本。" in sections["Risks And Missing Evidence"]
    assert "First 30 Minutes" in sections
    assert "搜索 tokenizer cache。" in sections["First 30 Minutes"]
    assert "Validation Path" in sections
    assert "复现测试先失败。" in sections["Validation Path"]
    assert "Agent Prompt" in sections
    assert "请分析 tokenizer cache 泄漏 issue。" in sections["Agent Prompt"]
```

- [ ] **Step 2: Run pack tests and confirm failure**

Run:

```bash
python -m pytest tests/test_library_service.py::test_write_issue_pack_can_include_issue_brief tests/test_pack_generator.py::test_issue_pack_uses_structured_brief_sections -q
```

Expected: missing structured sections because current pack embeds the whole brief only as `Issue Brief`.

- [ ] **Step 3: Add brief-specific section helpers**

In `osmind/packs/generator.py`, import `render_agent_prompt`:

```python
from osmind.engine.issue_brief import IssueBrief, render_agent_prompt, render_issue_brief_markdown
```

Add helpers near `_issue_brief_body`:

```python
def _issue_brief_summary(brief: IssueBrief) -> str:
    return "\n\n".join(
        [
            f"### One-Liner\n{brief.one_liner}",
            f"### Problem Summary\n{brief.problem_summary}",
            f"### Background\n{_plain_list(brief.background)}",
        ]
    )


def _brief_why_it_may_fit(brief: IssueBrief, issue: GHIssue) -> str:
    lines = [
        "### Matched Interests",
        _plain_list(brief.matched_interests),
        "",
        "### Matched Skills",
        _plain_list(brief.matched_skills),
        "",
        "### Resource Assessment",
        brief.resource_assessment,
        "",
        "### Evidence",
        _plain_list(brief.evidence),
    ]
    if issue.reason:
        lines.extend(["", "### Ranker Reason", issue.reason])
    return "\n".join(lines).rstrip()


def _plain_list(items: list[str]) -> str:
    if not items:
        return "- None identified."
    return "\n".join(f"- {item}" for item in items)


def _numbered_list(items: list[str]) -> str:
    if not items:
        return "1. No concrete step identified."
    return "\n".join(f"{index}. {item}" for index, item in enumerate(items, 1))
```

- [ ] **Step 4: Change issue pack section construction**

In `PackGenerator.from_issue`, replace the current `sections = [...]` and `sections.insert(...)` pattern with:

```python
sections = [
    PackSection("What This Is", _issue_what_this_is(issue)),
    PackSection("Recommendation Snapshot", format_decision_markdown(issue, resources)),
]
if brief is not None:
    sections.extend(
        [
            PackSection("Issue Brief", _issue_brief_summary(brief)),
            PackSection("Why It May Fit You", _brief_why_it_may_fit(brief, issue)),
            PackSection("Risks And Missing Evidence", _plain_list(brief.risks)),
            PackSection("First 30 Minutes", _numbered_list(brief.first_steps)),
            PackSection("Validation Path", _plain_list(brief.validation_path)),
            PackSection("Agent Prompt", render_agent_prompt(brief)),
        ]
    )
else:
    sections.extend(
        [
            PackSection("Why It May Fit You", _why_issue_may_fit(issue)),
            PackSection("First 10 Minutes", _issue_first_ten_minutes(issue)),
            PackSection("Validation Path", _issue_validation_path(issue)),
            PackSection("Agent Exploration Prompt", _issue_agent_prompt(issue)),
        ]
    )
sections.extend(
    [
        PackSection("Continue Or Stop Criteria", _issue_continue_stop_criteria(issue)),
        PackSection("Files And Symbols To Inspect", _issue_search_targets(issue)),
        PackSection("Known Facts", _issue_known_context(issue)),
        PackSection("Missing Context", _issue_missing_context(issue)),
        PackSection("Reproduction Hypothesis", _issue_reproduction_hypothesis(issue)),
        PackSection("Maintainer Signals", _issue_maintainer_signals(issue)),
        PackSection("Decision Log", _decision_log()),
        PackSection("Notes", ""),
    ]
)
```

- [ ] **Step 5: Run pack tests**

Run:

```bash
python -m pytest tests/test_library_service.py::test_write_issue_pack_can_include_issue_brief tests/test_pack_generator.py::test_issue_pack_uses_structured_brief_sections -q
```

Expected: selected tests pass.

- [ ] **Step 6: Run broader pack tests**

Run:

```bash
python -m pytest tests/test_library_service.py tests/test_pack_generator.py -q
```

Expected: all library and pack generator tests pass.

- [ ] **Step 7: Commit Task 4**

```bash
git add osmind/packs/generator.py tests/test_library_service.py tests/test_pack_generator.py
git commit -m "feat: persist structured issue briefs in packs"
```

## Task 5: Make Start Work Use The Enhanced Brief Reliably

**Files:**
- Modify: `osmind/tui/screens/discover.py`
- Test: `tests/test_tui.py`

- [ ] **Step 1: Add a test that `w` generates a pack with agent prompt**

Append to the Discover pack-generation test area in `tests/test_tui.py`:

```python
@pytest.mark.asyncio
async def test_discover_start_work_writes_pack_with_agent_prompt(temp_config, monkeypatch):
    from osmind.github.models import GHIssue
    from osmind.tui.screens.discover import DiscoverScreen
    from osmind.tui.widgets.issue_list import IssueTable
    from osmind.engine.issue_brief import IssueBrief
    import osmind.engine.issue_brief
    import osmind.engine.llm

    issue = GHIssue(42, "Tokenizer leak", "Body", ["bug"], "u", "o/r", "open", reason="fit reason")

    class DummyLLMClient:
        def __init__(self, cfg):
            pass

    class DummyIssueBriefGenerator:
        def __init__(self, llm):
            pass

        def generate(self, issue, reason="", profile_context=None):
            return IssueBrief(**_issue_brief_payload(agent_prompt="请先定位 tokenizer cache 并写最小复现测试。"))

    monkeypatch.setattr(osmind.engine.llm, "LLMClient", DummyLLMClient)
    monkeypatch.setattr(osmind.engine.issue_brief, "IssueBriefGenerator", DummyIssueBriefGenerator)

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        discover = app.query_one(DiscoverScreen)
        table = app.query_one(IssueTable)
        table.populate([issue])
        table.cursor_coordinate = (0, 0)
        discover._issues_by_number = {str(issue.number): issue}

        await discover.action_start_work()

    markdown = (temp_config.notes_vault / "osmind" / "o_r" / "issue-42-tokenizer-leak.md").read_text(encoding="utf-8")
    assert "## Agent Prompt" in markdown
    assert "请先定位 tokenizer cache 并写最小复现测试。" in markdown
    assert "## First 30 Minutes" in markdown
```

- [ ] **Step 2: Run the new test and confirm failure if brief is not generated**

Run:

```bash
python -m pytest tests/test_tui.py::test_discover_start_work_writes_pack_with_agent_prompt -q
```

Expected: failure if `action_start_work` writes the pack without generating a missing brief.

- [ ] **Step 3: Add a shared async brief loader in Discover**

In `osmind/tui/screens/discover.py`, add:

```python
async def _load_or_generate_issue_brief(self, issue):
    brief = self._cached_issue_brief(issue)
    if brief is not None:
        return brief

    from osmind.engine.issue_brief import IssueBriefGenerator
    from osmind.engine.llm import LLMClient

    llm = LLMClient(self.app.config.llm)

    def generate_and_store():
        generated = IssueBriefGenerator(llm).generate(
            issue,
            reason=issue.reason,
            profile_context=self._issue_brief_profile_context(),
        )
        self._cache().update_issue_brief(issue.repo, issue.number, generated.to_json())
        return generated

    return await asyncio.to_thread(generate_and_store)
```

Then update `action_view_issue` to call:

```python
brief = await self._load_or_generate_issue_brief(issue)
brief_markdown = render_issue_brief_markdown(brief)
```

Update `action_start_work`, `_set_issue_decision`, and `action_generate_pack` so they call the loader before writing an issue pack:

```python
brief = await self._load_or_generate_issue_brief(issue)
path = await asyncio.to_thread(lambda: self._library().write_issue_pack(issue, brief=brief))
```

For synchronous `action_open_pack`, do not generate briefs; opening should only open an existing pack.

- [ ] **Step 4: Keep pack generation working when brief generation fails**

Wrap the loader in `action_start_work` and `action_generate_pack`:

```python
try:
    brief = await self._load_or_generate_issue_brief(issue)
except Exception:
    log_exception(
        self.app.config.notes_vault,
        f"Failed to generate Issue Brief before writing pack for {issue.repo}#{issue.number}",
    )
    brief = None
path = await asyncio.to_thread(lambda: self._library().write_issue_pack(issue, brief=brief))
```

This preserves the acceptance criterion that pack generation still works without a brief.

- [ ] **Step 5: Run start-work focused tests**

Run:

```bash
python -m pytest tests/test_tui.py::test_discover_start_work_writes_pack_with_agent_prompt tests/test_tui.py::test_discover_start_work_generates_pack_and_marks_continue tests/test_tui.py::test_discover_generate_pack_writes_issue_pack_with_brief -q
```

Expected: selected tests pass after updating any old fixture fields.

- [ ] **Step 6: Commit Task 5**

```bash
git add osmind/tui/screens/discover.py tests/test_tui.py
git commit -m "feat: generate issue briefs before start work"
```

## Task 6: Error Handling And Regression Coverage

**Files:**
- Modify: `tests/test_tui.py`
- Modify: `osmind/tui/screens/discover.py` if needed

- [ ] **Step 1: Add a test for detail view failure preserving source**

Append to `tests/test_tui.py`:

```python
@pytest.mark.asyncio
async def test_discover_view_issue_keeps_original_text_when_brief_generation_fails(temp_config, monkeypatch):
    from osmind.github.models import GHIssue
    from osmind.tui.screens.discover import DiscoverScreen
    from osmind.tui.widgets.issue_list import IssueTable
    from textual.widgets import Static
    from osmind.engine.issue_brief import IssueBriefGenerationError
    import osmind.engine.issue_brief
    import osmind.engine.llm

    issue = GHIssue(42, "Tokenizer leak", "Original body stays visible.", ["bug"], "u", "o/r", "open")

    class DummyLLMClient:
        def __init__(self, cfg):
            pass

    class FailingIssueBriefGenerator:
        def __init__(self, llm):
            pass

        def generate(self, issue, reason="", profile_context=None):
            raise IssueBriefGenerationError("Failed to parse issue brief JSON")

    monkeypatch.setattr(osmind.engine.llm, "LLMClient", DummyLLMClient)
    monkeypatch.setattr(osmind.engine.issue_brief, "IssueBriefGenerator", FailingIssueBriefGenerator)

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        discover = app.query_one(DiscoverScreen)
        table = app.query_one(IssueTable)
        table.populate([issue])
        table.cursor_coordinate = (0, 0)
        discover._issues_by_number = {str(issue.number): issue}

        await discover.action_view_issue()

        source = app.query_one("#issue-source-panel", Static).renderable

    assert "Issue Brief 生成失败" in str(source)
    assert "Original body stays visible." in str(source)
    assert (temp_config.notes_vault / "osmind" / ".cache" / "osmind.log").exists()
```

- [ ] **Step 2: Add a test for pack fallback without brief**

Append:

```python
@pytest.mark.asyncio
async def test_discover_start_work_writes_basic_pack_when_brief_generation_fails(temp_config, monkeypatch):
    from osmind.github.models import GHIssue
    from osmind.tui.screens.discover import DiscoverScreen
    from osmind.tui.widgets.issue_list import IssueTable
    from osmind.engine.issue_brief import IssueBriefGenerationError
    import osmind.engine.issue_brief
    import osmind.engine.llm

    issue = GHIssue(42, "Tokenizer leak", "Body", ["bug"], "u", "o/r", "open")

    class DummyLLMClient:
        def __init__(self, cfg):
            pass

    class FailingIssueBriefGenerator:
        def __init__(self, llm):
            pass

        def generate(self, issue, reason="", profile_context=None):
            raise IssueBriefGenerationError("Failed to parse issue brief JSON")

    monkeypatch.setattr(osmind.engine.llm, "LLMClient", DummyLLMClient)
    monkeypatch.setattr(osmind.engine.issue_brief, "IssueBriefGenerator", FailingIssueBriefGenerator)

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        discover = app.query_one(DiscoverScreen)
        table = app.query_one(IssueTable)
        table.populate([issue])
        table.cursor_coordinate = (0, 0)
        discover._issues_by_number = {str(issue.number): issue}

        await discover.action_start_work()

    markdown = (temp_config.notes_vault / "osmind" / "o_r" / "issue-42-tokenizer-leak.md").read_text(encoding="utf-8")
    assert "## What This Is" in markdown
    assert "## Recommendation Snapshot" in markdown
    assert "## Notes" in markdown
```

- [ ] **Step 3: Run failure tests**

Run:

```bash
python -m pytest tests/test_tui.py::test_discover_view_issue_keeps_original_text_when_brief_generation_fails tests/test_tui.py::test_discover_start_work_writes_basic_pack_when_brief_generation_fails -q
```

Expected: pass if Task 5 implemented fallback correctly; otherwise fail with missing source text or missing pack.

- [ ] **Step 4: Patch Discover only if tests fail**

If detail view failure does not preserve source, ensure the `except` block in `action_view_issue` updates source with:

```python
source.update(_format_issue_source(issue, f"Issue Brief 生成失败，详情见 {log_path}"))
```

If start-work failure blocks pack generation, ensure the `action_start_work` fallback from Task 5 catches exceptions from `_load_or_generate_issue_brief` and continues with `brief = None`.

- [ ] **Step 5: Run broader TUI tests**

Run:

```bash
python -m pytest tests/test_tui.py -q
```

Expected: all TUI tests pass.

- [ ] **Step 6: Commit Task 6**

```bash
git add osmind/tui/screens/discover.py tests/test_tui.py
git commit -m "test: cover issue brief failure fallbacks"
```

## Task 7: Final Verification And Documentation Check

**Files:**
- Possibly modify: `README.md`
- Verify: full repository

- [ ] **Step 1: Search docs for stale section names**

Run:

```bash
rg -n "First 10 Minutes|Agent Exploration Prompt|plain_explanation|likely_files|agent_questions|Difficulty / Readiness" README.md tests osmind
```

Expected: remaining matches are only for PR packs or legacy tests intentionally not part of issue brief. If README describes issue packs using stale names, update it to use `First 30 Minutes` and `Agent Prompt`.

- [ ] **Step 2: Run all tests**

Run:

```bash
python -m pytest -q
```

Expected: all tests pass.

- [ ] **Step 3: Run diff hygiene check**

Run:

```bash
git diff --check
```

Expected: no output.

- [ ] **Step 4: Inspect changed files**

Run:

```bash
git status --short
git diff --stat
```

Expected: only files from this plan are modified. If unrelated files appear, do not revert them automatically; inspect whether they were pre-existing user changes and leave them out of the commit.

- [ ] **Step 5: Commit final doc or cleanup changes**

If README changed:

```bash
git add README.md
git commit -m "docs: describe enhanced issue detail workflow"
```

If README did not change, skip this commit.

- [ ] **Step 6: Final manual smoke path**

Run:

```bash
python -m pytest tests/test_tui.py::test_discover_view_issue_separates_analysis_from_source tests/test_tui.py::test_discover_start_work_writes_pack_with_agent_prompt -q
```

Expected: both tests pass, proving the core user loop still works after full-suite changes.

## Self-Review

- Spec coverage: Detail view brief, profile fit, risks, first steps, validation path, agent prompt, cache reuse/staleness, pack output, and failure fallback each have a task.
- Non-goals respected: no PR discovery, chatbot, full localization, automatic agent launch, or copy-to-clipboard.
- Placeholder scan: the plan contains no implementation placeholders; all code-changing steps include concrete snippets.
- Type consistency: `IssueBrief`, `IssueBriefMetadata`, `IssueBriefProfileContext`, `IssueBriefGenerationError`, `issue_brief_metadata`, and `is_issue_brief_current` are defined before later tasks use them.
- Test strategy: every implementation task begins with failing focused tests, then runs focused tests, then commits.
