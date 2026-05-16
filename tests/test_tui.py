# tests/test_tui.py
import pytest
from unittest.mock import MagicMock
from osmind.config import Config, LLMConfig, AgentConfig
from osmind.tui.app import OsmindApp
from pathlib import Path


@pytest.fixture
def mock_config():
    return Config(
        interests=["SGLang"],
        skills=["Python"],
        resources={},
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
        resources={},
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
        # Verify tab IDs exist in the TabbedContent
        tab_ids = {pane.id for pane in tabs.query("TabPane")}
        assert "discover" in tab_ids
        assert "packs" in tab_ids
        assert "learn" not in tab_ids
        assert "review" in tab_ids


def test_discover_has_no_learn_binding():
    from osmind.tui.screens.discover import DiscoverScreen

    binding_actions = {b[1] for b in DiscoverScreen.BINDINGS}

    assert "open_in_learn" not in binding_actions
    assert all("learn" not in action for action in binding_actions)


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
        assert table.row_count == 1
