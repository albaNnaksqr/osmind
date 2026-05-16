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
