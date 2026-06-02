from __future__ import annotations

import asyncio
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Label, Markdown, Static

from osmind.logs import log_exception
from osmind.packs.opener import open_path
from osmind.services.library import PackLibrary
from osmind.tui.decision_dialog import DecisionDialog
from osmind.tui.packet_reader import packet_outline, packet_section_markdown
from osmind.tui.lifecycle import resources_hash
from osmind.tui.suspend import suspend_if_supported
from osmind.tui.workflow import format_start_work_from_packet


class PacksScreen(Vertical):
    DEFAULT_CSS = """
    PacksScreen #packs-list-view { height: 1fr; }
    PacksScreen #packet-reader-view { display: none; height: 1fr; }
    PacksScreen #packet-reader-body { height: 1fr; }
    PacksScreen #packet-section-table { width: 32; height: 1fr; border-right: solid $panel; }
    PacksScreen #packet-markdown { width: 1fr; height: 1fr; padding: 0 1; }
    PacksScreen #pack-start-work-view { display: none; height: 1fr; }
    PacksScreen #pack-start-work-panel { height: 1fr; padding: 0 1; overflow-y: auto; }
    """
    BINDINGS = [
        ("enter", "view_pack", "Read Packet"),
        ("o", "open_pack", "Open"),
        ("space", "decide", "Decide"),
        ("escape", "back_to_list", "Back"),
        ("q", "back_to_list", "Back"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="packs-list-view"):
            yield Label("[bold]Contribution Packets[/bold]", markup=True)
            yield DataTable(id="packs-table", cursor_type="row")
            yield Label("[dim]Enter: Read  Space: Decide  o: Open[/dim]", markup=True)
        with Vertical(id="packet-reader-view"):
            yield Static("[dim]o: Open  Esc: Back[/dim]", id="packet-reader-hint")
            with Horizontal(id="packet-reader-body"):
                yield DataTable(id="packet-section-table", cursor_type="row")
                yield Markdown("", id="packet-markdown")
        with Vertical(id="pack-start-work-view"):
            yield Static("[dim]o: Open  Esc: Back[/dim]", id="pack-start-work-hint")
            yield Static("", id="pack-start-work-panel")

    def on_mount(self) -> None:
        table = self.query_one("#packs-table", DataTable)
        table.add_column("Type", key="type")
        table.add_column("#", key="number")
        table.add_column("Repo", key="repo")
        table.add_column("Status", key="status")
        table.add_column("Decision", key="decision")
        table.add_column("Confidence", key="confidence")
        table.add_column("Path", key="path")
        self._packs_by_key: dict[str, dict] = {}
        section_table = self.query_one("#packet-section-table", DataTable)
        section_table.add_columns("Section")
        self._reader_markdown = ""
        self._reader_pack = None

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

    def action_view_pack(self) -> None:
        pack = self._selected_pack()
        if pack is None:
            return
        try:
            markdown = Path(pack["path"]).read_text(encoding="utf-8")
            self._reader_markdown = markdown
            self._reader_pack = pack
            section_table = self.query_one("#packet-section-table", DataTable)
            section_table.clear()
            for idx, section in enumerate(packet_outline(markdown)):
                section_table.add_row(section.title, key=str(idx))
            section_table.cursor_coordinate = (0, 0)
            self._show_packet_section(0)
            self._show_packet_reader()
        except Exception as e:
            log_path = log_exception(
                self.app.config.notes_vault,
                f"Failed to read Contribution Packet for {pack['repo']}#{pack['number']}",
            )
            self.notify(f"{e} (log: {log_path})", severity="error")

    def action_start_work(self) -> None:
        pack = self._selected_pack()
        if pack is None:
            return
        try:
            path = self._write_pack_decision(pack, "continue")
            self._load()
            markdown = path.read_text(encoding="utf-8")
            panel = self.query_one("#pack-start-work-panel", Static)
            panel.update(format_start_work_from_packet(markdown, self.app.config.resources))
            self._show_start_work()
        except Exception as e:
            log_path = log_exception(
                self.app.config.notes_vault,
                f"Failed to start work for {pack['repo']}#{pack['number']}",
            )
            self.notify(f"{e} (log: {log_path})", severity="error")

    def action_back_to_list(self) -> None:
        if not self.query_one("#pack-start-work-view").display and not self.query_one("#packet-reader-view").display:
            return
        self.query_one("#packs-list-view").display = True
        self.query_one("#packet-reader-view").display = False
        self.query_one("#pack-start-work-view").display = False
        self.call_after_refresh(lambda: self.query_one("#packs-table", DataTable).focus())

    def on_key(self, event) -> None:
        if event.key != "q":
            return
        if not self.query_one("#pack-start-work-view").display and not self.query_one("#packet-reader-view").display:
            return
        event.prevent_default()
        event.stop()
        self.action_back_to_list()

    def _show_packet_reader(self) -> None:
        self.query_one("#packs-list-view").display = False
        self.query_one("#packet-reader-view").display = True
        self.query_one("#pack-start-work-view").display = False
        self.call_after_refresh(lambda: self.query_one("#packet-section-table", DataTable).focus())

    def _show_start_work(self) -> None:
        self.query_one("#packs-list-view").display = False
        self.query_one("#packet-reader-view").display = False
        self.query_one("#pack-start-work-view").display = True
        panel = self.query_one("#pack-start-work-panel", Static)
        panel.can_focus = True
        self.call_after_refresh(panel.focus)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table.id != "packet-section-table":
            return
        try:
            self._show_packet_section(int(event.row_key.value))
        except (TypeError, ValueError):
            return

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "packs-table":
            return
        event.stop()
        self.action_view_pack()

    def _show_packet_section(self, index: int) -> None:
        markdown = packet_section_markdown(self._reader_markdown, index)
        viewer = self.query_one("#packet-markdown", Markdown)
        viewer.update(markdown)

    def _write_pack_decision(self, pack: dict, decision: str) -> Path:
        return self._library().set_pack_decision(
            pack["repo"],
            pack["source_type"],
            int(pack["number"]),
            decision,
            decision_resource_hash=resources_hash(self.app.config.resources),
        )

    async def action_decide(self) -> None:
        pack = self._selected_pack()
        if pack is None:
            return
        async def handle_decision(decision: str | None) -> None:
            if decision not in {"defer", "discard"}:
                return
            await self._mark_pack_decision(pack, str(decision))

        self.app.push_screen(DecisionDialog(), handle_decision)

    async def _mark_pack_decision(self, pack: dict, decision: str) -> None:
        if decision not in {"defer", "discard"}:
            return
        try:
            path = await asyncio.to_thread(lambda: self._write_pack_decision(pack, decision))
            self._load()
            self.notify(f"Marked {decision}: {path}", timeout=5)
        except Exception as e:
            log_path = log_exception(
                self.app.config.notes_vault,
                f"Failed to mark Contribution Packet decision for {pack['repo']}#{pack['number']}",
            )
            self.notify(f"{e} (log: {log_path})", severity="error")

    async def _mark_selected_pack_decision(self, decision: str) -> None:
        pack = self._selected_pack()
        if pack is None:
            return
        await self._mark_pack_decision(pack, decision)

    async def action_mark_continue(self) -> None:
        await self._mark_selected_pack_decision("continue")

    async def action_mark_defer(self) -> None:
        await self._mark_selected_pack_decision("defer")

    async def action_mark_discard(self) -> None:
        await self._mark_selected_pack_decision("discard")
