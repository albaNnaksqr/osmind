from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Label

from osmind.packs.opener import open_path
from osmind.services.library import PackLibrary
from osmind.tui.suspend import suspend_if_supported


class PacksScreen(Vertical):
    BINDINGS = [
        ("o", "open_pack", "Open Packet"),
        ("u", "reload", "Reload"),
    ]

    def compose(self) -> ComposeResult:
        yield Label("[bold]Contribution Packets[/bold]", markup=True)
        yield DataTable(id="packs-table", cursor_type="row")
        yield Label("[dim]o: open  u: reload  r: review[/dim]", markup=True)

    def on_mount(self) -> None:
        table = self.query_one("#packs-table", DataTable)
        table.add_columns(
            ("Type", "type"),
            ("#", "number"),
            ("Repo", "repo"),
            ("Status", "status"),
            ("Decision", "decision"),
            ("Confidence", "confidence"),
            ("Path", "path"),
        )
        self._packs_by_key: dict[str, dict] = {}

    def _library(self) -> PackLibrary:
        cache_path = self.app.config.notes_vault / "osmind" / ".cache" / "osmind.db"
        return PackLibrary(self.app.config.notes_vault, cache_path)

    def _load(self) -> None:
        packs = self._library().list_packs()
        self._packs_by_key = {str(idx): pack for idx, pack in enumerate(packs)}
        table = self.query_one("#packs-table", DataTable)
        table.clear()
        for idx, pack in enumerate(packs):
            table.add_row(
                pack["source_type"],
                str(pack["number"]),
                pack["repo"],
                pack["status"],
                pack.get("decision", "undecided"),
                pack["confidence"],
                pack["path"],
                key=str(idx),
            )

    def action_reload(self) -> None:
        self._load()

    def action_open_pack(self) -> None:
        table = self.query_one("#packs-table", DataTable)
        if table.cursor_row is None or table.cursor_row >= len(table.ordered_rows):
            self.notify("No pack selected", severity="warning")
            return
        row_key = table.ordered_rows[table.cursor_row].key
        pack = self._packs_by_key.get(str(row_key.value))
        if pack is None:
            self.notify("No pack selected", severity="warning")
            return
        with suspend_if_supported(self.app):
            open_path(Path(pack["path"]))
