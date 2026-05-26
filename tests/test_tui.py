# tests/test_tui.py
import pytest
from unittest.mock import MagicMock
from osmind.config import Config, LLMConfig, AgentConfig
from osmind.tui.app import OsmindApp
from pathlib import Path


def _issue_brief_payload(**overrides):
    payload = {
        "one_liner": "Tokenizer cache grows without bounds.",
        "plain_explanation": "The tokenizer cache keeps growing after repeated requests.",
        "why_it_fits": "The cached recommendation says this is actionable for Python work.",
        "project_context": ["Tokenizer code owns request text normalization."],
        "likely_files": ["python/sglang/tokenizer.py"],
        "difficulty": "medium",
        "readiness": "ready",
        "background_to_learn": ["Read the tokenizer cache implementation."],
        "next_steps": ["Add a regression test for repeated tokenization."],
        "agent_questions": ["Which cache key is expected to be bounded?"],
        "risks": ["The cache may be intentionally process-wide."],
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def mock_config():
    return Config(
        interests=["SGLang"],
        skills=["Python"],
        resources={"gpus": "4x RTX 4090"},
        watching=[{"repo": "sgl-project/sglang"}],
        notes_vault=Path("/tmp/osmind_test_vault"),
        llm=LLMConfig(base_url="http://localhost:1234/v1", model="test", api_key="test"),
        external_agents=AgentConfig(claude_code="claude", codex="codex"),
    )


@pytest.fixture
def temp_config(tmp_path):
    return Config(
        interests=["SGLang"],
        skills=["Python"],
        resources={"gpus": "4x RTX 4090"},
        watching=[{"repo": "sgl-project/sglang"}],
        notes_vault=tmp_path / "vault",
        llm=LLMConfig(base_url="http://localhost:1234/v1", model="test", api_key="test"),
        external_agents=AgentConfig(claude_code="claude", codex="codex"),
    )


@pytest.mark.asyncio
async def test_app_composes_without_creating_pack_cache(temp_config):
    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        assert app.query_one("TabbedContent") is not None
    assert not (temp_config.notes_vault / "osmind" / ".cache" / "osmind.db").exists()


@pytest.mark.asyncio
async def test_tab_navigation(mock_config):
    app = OsmindApp(mock_config)
    async with app.run_test() as pilot:
        from textual.widgets import TabbedContent
        tabs = app.query_one(TabbedContent)
        # Verify BINDINGS list covers all three tabs
        binding_actions = {b[1] for b in app.BINDINGS}
        assert "switch_tab('discover')" in binding_actions
        assert "switch_tab('packs')" in binding_actions
        assert "switch_tab('review')" in binding_actions
        assert "switch_tab('settings')" in binding_actions
        # Verify tab IDs exist in the TabbedContent
        tab_ids = {pane.id for pane in tabs.query("TabPane")}
        assert "discover" in tab_ids
        assert "packs" in tab_ids
        assert "learn" not in tab_ids
        assert "review" in tab_ids
        assert "settings" in tab_ids


@pytest.mark.asyncio
async def test_escape_moves_focus_from_review_input_back_to_table(temp_config):
    from textual.widgets import DataTable, Input

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        app.action_switch_tab("review")
        review_input = app.query_one("#review-input", Input)
        review_table = app.query_one("#notes-table", DataTable)
        review_input.focus()

        await pilot.press("escape")

        assert app.focused is review_table


@pytest.mark.asyncio
async def test_discover_toolbar_does_not_expand_vertically(temp_config):
    app = OsmindApp(temp_config)
    async with app.run_test(size=(100, 40)) as pilot:
        toolbar = app.query_one("#toolbar")
        issue_list = app.query_one("#issue-list-view")

        assert toolbar.region.height <= 4
        assert issue_list.region.y <= 8


def test_discover_has_no_learn_binding():
    from osmind.tui.screens.discover import DiscoverScreen

    binding_actions = {b[1] for b in DiscoverScreen.BINDINGS}

    assert "open_in_learn" not in binding_actions
    assert all("learn" not in action for action in binding_actions)


def test_discover_agent_launchers_are_not_shown_as_primary_bindings():
    from osmind.tui.screens.discover import DiscoverScreen

    binding_text = " ".join(f"{binding[0]} {binding[1]} {binding[2]}" for binding in DiscoverScreen.BINDINGS)

    assert "Claude" not in binding_text
    assert "Codex" not in binding_text
    assert "launch_claude" not in binding_text
    assert "launch_codex" not in binding_text


@pytest.mark.asyncio
async def test_discover_hidden_agent_shortcuts_still_dispatch(temp_config, monkeypatch):
    from osmind.tui.screens.discover import DiscoverScreen

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        discover = app.query_one(DiscoverScreen)
        calls = []

        async def fake_launch_claude():
            calls.append("claude")

        async def fake_launch_codex():
            calls.append("codex")

        monkeypatch.setattr(discover, "action_launch_claude", fake_launch_claude)
        monkeypatch.setattr(discover, "action_launch_codex", fake_launch_codex)

        await discover.key_c()
        await discover.key_x()

    assert calls == ["claude", "codex"]


def test_packs_reload_does_not_shadow_review_navigation_key():
    from osmind.tui.app import OsmindApp
    from osmind.tui.screens.packs import PacksScreen

    review_keys = {
        binding[0]
        for binding in OsmindApp.BINDINGS
        if binding[1] == "switch_tab('review')"
    }
    packs_reload_keys = {
        binding[0]
        for binding in PacksScreen.BINDINGS
        if binding[1] == "reload"
    }

    assert packs_reload_keys.isdisjoint(review_keys)


def test_start_work_key_does_not_shadow_review_navigation_key():
    from osmind.tui.app import OsmindApp
    from osmind.tui.screens.discover import DiscoverScreen
    from osmind.tui.screens.packs import PacksScreen

    review_keys = {
        binding[0]
        for binding in OsmindApp.BINDINGS
        if binding[1] == "switch_tab('review')"
    }
    start_work_keys = {
        binding[0]
        for binding in [*DiscoverScreen.BINDINGS, *PacksScreen.BINDINGS]
        if binding[1] == "start_work"
    }

    assert start_work_keys == {"w"}
    assert start_work_keys.isdisjoint(review_keys)


def test_packs_reader_reuses_enter_without_extra_view_keys():
    from osmind.tui.screens.packs import PacksScreen

    keys_by_action = {binding[1]: binding[0] for binding in PacksScreen.BINDINGS}
    bound_keys = {binding[0] for binding in PacksScreen.BINDINGS}

    assert keys_by_action["view_pack"] == "enter"
    assert keys_by_action["decide"] == "space"
    assert "v" not in {binding[0] for binding in PacksScreen.BINDINGS}
    assert "m" not in {binding[0] for binding in PacksScreen.BINDINGS}
    assert {"y", "l", "n", "u"}.isdisjoint(bound_keys)


def test_plain_q_is_not_global_quit_shortcut():
    from osmind.tui.app import OsmindApp

    assert ("q", "quit", "Quit") not in OsmindApp.BINDINGS


@pytest.mark.asyncio
async def test_discover_fetch_exception_is_logged(temp_config, monkeypatch):
    from osmind.tui.screens.discover import DiscoverScreen
    import osmind.github.client

    class FailingGitHubClient:
        def __init__(self, token=""):
            pass

        def get_issues(self, repo, limit=30, include_comments=False):
            raise RuntimeError("no connected db")

    monkeypatch.setattr(osmind.github.client, "GitHubClient", FailingGitHubClient)

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        discover = app.query_one(DiscoverScreen)
        await discover.action_fetch()

    log_path = temp_config.notes_vault / "osmind" / ".cache" / "osmind.log"
    text = log_path.read_text(encoding="utf-8")
    assert "Failed to fetch issues" in text
    assert "RuntimeError: no connected db" in text


@pytest.mark.asyncio
async def test_discover_fetch_does_not_request_issue_comments(temp_config, monkeypatch):
    from osmind.github.models import GHIssue
    from osmind.tui.screens.discover import DiscoverScreen
    import osmind.github.client

    calls = []

    class RecordingGitHubClient:
        def __init__(self, token=""):
            pass

        def get_issues(self, repo, limit=30, include_comments=False):
            calls.append((repo, limit, include_comments))
            return [GHIssue(42, "Tokenizer leak", "Body", [], "u", "o/r", "open")]

    monkeypatch.setattr(osmind.github.client, "GitHubClient", RecordingGitHubClient)

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        discover = app.query_one(DiscoverScreen)
        await discover.action_fetch()

    assert calls == [("sgl-project/sglang", 30, False)]


@pytest.mark.asyncio
async def test_discover_fetch_uses_cached_issues_without_github_or_rescoring(temp_config, monkeypatch):
    from osmind.cache.store import CacheStore
    from osmind.github.models import GHIssue
    from osmind.tui.screens.discover import DiscoverScreen
    from osmind.tui.widgets.issue_list import IssueTable
    import osmind.engine.ranker
    import osmind.github.client

    issue = GHIssue(
        42,
        "Tokenizer leak",
        "Body",
        ["bug"],
        "https://github.com/sgl-project/sglang/issues/42",
        "sgl-project/sglang",
        "open",
        score=0.8,
        reason="cached reason",
        updated_at="u42",
    )
    cache = CacheStore(temp_config.notes_vault / "osmind" / ".cache" / "osmind.db")
    cache.upsert_issue(issue)
    cache.update_issue_score(issue.repo, "issue", issue.number, issue.score, issue.reason)

    class FailingGitHubClient:
        def __init__(self, token=""):
            pass

        def get_issues(self, repo, limit=30, include_comments=False):
            raise AssertionError("GitHub should not be called for cached issues")

    class FailingRanker:
        def __init__(self, llm, interests, skills, resources=None):
            pass

        def score_one(self, issue):
            raise AssertionError("Cached issues should not be rescored")

    monkeypatch.setattr(osmind.github.client, "GitHubClient", FailingGitHubClient)
    monkeypatch.setattr(osmind.engine.ranker, "Ranker", FailingRanker)

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        discover = app.query_one(DiscoverScreen)
        await discover.action_fetch()

        table = app.query_one(IssueTable)
        assert table.row_count == 1
        assert discover._issues_by_number["42"].score == 0.8
        assert discover._issues_by_number["42"].reason == "cached reason"


@pytest.mark.asyncio
async def test_discover_loads_existing_cached_queue_on_mount_without_github(temp_config, monkeypatch):
    from osmind.cache.store import CacheStore
    from osmind.github.models import GHIssue
    from osmind.tui.widgets.issue_list import IssueTable
    import osmind.github.client

    issue = GHIssue(
        42,
        "Cached issue",
        "Body",
        [],
        "https://github.com/sgl-project/sglang/issues/42",
        "sgl-project/sglang",
        "open",
        score=0.8,
        reason="cached reason",
        updated_at="u42",
    )
    cache = CacheStore(temp_config.notes_vault / "osmind" / ".cache" / "osmind.db")
    cache.upsert_issue(issue)
    cache.update_issue_score(issue.repo, "issue", issue.number, issue.score, issue.reason)

    class FailingGitHubClient:
        def __init__(self, token=""):
            pass

        def get_issues(self, repo, limit=30, include_comments=False):
            raise AssertionError("Mount should only read existing cache")

    monkeypatch.setattr(osmind.github.client, "GitHubClient", FailingGitHubClient)

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        await pilot.pause()

        table = app.query_one(IssueTable)
        assert table.row_count == 1
        assert table.get_row_at(0)[2] == "42"


@pytest.mark.asyncio
async def test_discover_cached_mount_load_does_not_steal_focus_after_switching_tabs(temp_config):
    from osmind.cache.store import CacheStore
    from osmind.github.models import GHIssue
    from textual.widgets import DataTable, TabbedContent

    issue = GHIssue(
        42,
        "Cached issue",
        "Body",
        [],
        "https://github.com/sgl-project/sglang/issues/42",
        "sgl-project/sglang",
        "open",
        score=0.8,
        reason="cached reason",
        updated_at="u42",
    )
    cache = CacheStore(temp_config.notes_vault / "osmind" / ".cache" / "osmind.db")
    cache.upsert_issue(issue)
    cache.update_issue_score(issue.repo, "issue", issue.number, issue.score, issue.reason)

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        app.action_switch_tab("packs")
        await pilot.pause()

        app.query_one("DiscoverScreen")._load_cached_queue_if_available()
        packs_table = app.query_one("#packs-table", DataTable)
        assert app.query_one(TabbedContent).active == "packs"
        assert app.focused is packs_table


@pytest.mark.asyncio
async def test_discover_fetch_sorts_cached_issues_by_score_and_shows_reason(temp_config, monkeypatch):
    from osmind.cache.store import CacheStore
    from osmind.github.models import GHIssue
    from osmind.tui.screens.discover import DiscoverScreen
    from osmind.tui.widgets.issue_list import IssueTable
    import osmind.github.client

    issues = [
        GHIssue(1, "Low match", "Body", [], "u1", "sgl-project/sglang", "open", score=0.2, reason="low reason"),
        GHIssue(2, "High match", "Body", [], "u2", "sgl-project/sglang", "open", score=0.9, reason="high reason"),
    ]
    cache = CacheStore(temp_config.notes_vault / "osmind" / ".cache" / "osmind.db")
    for issue in issues:
        cache.upsert_issue(issue)
        cache.update_issue_score(issue.repo, "issue", issue.number, issue.score, issue.reason)

    class FailingGitHubClient:
        def __init__(self, token=""):
            pass

        def get_issues(self, repo, limit=30, include_comments=False):
            raise AssertionError("GitHub should not be called for cached issues")

    monkeypatch.setattr(osmind.github.client, "GitHubClient", FailingGitHubClient)

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        discover = app.query_one(DiscoverScreen)
        await discover.action_fetch()

        table = app.query_one(IssueTable)
        first_row = table.get_row_at(0)

        assert first_row[2] == "2"
        assert "high reason" in first_row[1]


@pytest.mark.asyncio
async def test_issue_table_shows_decision_oriented_recommendation_columns(temp_config):
    from osmind.github.models import GHIssue
    from osmind.tui.widgets.issue_list import IssueTable

    issue = GHIssue(
        42,
        "DeepSeek V4Pro reproduction fails",
        "Requires full model reproduction.",
        ["bug"],
        "u",
        "o/r",
        "open",
        score=0.2,
        reason="主题匹配，但当前 GPU 资源不足以复现",
        priority="low",
        fit="high",
        resource_fit="blocked",
        actionability="low",
    )

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        table = app.query_one(IssueTable)
        table.populate([issue])

        labels = [str(column.label) for column in table.columns.values()]
        row = table.get_row_at(0)

    assert labels == ["Action", "Why", "#", "Title", "Labels"]
    assert row[0] == "Defer"
    assert row[1].startswith("resource blocked:")
    assert "当前 GPU 资源不足" in row[1]


@pytest.mark.asyncio
async def test_discover_action_filter_cycles_visible_recommendations(temp_config):
    from osmind.github.models import GHIssue
    from osmind.tui.screens.discover import DiscoverScreen
    from osmind.tui.widgets.issue_list import IssueTable
    from textual.widgets import Static

    issues = [
        GHIssue(1, "High match", "Body", [], "u1", "o/r", "open", score=0.9, reason="ready"),
        GHIssue(
            2,
            "Resource blocked",
            "Body",
            [],
            "u2",
            "o/r",
            "open",
            score=0.2,
            reason="needs bigger GPU",
            priority="low",
            fit="high",
            resource_fit="blocked",
            actionability="low",
        ),
        GHIssue(3, "Low match", "Body", [], "u3", "o/r", "open", score=0.1, reason="not relevant"),
    ]

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        discover = app.query_one(DiscoverScreen)
        table = app.query_one(IssueTable)
        discover._show_issues(issues)

        assert table.row_count == 3

        await pilot.press("a")
        await pilot.pause()

        assert table.row_count == 1
        assert table.get_row_at(0)[0] == "Do now"
        assert "Filter: Do now" in str(app.query_one("#freshness-status", Static).renderable)


@pytest.mark.asyncio
async def test_discover_active_queue_hides_user_deferred_and_discarded_items(temp_config):
    from osmind.cache.store import CacheStore
    from osmind.github.models import GHIssue
    from osmind.tui.screens.discover import DiscoverScreen
    from osmind.tui.widgets.issue_list import IssueTable
    from textual.widgets import Select, Static

    active = GHIssue(1, "Active issue", "Body", [], "u1", "sgl-project/sglang", "open", score=0.9)
    deferred = GHIssue(2, "Deferred issue", "Body", [], "u2", "sgl-project/sglang", "open", score=0.8)
    discarded = GHIssue(3, "Discarded issue", "Body", [], "u3", "sgl-project/sglang", "open", score=0.7)
    cache = CacheStore(temp_config.notes_vault / "osmind" / ".cache" / "osmind.db")
    for issue in (active, deferred, discarded):
        cache.upsert_issue(issue)
    cache.upsert_pack("sgl-project/sglang", "issue", 2, temp_config.notes_vault / "d.md", "unread", "unknown", "u2", decision="defer")
    cache.upsert_pack("sgl-project/sglang", "issue", 3, temp_config.notes_vault / "x.md", "unread", "unknown", "u3", decision="discard")

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        discover = app.query_one(DiscoverScreen)
        table = app.query_one(IssueTable)
        discover._show_issues([active, deferred, discarded])

        assert table.row_count == 1
        assert table.get_row_at(0)[2] == "1"
        status = str(app.query_one("#freshness-status", Static).renderable)
        assert "Filter: Active" in status
        assert "Deferred: 1" in status
        assert "Discarded: 1" in status

        app.query_one("#action-filter", Select).value = "deferred"
        await pilot.pause()

        assert table.row_count == 1
        assert table.get_row_at(0)[2] == "2"


@pytest.mark.asyncio
async def test_discover_active_queue_resurfaces_deferred_item_when_source_updates(temp_config):
    from osmind.cache.store import CacheStore
    from osmind.github.models import GHIssue
    from osmind.tui.screens.discover import DiscoverScreen
    from osmind.tui.widgets.issue_list import IssueTable
    from textual.widgets import Static

    issue = GHIssue(
        42,
        "Updated issue",
        "Body",
        [],
        "https://github.com/sgl-project/sglang/issues/42",
        "sgl-project/sglang",
        "open",
        score=0.8,
        updated_at="new-update",
    )
    cache = CacheStore(temp_config.notes_vault / "osmind" / ".cache" / "osmind.db")
    cache.upsert_issue(issue)
    cache.upsert_pack(
        "sgl-project/sglang",
        "issue",
        42,
        temp_config.notes_vault / "deferred.md",
        "unread",
        "unknown",
        "old-update",
        decision="defer",
    )

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        discover = app.query_one(DiscoverScreen)
        table = app.query_one(IssueTable)
        discover._show_issues([issue])

        assert table.row_count == 1
        assert table.get_row_at(0)[2] == "42"
        assert "Changed: 1" in str(app.query_one("#freshness-status", Static).renderable)


@pytest.mark.asyncio
async def test_discover_active_queue_resurfaces_deferred_item_when_resources_change(temp_config):
    from osmind.cache.store import CacheStore
    from osmind.github.models import GHIssue
    from osmind.tui.screens.discover import DiscoverScreen
    from osmind.tui.widgets.issue_list import IssueTable
    from textual.widgets import Static

    issue = GHIssue(42, "Resource-sensitive issue", "Body", [], "u42", "sgl-project/sglang", "open", score=0.8)
    cache = CacheStore(temp_config.notes_vault / "osmind" / ".cache" / "osmind.db")
    cache.upsert_issue(issue)
    cache.upsert_pack(
        "sgl-project/sglang",
        "issue",
        42,
        temp_config.notes_vault / "deferred.md",
        "unread",
        "unknown",
        "u42",
        decision="defer",
        decision_resource_hash="previous-resources",
    )

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        discover = app.query_one(DiscoverScreen)
        table = app.query_one(IssueTable)
        discover._show_issues([issue])

        assert table.row_count == 1
        assert table.get_row_at(0)[2] == "42"
        assert "Changed: 1" in str(app.query_one("#freshness-status", Static).renderable)


@pytest.mark.asyncio
async def test_discover_freshness_status_shows_cached_fetch_and_rank_times(temp_config):
    from osmind.cache.store import CacheStore
    from osmind.github.models import GHIssue
    from osmind.tui.screens.discover import DiscoverScreen
    from textual.widgets import Static

    issue = GHIssue(42, "Cached issue", "Body", [], "u42", "sgl-project/sglang", "open")
    cache = CacheStore(temp_config.notes_vault / "osmind" / ".cache" / "osmind.db")
    cache.upsert_issue(issue)
    cache.update_issue_score(issue.repo, "issue", issue.number, 0.8, "cached score")

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        discover = app.query_one(DiscoverScreen)
        await discover.action_fetch()

        status = str(app.query_one("#freshness-status", Static).renderable)

    assert "1 issues" in status
    assert "Last fetched:" in status
    assert "Last ranked:" in status
    assert "Filter: Active" in status


@pytest.mark.asyncio
async def test_discover_scoring_continues_after_issue_error(temp_config, monkeypatch):
    from osmind.github.models import GHIssue
    from osmind.tui.screens.discover import DiscoverScreen
    from osmind.tui.widgets.issue_list import IssueTable
    import osmind.engine.llm
    import osmind.engine.ranker

    issues = [
        GHIssue(1, "Broken score", "Body", [], "u", "o/r", "open"),
        GHIssue(2, "Working score", "Body", [], "u", "o/r", "open"),
    ]

    class DummyLLMClient:
        def __init__(self, cfg):
            pass

    class PartlyFailingRanker:
        def __init__(self, llm, interests, skills, resources=None):
            pass

        def score_one(self, issue):
            if issue.number == 1:
                raise RuntimeError("no connected db")
            issue.score = 0.8
            issue.reason = "ok"
            return issue

    monkeypatch.setattr(osmind.engine.llm, "LLMClient", DummyLLMClient)
    monkeypatch.setattr(osmind.engine.ranker, "Ranker", PartlyFailingRanker)

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        discover = app.query_one(DiscoverScreen)
        table = app.query_one(IssueTable)
        table.populate(issues)
        discover._issues_by_number = {str(issue.number): issue for issue in issues}
        await discover._score_progressively(issues, "o/r", "")

    assert discover._issues_by_number["1"].score == 0.0
    assert discover._issues_by_number["2"].score == 0.8
    text = (temp_config.notes_vault / "osmind" / ".cache" / "osmind.log").read_text(encoding="utf-8")
    assert "Failed to score issue o/r#1" in text
    assert "RuntimeError: no connected db" in text


@pytest.mark.asyncio
async def test_discover_scoring_reorders_rows_and_updates_reason(temp_config, monkeypatch):
    from osmind.github.models import GHIssue
    from osmind.tui.screens.discover import DiscoverScreen
    from osmind.tui.widgets.issue_list import IssueTable
    import osmind.engine.llm
    import osmind.engine.ranker

    issues = [
        GHIssue(1, "Low match", "Body", [], "u1", "o/r", "open"),
        GHIssue(2, "High match", "Body", [], "u2", "o/r", "open"),
    ]

    class DummyLLMClient:
        def __init__(self, cfg):
            pass

    class OrderedRanker:
        def __init__(self, llm, interests, skills, resources=None):
            pass

        def score_one(self, issue):
            issue.score = 0.9 if issue.number == 2 else 0.2
            issue.reason = "high reason" if issue.number == 2 else "low reason"
            return issue

    monkeypatch.setattr(osmind.engine.llm, "LLMClient", DummyLLMClient)
    monkeypatch.setattr(osmind.engine.ranker, "Ranker", OrderedRanker)

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        discover = app.query_one(DiscoverScreen)
        table = app.query_one(IssueTable)
        table.populate(issues)
        discover._issues_by_number = {str(issue.number): issue for issue in issues}

        await discover._score_progressively(issues, "o/r", "")

        first_row = table.get_row_at(0)
        assert first_row[2] == "2"
        assert "high reason" in first_row[1]


@pytest.mark.asyncio
async def test_discover_view_issue_separates_analysis_from_source(temp_config, monkeypatch):
    from osmind.github.models import GHComment, GHIssue
    from osmind.tui.screens.discover import DiscoverScreen
    from osmind.tui.widgets.issue_list import IssueTable
    from textual.widgets import Static
    from osmind.engine.issue_brief import IssueBrief
    import osmind.engine.issue_brief
    import osmind.engine.llm

    long_tail = "FULL_TEXT_SENTINEL_" + ("x" * 1900)
    issue = GHIssue(
        42,
        "Tokenizer leak",
        f"The tokenizer cache keeps growing.\n\n{long_tail}",
        ["bug"],
        "https://github.com/o/r/issues/42",
        "o/r",
        "open",
        comments=[
            GHComment("maintainer", "Please include a regression test.", "u", "2026-05-15T01:02:03+00:00")
        ],
    )

    class DummyLLMClient:
        def __init__(self, cfg):
            pass

    class DummyIssueBriefGenerator:
        def __init__(self, llm):
            pass

        def generate(self, issue, reason=""):
            return IssueBrief(
                **_issue_brief_payload(
                    one_liner="这是 tokenizer cache 泄漏问题，适合先补复现测试。",
                    next_steps=["先补复现测试。"],
                )
            )

    monkeypatch.setattr(osmind.engine.llm, "LLMClient", DummyLLMClient)
    monkeypatch.setattr(osmind.engine.issue_brief, "IssueBriefGenerator", DummyIssueBriefGenerator)

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        discover = app.query_one(DiscoverScreen)
        table = app.query_one(IssueTable)
        table.populate([issue])
        table.cursor_coordinate = (0, 0)
        discover._issues_by_number = {str(issue.number): issue}

        await discover.action_view_issue()

        analysis = app.query_one("#issue-analysis-panel", Static).renderable
        source = app.query_one("#issue-source-panel", Static).renderable

    assert "Recommendation" in str(analysis)
    assert "Decision Factors" in str(analysis)
    assert "Evidence" in str(analysis)
    assert "继续/放弃判断" in str(analysis)
    assert "Continue" in str(analysis)
    assert "Stop" in str(analysis)
    assert long_tail not in str(analysis)
    assert "Issue #42: Tokenizer leak" in str(source)
    assert "Issue Brief" in str(source)
    assert str(source).count("Issue Brief") == 1
    assert "One-Liner" in str(source)
    assert "Next Steps" in str(source)
    assert "这是 tokenizer cache 泄漏问题" in str(source)
    assert "Original Issue" in str(source)
    assert "The tokenizer cache keeps growing." in str(source)
    assert long_tail in str(source)
    assert "Comments" in str(source)
    assert "maintainer: Please include a regression test." in str(source)


@pytest.mark.asyncio
async def test_discover_view_issue_uses_cached_issue_brief_without_llm(temp_config, monkeypatch):
    from osmind.cache.store import CacheStore
    from osmind.github.models import GHIssue
    from osmind.tui.screens.discover import DiscoverScreen
    from osmind.tui.widgets.issue_list import IssueTable
    from textual.widgets import Static
    from osmind.engine.issue_brief import IssueBrief
    import osmind.engine.issue_brief
    import osmind.engine.llm

    issue = GHIssue(
        42,
        "Tokenizer leak",
        "Original body stays visible.",
        ["bug"],
        "https://github.com/o/r/issues/42",
        "o/r",
        "open",
        reason="cached issue reason",
    )
    cached_brief = IssueBrief(
        **_issue_brief_payload(
            one_liner="Cached tokenizer brief.",
            why_it_fits="cached issue reason",
            next_steps=["Use cached next step."],
        )
    )
    cache = CacheStore(temp_config.notes_vault / "osmind" / ".cache" / "osmind.db")
    cache.upsert_issue(issue)
    cache.update_issue_brief(issue.repo, issue.number, cached_brief.to_json())

    class FailingLLMClient:
        def __init__(self, cfg):
            raise AssertionError("LLMClient should not be created when a cached brief exists")

    class FailingIssueBriefGenerator:
        def __init__(self, llm):
            raise AssertionError("IssueBriefGenerator should not be created when a cached brief exists")

    monkeypatch.setattr(osmind.engine.llm, "LLMClient", FailingLLMClient)
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

    assert "Cached tokenizer brief." in str(source)
    assert "Use cached next step." in str(source)
    assert "Original body stays visible." in str(source)


@pytest.mark.asyncio
async def test_discover_view_issue_regenerates_cached_brief_when_reason_changes(temp_config, monkeypatch):
    from osmind.cache.store import CacheStore
    from osmind.github.models import GHIssue
    from osmind.tui.screens.discover import DiscoverScreen
    from osmind.tui.widgets.issue_list import IssueTable
    from textual.widgets import Static
    from osmind.engine.issue_brief import IssueBrief
    import osmind.engine.issue_brief
    import osmind.engine.llm

    issue = GHIssue(
        42,
        "Tokenizer leak",
        "Original body stays visible.",
        ["bug"],
        "https://github.com/o/r/issues/42",
        "o/r",
        "open",
        reason="new recommendation reason",
    )
    stale_brief = IssueBrief(
        **_issue_brief_payload(
            one_liner="Old cached tokenizer brief.",
            why_it_fits="old recommendation reason",
        )
    )
    cache = CacheStore(temp_config.notes_vault / "osmind" / ".cache" / "osmind.db")
    cache.upsert_issue(issue)
    cache.update_issue_brief(issue.repo, issue.number, stale_brief.to_json())
    calls = []

    class DummyLLMClient:
        def __init__(self, cfg):
            pass

    class RecordingIssueBriefGenerator:
        def __init__(self, llm):
            pass

        def generate(self, issue, reason=""):
            calls.append((issue.number, reason))
            return IssueBrief(
                **_issue_brief_payload(
                    one_liner="Fresh tokenizer brief.",
                    why_it_fits=reason,
                )
            )

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

    assert calls == [(42, "new recommendation reason")]
    assert "Fresh tokenizer brief." in str(source)
    assert "new recommendation reason" in str(source)
    assert "old recommendation reason" not in str(source)
    assert "new recommendation reason" in cache.get_issue_brief(issue.repo, issue.number)


@pytest.mark.asyncio
async def test_discover_view_issue_ignores_stale_slow_generation_result(temp_config, monkeypatch):
    import asyncio
    import threading
    from osmind.github.models import GHIssue
    from osmind.tui.screens.discover import DiscoverScreen
    from osmind.tui.widgets.issue_list import IssueTable
    from textual.widgets import Static
    from osmind.engine.issue_brief import IssueBrief
    import osmind.engine.issue_brief
    import osmind.engine.llm

    first = GHIssue(1, "First issue", "First body.", [], "u1", "o/r", "open", reason="first reason")
    second = GHIssue(2, "Second issue", "Second body.", [], "u2", "o/r", "open", reason="second reason")
    slow_started = threading.Event()
    release_slow = threading.Event()

    class DummyLLMClient:
        def __init__(self, cfg):
            pass

    class OrderedIssueBriefGenerator:
        def __init__(self, llm):
            pass

        def generate(self, issue, reason=""):
            if issue.number == 1:
                slow_started.set()
                release_slow.wait(timeout=2)
                return IssueBrief(**_issue_brief_payload(one_liner="Slow first brief.", why_it_fits=reason))
            return IssueBrief(**_issue_brief_payload(one_liner="Fast second brief.", why_it_fits=reason))

    monkeypatch.setattr(osmind.engine.llm, "LLMClient", DummyLLMClient)
    monkeypatch.setattr(osmind.engine.issue_brief, "IssueBriefGenerator", OrderedIssueBriefGenerator)

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        discover = app.query_one(DiscoverScreen)
        table = app.query_one(IssueTable)
        table.populate([first, second])
        discover._issues_by_number = {str(first.number): first, str(second.number): second}

        table.cursor_coordinate = (0, 0)
        first_task = asyncio.create_task(discover.action_view_issue())
        while not slow_started.is_set():
            await asyncio.sleep(0.01)

        table.cursor_coordinate = (1, 0)
        await discover.action_view_issue()
        release_slow.set()
        await first_task

        source = app.query_one("#issue-source-panel", Static).renderable

    assert "Issue #2: Second issue" in str(source)
    assert "Fast second brief." in str(source)
    assert "Slow first brief." not in str(source)


@pytest.mark.asyncio
async def test_discover_detail_tab_toggles_analysis_and_source_focus(temp_config, monkeypatch):
    from osmind.github.models import GHIssue
    from osmind.tui.screens.discover import DiscoverScreen
    from osmind.tui.widgets.issue_list import IssueTable
    from textual.widgets import Static
    from osmind.engine.issue_brief import IssueBrief
    import osmind.engine.issue_brief
    import osmind.engine.llm

    issue = GHIssue(42, "Tokenizer leak", "Body", [], "u", "o/r", "open")

    class DummyLLMClient:
        def __init__(self, cfg):
            pass

    class DummyIssueBriefGenerator:
        def __init__(self, llm):
            pass

        def generate(self, issue, reason=""):
            return IssueBrief(**_issue_brief_payload(one_liner="摘要"))

    monkeypatch.setattr(osmind.engine.llm, "LLMClient", DummyLLMClient)
    monkeypatch.setattr(osmind.engine.issue_brief, "IssueBriefGenerator", DummyIssueBriefGenerator)

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        discover = app.query_one(DiscoverScreen)
        table = app.query_one(IssueTable)
        table.populate([issue])
        table.cursor_coordinate = (0, 0)
        discover._issues_by_number = {str(issue.number): issue}

        await discover.action_view_issue()
        analysis = app.query_one("#issue-analysis-panel", Static)
        source = app.query_one("#issue-source-panel", Static)

        assert app.focused is source

        await pilot.press("tab")
        assert app.focused is analysis

        await pilot.press("tab")
        assert app.focused is source


@pytest.mark.asyncio
async def test_discover_enter_key_opens_issue_detail_from_focused_table(temp_config, monkeypatch):
    from osmind.github.models import GHIssue
    from osmind.tui.screens.discover import DiscoverScreen
    from osmind.tui.widgets.issue_list import IssueTable
    from textual.widgets import Static
    from osmind.engine.issue_brief import IssueBrief
    import osmind.engine.issue_brief
    import osmind.engine.llm

    issue = GHIssue(42, "Tokenizer leak", "Body", [], "u", "o/r", "open")

    class DummyLLMClient:
        def __init__(self, cfg):
            pass

    class DummyIssueBriefGenerator:
        def __init__(self, llm):
            pass

        def generate(self, issue, reason=""):
            return IssueBrief(**_issue_brief_payload(one_liner="摘要"))

    monkeypatch.setattr(osmind.engine.llm, "LLMClient", DummyLLMClient)
    monkeypatch.setattr(osmind.engine.issue_brief, "IssueBriefGenerator", DummyIssueBriefGenerator)

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        discover = app.query_one(DiscoverScreen)
        table = app.query_one(IssueTable)
        table.populate([issue])
        table.cursor_coordinate = (0, 0)
        table.focus()
        discover._issues_by_number = {str(issue.number): issue}

        await pilot.press("enter")
        await pilot.pause()

        assert app.query_one("#issue-list-view").display is False
        assert app.query_one("#issue-detail-view").display is True
        assert app.focused is app.query_one("#issue-source-panel", Static)

        await pilot.press("tab")

        assert app.focused is app.query_one("#issue-analysis-panel", Static)


@pytest.mark.asyncio
async def test_discover_issue_detail_is_a_separate_view_and_escape_returns_to_list(temp_config, monkeypatch):
    from osmind.github.models import GHIssue
    from osmind.tui.screens.discover import DiscoverScreen
    from osmind.tui.widgets.issue_list import IssueTable
    from osmind.engine.issue_brief import IssueBrief
    import osmind.engine.issue_brief
    import osmind.engine.llm

    issue = GHIssue(42, "Tokenizer leak", "Body", [], "u", "o/r", "open")

    class DummyLLMClient:
        def __init__(self, cfg):
            pass

    class DummyIssueBriefGenerator:
        def __init__(self, llm):
            pass

        def generate(self, issue, reason=""):
            return IssueBrief(**_issue_brief_payload(one_liner="摘要"))

    monkeypatch.setattr(osmind.engine.llm, "LLMClient", DummyLLMClient)
    monkeypatch.setattr(osmind.engine.issue_brief, "IssueBriefGenerator", DummyIssueBriefGenerator)

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        discover = app.query_one(DiscoverScreen)
        table = app.query_one(IssueTable)
        table.populate([issue])
        table.cursor_coordinate = (0, 0)
        discover._issues_by_number = {str(issue.number): issue}

        await discover.action_view_issue()

        assert app.query_one("#issue-list-view").display is False
        assert app.query_one("#issue-detail-view").display is True

        await pilot.press("escape")

        assert app.query_one("#issue-list-view").display is True
        assert app.query_one("#issue-detail-view").display is False
        assert app.focused is table


@pytest.mark.asyncio
async def test_discover_q_returns_from_issue_detail_without_quitting(temp_config, monkeypatch):
    from osmind.github.models import GHIssue
    from osmind.tui.screens.discover import DiscoverScreen
    from osmind.tui.widgets.issue_list import IssueTable
    from osmind.engine.issue_brief import IssueBrief
    import osmind.engine.issue_brief
    import osmind.engine.llm

    issue = GHIssue(42, "Tokenizer leak", "Body", [], "u", "o/r", "open")

    class DummyLLMClient:
        def __init__(self, cfg):
            pass

    class DummyIssueBriefGenerator:
        def __init__(self, llm):
            pass

        def generate(self, issue, reason=""):
            return IssueBrief(**_issue_brief_payload(one_liner="摘要"))

    monkeypatch.setattr(osmind.engine.llm, "LLMClient", DummyLLMClient)
    monkeypatch.setattr(osmind.engine.issue_brief, "IssueBriefGenerator", DummyIssueBriefGenerator)

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        discover = app.query_one(DiscoverScreen)
        table = app.query_one(IssueTable)
        table.populate([issue])
        table.cursor_coordinate = (0, 0)
        discover._issues_by_number = {str(issue.number): issue}

        await discover.action_view_issue()
        await pilot.press("q")

        assert app.query_one("#issue-list-view").display is True
        assert app.query_one("#issue-detail-view").display is False
        assert app.focused is table


def test_issue_analysis_shows_recommendation_dimensions():
    from osmind.github.models import GHIssue
    from osmind.tui.screens.discover import _format_issue_analysis

    issue = GHIssue(
        42,
        "DeepSeek V4Pro reproduction fails",
        "Requires full model reproduction.",
        ["bug"],
        "https://github.com/o/r/issues/42",
        "o/r",
        "open",
        score=0.2,
        reason="主题匹配，但当前 GPU 资源不足以复现",
        priority="low",
        fit="high",
        resource_fit="blocked",
        actionability="low",
    )

    detail = _format_issue_analysis(issue, resources={"gpus": "4x RTX 4090"})

    assert "Recommendation" in detail
    assert "Action: Defer" in detail
    assert "Why: resource blocked" in detail
    assert "Next Step: Defer until the required environment is available." in detail
    assert "Decision Factors" in detail
    assert "Priority: Low" in detail
    assert "Fit: High" in detail
    assert "Resource Fit: Blocked" in detail
    assert "Actionability: Low" in detail
    assert "Configured Resources: gpus: 4x RTX 4090" in detail
    assert "Evidence" in detail
    assert "- LLM: 主题匹配，但当前 GPU 资源不足以复现" in detail


@pytest.mark.asyncio
async def test_packs_open_uses_visible_row_key_after_sort(temp_config, monkeypatch):
    from osmind.github.models import GHPR
    from osmind.services.library import PackLibrary
    from textual.widgets import DataTable

    library = PackLibrary(
        temp_config.notes_vault,
        temp_config.notes_vault / "osmind" / ".cache" / "osmind.db",
    )
    first = library.write_pr_pack(
        GHPR(
            number=1,
            title="First Pack",
            body="",
            url="https://github.com/o/r/pull/1",
            repo="o/r",
            updated_at="u1",
        )
    )
    second = library.write_pr_pack(
        GHPR(
            number=2,
            title="Second Pack",
            body="",
            url="https://github.com/o/r/pull/2",
            repo="o/r",
            updated_at="u2",
        )
    )
    opened = []
    monkeypatch.setattr("osmind.tui.screens.packs.open_path", lambda path: opened.append(path))

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        app.action_switch_tab("packs")
        table = app.query_one("#packs-table", DataTable)
        app.query_one("PacksScreen").action_reload()
        table.sort("number", key=lambda value: int(str(value)), reverse=False)
        table.cursor_coordinate = (0, 0)
        app.query_one("PacksScreen").action_open_pack()

    assert opened == [first]


@pytest.mark.asyncio
async def test_packs_open_empty_table_does_not_crash(temp_config, monkeypatch):
    opened = []
    monkeypatch.setattr("osmind.tui.screens.packs.open_path", lambda path: opened.append(path))

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        app.action_switch_tab("packs")
        app.query_one("PacksScreen").action_open_pack()

    assert opened == []


@pytest.mark.asyncio
async def test_packs_enter_opens_packet_reader_without_new_shortcut_sprawl(temp_config):
    from osmind.github.models import GHPR
    from osmind.services.library import PackLibrary
    from textual.widgets import DataTable, Markdown

    library = PackLibrary(
        temp_config.notes_vault,
        temp_config.notes_vault / "osmind" / ".cache" / "osmind.db",
    )
    library.write_pr_pack(
        GHPR(
            number=4,
            title="Readable Pack",
            body="Packet body.",
            url="https://github.com/o/r/pull/4",
            repo="o/r",
            updated_at="u4",
        )
    )

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        app.action_switch_tab("packs")
        await pilot.pause()
        packs_table = app.query_one("#packs-table", DataTable)
        packs_table.cursor_coordinate = (0, 0)

        packs_table.focus()
        await pilot.press("enter")
        await pilot.pause()

        section_table = app.query_one("#packet-section-table", DataTable)
        markdown = app.query_one("#packet-markdown", Markdown)

        assert app.query_one("#packs-list-view").display is False
        assert app.query_one("#packet-reader-view").display is True
        assert section_table.row_count >= 3
        assert "# PR #4: Readable Pack" in markdown.source

        first_ten_index = next(
            index
            for index in range(section_table.row_count)
            if section_table.get_row_at(index)[0] == "First 10 Minutes"
        )
        section_table.cursor_coordinate = (first_ten_index, 0)
        app.query_one("PacksScreen").on_data_table_row_highlighted(
            DataTable.RowHighlighted(section_table, first_ten_index, section_table.ordered_rows[first_ten_index].key)
        )
        await pilot.pause()

        assert markdown.source.startswith("## First 10 Minutes")


@pytest.mark.asyncio
async def test_packs_q_returns_from_packet_reader_without_quitting(temp_config):
    from osmind.github.models import GHPR
    from osmind.services.library import PackLibrary
    from textual.widgets import DataTable

    library = PackLibrary(
        temp_config.notes_vault,
        temp_config.notes_vault / "osmind" / ".cache" / "osmind.db",
    )
    library.write_pr_pack(
        GHPR(
            number=4,
            title="Readable Pack",
            body="Packet body.",
            url="https://github.com/o/r/pull/4",
            repo="o/r",
            updated_at="u4",
        )
    )

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        app.action_switch_tab("packs")
        await pilot.pause()
        table = app.query_one("#packs-table", DataTable)
        table.cursor_coordinate = (0, 0)

        table.focus()
        await pilot.press("enter")
        await pilot.pause()

        assert app.query_one("#packet-reader-view").display is True

        await pilot.press("q")
        await pilot.pause()
        await pilot.pause()

        assert app.query_one("#packs-list-view").display is True
        assert app.query_one("#packet-reader-view").display is False
        assert app.focused is table


@pytest.mark.asyncio
async def test_packs_start_work_shows_selected_packet_plan(temp_config):
    from osmind.github.models import GHPR
    from osmind.services.library import PackLibrary
    from textual.widgets import DataTable, Static

    library = PackLibrary(
        temp_config.notes_vault,
        temp_config.notes_vault / "osmind" / ".cache" / "osmind.db",
    )
    library.write_pr_pack(
        GHPR(
            number=3,
            title="Workable Pack",
            body="A small contribution path.",
            url="https://github.com/o/r/pull/3",
            repo="o/r",
            updated_at="u3",
        )
    )

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        app.action_switch_tab("packs")
        await pilot.pause()
        table = app.query_one("#packs-table", DataTable)
        table.cursor_coordinate = (0, 0)

        app.query_one("PacksScreen").action_start_work()
        panel = app.query_one("#pack-start-work-panel", Static)

        assert app.query_one("#packs-list-view").display is False
        assert app.query_one("#pack-start-work-view").display is True

    content = str(panel.renderable)
    markdown = (temp_config.notes_vault / "osmind" / "o_r" / "pr-3-workable-pack.md").read_text(encoding="utf-8")
    assert "Start Work" in content
    assert "Decision: continue" in content
    assert "decision: continue" in markdown
    assert "PR #3: Workable Pack" in content
    assert "First 10 Minutes" in content
    assert "Validation Path" in content
    assert "Agent Exploration Prompt" in content


@pytest.mark.asyncio
async def test_switching_to_packs_lazy_loads_existing_packs(temp_config):
    from osmind.github.models import GHPR
    from osmind.services.library import PackLibrary
    from textual.widgets import DataTable

    library = PackLibrary(
        temp_config.notes_vault,
        temp_config.notes_vault / "osmind" / ".cache" / "osmind.db",
    )
    library.write_pr_pack(
        GHPR(
            number=9,
            title="Existing Pack",
            body="",
            url="https://github.com/o/r/pull/9",
            repo="o/r",
            updated_at="u9",
        )
    )

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        table = app.query_one("#packs-table", DataTable)
        assert table.row_count == 0
        app.action_switch_tab("packs")
        await pilot.pause()
        assert table.row_count == 1


@pytest.mark.asyncio
async def test_switching_to_packs_focuses_packs_table(temp_config):
    from osmind.github.models import GHPR
    from osmind.services.library import PackLibrary
    from textual.widgets import DataTable

    library = PackLibrary(
        temp_config.notes_vault,
        temp_config.notes_vault / "osmind" / ".cache" / "osmind.db",
    )
    library.write_pr_pack(
        GHPR(
            number=12,
            title="Focusable Pack",
            body="",
            url="https://github.com/o/r/pull/12",
            repo="o/r",
            updated_at="u12",
        )
    )

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        table = app.query_one("#packs-table", DataTable)
        await pilot.pause()

        app.action_switch_tab("packs")
        await pilot.pause()

        assert app.focused is table


@pytest.mark.asyncio
async def test_direct_tab_activation_lazy_loads_existing_packs(temp_config):
    from osmind.github.models import GHPR
    from osmind.services.library import PackLibrary
    from textual.widgets import DataTable, TabbedContent

    library = PackLibrary(
        temp_config.notes_vault,
        temp_config.notes_vault / "osmind" / ".cache" / "osmind.db",
    )
    library.write_pr_pack(
        GHPR(
            number=10,
            title="Clicked Pack",
            body="",
            url="https://github.com/o/r/pull/10",
            repo="o/r",
            updated_at="u10",
        )
    )

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        table = app.query_one("#packs-table", DataTable)
        assert table.row_count == 0
        app.query_one(TabbedContent).active = "packs"
        await pilot.pause()
        assert table.row_count == 1


@pytest.mark.asyncio
async def test_switching_to_review_lazy_loads_existing_packs(temp_config):
    from osmind.github.models import GHPR
    from osmind.services.library import PackLibrary
    from textual.widgets import DataTable

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        table = app.query_one("#notes-table", DataTable)
        assert table.row_count == 0
        library = PackLibrary(
            temp_config.notes_vault,
            temp_config.notes_vault / "osmind" / ".cache" / "osmind.db",
        )
        library.write_pr_pack(
            GHPR(
                number=11,
                title="Reviewable Pack",
                body="",
                url="https://github.com/o/r/pull/11",
                repo="o/r",
                updated_at="u11",
            )
        )
        app.action_switch_tab("review")
        await pilot.pause()
        assert table.row_count == 1


def test_review_answer_appends_to_pack_notes(tmp_path):
    from osmind.tui.screens.review import _append_answer_to_pack

    path = tmp_path / "pack.md"
    path.write_text(
        """---
type: osmind-learning-pack
---

# PR #7: Refactor runner

## Notes

Existing note.
""",
        encoding="utf-8",
    )

    _append_answer_to_pack(path, "What changed?", "The runner flow changed.")

    text = path.read_text(encoding="utf-8")
    assert "Existing note." in text
    assert "**Q: What changed?**\n\nThe runner flow changed." in text


def test_review_answer_appends_inside_notes_before_follow_up_section(tmp_path):
    from osmind.tui.screens.review import _append_answer_to_pack

    path = tmp_path / "pack.md"
    path.write_text(
        """---
type: osmind-contribution-packet
---

# PR #7: Refactor runner

## Notes

Existing note.

## Follow-up

Keep this user section.
""",
        encoding="utf-8",
    )

    _append_answer_to_pack(path, "What changed?", "The runner flow changed.")

    text = path.read_text(encoding="utf-8")
    assert (
        "## Notes\n\nExisting note.\n\n**Q: What changed?**\n\n"
        "The runner flow changed.\n\n## Follow-up\n\nKeep this user section."
    ) in text


def test_review_answers_from_pack_lists_saved_review_entries(tmp_path):
    from osmind.tui.screens.review import _review_answers_from_pack

    path = tmp_path / "pack.md"
    path.write_text(
        """---
type: osmind-contribution-packet
---

# Issue #7: Tokenizer leak

## Notes

Existing note.

**Q: First question?**

First answer.

**Q: Second question?**

Second answer.
""",
        encoding="utf-8",
    )

    answers = _review_answers_from_pack(path)

    assert [answer.question for answer in answers] == ["First question?", "Second question?"]
    assert [answer.answer for answer in answers] == ["First answer.", "Second answer."]


def test_review_delete_selected_answer_removes_middle_review_entry(tmp_path):
    from osmind.tui.screens.review import _delete_answer_from_pack

    path = tmp_path / "pack.md"
    path.write_text(
        """---
type: osmind-contribution-packet
---

# Issue #7: Tokenizer leak

## Notes

Existing note.

**Q: First question?**

First answer.

**Q: Second question?**

Second answer.

**Q: Third question?**

Third answer.
""",
        encoding="utf-8",
    )

    deleted = _delete_answer_from_pack(path, 1)

    text = path.read_text(encoding="utf-8")
    assert deleted is True
    assert "Existing note." in text
    assert "**Q: First question?**\n\nFirst answer." in text
    assert "Second question" not in text
    assert "Second answer" not in text
    assert "**Q: Third question?**\n\nThird answer." in text


def test_review_rewrite_selected_answer_updates_only_that_entry(tmp_path):
    from osmind.tui.screens.review import _replace_answer_in_pack

    path = tmp_path / "pack.md"
    path.write_text(
        """---
type: osmind-contribution-packet
---

# Issue #7: Tokenizer leak

## Notes

**Q: First question?**

First answer.

**Q: Second question?**

Second answer.
""",
        encoding="utf-8",
    )

    replaced = _replace_answer_in_pack(path, 1, "Updated second answer.")

    text = path.read_text(encoding="utf-8")
    assert replaced is True
    assert "**Q: First question?**\n\nFirst answer." in text
    assert "**Q: Second question?**\n\nUpdated second answer." in text
    assert "Second answer." not in text


def test_review_delete_last_answer_removes_only_latest_review_entry(tmp_path):
    from osmind.tui.screens.review import _delete_last_answer_from_pack

    path = tmp_path / "pack.md"
    path.write_text(
        """---
type: osmind-contribution-packet
---

# Issue #7: Tokenizer leak

## Notes

Existing note.

**Q: First question?**

First answer.

**Q: Second question?**

Second answer.
""",
        encoding="utf-8",
    )

    deleted = _delete_last_answer_from_pack(path)

    text = path.read_text(encoding="utf-8")
    assert deleted is True
    assert "Existing note." in text
    assert "**Q: First question?**\n\nFirst answer." in text
    assert "Second question" not in text
    assert "Second answer" not in text


@pytest.mark.asyncio
async def test_review_delete_action_removes_last_answer_for_selected_pack(temp_config):
    from osmind.github.models import GHPR
    from osmind.services.library import PackLibrary
    from osmind.tui.screens.review import _append_answer_to_pack
    from textual.widgets import DataTable

    library = PackLibrary(
        temp_config.notes_vault,
        temp_config.notes_vault / "osmind" / ".cache" / "osmind.db",
    )
    path = library.write_pr_pack(
        GHPR(
            number=13,
            title="Review delete pack",
            body="",
            url="https://github.com/o/r/pull/13",
            repo="o/r",
            updated_at="u13",
        )
    )
    _append_answer_to_pack(path, "Can this be deleted?", "Yes, delete this answer.")

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        app.action_switch_tab("review")
        await pilot.pause()
        await pilot.pause()
        table = app.query_one("#notes-table", DataTable)
        table.cursor_coordinate = (0, 0)

        app.query_one("ReviewScreen").action_delete_last_answer()
        await pilot.pause()

    text = path.read_text(encoding="utf-8")
    assert "Can this be deleted?" not in text
    assert "Yes, delete this answer." not in text


@pytest.mark.asyncio
async def test_review_screen_lists_saved_answers_for_selected_pack(temp_config):
    from osmind.github.models import GHPR
    from osmind.services.library import PackLibrary
    from osmind.tui.screens.review import _append_answer_to_pack
    from textual.widgets import DataTable

    library = PackLibrary(
        temp_config.notes_vault,
        temp_config.notes_vault / "osmind" / ".cache" / "osmind.db",
    )
    path = library.write_pr_pack(
        GHPR(
            number=14,
            title="Review answer table pack",
            body="",
            url="https://github.com/o/r/pull/14",
            repo="o/r",
            updated_at="u14",
        )
    )
    _append_answer_to_pack(path, "First question?", "First answer.")
    _append_answer_to_pack(path, "Second question?", "Second answer.")

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        app.action_switch_tab("review")
        await pilot.pause()
        await pilot.pause()
        answers = app.query_one("#answers-table", DataTable)

        assert answers.row_count == 2
        assert answers.get_row_at(0)[1] == "First question?"
        assert answers.get_row_at(1)[1] == "Second question?"


@pytest.mark.asyncio
async def test_review_delete_action_removes_selected_answer_for_selected_pack(temp_config):
    from osmind.github.models import GHPR
    from osmind.services.library import PackLibrary
    from osmind.tui.screens.review import _append_answer_to_pack
    from textual.widgets import DataTable

    library = PackLibrary(
        temp_config.notes_vault,
        temp_config.notes_vault / "osmind" / ".cache" / "osmind.db",
    )
    path = library.write_pr_pack(
        GHPR(
            number=15,
            title="Review selected delete pack",
            body="",
            url="https://github.com/o/r/pull/15",
            repo="o/r",
            updated_at="u15",
        )
    )
    _append_answer_to_pack(path, "First question?", "First answer.")
    _append_answer_to_pack(path, "Second question?", "Second answer.")

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        app.action_switch_tab("review")
        await pilot.pause()
        await pilot.pause()
        answers = app.query_one("#answers-table", DataTable)
        answers.focus()
        answers.cursor_coordinate = (0, 0)

        app.query_one("ReviewScreen").action_delete_selected_answer()
        await pilot.pause()

    text = path.read_text(encoding="utf-8")
    assert "First question?" not in text
    assert "First answer." not in text
    assert "**Q: Second question?**\n\nSecond answer." in text


@pytest.mark.asyncio
async def test_review_rewrite_action_replaces_selected_answer(temp_config):
    from osmind.github.models import GHPR
    from osmind.services.library import PackLibrary
    from osmind.tui.screens.review import _append_answer_to_pack
    from textual.widgets import DataTable, Input

    library = PackLibrary(
        temp_config.notes_vault,
        temp_config.notes_vault / "osmind" / ".cache" / "osmind.db",
    )
    path = library.write_pr_pack(
        GHPR(
            number=16,
            title="Review rewrite pack",
            body="",
            url="https://github.com/o/r/pull/16",
            repo="o/r",
            updated_at="u16",
        )
    )
    _append_answer_to_pack(path, "First question?", "First answer.")
    _append_answer_to_pack(path, "Second question?", "Second answer.")

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        app.action_switch_tab("review")
        await pilot.pause()
        await pilot.pause()
        answers = app.query_one("#answers-table", DataTable)
        answers.focus()
        answers.cursor_coordinate = (1, 0)

        review = app.query_one("ReviewScreen")
        review.action_rewrite_answer()
        review_input = app.query_one("#review-input", Input)
        assert app.focused is review_input
        assert review_input.value == "Second answer."

        review_input.value = "Updated second answer."
        review.on_input_submitted(Input.Submitted(review_input, review_input.value))
        await pilot.pause()

    text = path.read_text(encoding="utf-8")
    assert "**Q: First question?**\n\nFirst answer." in text
    assert "**Q: Second question?**\n\nUpdated second answer." in text
    assert "Second answer." not in text


def test_review_bindings_include_delete_last_answer():
    from osmind.tui.screens.review import ReviewScreen

    bindings_by_action = {binding[1]: binding for binding in ReviewScreen.BINDINGS}

    assert bindings_by_action["delete_selected_answer"][0] == "delete"
    assert bindings_by_action["rewrite_answer"][0] == "e"


@pytest.mark.asyncio
async def test_discover_generate_pack_writes_selected_issue(temp_config, monkeypatch):
    from osmind.github.models import GHIssue
    from osmind.tui.screens.discover import DiscoverScreen

    issue = GHIssue(
        number=42,
        title="Tokenizer leak",
        body="Body",
        labels=["bug"],
        url="https://github.com/o/r/issues/42",
        repo="o/r",
        state="open",
        updated_at="u42",
    )
    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        discover = app.query_one(DiscoverScreen)
        monkeypatch.setattr(discover, "_get_selected_issue", lambda: issue)
        await discover.action_generate_pack()

    path = temp_config.notes_vault / "osmind" / "o_r" / "issue-42-tokenizer-leak.md"
    assert path.exists()
    assert "# Issue #42: Tokenizer leak" in path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_discover_generate_pack_includes_cached_issue_brief(temp_config, monkeypatch):
    from osmind.cache.store import CacheStore
    from osmind.engine.issue_brief import IssueBrief
    from osmind.github.models import GHIssue
    from osmind.tui.screens.discover import DiscoverScreen

    issue = GHIssue(
        number=42,
        title="Tokenizer leak",
        body="Body",
        labels=["bug"],
        url="https://github.com/o/r/issues/42",
        repo="o/r",
        state="open",
        updated_at="u42",
        reason="cached fit reason",
    )
    brief = IssueBrief(
        **_issue_brief_payload(
            one_liner="Cached packet brief.",
            why_it_fits="cached fit reason",
            next_steps=["Carry this brief into the packet."],
        )
    )
    cache = CacheStore(temp_config.notes_vault / "osmind" / ".cache" / "osmind.db")
    cache.upsert_issue(issue)
    cache.update_issue_brief(issue.repo, issue.number, brief.to_json())

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        discover = app.query_one(DiscoverScreen)
        monkeypatch.setattr(discover, "_get_selected_issue", lambda: issue)
        await discover.action_generate_pack()

    path = temp_config.notes_vault / "osmind" / "o_r" / "issue-42-tokenizer-leak.md"
    markdown = path.read_text(encoding="utf-8")
    assert "## Issue Brief" in markdown
    assert "Cached packet brief." in markdown
    assert "Carry this brief into the packet." in markdown


@pytest.mark.asyncio
async def test_discover_start_work_generates_packet_and_shows_plan(temp_config, monkeypatch):
    from osmind.github.models import GHIssue
    from osmind.tui.screens.discover import DiscoverScreen
    from textual.widgets import Static

    issue = GHIssue(
        number=43,
        title="Tokenizer leak",
        body="The tokenizer cache keeps growing. Please add a pytest regression.",
        labels=["bug"],
        url="https://github.com/o/r/issues/43",
        repo="o/r",
        state="open",
        updated_at="u43",
        reason="资源足够，适合先写最小复现。",
        priority="high",
        fit="high",
        resource_fit="ok",
        actionability="high",
    )

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        discover = app.query_one(DiscoverScreen)
        monkeypatch.setattr(discover, "_get_selected_issue", lambda: issue)

        await discover.action_start_work()
        panel = app.query_one("#start-work-panel", Static)

        assert app.query_one("#issue-list-view").display is False
        assert app.query_one("#start-work-view").display is True

    content = str(panel.renderable)
    markdown = (temp_config.notes_vault / "osmind" / "o_r" / "issue-43-tokenizer-leak.md").read_text(encoding="utf-8")
    assert "Start Work" in content
    assert "Decision: continue" in content
    assert "decision: continue" in markdown
    assert "Issue #43: Tokenizer leak" in content
    assert "First 10 Minutes" in content
    assert "Validation Path" in content
    assert "Agent Exploration Prompt" in content


def test_discover_bindings_keep_only_core_opportunity_actions():
    from osmind.tui.screens.discover import DiscoverScreen

    bindings_by_action = {b[1]: b[2] for b in DiscoverScreen.BINDINGS}
    keys_by_action = {b[1]: b[0] for b in DiscoverScreen.BINDINGS}
    bound_keys = {b[0] for b in DiscoverScreen.BINDINGS}

    assert bindings_by_action["open_pack"] == "Open Packet"
    assert bindings_by_action["decide"] == "Decide"
    assert bindings_by_action["update"] == "Load/Update"
    assert bindings_by_action["start_work"] == "Start Work"
    assert keys_by_action["update"] == "u"
    assert keys_by_action["start_work"] == "w"
    assert keys_by_action["decide"] == "space"
    assert keys_by_action["view_issue"] == "enter"
    assert ("v", "view_issue", "View Issue") in DiscoverScreen.BINDINGS
    assert {"f", "s", "g", "y", "l", "n"}.isdisjoint(bound_keys)
    assert "r" not in {binding[0] for binding in DiscoverScreen.BINDINGS}


@pytest.mark.asyncio
async def test_discover_update_menu_can_read_cache_without_github(temp_config, monkeypatch):
    from osmind.cache.store import CacheStore
    from osmind.github.models import GHIssue
    from osmind.tui.screens.discover import DiscoverScreen
    from osmind.tui.update_dialog import QueueUpdateDialog
    from osmind.tui.widgets.issue_list import IssueTable
    import osmind.github.client

    cache = CacheStore(temp_config.notes_vault / "osmind" / ".cache" / "osmind.db")
    cached = GHIssue(1, "Cached issue", "Old body", [], "old", "sgl-project/sglang", "open")
    cache.upsert_issue(cached)
    cache.update_issue_score(cached.repo, "issue", cached.number, 0.1, "old cached reason")

    class FailingGitHubClient:
        def __init__(self, token=""):
            pass

        def get_issues(self, repo, limit=30, include_comments=False):
            raise AssertionError("Reading cache should not fetch from GitHub")

    monkeypatch.setattr(osmind.github.client, "GitHubClient", FailingGitHubClient)

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.query_one(DiscoverScreen).action_update()
        await pilot.pause()

        assert isinstance(app.screen, QueueUpdateDialog)

        await pilot.press("enter")
        await pilot.pause()
        table = app.query_one(IssueTable)
        row = table.get_row_at(0)

    assert row[0] == "Skip"
    assert "old cached reason" in row[1]
    assert row[2] == "1"
    log_path = temp_config.notes_vault / "osmind" / ".cache" / "osmind.log"
    if log_path.exists():
        log_text = log_path.read_text(encoding="utf-8")
        assert "NoActiveWorker" not in log_text
        assert "Failed to update issues" not in log_text


@pytest.mark.asyncio
async def test_discover_update_menu_can_fetch_and_rescore(temp_config, monkeypatch):
    from osmind.cache.store import CacheStore
    from osmind.github.models import GHIssue
    from osmind.tui.screens.discover import DiscoverScreen
    from osmind.tui.update_dialog import QueueUpdateDialog
    from osmind.tui.widgets.issue_list import IssueTable
    import osmind.engine.llm
    import osmind.engine.ranker
    import osmind.github.client

    cache = CacheStore(temp_config.notes_vault / "osmind" / ".cache" / "osmind.db")
    cached = GHIssue(1, "Cached issue", "Old body", [], "old", "sgl-project/sglang", "open")
    cache.upsert_issue(cached)
    cache.update_issue_score(cached.repo, "issue", cached.number, 0.1, "old cached reason")
    fetched = GHIssue(2, "Fetched issue", "New body", [], "new", "sgl-project/sglang", "open")
    calls = []

    class RecordingGitHubClient:
        def __init__(self, token=""):
            pass

        def get_issues(self, repo, limit=30, include_comments=False):
            calls.append((repo, limit, include_comments))
            return [fetched]

    class DummyLLMClient:
        def __init__(self, cfg):
            pass

    class RecordingRanker:
        def __init__(self, llm, interests, skills, resources=None):
            assert resources == {"gpus": "4x RTX 4090"}

        def score_one(self, issue):
            issue.score = 0.8
            issue.priority = "high"
            issue.fit = "high"
            issue.resource_fit = "ok"
            issue.actionability = "high"
            issue.reason = "fresh score"
            return issue

    monkeypatch.setattr(osmind.github.client, "GitHubClient", RecordingGitHubClient)
    monkeypatch.setattr(osmind.engine.llm, "LLMClient", DummyLLMClient)
    monkeypatch.setattr(osmind.engine.ranker, "Ranker", RecordingRanker)

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app.query_one(DiscoverScreen).action_update()
        await pilot.pause()

        assert isinstance(app.screen, QueueUpdateDialog)

        await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause()
        table = app.query_one(IssueTable)
        row = table.get_row_at(0)

    fresh_cache = CacheStore(temp_config.notes_vault / "osmind" / ".cache" / "osmind.db")
    cached_new_issue = {issue.number: issue for issue in fresh_cache.list_issues("sgl-project/sglang")}[2]
    assert calls == [("sgl-project/sglang", 30, False)]
    assert row[0] == "Do now"
    assert "fresh score" in row[1]
    assert row[2] == "2"
    assert cached_new_issue.priority == "high"
    assert cached_new_issue.reason == "fresh score"


@pytest.mark.asyncio
async def test_discover_update_fetches_directly_when_no_cache(temp_config, monkeypatch):
    from osmind.cache.store import CacheStore
    from osmind.github.models import GHIssue
    from osmind.tui.screens.discover import DiscoverScreen
    from osmind.tui.widgets.issue_list import IssueTable
    import osmind.engine.llm
    import osmind.engine.ranker
    import osmind.github.client

    fetched = GHIssue(2, "Fetched issue", "New body", [], "new", "sgl-project/sglang", "open")
    calls = []

    class RecordingGitHubClient:
        def __init__(self, token=""):
            pass

        def get_issues(self, repo, limit=30, include_comments=False):
            calls.append((repo, limit, include_comments))
            return [fetched]

    class DummyLLMClient:
        def __init__(self, cfg):
            pass

    class RecordingRanker:
        def __init__(self, llm, interests, skills, resources=None):
            pass

        def score_one(self, issue):
            issue.score = 0.8
            issue.priority = "high"
            issue.fit = "high"
            issue.resource_fit = "ok"
            issue.actionability = "high"
            issue.reason = "fresh score"
            return issue

    monkeypatch.setattr(osmind.github.client, "GitHubClient", RecordingGitHubClient)
    monkeypatch.setattr(osmind.engine.llm, "LLMClient", DummyLLMClient)
    monkeypatch.setattr(osmind.engine.ranker, "Ranker", RecordingRanker)

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        discover = app.query_one(DiscoverScreen)
        await discover.action_update()

        table = app.query_one(IssueTable)
        row = table.get_row_at(0)

    fresh_cache = CacheStore(temp_config.notes_vault / "osmind" / ".cache" / "osmind.db")
    cached_new_issue = {issue.number: issue for issue in fresh_cache.list_issues("sgl-project/sglang")}[2]
    assert calls == [("sgl-project/sglang", 30, False)]
    assert row[0] == "Do now"
    assert "fresh score" in row[1]
    assert cached_new_issue.reason == "fresh score"


@pytest.mark.asyncio
async def test_discover_rescore_uses_cached_issues_without_github(temp_config, monkeypatch):
    from osmind.cache.store import CacheStore
    from osmind.github.models import GHIssue
    from osmind.tui.screens.discover import DiscoverScreen
    from osmind.tui.widgets.issue_list import IssueTable
    import osmind.engine.llm
    import osmind.engine.ranker
    import osmind.github.client

    issue = GHIssue(42, "Cached issue", "Body", [], "u", "sgl-project/sglang", "open")
    cache = CacheStore(temp_config.notes_vault / "osmind" / ".cache" / "osmind.db")
    cache.upsert_issue(issue)
    cache.update_issue_score(issue.repo, "issue", issue.number, 0.1, "old score")

    class FailingGitHubClient:
        def __init__(self, token=""):
            pass

        def get_issues(self, repo, limit=30, include_comments=False):
            raise AssertionError("Rescore should not fetch from GitHub")

    class DummyLLMClient:
        def __init__(self, cfg):
            pass

    class ResourceAwareRanker:
        def __init__(self, llm, interests, skills, resources=None):
            assert resources == {"gpus": "4x RTX 4090"}

        def score_one(self, issue):
            issue.score = 0.2
            issue.priority = "low"
            issue.fit = "high"
            issue.resource_fit = "blocked"
            issue.actionability = "low"
            issue.reason = "rescored with current resources"
            return issue

    monkeypatch.setattr(osmind.github.client, "GitHubClient", FailingGitHubClient)
    monkeypatch.setattr(osmind.engine.llm, "LLMClient", DummyLLMClient)
    monkeypatch.setattr(osmind.engine.ranker, "Ranker", ResourceAwareRanker)

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        discover = app.query_one(DiscoverScreen)
        await discover.action_rescore()

        table = app.query_one(IssueTable)
        row = table.get_row_at(0)

    assert row[0] == "Defer"
    assert row[1].startswith("resource blocked:")
    assert "rescored with current resources" in row[1]
    assert row[2] == "42"


@pytest.mark.asyncio
async def test_discover_space_decides_selected_choice(temp_config):
    from osmind.github.models import GHIssue
    from osmind.services.library import PackLibrary
    from osmind.tui.decision_dialog import DecisionDialog
    from osmind.tui.screens.discover import DiscoverScreen
    from osmind.tui.widgets.issue_list import IssueTable

    issue = GHIssue(
        number=42,
        title="Tokenizer leak",
        body="Body",
        labels=["bug"],
        url="https://github.com/o/r/issues/42",
        repo="o/r",
        state="open",
        updated_at="u42",
    )
    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        discover = app.query_one(DiscoverScreen)
        table = app.query_one(IssueTable)
        table.populate([issue])
        table.cursor_coordinate = (0, 0)
        table.focus()
        discover._issues_by_number = {str(issue.number): issue}

        await pilot.press("space")
        await pilot.pause()

        assert isinstance(app.screen, DecisionDialog)

        await pilot.press("enter")
        await pilot.pause()

    path = temp_config.notes_vault / "osmind" / "o_r" / "issue-42-tokenizer-leak.md"
    library = PackLibrary(
        temp_config.notes_vault,
        temp_config.notes_vault / "osmind" / ".cache" / "osmind.db",
    )
    markdown = path.read_text(encoding="utf-8")
    assert "decision: defer" in markdown
    assert library.list_packs()[0]["decision"] == "defer"
    assert library.list_packs()[0]["decision_resource_hash"]


@pytest.mark.asyncio
async def test_packs_screen_uses_contribution_packet_language(temp_config):
    from textual.widgets import DataTable, Label

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        labels = [str(label.renderable) for label in app.query(Label)]
        table = app.query_one("#packs-table", DataTable)

    assert any("Contribution Packets" in label for label in labels)
    assert all("Learning Packs" not in label for label in labels)
    assert any("decision" in str(column.label).lower() for column in table.columns.values())


@pytest.mark.asyncio
async def test_packs_space_decides_selected_packet_from_menu_choice(temp_config):
    from osmind.github.models import GHIssue
    from osmind.services.library import PackLibrary
    from osmind.tui.decision_dialog import DecisionDialog
    from textual.widgets import DataTable

    library = PackLibrary(
        temp_config.notes_vault,
        temp_config.notes_vault / "osmind" / ".cache" / "osmind.db",
    )
    path = library.write_issue_pack(
        GHIssue(
            number=42,
            title="Tokenizer leak",
            body="Body",
            labels=["bug"],
            url="https://github.com/o/r/issues/42",
            repo="o/r",
            state="open",
            updated_at="u42",
        )
    )

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        app.action_switch_tab("packs")
        await pilot.pause()
        table = app.query_one("#packs-table", DataTable)
        table.cursor_coordinate = (0, 0)
        table.focus()

        await pilot.press("space")
        await pilot.pause()

        assert isinstance(app.screen, DecisionDialog)

        await pilot.press("enter")
        await pilot.pause()
        visible_row = table.get_row_at(0)

    markdown = path.read_text(encoding="utf-8")
    assert "decision: defer" in markdown
    assert "defer" in [str(cell) for cell in visible_row]


@pytest.mark.asyncio
async def test_review_screen_uses_contribution_packet_language(temp_config):
    from textual.widgets import Label

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        labels = [str(label.renderable) for label in app.query(Label)]

    assert any("Contribution Packets" in label for label in labels)


@pytest.mark.asyncio
async def test_settings_screen_reports_runtime_health(temp_config):
    from osmind.tui.screens.settings import SettingsScreen
    from textual.widgets import Static

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        app.action_switch_tab("settings")
        await pilot.pause()
        settings = app.query_one(SettingsScreen)
        settings.action_reload()

        content = str(app.query_one("#settings-health", Static).renderable)

    assert "GitHub token" in content
    assert "LLM" in content
    assert "Notes vault" in content
    assert "Resources" in content
    assert "4x RTX 4090" in content


@pytest.mark.asyncio
async def test_discover_open_pack_uses_generated_pack_path(temp_config, monkeypatch):
    from osmind.github.models import GHIssue
    from osmind.tui.screens.discover import DiscoverScreen

    issue = GHIssue(
        number=42,
        title="Tokenizer leak",
        body="Body",
        labels=["bug"],
        url="https://github.com/o/r/issues/42",
        repo="o/r",
        state="open",
        updated_at="u42",
    )
    opened = []
    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        discover = app.query_one(DiscoverScreen)
        monkeypatch.setattr(discover, "_get_selected_issue", lambda: issue)
        monkeypatch.setattr("osmind.tui.screens.discover.open_path", lambda path: opened.append(path))
        await discover.action_generate_pack()
        discover.action_open_pack()

    assert opened == [temp_config.notes_vault / "osmind" / "o_r" / "issue-42-tokenizer-leak.md"]


@pytest.mark.asyncio
async def test_discover_open_pack_uses_cached_pack_without_in_memory_path(temp_config, monkeypatch):
    from osmind.github.models import GHIssue
    from osmind.services.library import PackLibrary
    from osmind.tui.screens.discover import DiscoverScreen

    issue = GHIssue(
        number=42,
        title="Tokenizer leak",
        body="Body",
        labels=["bug"],
        url="https://github.com/o/r/issues/42",
        repo="o/r",
        state="open",
        updated_at="u42",
    )
    path = PackLibrary(
        temp_config.notes_vault,
        temp_config.notes_vault / "osmind" / ".cache" / "osmind.db",
    ).write_issue_pack(issue)
    opened = []

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        discover = app.query_one(DiscoverScreen)
        monkeypatch.setattr(discover, "_get_selected_issue", lambda: issue)
        monkeypatch.setattr("osmind.tui.screens.discover.open_path", lambda opened_path: opened.append(opened_path))
        discover.action_open_pack()

    assert opened == [path]


@pytest.mark.asyncio
async def test_discover_open_pack_ignores_missing_cached_file(temp_config, monkeypatch):
    from osmind.github.models import GHIssue
    from osmind.services.library import PackLibrary
    from osmind.tui.screens.discover import DiscoverScreen

    issue = GHIssue(
        number=42,
        title="Tokenizer leak",
        body="Body",
        labels=["bug"],
        url="https://github.com/o/r/issues/42",
        repo="o/r",
        state="open",
        updated_at="u42",
    )
    path = PackLibrary(
        temp_config.notes_vault,
        temp_config.notes_vault / "osmind" / ".cache" / "osmind.db",
    ).write_issue_pack(issue)
    path.unlink()
    opened = []

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        discover = app.query_one(DiscoverScreen)
        monkeypatch.setattr(discover, "_get_selected_issue", lambda: issue)
        monkeypatch.setattr("osmind.tui.screens.discover.open_path", lambda opened_path: opened.append(opened_path))
        discover.action_open_pack()

    assert opened == []


@pytest.mark.asyncio
async def test_discover_open_pack_does_not_confuse_same_number_different_repos(temp_config, monkeypatch):
    from osmind.github.models import GHIssue
    from osmind.tui.screens.discover import DiscoverScreen

    first_issue = GHIssue(42, "First", "Body", [], "https://github.com/a/r/issues/42", "a/r", "open")
    second_issue = GHIssue(42, "Second", "Body", [], "https://github.com/b/r/issues/42", "b/r", "open")
    opened = []

    app = OsmindApp(temp_config)
    async with app.run_test() as pilot:
        discover = app.query_one(DiscoverScreen)
        monkeypatch.setattr("osmind.tui.screens.discover.open_path", lambda path: opened.append(path))
        monkeypatch.setattr(discover, "_get_selected_issue", lambda: first_issue)
        await discover.action_generate_pack()
        monkeypatch.setattr(discover, "_get_selected_issue", lambda: second_issue)
        discover.action_open_pack()

    assert opened == []
