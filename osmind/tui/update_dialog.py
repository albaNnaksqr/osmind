from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import DataTable, Static


class QueueUpdateDialog(ModalScreen[str | None]):
    DEFAULT_CSS = """
    QueueUpdateDialog {
        align: center middle;
    }
    QueueUpdateDialog #queue-update-dialog {
        width: 72;
        height: auto;
        padding: 1 2;
        border: thick $panel;
        background: $surface;
    }
    QueueUpdateDialog #queue-update-options {
        height: 5;
        margin-top: 1;
    }
    """
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
    ]

    def __init__(self, cached_count: int):
        super().__init__()
        self.cached_count = cached_count

    def compose(self) -> ComposeResult:
        with Vertical(id="queue-update-dialog"):
            yield Static(
                "[bold]Update Opportunities[/bold]\n"
                f"[dim]{self.cached_count} cached items are available for this repo.[/dim]"
            )
            yield DataTable(id="queue-update-options", cursor_type="row")
            yield Static("[dim]Enter: choose  Esc/q: cancel[/dim]")

    def on_mount(self) -> None:
        table = self.query_one("#queue-update-options", DataTable)
        table.add_columns("Source", "Effect")
        table.add_row("Read Cache", "Use local queue without GitHub or reranking", key="cache")
        table.add_row("Fetch + Rank", "Pull latest issues from GitHub and rerank", key="fetch")
        table.cursor_coordinate = (0, 0)
        table.focus()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "queue-update-options":
            return
        event.stop()
        self.dismiss(str(event.row_key.value))

    def action_cancel(self) -> None:
        self.dismiss(None)
