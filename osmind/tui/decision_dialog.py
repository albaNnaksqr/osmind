from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Static


class DecisionDialog(ModalScreen[str | None]):
    def __init__(self, include_start_work: bool = False):
        super().__init__()
        self._include_start_work = include_start_work

    DEFAULT_CSS = """
    DecisionDialog {
        align: center middle;
    }
    DecisionDialog #decision-dialog {
        width: 64;
        height: auto;
        padding: 1 2;
        border: thick $panel;
        background: $surface;
    }
    DecisionDialog #decision-options {
        height: 5;
        margin-top: 1;
    }
    """
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="decision-dialog"):
            yield Static("[bold]Decide[/bold]\n[dim]Choose what should leave the active queue.[/dim]")
            yield DataTable(id="decision-options", cursor_type="row")
            yield Static("[dim]Enter: choose  Esc/q: cancel[/dim]")

    def on_mount(self) -> None:
        table = self.query_one("#decision-options", DataTable)
        table.add_columns("Decision", "Effect")
        if self._include_start_work:
            table.add_row("Start Work", "Generate a Contribution Packet and start working", key="continue")
        table.add_row("Defer", "Hide until upstream or resources change", key="defer")
        table.add_row("Discard", "Hide unless you revisit discarded items", key="discard")
        table.cursor_coordinate = (0, 0)
        table.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "decision-options":
            return
        event.stop()
        self.dismiss(str(event.row_key.value))

    def action_cancel(self) -> None:
        self.dismiss(None)
