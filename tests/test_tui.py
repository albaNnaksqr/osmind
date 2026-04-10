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


@pytest.mark.asyncio
async def test_app_composes(mock_config):
    app = OsmindApp(mock_config)
    async with app.run_test() as pilot:
        assert app.query_one("TabbedContent") is not None


@pytest.mark.asyncio
async def test_tab_navigation(mock_config):
    app = OsmindApp(mock_config)
    async with app.run_test() as pilot:
        from textual.widgets import TabbedContent
        tabs = app.query_one(TabbedContent)
        # Verify BINDINGS list covers all three tabs
        binding_actions = {b[1] for b in app.BINDINGS}
        assert "switch_tab('discover')" in binding_actions
        assert "switch_tab('learn')" in binding_actions
        assert "switch_tab('review')" in binding_actions
        # Verify tab IDs exist in the TabbedContent
        tab_ids = {pane.id for pane in tabs.query("TabPane")}
        assert "discover" in tab_ids
        assert "learn" in tab_ids
        assert "review" in tab_ids
