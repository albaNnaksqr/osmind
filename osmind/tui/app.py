from __future__ import annotations
from pathlib import Path
import sys

from textual.app import App, ComposeResult
from textual.css.query import NoMatches
from textual.widgets import DataTable, Footer, Header, Input, TabbedContent, TabPane

from osmind.config import Config
from osmind.tui.screens.discover import DiscoverScreen
from osmind.tui.screens.packs import PacksScreen
from osmind.tui.screens.review import ReviewScreen
from osmind.tui.screens.settings import SettingsScreen
from osmind.tui.widgets.issue_list import IssueTable


class OsmindApp(App):
    CSS = """
    TabbedContent { height: 1fr; }
    """
    BINDINGS = [
        ("d", "switch_tab('discover')", "Discover"),
        ("p", "switch_tab('packs')", "Packs"),
        ("r", "switch_tab('review')", "Review"),
        ("t", "switch_tab('settings')", "Settings"),
        ("escape", "leave_input", "Back"),
        ("ctrl+q", "quit", "Quit"),
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
            with TabPane("Settings", id="settings"):
                yield SettingsScreen()
        yield Footer()

    def action_switch_tab(self, tab: str) -> None:
        self.query_one(TabbedContent).active = tab
        self._focus_active_tab_after_refresh(tab)

    def action_leave_input(self) -> None:
        if not isinstance(self.focused, Input):
            return

        active_tab = self.query_one(TabbedContent).active
        if active_tab == "discover":
            self.query_one(IssueTable).focus()
        elif active_tab == "packs":
            self.query_one("#packs-table", DataTable).focus()
        elif active_tab == "review":
            self.query_one("#notes-table", DataTable).focus()
        else:
            self.set_focus(None)

    def on_key(self, event) -> None:
        if event.key != "q" or isinstance(self.focused, Input):
            return
        if self._context_back():
            event.prevent_default()
            event.stop()

    def _context_back(self) -> bool:
        try:
            active_tab = self.query_one(TabbedContent).active
            if active_tab == "discover" and self._discover_back_if_open():
                return True
            if active_tab == "packs" and self._packs_back_if_open():
                return True
            return self._discover_back_if_open() or self._packs_back_if_open()
        except NoMatches:
            return False

    def _discover_back_if_open(self) -> bool:
        discover = self.query_one(DiscoverScreen)
        if (
            discover.query_one("#issue-detail-view").display
            or discover.query_one("#start-work-view").display
        ):
            discover.action_back_to_list()
            return True
        return False

    def _packs_back_if_open(self) -> bool:
        packs = self.query_one(PacksScreen)
        if (
            packs.query_one("#packet-reader-view").display
            or packs.query_one("#pack-start-work-view").display
        ):
            packs.action_back_to_list()
            return True
        return False

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        if event.pane.id:
            self.call_after_refresh(lambda pane_id=event.pane.id: self._activate_tab_if_current(pane_id))

    def _activate_tab_if_current(self, tab: str) -> None:
        if self.query_one(TabbedContent).active != tab:
            return
        self._activate_tab(tab)

    def _activate_tab(self, tab: str) -> None:
        try:
            if tab == "packs":
                self.query_one(PacksScreen).action_reload()
            elif tab == "review":
                self.query_one(ReviewScreen).action_reload()
            elif tab == "settings":
                self.query_one(SettingsScreen).action_reload()
            self._focus_active_tab(tab)
        except NoMatches:
            return

    def _focus_active_tab_after_refresh(self, tab: str) -> None:
        self.call_after_refresh(lambda: self._focus_active_tab(tab))

    def _focus_active_tab(self, tab: str) -> None:
        if tab == "discover":
            self.query_one(IssueTable).focus()
        elif tab == "packs":
            self.query_one("#packs-table", DataTable).focus()
        elif tab == "review":
            self.query_one("#notes-table", DataTable).focus()
        elif tab == "settings":
            self.query_one("#settings-health").focus()


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
