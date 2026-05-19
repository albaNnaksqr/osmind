from __future__ import annotations

import asyncio
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import DataTable, Label

from osmind.logs import log_exception
from osmind.packs.opener import open_path
from osmind.services.library import PackLibrary
from osmind.tui.suspend import suspend_if_supported


class PacksScreen(Vertical):
    BINDINGS = [
        ("o", "open_pack", "Open Packet"),
        ("y", "mark_continue", "Continue"),
        ("l", "mark_defer", "Defer"),
        ("n", "mark_discard", "Discard"),
        ("u", "reload", "Reload"),
    ]

    def compose(self) -> ComposeResult:
        yield Label("[bold]Contribution Packets[/bold]", markup=True)
        yield DataTable(id="packs-table", cursor_type="row")
        yield Label("[dim]o: open  y/l/n: continue/defer/discard  u: reload  r: review[/dim]", markup=True)

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

    def _selected_pack(self) -> dict | None:
        table = self.query_one("#packs-table", DataTable)
        if table.cursor_row is None or table.cursor_row >= len(table.ordered_rows):
            self.notify("No pack selected", severity="warning")
            return None
        row_key = table.ordered_rows[table.cursor_row].key
        pack = self._packs_by_key.get(str(row_key.value))
        if pack is None:
            self.notify("No pack selected", severity="warning")
        return pack

    def action_open_pack(self) -> None:
        pack = self._selected_pack()
        if pack is None:
            return
        with suspend_if_supported(self.app):
            open_path(Path(pack["path"]))

    async def _mark_selected_pack_decision(self, decision: str) -> None:
        pack = self._selected_pack()
        if pack is None:
            return
        try:
            path = await asyncio.to_thread(
                lambda: self._library().set_pack_decision(
                    pack["repo"],
                    pack["source_type"],
                    int(pack["number"]),
                    decision,
                )
            )
            self._load()
            self.notify(f"Marked {decision}: {path}", timeout=5)
        except Exception as e:
            log_path = log_exception(
                self.app.config.notes_vault,
                f"Failed to mark Contribution Packet decision for {pack['repo']}#{pack['number']}",
            )
            self.notify(f"{e} (log: {log_path})", severity="error")

    async def action_mark_continue(self) -> None:
        await self._mark_selected_pack_decision("continue")

    async def action_mark_defer(self) -> None:
        await self._mark_selected_pack_decision("defer")

    async def action_mark_discard(self) -> None:
        await self._mark_selected_pack_decision("discard")
