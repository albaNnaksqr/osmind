from __future__ import annotations
from textual.widgets import RichLog, Input
from textual.containers import Vertical
from textual.app import ComposeResult


class ChatPanel(Vertical):
    def compose(self) -> ComposeResult:
        yield RichLog(id="chat-log", wrap=True, markup=True)
        yield Input(placeholder="你的回答...", id="chat-input")

    def add_message(self, role: str, text: str) -> None:
        log = self.query_one(RichLog)
        if role == "assistant":
            log.write(f"[bold cyan]osmind:[/bold cyan] {text}\n")
        else:
            log.write(f"[bold green]你:[/bold green] {text}\n")
