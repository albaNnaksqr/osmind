from __future__ import annotations
from pathlib import Path
import sys

from textual.app import App, ComposeResult
from textual.widgets import Header, Footer, TabbedContent, TabPane

from osmind.config import Config
from osmind.tui.screens.discover import DiscoverScreen
from osmind.tui.screens.packs import PacksScreen
from osmind.tui.screens.review import ReviewScreen


class OsmindApp(App):
    CSS = """
    TabbedContent { height: 1fr; }
    """
    BINDINGS = [
        ("d", "switch_tab('discover')", "Discover"),
        ("p", "switch_tab('packs')", "Packs"),
        ("r", "switch_tab('review')", "Review"),
        ("q", "quit", "Quit"),
    ]

    def __init__(self, config: Config):
        super().__init__()
        self.config = config

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="discover"):
            with TabPane("Discover", id="discover"):
                yield DiscoverScreen()
            with TabPane("Packs", id="packs"):
                yield PacksScreen()
            with TabPane("Review", id="review"):
                yield ReviewScreen()
        yield Footer()

    def action_switch_tab(self, tab: str) -> None:
        self.query_one(TabbedContent).active = tab

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        if event.pane.id == "packs":
            self.query_one(PacksScreen).action_reload()


def main():
    profile_path = Path("profile.yaml")
    if not profile_path.exists():
        print("profile.yaml not found. Copy profile.yaml.example and edit it.")
        sys.exit(1)
    config = Config.from_file(profile_path)
    app = OsmindApp(config)
    app.run()


if __name__ == "__main__":
    main()
