# Open Resources + First-Launch Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hand-edited `profile.yaml` onboarding with an interactive first-launch wizard, and change `resources` from a fixed `gpus/time` dict into a free-form list of human-written strings backed by an LLM-extracted facet cache that the ranker consumes.

**Architecture:** Three concerns kept separate. (1) `resources` becomes `list[str]` end-to-end with a backward-compatible dict→list migration in `Config.from_file`, so every existing profile still loads. (2) A new `osmind/engine/resources.py` module owns facet extraction (one LLM call) plus a signature-keyed JSON cache living under the notes vault. (3) A new `osmind/wizard.py` uses `rich.prompt` (we already depend on `rich`) for an interactive first-launch flow, with `osmind init` as the explicit re-entry. The Ranker prompt now sees both raw user text and the structured facets, with graceful fallback if the LLM facet step fails.

**Tech Stack:** Python dataclasses, `PyYAML`, `rich.prompt`, existing `LLMClient`, existing SQLite cache, pytest.

---

## File Structure

- Create `osmind/engine/resources.py`
  - `ResourceFacet` dataclass, `extract_facets(resources, llm)` LLM call, `load_cached_facets`/`save_cached_facets`, `ensure_facets(resources, llm, cache_path)` orchestrator.
- Create `osmind/wizard.py`
  - `run_wizard(target_path: Path) -> Config` — interactive prompts, writes `profile.yaml`, returns parsed `Config`.
- Modify `osmind/config.py`
  - Change `Config.resources` to `list[str]`; `from_file` migrates legacy dict shape transparently.
- Modify `osmind/tui/lifecycle.py`
  - `resources_hash` accepts `list[str]`.
- Modify `osmind/engine/ranker.py`
  - `Ranker` accepts `resources: list[str]` and optional `resources_facets: list[ResourceFacet]`; updates prompt template; helper `_format_resources` rewritten.
- Modify `osmind/decision.py`
  - `_format_resources` rewritten to accept `list[str]`; signatures of `explain_issue_decision`, `format_decision_panel`, `format_decision_markdown` updated.
- Modify `osmind/tui/workflow.py`
  - `_format_resources` rewritten to accept `list[str]`.
- Modify `osmind/tui/screens/settings.py`
  - Resources section renders bullet list and facet cache freshness; drops `_format_mapping`.
- Modify `osmind/tui/app.py`
  - `main` becomes argv-aware: `osmind` and `osmind init` paths; calls wizard when profile is missing; pre-warms facets after Config load.
- Modify `profile.yaml.example`
  - New `resources:` shape (list of strings).
- Modify `README.md`
  - Update install/configure section to document the wizard and the new resources format.
- Create `tests/test_resources_facets.py`
- Create `tests/test_wizard.py`
- Modify `tests/test_config.py`, `tests/test_ranker.py`, `tests/test_decision_explanation.py`, `tests/test_workflow.py`

---

## Task 1: Migrate `Config.resources` to `list[str]` with Backward Compatibility

**Files:**
- Modify: `osmind/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing test for list-of-strings resources**

```python
# tests/test_config.py — append at end of file

LIST_SAMPLE = """
interests: [RL post-training]
skills: [Python]
resources:
  - "4x RTX 4090, evenings only"
  - "company forbids direct PR; fork required"
  - "8 hours per week"
watching:
  - repo: THUDM/slime
notes_vault: ~/workspace/Note
llm:
  base_url: http://localhost:30000/v1
  model: test-model
  api_key: sk-test
external_agents:
  claude_code: claude
  codex: codex
"""


def test_resources_loaded_as_list_of_strings(tmp_path):
    p = tmp_path / "profile.yaml"
    p.write_text(LIST_SAMPLE)
    cfg = Config.from_file(p)
    assert cfg.resources == [
        "4x RTX 4090, evenings only",
        "company forbids direct PR; fork required",
        "8 hours per week",
    ]


def test_legacy_dict_resources_are_migrated_to_list(tmp_path):
    p = tmp_path / "profile.yaml"
    # Existing profile.yaml.example shape
    legacy = """
interests: [RL post-training]
skills: [Python]
resources:
  gpus: "4x RTX 4090"
  time: part-time
watching:
  - repo: THUDM/slime
notes_vault: ~/workspace/Note
llm:
  base_url: http://localhost:30000/v1
  model: test-model
  api_key: sk-test
external_agents:
  claude_code: claude
  codex: codex
"""
    p.write_text(legacy)
    cfg = Config.from_file(p)
    assert cfg.resources == ["gpus: 4x RTX 4090", "time: part-time"]


def test_missing_resources_is_empty_list(tmp_path):
    p = tmp_path / "profile.yaml"
    p.write_text(LIST_SAMPLE.replace('resources:\n  - "4x RTX 4090, evenings only"\n  - "company forbids direct PR; fork required"\n  - "8 hours per week"', ""))
    cfg = Config.from_file(p)
    assert cfg.resources == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py::test_resources_loaded_as_list_of_strings tests/test_config.py::test_legacy_dict_resources_are_migrated_to_list tests/test_config.py::test_missing_resources_is_empty_list -v`
Expected: FAIL — `cfg.resources` is still a dict.

- [ ] **Step 3: Update `Config.resources` to `list[str]` and add migration in `from_file`**

```python
# osmind/config.py — replace the dataclass field and from_file body for resources

@dataclass
class Config:
    interests: list[str]
    skills: list[str]
    resources: list[str]
    watching: list[dict]
    notes_vault: Path
    llm: LLMConfig
    external_agents: AgentConfig

    @classmethod
    def from_file(cls, path: Path) -> "Config":
        data = yaml.safe_load(path.read_text())
        for field in ("interests", "skills", "watching", "notes_vault", "llm", "external_agents"):
            if field not in data:
                raise ConfigError(f"Missing required field: {field}")
        llm = data["llm"]
        agents = data["external_agents"]
        return cls(
            interests=data["interests"],
            skills=data["skills"],
            resources=_normalize_resources(data.get("resources")),
            watching=data["watching"],
            notes_vault=Path(data["notes_vault"]).expanduser(),
            llm=LLMConfig(
                base_url=llm["base_url"],
                model=llm["model"],
                api_key=llm.get("api_key", ""),
                enable_thinking=llm.get("enable_thinking", False),
            ),
            external_agents=AgentConfig(
                claude_code=agents.get("claude_code", "claude"),
                codex=agents.get("codex", "codex"),
            ),
        )


def _normalize_resources(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, dict):
        return [f"{key}: {val}" for key, val in value.items() if str(val).strip()]
    raise ConfigError(f"resources must be a list or mapping, got {type(value).__name__}")
```

- [ ] **Step 4: Run config tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: PASS (all four cases).

- [ ] **Step 5: Commit**

```bash
git add osmind/config.py tests/test_config.py
git commit -m "feat: accept resources as list of strings with dict back-compat"
```

---

## Task 2: Propagate `list[str]` Through Display Helpers and Hash

**Files:**
- Modify: `osmind/tui/lifecycle.py`
- Modify: `osmind/decision.py`
- Modify: `osmind/tui/workflow.py`
- Modify: `osmind/tui/screens/settings.py`
- Test: `tests/test_decision_explanation.py`, `tests/test_workflow.py`

- [ ] **Step 1: Write failing tests for list-shaped resources rendering**

```python
# tests/test_decision_explanation.py — add

def test_format_decision_panel_renders_resources_list():
    from osmind.decision import format_decision_panel
    from osmind.github.models import GHIssue
    issue = GHIssue(
        number=1, title="t", body="b", labels=[], url="u", repo="r", state="open",
    )
    panel = format_decision_panel(issue, ["4x RTX 4090", "8 hours per week"])
    assert "Configured Resources:" in panel
    assert "4x RTX 4090" in panel
    assert "8 hours per week" in panel


def test_format_decision_panel_handles_empty_resources():
    from osmind.decision import format_decision_panel
    from osmind.github.models import GHIssue
    issue = GHIssue(number=1, title="t", body="b", labels=[], url="u", repo="r", state="open")
    panel = format_decision_panel(issue, [])
    assert "unspecified" in panel
```

```python
# tests/test_workflow.py — add

def test_format_start_work_renders_resources_list():
    from osmind.tui.workflow import format_start_work_from_packet
    markdown = (
        "---\n"
        "source_type: issue\nnumber: 1\ntitle: t\nrepo: r/x\nurl: u\ndecision: continue\n"
        "---\n## First 10 Minutes\nread the code\n"
    )
    rendered = format_start_work_from_packet(
        markdown,
        ["4x RTX 4090", "evenings only"],
    )
    assert "4x RTX 4090" in rendered
    assert "evenings only" in rendered
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_decision_explanation.py::test_format_decision_panel_renders_resources_list tests/test_decision_explanation.py::test_format_decision_panel_handles_empty_resources tests/test_workflow.py::test_format_start_work_renders_resources_list -v`
Expected: FAIL — current helpers iterate dict items.

- [ ] **Step 3: Update `resources_hash` to accept `list[str]`**

```python
# osmind/tui/lifecycle.py — replace body

from __future__ import annotations

import hashlib
import json


def resources_hash(resources: list[str] | None) -> str:
    if not resources:
        return ""
    payload = json.dumps(list(resources), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Update `_format_resources` in decision.py, workflow.py**

```python
# osmind/decision.py — replace _format_resources and update type hints on
# explain_issue_decision, format_decision_panel, format_decision_markdown

def _format_resources(resources: list[str] | None) -> str:
    if not resources:
        return "unspecified"
    return "; ".join(resources)


def explain_issue_decision(issue: GHIssue, resources: list[str] | None = None) -> DecisionExplanation:
    # ... body unchanged except resources type
    ...


def format_decision_panel(issue: GHIssue, resources: list[str] | None = None) -> str:
    ...


def format_decision_markdown(issue: GHIssue, resources: list[str] | None = None) -> str:
    ...
```

```python
# osmind/tui/workflow.py — replace _format_resources and update the signature

def format_start_work_from_packet(markdown: str, resources: list[str] | None = None) -> str:
    # ... body unchanged except resources type
    ...


def _format_resources(resources: list[str] | None) -> str:
    if not resources:
        return "unspecified"
    return "; ".join(resources)
```

- [ ] **Step 5: Update `SettingsScreen` rendering**

```python
# osmind/tui/screens/settings.py — replace _format_health resources section
# and remove _format_mapping

def _format_health(config) -> str:
    token = os.environ.get("GITHUB_TOKEN", "")
    vault = config.notes_vault
    cache_path = vault / "osmind" / ".cache" / "osmind.db"
    resources_lines = _format_resources_block(config.resources)
    watching = ", ".join(repo["repo"] for repo in config.watching) if config.watching else "none"
    claude_status = _command_status(config.external_agents.claude_code)
    codex_status = _command_status(config.external_agents.codex)

    return "\n".join(
        [
            "[bold]Settings / Health[/bold]",
            "",
            f"GitHub token: {_status('OK' if token else 'Missing')} GITHUB_TOKEN",
            f"LLM: {_status('Configured' if config.llm.base_url and config.llm.model else 'Missing')} "
            f"{config.llm.model} @ {config.llm.base_url}",
            f"Notes vault: {_status('OK' if vault.exists() else 'Will create')} {vault}",
            f"Cache: {cache_path}",
            "Resources:",
            resources_lines,
            f"Watching: {watching}",
            f"Claude Code: {claude_status}",
            f"Codex: {codex_status}",
            "",
            "[dim]u: reload health status[/dim]",
        ]
    )


def _format_resources_block(resources: list[str]) -> str:
    if not resources:
        return "  not configured"
    return "\n".join(f"  - {item}" for item in resources)
```

- [ ] **Step 6: Update callsites that still pass dicts**

Run: `grep -n "self.app.config.resources" osmind/tui/`
Confirm: every callsite now passes a list; no dict accesses remain. The signatures were already typed `dict | None` in some places — those `| None` paths are now `list[str] | None`. No behavior change needed in `services/library.py`/`packs/generator.py` other than updating the type hint:

```python
# osmind/services/library.py — change the type only

class PackLibrary:
    def __init__(self, notes_vault: Path, cache_path: Path, resources: list[str] | None = None):
        ...
        self.resources = resources or []
```

```python
# osmind/packs/generator.py — change the type only

@staticmethod
def from_issue(issue: GHIssue, resources: list[str] | None = None, brief: IssueBrief | None = None) -> LearningPack:
    ...
```

- [ ] **Step 7: Run full test suite to verify nothing else regresses**

Run: `pytest -q`
Expected: PASS for the new tests, no regressions. Existing `test_ranker.py::test_ranker_scores_resource_fit_and_includes_resources_in_prompt` will fail because it passes a dict — that's Task 3's job to fix.

If `test_ranker.py` fails on the dict input but no other tests fail, this task is good. Proceed.

- [ ] **Step 8: Commit**

```bash
git add osmind/tui/lifecycle.py osmind/decision.py osmind/tui/workflow.py osmind/tui/screens/settings.py osmind/services/library.py osmind/packs/generator.py tests/test_decision_explanation.py tests/test_workflow.py
git commit -m "refactor: render resources as bullet list throughout the UI"
```

---

## Task 3: Resource Facet Model + Cache I/O

**Files:**
- Create: `osmind/engine/resources.py`
- Test: `tests/test_resources_facets.py`

- [ ] **Step 1: Write failing tests for facet dataclass and cache round-trip**

```python
# tests/test_resources_facets.py — new file

import json
from pathlib import Path

from osmind.engine.resources import (
    ResourceFacet,
    load_cached_facets,
    save_cached_facets,
    resources_signature,
)


def test_resource_facet_roundtrip_dict():
    facet = ResourceFacet(
        text="4x RTX 4090",
        kind="hardware",
        polarity="enabling",
        strength="medium",
    )
    data = facet.to_dict()
    assert data == {
        "text": "4x RTX 4090",
        "kind": "hardware",
        "polarity": "enabling",
        "strength": "medium",
    }
    assert ResourceFacet.from_dict(data) == facet


def test_resources_signature_is_stable():
    a = resources_signature(["x", "y"])
    b = resources_signature(["x", "y"])
    c = resources_signature(["y", "x"])
    assert a == b
    assert a != c  # order matters; user wrote it that way


def test_save_and_load_facets_roundtrip(tmp_path):
    cache_path = tmp_path / "resources_facets.json"
    facets = [
        ResourceFacet(text="4x RTX 4090", kind="hardware", polarity="enabling", strength="medium"),
        ResourceFacet(text="evenings only", kind="time", polarity="limiting", strength="soft"),
    ]
    signature = resources_signature(["4x RTX 4090", "evenings only"])
    save_cached_facets(cache_path, signature, facets)

    loaded = load_cached_facets(cache_path, signature)
    assert loaded == facets


def test_load_cached_facets_signature_mismatch_returns_none(tmp_path):
    cache_path = tmp_path / "resources_facets.json"
    save_cached_facets(cache_path, "old-sig", [
        ResourceFacet(text="x", kind="other", polarity="enabling", strength="soft"),
    ])
    assert load_cached_facets(cache_path, "new-sig") is None


def test_load_cached_facets_missing_file_returns_none(tmp_path):
    cache_path = tmp_path / "absent.json"
    assert load_cached_facets(cache_path, "any") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_resources_facets.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the dataclass and cache I/O**

```python
# osmind/engine/resources.py — new file

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path


VALID_KINDS = {"hardware", "time", "skill", "policy", "location", "other"}
VALID_POLARITIES = {"enabling", "limiting"}
VALID_STRENGTHS = {"soft", "medium", "hard"}


@dataclass(frozen=True)
class ResourceFacet:
    text: str
    kind: str
    polarity: str
    strength: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "ResourceFacet":
        return cls(
            text=str(data.get("text", "")),
            kind=_normalize(data.get("kind"), VALID_KINDS, "other"),
            polarity=_normalize(data.get("polarity"), VALID_POLARITIES, "limiting"),
            strength=_normalize(data.get("strength"), VALID_STRENGTHS, "medium"),
        )


def resources_signature(resources: list[str]) -> str:
    payload = json.dumps(list(resources), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_cached_facets(cache_path: Path, signature: str) -> list[ResourceFacet] | None:
    if not cache_path.exists():
        return None
    try:
        raw = json.loads(cache_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if raw.get("signature") != signature:
        return None
    items = raw.get("items") or []
    return [ResourceFacet.from_dict(item) for item in items if isinstance(item, dict)]


def save_cached_facets(cache_path: Path, signature: str, facets: list[ResourceFacet]) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "signature": signature,
        "items": [facet.to_dict() for facet in facets],
    }
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


def _normalize(value, allowed: set[str], fallback: str) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in allowed else fallback
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_resources_facets.py -v`
Expected: PASS (all five cases).

- [ ] **Step 5: Commit**

```bash
git add osmind/engine/resources.py tests/test_resources_facets.py
git commit -m "feat: add resource facet model and signature-keyed cache"
```

---

## Task 4: LLM-Backed Facet Extraction with Fallback

**Files:**
- Modify: `osmind/engine/resources.py`
- Test: `tests/test_resources_facets.py`

- [ ] **Step 1: Write failing tests for `extract_facets` and `ensure_facets`**

```python
# tests/test_resources_facets.py — append

from unittest.mock import MagicMock

from osmind.engine.resources import extract_facets, ensure_facets


def test_extract_facets_parses_valid_json():
    llm = MagicMock()
    llm.chat.return_value = (
        '{"items": ['
        '{"text": "4x RTX 4090", "kind": "hardware", "polarity": "enabling", "strength": "medium"},'
        '{"text": "evenings only", "kind": "time", "polarity": "limiting", "strength": "soft"}'
        ']}'
    )
    facets = extract_facets(["4x RTX 4090", "evenings only"], llm)
    assert facets == [
        ResourceFacet(text="4x RTX 4090", kind="hardware", polarity="enabling", strength="medium"),
        ResourceFacet(text="evenings only", kind="time", polarity="limiting", strength="soft"),
    ]
    prompt = llm.chat.call_args.args[1]
    assert "4x RTX 4090" in prompt
    assert "evenings only" in prompt


def test_extract_facets_returns_other_facets_on_invalid_json():
    llm = MagicMock()
    llm.chat.return_value = "not json"
    facets = extract_facets(["4x RTX 4090"], llm)
    assert facets == [
        ResourceFacet(text="4x RTX 4090", kind="other", polarity="limiting", strength="medium"),
    ]


def test_extract_facets_empty_input_skips_llm():
    llm = MagicMock()
    assert extract_facets([], llm) == []
    llm.chat.assert_not_called()


def test_ensure_facets_uses_cache_when_signature_matches(tmp_path):
    llm = MagicMock()
    cache_path = tmp_path / "resources_facets.json"
    resources = ["a", "b"]
    signature = resources_signature(resources)
    save_cached_facets(cache_path, signature, [
        ResourceFacet(text="a", kind="other", polarity="enabling", strength="soft"),
        ResourceFacet(text="b", kind="other", polarity="enabling", strength="soft"),
    ])
    facets = ensure_facets(resources, llm, cache_path)
    assert len(facets) == 2
    llm.chat.assert_not_called()


def test_ensure_facets_regenerates_when_signature_mismatches(tmp_path):
    llm = MagicMock()
    llm.chat.return_value = (
        '{"items": ['
        '{"text": "c", "kind": "skill", "polarity": "enabling", "strength": "medium"}'
        ']}'
    )
    cache_path = tmp_path / "resources_facets.json"
    save_cached_facets(cache_path, "stale", [
        ResourceFacet(text="old", kind="other", polarity="enabling", strength="soft"),
    ])
    facets = ensure_facets(["c"], llm, cache_path)
    assert facets == [
        ResourceFacet(text="c", kind="skill", polarity="enabling", strength="medium"),
    ]
    # Cache was updated
    reloaded = load_cached_facets(cache_path, resources_signature(["c"]))
    assert reloaded == facets
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_resources_facets.py -v`
Expected: FAIL — functions not yet defined.

- [ ] **Step 3: Implement `extract_facets` and `ensure_facets`**

```python
# osmind/engine/resources.py — append

_FACET_SYSTEM = """\
You parse a user's free-form resource and constraint descriptions into structured facets so a recommender can use them.
For each input string return: {"text": "<original>", "kind": "<...>", "polarity": "<...>", "strength": "<...>"}.
kind: one of hardware, time, skill, policy, location, other.
polarity: enabling if the line gives the user more capability, limiting if it constrains them.
strength: soft for preferences, medium for typical limits, hard for blockers.
Return only valid JSON of shape {"items": [...]} with no markdown."""


def extract_facets(resources: list[str], llm) -> list[ResourceFacet]:
    if not resources:
        return []
    user_prompt = "\n".join(f"{idx + 1}. {item}" for idx, item in enumerate(resources))
    raw = llm.chat(_FACET_SYSTEM, user_prompt, max_tokens=512)
    try:
        data = json.loads(raw)
        items = data.get("items") or []
        parsed = [ResourceFacet.from_dict(item) for item in items if isinstance(item, dict)]
    except (json.JSONDecodeError, AttributeError):
        parsed = []
    if not parsed:
        return [_default_facet(text) for text in resources]
    return parsed


def ensure_facets(resources: list[str], llm, cache_path: Path) -> list[ResourceFacet]:
    signature = resources_signature(resources)
    cached = load_cached_facets(cache_path, signature)
    if cached is not None:
        return cached
    facets = extract_facets(resources, llm)
    if resources:
        save_cached_facets(cache_path, signature, facets)
    return facets


def _default_facet(text: str) -> ResourceFacet:
    return ResourceFacet(text=text, kind="other", polarity="limiting", strength="medium")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_resources_facets.py -v`
Expected: PASS (all cases including Task 3's).

- [ ] **Step 5: Commit**

```bash
git add osmind/engine/resources.py tests/test_resources_facets.py
git commit -m "feat: extract resource facets via LLM with cache and fallback"
```

---

## Task 5: Wire `Ranker` to Consume Resources List + Facets

**Files:**
- Modify: `osmind/engine/ranker.py`
- Test: `tests/test_ranker.py`

- [ ] **Step 1: Update existing test that passed a dict; add facet-aware test**

```python
# tests/test_ranker.py — replace test_ranker_scores_resource_fit_and_includes_resources_in_prompt
# and add a new test below it

def test_ranker_scores_resource_fit_and_includes_resources_in_prompt():
    from osmind.engine.ranker import Ranker
    from osmind.github.models import GHIssue

    mock_llm = MagicMock()
    mock_llm.chat.return_value = (
        '{"score": 0.2, "priority": "low", "fit": "high", '
        '"resource_fit": "blocked", "actionability": "low", '
        '"reason": "主题匹配，但当前 GPU 资源不足以复现"}'
    )
    ranker = Ranker(
        llm=mock_llm,
        interests=["large model inference"],
        skills=["Python"],
        resources=["4x RTX 4090", "part-time, evenings only"],
    )
    issue = GHIssue(
        number=7,
        title="DeepSeek V4Pro reproduction fails",
        body="Requires reproducing with the full model.",
        labels=["bug"],
        url="https://github.com/x/y/issues/7",
        repo="x/y",
        state="open",
    )
    scored = ranker.score_one(issue)
    prompt = mock_llm.chat.call_args.args[1]
    assert "User resources:" in prompt
    assert "4x RTX 4090" in prompt
    assert "part-time, evenings only" in prompt
    assert scored.resource_fit == "blocked"


def test_ranker_includes_facets_in_prompt_when_provided():
    from osmind.engine.ranker import Ranker
    from osmind.engine.resources import ResourceFacet
    from osmind.github.models import GHIssue

    mock_llm = MagicMock()
    mock_llm.chat.return_value = '{"score": 0.5, "reason": "x"}'
    ranker = Ranker(
        llm=mock_llm,
        interests=["x"],
        skills=["y"],
        resources=["company forbids direct PR; fork required"],
        resources_facets=[
            ResourceFacet(
                text="company forbids direct PR; fork required",
                kind="policy",
                polarity="limiting",
                strength="hard",
            ),
        ],
    )
    issue = GHIssue(number=1, title="t", body="b", labels=[], url="u", repo="r", state="open")
    ranker.score_one(issue)
    prompt = mock_llm.chat.call_args.args[1]
    assert "policy" in prompt
    assert "limiting" in prompt
    assert "hard" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ranker.py -v`
Expected: FAIL — `Ranker` still expects a dict and ignores facets.

- [ ] **Step 3: Update `Ranker` to accept list resources + optional facets**

```python
# osmind/engine/ranker.py — replace the class and helpers

from __future__ import annotations
import json
from osmind.engine.llm import LLMClient
from osmind.engine.resources import ResourceFacet
from osmind.github.models import GHIssue


_SYSTEM = """\
You are a contribution opportunity scorer. Given a user profile, their resources/constraints, and a GitHub issue, return a JSON object:
{
  "score": <float 0-1>,
  "priority": "high" | "medium" | "low",
  "fit": "high" | "medium" | "low",
  "resource_fit": "ok" | "risk" | "blocked",
  "actionability": "high" | "medium" | "low",
  "reason": "<one sentence in Chinese explaining the recommendation and any resource constraint>"
}
Treat any resource line marked polarity=limiting and strength=hard as a likely blocker.
Only return valid JSON, no markdown."""

_UNKNOWN = "unknown"
_LEVELS = {"high", "medium", "low", _UNKNOWN}
_RESOURCE_FIT = {"ok", "risk", "blocked", _UNKNOWN}


class Ranker:
    def __init__(
        self,
        llm: LLMClient,
        interests: list[str],
        skills: list[str],
        resources: list[str] | None = None,
        resources_facets: list[ResourceFacet] | None = None,
    ):
        self._llm = llm
        self._interests = interests
        self._skills = skills
        self._resources = resources or []
        self._resources_facets = resources_facets or []

    def _score_issue(self, issue: GHIssue) -> dict:
        prompt = (
            f"User interests: {', '.join(self._interests)}\n"
            f"User skills: {', '.join(self._skills)}\n\n"
            f"User resources:\n{_format_resources(self._resources, self._resources_facets)}\n\n"
            f"Issue #{issue.number}: {issue.title}\n"
            f"Labels: {', '.join(issue.labels)}\n"
            f"Body: {issue.body[:400]}"
        )
        raw = self._llm.chat(_SYSTEM, prompt, max_tokens=128)
        try:
            data = json.loads(raw)
            return {
                "score": float(data["score"]),
                "priority": _normalize_level(data.get("priority")),
                "fit": _normalize_level(data.get("fit")),
                "resource_fit": _normalize_resource_fit(data.get("resource_fit")),
                "actionability": _normalize_level(data.get("actionability")),
                "reason": str(data.get("reason", "")),
            }
        except (json.JSONDecodeError, KeyError, ValueError):
            return {
                "score": 0.0,
                "priority": _UNKNOWN,
                "fit": _UNKNOWN,
                "resource_fit": _UNKNOWN,
                "actionability": _UNKNOWN,
                "reason": "",
            }

    def score_one(self, issue: GHIssue) -> GHIssue:
        result = self._score_issue(issue)
        issue.score = result["score"]
        issue.reason = result["reason"]
        issue.priority = result["priority"]
        issue.fit = result["fit"]
        issue.resource_fit = result["resource_fit"]
        issue.actionability = result["actionability"]
        return issue

    def rank(self, issues: list[GHIssue]) -> list[GHIssue]:
        for issue in issues:
            self.score_one(issue)
        return sorted(issues, key=lambda i: i.score, reverse=True)


def _format_resources(resources: list[str], facets: list[ResourceFacet]) -> str:
    if not resources:
        return "- unspecified"
    facet_by_text = {facet.text: facet for facet in facets}
    lines = []
    for item in resources:
        facet = facet_by_text.get(item)
        if facet is None:
            lines.append(f"- {item}")
        else:
            lines.append(
                f"- {item}  [kind={facet.kind}, polarity={facet.polarity}, strength={facet.strength}]"
            )
    return "\n".join(lines)


def _normalize_level(value) -> str:
    normalized = str(value or _UNKNOWN).strip().lower()
    if normalized == "med":
        normalized = "medium"
    return normalized if normalized in _LEVELS else _UNKNOWN


def _normalize_resource_fit(value) -> str:
    normalized = str(value or _UNKNOWN).strip().lower()
    return normalized if normalized in _RESOURCE_FIT else _UNKNOWN
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ranker.py -v`
Expected: PASS for both updated tests.

- [ ] **Step 5: Update `discover.py` to construct the Ranker with facets**

```python
# osmind/tui/screens/discover.py — replace the existing Ranker construction
# at ~line 414. Search for: ranker = Ranker(llm, interests, skills, resources)

# Before:
#   ranker = Ranker(llm, interests, skills, resources)
# After:
        from osmind.engine.resources import ensure_facets

        resources_cache = self.app.config.notes_vault / "osmind" / ".cache" / "resources_facets.json"
        facets = ensure_facets(resources, llm, resources_cache)
        ranker = Ranker(llm, interests, skills, resources, resources_facets=facets)
```

- [ ] **Step 6: Run full test suite — only TUI integration tests should remain to verify**

Run: `pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add osmind/engine/ranker.py osmind/tui/screens/discover.py tests/test_ranker.py
git commit -m "feat: feed resource facets into Ranker prompt"
```

---

## Task 6: First-Launch Wizard Module

**Files:**
- Create: `osmind/wizard.py`
- Test: `tests/test_wizard.py`

- [ ] **Step 1: Write failing test that drives the wizard with scripted input**

```python
# tests/test_wizard.py — new file

from pathlib import Path
import yaml

from osmind.wizard import run_wizard


def test_wizard_writes_valid_profile(tmp_path, monkeypatch):
    target = tmp_path / "profile.yaml"
    inputs = iter([
        "RL post-training, SGLang",        # interests
        "Python, distributed training",    # skills
        "4x RTX 4090",                     # resource line 1
        "8 hours per week, evenings",      # resource line 2
        "",                                # blank line ends resources
        "sgl-project/sglang",              # watch line 1
        "THUDM/slime",                     # watch line 2
        "",                                # blank line ends watching
        str(tmp_path / "vault"),           # notes_vault
        "http://localhost:30000/v1",       # llm.base_url
        "Qwen3.5-27B",                     # llm.model
        "placeholder",                     # llm.api_key
        "claude",                          # claude_code
        "codex",                           # codex
    ])
    monkeypatch.setattr("builtins.input", lambda *_: next(inputs))

    cfg = run_wizard(target)

    assert target.exists()
    data = yaml.safe_load(target.read_text())
    assert data["interests"] == ["RL post-training", "SGLang"]
    assert data["skills"] == ["Python", "distributed training"]
    assert data["resources"] == ["4x RTX 4090", "8 hours per week, evenings"]
    assert data["watching"] == [
        {"repo": "sgl-project/sglang"},
        {"repo": "THUDM/slime"},
    ]
    assert cfg.notes_vault == (tmp_path / "vault").expanduser()
    assert cfg.llm.model == "Qwen3.5-27B"
    assert cfg.external_agents.claude_code == "claude"


def test_wizard_uses_defaults_for_blank_llm_inputs(tmp_path, monkeypatch):
    target = tmp_path / "profile.yaml"
    inputs = iter([
        "x", "y",
        "",                                # no resources
        "a/b", "",                         # one watch
        str(tmp_path / "vault"),
        "",                                # llm.base_url default
        "",                                # llm.model default
        "",                                # llm.api_key default
        "",                                # claude_code default
        "",                                # codex default
    ])
    monkeypatch.setattr("builtins.input", lambda *_: next(inputs))

    cfg = run_wizard(target)
    assert cfg.llm.base_url == "http://localhost:30000/v1"
    assert cfg.llm.model == "Qwen3.5-27B"
    assert cfg.external_agents.claude_code == "claude"
    assert cfg.external_agents.codex == "codex"
    assert cfg.resources == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_wizard.py -v`
Expected: FAIL — module not yet present.

- [ ] **Step 3: Implement `run_wizard`**

```python
# osmind/wizard.py — new file

from __future__ import annotations

from pathlib import Path

import yaml

from osmind.config import Config


_LLM_DEFAULT_BASE = "http://localhost:30000/v1"
_LLM_DEFAULT_MODEL = "Qwen3.5-27B"
_LLM_DEFAULT_KEY = "placeholder"
_DEFAULT_CLAUDE = "claude"
_DEFAULT_CODEX = "codex"


def run_wizard(target_path: Path) -> Config:
    print("osmind first-launch wizard")
    print("Empty answers accept defaults. End multi-line sections with a blank line.\n")

    interests = _prompt_csv("Interests (comma-separated, e.g. RL post-training, SGLang)")
    skills = _prompt_csv("Skills (comma-separated, e.g. Python, distributed training)")

    print("\nResources / constraints — one per line. Write whatever is useful:")
    print("  hardware, time, company policy, geography, weak/strong skills, etc.")
    resources = _prompt_lines("resource")

    print("\nWatched repos — one owner/name per line, blank to finish:")
    watching_repos = _prompt_lines("repo")
    watching = [{"repo": repo} for repo in watching_repos]

    notes_vault = _prompt_text("Notes vault path (Obsidian)", default="~/workspace/Note")

    print("\nLLM endpoint (OpenAI-compatible):")
    llm_base = _prompt_text("  base_url", default=_LLM_DEFAULT_BASE)
    llm_model = _prompt_text("  model", default=_LLM_DEFAULT_MODEL)
    llm_key = _prompt_text("  api_key", default=_LLM_DEFAULT_KEY)

    print("\nExternal agent commands (must be on PATH):")
    claude_cmd = _prompt_text("  claude_code", default=_DEFAULT_CLAUDE)
    codex_cmd = _prompt_text("  codex", default=_DEFAULT_CODEX)

    data = {
        "interests": interests,
        "skills": skills,
        "resources": resources,
        "watching": watching,
        "notes_vault": notes_vault,
        "llm": {
            "base_url": llm_base,
            "model": llm_model,
            "api_key": llm_key,
        },
        "external_agents": {
            "claude_code": claude_cmd,
            "codex": codex_cmd,
        },
    }
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    print(f"\nWrote {target_path}")
    return Config.from_file(target_path)


def _prompt_text(label: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip()
    return value or default


def _prompt_csv(label: str) -> list[str]:
    raw = input(f"{label}: ").strip()
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _prompt_lines(item_label: str) -> list[str]:
    collected: list[str] = []
    while True:
        value = input(f"  {item_label} {len(collected) + 1} (blank to finish): ").strip()
        if not value:
            return collected
        collected.append(value)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_wizard.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add osmind/wizard.py tests/test_wizard.py
git commit -m "feat: add first-launch profile wizard"
```

---

## Task 7: Wire `main()` — Auto-Wizard and `osmind init` Subcommand

**Files:**
- Modify: `osmind/tui/app.py`
- Test: `tests/test_launcher.py`

- [ ] **Step 1: Inspect existing launcher tests to follow established patterns**

Run: `pytest tests/test_launcher.py -v` to confirm baseline passes.

- [ ] **Step 2: Write failing test for wizard auto-launch**

```python
# tests/test_launcher.py — append (this file already exists; add to it)

import sys
from pathlib import Path


def test_main_runs_wizard_when_profile_missing(tmp_path, monkeypatch):
    from osmind.tui import app as app_module

    profile = tmp_path / "profile.yaml"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["osmind"])

    wizard_called = {"hit": False}

    def fake_wizard(target):
        wizard_called["hit"] = True
        target.write_text(
            "interests: [x]\n"
            "skills: [y]\n"
            "resources: []\n"
            "watching:\n  - repo: a/b\n"
            f"notes_vault: {tmp_path / 'vault'}\n"
            "llm:\n  base_url: http://x\n  model: m\n  api_key: k\n"
            "external_agents:\n  claude_code: claude\n  codex: codex\n"
        )
        from osmind.config import Config
        return Config.from_file(target)

    run_calls = {"hit": False}

    class FakeApp:
        def __init__(self, config):
            self.config = config

        def run(self):
            run_calls["hit"] = True

    monkeypatch.setattr(app_module, "run_wizard", fake_wizard)
    monkeypatch.setattr(app_module, "OsmindApp", FakeApp)

    app_module.main()
    assert wizard_called["hit"] is True
    assert run_calls["hit"] is True
    assert profile.exists()


def test_main_init_subcommand_forces_wizard(tmp_path, monkeypatch):
    from osmind.tui import app as app_module

    profile = tmp_path / "profile.yaml"
    profile.write_text(
        "interests: [x]\nskills: [y]\nresources: []\nwatching:\n  - repo: a/b\n"
        f"notes_vault: {tmp_path / 'vault'}\n"
        "llm:\n  base_url: http://x\n  model: m\n  api_key: k\n"
        "external_agents:\n  claude_code: claude\n  codex: codex\n"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["osmind", "init"])

    wizard_called = {"hit": False}

    def fake_wizard(target):
        wizard_called["hit"] = True
        target.write_text(
            "interests: [a]\nskills: [b]\nresources: []\nwatching:\n  - repo: c/d\n"
            f"notes_vault: {tmp_path / 'vault'}\n"
            "llm:\n  base_url: http://x\n  model: m\n  api_key: k\n"
            "external_agents:\n  claude_code: claude\n  codex: codex\n"
        )
        from osmind.config import Config
        return Config.from_file(target)

    monkeypatch.setattr(app_module, "run_wizard", fake_wizard)
    monkeypatch.setattr("builtins.input", lambda *_: "y")  # confirm overwrite

    app_module.main()
    assert wizard_called["hit"] is True
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_launcher.py -v`
Expected: FAIL — `run_wizard` is not imported in `app.py`, init subcommand not handled.

- [ ] **Step 4: Update `main()` in `osmind/tui/app.py`**

```python
# osmind/tui/app.py — replace `main` and add the import

from osmind.wizard import run_wizard


def main():
    argv = sys.argv[1:]
    profile_path = Path("profile.yaml")

    if argv and argv[0] == "init":
        if profile_path.exists():
            answer = input(f"{profile_path} exists. Overwrite? [y/N]: ").strip().lower()
            if answer not in {"y", "yes"}:
                print("Aborted.")
                return
        config = run_wizard(profile_path)
    elif not profile_path.exists():
        print("No profile.yaml found — starting first-launch wizard.\n")
        config = run_wizard(profile_path)
    else:
        config = Config.from_file(profile_path)

    app = OsmindApp(config)
    app.run()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_launcher.py -v`
Expected: PASS for both new tests.

- [ ] **Step 6: Manual smoke check (optional but recommended)**

Run in a scratch directory:
```bash
cd /tmp && rm -rf osmind-smoke && mkdir osmind-smoke && cd osmind-smoke
osmind init
```
Expected: wizard prompts walk through interests/skills/resources/etc.; `profile.yaml` is written; TUI starts.

- [ ] **Step 7: Commit**

```bash
git add osmind/tui/app.py tests/test_launcher.py
git commit -m "feat: launch wizard on first run and via 'osmind init'"
```

---

## Task 8: Pre-Warm Facet Cache at App Start

**Files:**
- Modify: `osmind/tui/app.py`
- Test: `tests/test_launcher.py`

- [ ] **Step 1: Write failing test for facet pre-warm**

```python
# tests/test_launcher.py — append

def test_main_prewarms_facet_cache(tmp_path, monkeypatch):
    from osmind.tui import app as app_module

    profile = tmp_path / "profile.yaml"
    vault = tmp_path / "vault"
    profile.write_text(
        "interests: [x]\nskills: [y]\n"
        "resources:\n  - '4x RTX 4090'\n"
        "watching:\n  - repo: a/b\n"
        f"notes_vault: {vault}\n"
        "llm:\n  base_url: http://x\n  model: m\n  api_key: k\n"
        "external_agents:\n  claude_code: claude\n  codex: codex\n"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["osmind"])

    ensure_calls = []

    def fake_ensure(resources, llm, cache_path):
        ensure_calls.append((tuple(resources), cache_path))
        from osmind.engine.resources import ResourceFacet
        return [ResourceFacet(text=resources[0], kind="hardware", polarity="enabling", strength="medium")]

    class FakeApp:
        def __init__(self, config):
            self.config = config

        def run(self):
            pass

    monkeypatch.setattr(app_module, "ensure_facets", fake_ensure)
    monkeypatch.setattr(app_module, "OsmindApp", FakeApp)

    app_module.main()
    assert ensure_calls, "expected ensure_facets to be invoked at startup"
    resources, cache_path = ensure_calls[0]
    assert resources == ("4x RTX 4090",)
    assert cache_path == vault / "osmind" / ".cache" / "resources_facets.json"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_launcher.py::test_main_prewarms_facet_cache -v`
Expected: FAIL — `ensure_facets` is not called from `main`.

- [ ] **Step 3: Pre-warm the cache in `main`**

```python
# osmind/tui/app.py — update main; add imports

from osmind.engine.llm import LLMClient
from osmind.engine.resources import ensure_facets


def main():
    argv = sys.argv[1:]
    profile_path = Path("profile.yaml")

    if argv and argv[0] == "init":
        if profile_path.exists():
            answer = input(f"{profile_path} exists. Overwrite? [y/N]: ").strip().lower()
            if answer not in {"y", "yes"}:
                print("Aborted.")
                return
        config = run_wizard(profile_path)
    elif not profile_path.exists():
        print("No profile.yaml found — starting first-launch wizard.\n")
        config = run_wizard(profile_path)
    else:
        config = Config.from_file(profile_path)

    if config.resources:
        cache_path = config.notes_vault / "osmind" / ".cache" / "resources_facets.json"
        try:
            ensure_facets(config.resources, LLMClient(config.llm), cache_path)
        except Exception as exc:  # pragma: no cover — LLM unreachable on first run
            print(f"[warn] could not extract resource facets: {exc}")

    app = OsmindApp(config)
    app.run()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_launcher.py::test_main_prewarms_facet_cache -v`
Expected: PASS.

- [ ] **Step 5: Run full suite to verify no regressions**

Run: `pytest -q`
Expected: PASS across the board.

- [ ] **Step 6: Commit**

```bash
git add osmind/tui/app.py tests/test_launcher.py
git commit -m "feat: pre-warm resource facet cache at app startup"
```

---

## Task 9: Surface Facets in the Settings Tab

**Files:**
- Modify: `osmind/tui/screens/settings.py`
- Test: `tests/test_tui.py`

- [ ] **Step 1: Write failing test that asserts facets appear in the Settings render**

```python
# tests/test_tui.py — append (existing file)

def test_settings_renders_resource_facets(tmp_path):
    from osmind.tui.screens.settings import _format_health
    from osmind.config import Config, LLMConfig, AgentConfig
    from osmind.engine.resources import ResourceFacet, save_cached_facets, resources_signature

    vault = tmp_path / "vault"
    vault.mkdir()
    cache_path = vault / "osmind" / ".cache" / "resources_facets.json"
    save_cached_facets(
        cache_path,
        resources_signature(["4x RTX 4090"]),
        [ResourceFacet(text="4x RTX 4090", kind="hardware", polarity="enabling", strength="medium")],
    )

    cfg = Config(
        interests=["x"],
        skills=["y"],
        resources=["4x RTX 4090"],
        watching=[{"repo": "a/b"}],
        notes_vault=vault,
        llm=LLMConfig(base_url="http://x", model="m", api_key="k"),
        external_agents=AgentConfig(claude_code="claude", codex="codex"),
    )

    output = _format_health(cfg)
    assert "4x RTX 4090" in output
    assert "hardware" in output
    assert "Facets: cached (fresh)" in output


def test_settings_marks_facets_stale_when_signature_mismatch(tmp_path):
    from osmind.tui.screens.settings import _format_health
    from osmind.config import Config, LLMConfig, AgentConfig
    from osmind.engine.resources import ResourceFacet, save_cached_facets

    vault = tmp_path / "vault"
    vault.mkdir()
    cache_path = vault / "osmind" / ".cache" / "resources_facets.json"
    save_cached_facets(
        cache_path,
        "old-sig",
        [ResourceFacet(text="old", kind="other", polarity="limiting", strength="soft")],
    )

    cfg = Config(
        interests=["x"], skills=["y"],
        resources=["4x RTX 4090"],
        watching=[{"repo": "a/b"}], notes_vault=vault,
        llm=LLMConfig(base_url="http://x", model="m", api_key="k"),
        external_agents=AgentConfig(claude_code="claude", codex="codex"),
    )
    output = _format_health(cfg)
    assert "Facets: stale" in output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_tui.py::test_settings_renders_resource_facets tests/test_tui.py::test_settings_marks_facets_stale_when_signature_mismatch -v`
Expected: FAIL.

- [ ] **Step 3: Update `_format_health` and helpers**

```python
# osmind/tui/screens/settings.py — extend _format_health and add helpers

from osmind.engine.resources import load_cached_facets, resources_signature


def _format_health(config) -> str:
    token = os.environ.get("GITHUB_TOKEN", "")
    vault = config.notes_vault
    cache_path = vault / "osmind" / ".cache" / "osmind.db"
    facet_cache_path = vault / "osmind" / ".cache" / "resources_facets.json"
    resources_block = _format_resources_block(config.resources, facet_cache_path)
    watching = ", ".join(repo["repo"] for repo in config.watching) if config.watching else "none"
    claude_status = _command_status(config.external_agents.claude_code)
    codex_status = _command_status(config.external_agents.codex)

    return "\n".join(
        [
            "[bold]Settings / Health[/bold]",
            "",
            f"GitHub token: {_status('OK' if token else 'Missing')} GITHUB_TOKEN",
            f"LLM: {_status('Configured' if config.llm.base_url and config.llm.model else 'Missing')} "
            f"{config.llm.model} @ {config.llm.base_url}",
            f"Notes vault: {_status('OK' if vault.exists() else 'Will create')} {vault}",
            f"Cache: {cache_path}",
            "Resources:",
            resources_block,
            f"Watching: {watching}",
            f"Claude Code: {claude_status}",
            f"Codex: {codex_status}",
            "",
            "[dim]u: reload health status[/dim]",
        ]
    )


def _format_resources_block(resources: list[str], facet_cache_path) -> str:
    if not resources:
        return "  not configured"
    signature = resources_signature(resources)
    facets = load_cached_facets(facet_cache_path, signature)
    facet_status = "Facets: not generated yet"
    facet_by_text: dict = {}
    if facets is not None:
        facet_status = "Facets: cached (fresh)"
        facet_by_text = {facet.text: facet for facet in facets}
    elif facet_cache_path.exists():
        facet_status = "Facets: stale (will rebuild on next ranking)"

    lines = [f"  {facet_status}"]
    for item in resources:
        facet = facet_by_text.get(item)
        if facet is None:
            lines.append(f"  - {item}")
        else:
            lines.append(
                f"  - {item}  [{facet.kind} / {facet.polarity} / {facet.strength}]"
            )
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_tui.py::test_settings_renders_resource_facets tests/test_tui.py::test_settings_marks_facets_stale_when_signature_mismatch -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add osmind/tui/screens/settings.py tests/test_tui.py
git commit -m "feat: show resource facets and cache freshness in Settings"
```

---

## Task 10: Update `profile.yaml.example` and README

**Files:**
- Modify: `profile.yaml.example`
- Modify: `README.md`

- [ ] **Step 1: Replace `resources:` block in `profile.yaml.example`**

```yaml
# profile.yaml.example — replace resources block only

resources:
  - "4x RTX 4090, evenings only"
  - "8 hours per week"
  - "company forbids direct PR; fork required"
  - "Python yes, CUDA kernel no"
```

- [ ] **Step 2: Replace the Configuration section in `README.md`**

Find the existing `## Configuration` section and replace it with:

```markdown
## Configuration

osmind ships an interactive first-launch wizard. The first time you run `osmind` in a directory without `profile.yaml`, the wizard collects your interests, skills, resources, watched repos, notes vault, LLM endpoint, and external agents, then writes `profile.yaml` for you. Run `osmind init` to redo the wizard at any time.

If you prefer to edit by hand:

```yaml
interests:
  - RL post-training
  - SGLang inference optimization

skills:
  - Python
  - distributed training

resources:
  - "4x RTX 4090, evenings only"
  - "8 hours per week"
  - "company forbids direct PR; fork required"
  - "Python yes, CUDA kernel no"

watching:
  - repo: THUDM/slime
  - repo: sgl-project/sglang

notes_vault: ~/workspace/Note

llm:
  base_url: http://localhost:30000/v1
  model: Qwen3.5-27B
  api_key: placeholder

external_agents:
  claude_code: claude
  codex: codex
```

`resources` is now a free-form list of strings — write hardware, time, company policy, geography, language, weak/strong skills, anything that should bias the recommender. osmind extracts each line into a structured facet (kind / polarity / strength) using your configured LLM on first launch and caches the result under `<notes_vault>/osmind/.cache/resources_facets.json`. Edit `resources` later and the cache is rebuilt automatically. Legacy `resources: { gpus: ..., time: ... }` profiles are loaded as `["gpus: ...", "time: ..."]` so nothing breaks.

Set your GitHub token:

```bash
export GITHUB_TOKEN=ghp_...
```

Run:

```bash
osmind          # opens the TUI (wizard runs if no profile.yaml)
osmind init     # redo the wizard
```
```

- [ ] **Step 3: Commit**

```bash
git add profile.yaml.example README.md
git commit -m "docs: document wizard and free-form resources"
```

---

## Self-Review

**Spec coverage:**

- Improvement #1 "First-launch wizard, replacing manual profile.yaml" → Tasks 6, 7, 10 ✓
- Improvement #3 "Multi-dimensional resource fit, but expressed as free-form, not GPU-locked fields" → Tasks 1, 2, 3, 4, 5 ✓
- User feedback: "resources should not be固化成 GPU 字段" → Resources are `list[str]`, no fixed fields. Facets are derived, not user-declared. ✓
- User feedback: "可能不一定是 GPU" → kind taxonomy includes `time`, `skill`, `policy`, `location`, `other`. ✓
- User feedback: "时间、客观原因等等限制" → polarity (enabling/limiting) and strength (soft/medium/hard) capture these. ✓
- Backward compatibility for existing `profile.yaml` users → `_normalize_resources` in Task 1. ✓
- UI surfaces the new structure → Tasks 2 (decision panel, workflow), 9 (settings). ✓
- Ranker actually uses facets → Task 5. ✓
- Pre-warm so first ranking is fast → Task 8. ✓

**Placeholder scan:** No "TBD" or "implement later" steps. Each code block is complete. Every reference (`_format_resources`, `ensure_facets`, `ResourceFacet`, `run_wizard`) is defined in an earlier task.

**Type consistency:**
- `resources: list[str]` everywhere (Config, Ranker, decision, workflow, settings, library, generator).
- `ResourceFacet` carries `text, kind, polarity, strength` consistently across creation, persistence, and rendering.
- `resources_signature` and `resources_hash` are different helpers (different files) by intent: `resources_signature` keys the facet cache; `resources_hash` keys the issue decision lifecycle. Both accept `list[str]`. Kept separate to avoid coupling cache invalidation to decision invalidation.

---

## Execution Notes

- Tasks 1 → 2 are sequential (config shape change → all helpers).
- Tasks 3 → 4 → 5 are sequential (facet model → extractor → ranker wiring).
- Task 6 (wizard) is independent of 1–5 and can run in parallel if dispatched to a separate subagent.
- Task 7 depends on 6; Task 8 depends on 4 and 7.
- Task 9 depends on 1 and 4.
- Task 10 is doc-only and can run last.
