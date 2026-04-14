from __future__ import annotations
import asyncio
from textual.app import ComposeResult
from textual.widgets import DataTable, Input, Label, LoadingIndicator, RichLog
from textual.containers import Horizontal, Vertical


class ReviewScreen(Vertical):
    DEFAULT_CSS = """
    ReviewScreen #notes-pane { width: 38; border-right: solid $panel; }
    ReviewScreen #notes-table { height: 1fr; }
    ReviewScreen #qa-pane { width: 1fr; }
    ReviewScreen RichLog { height: 1fr; }
    ReviewScreen #loader { display: none; height: 3; }
    """
    BINDINGS = [
        ("a", "review_all", "Review All"),
    ]

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="notes-pane"):
                yield Label("[bold]Saved Notes[/bold]", markup=True)
                yield DataTable(id="notes-table", cursor_type="row")
                yield Label("[dim]Enter: review note  a: review all[/dim]", markup=True)
            with Vertical(id="qa-pane"):
                yield LoadingIndicator(id="loader")
                yield RichLog(id="review-log", wrap=True, markup=True)
                yield Input(placeholder="你的回答…", id="review-input")

    def on_mount(self) -> None:
        table = self.query_one("#notes-table", DataTable)
        table.add_columns("PR", "Repo")
        self._load_notes_list()

    def _load_notes_list(self) -> None:
        from osmind.notes.vault import NotesVault
        vault = NotesVault(self.app.config.notes_vault)
        self._notes = vault.list_all()

        table = self.query_one("#notes-table", DataTable)
        table.clear()
        log = self.query_one(RichLog)
        log.clear()

        if not self._notes:
            log.write("[dim]还没有笔记。去 Learn 模式读几个 PR，用 Ctrl+S 保存笔记。[/dim]")
            return

        for idx, note in enumerate(self._notes):
            table.add_row(
                f"#{note.pr_number}",
                note.repo.split("/")[-1],
                key=str(idx),
            )
        log.write(
            f"[bold]{len(self._notes)} 篇笔记[/bold]\n\n"
            "选中一篇笔记按 [bold]Enter[/bold] 开始针对性复习，\n"
            "或按 [bold]a[/bold] 让 osmind 从所有笔记里找知识盲点提问。\n"
        )
        self._current_note = None
        self._current_q = None

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        idx = int(event.row_key.value)
        note = self._notes[idx]
        self.run_worker(self._start_note_review(note), exclusive=True)

    async def _start_note_review(self, note) -> None:
        from osmind.engine.llm import LLMClient
        log = self.query_one(RichLog)
        loader = self.query_one("#loader", LoadingIndicator)
        loader.display = True
        log.write(
            f"\n[bold cyan]复习 PR #{note.pr_number}:[/bold cyan] {note.pr_title}\n"
        )
        try:
            llm_cfg = self.app.config.llm
            content = note.content

            def _ask():
                llm = LLMClient(llm_cfg)
                return llm.chat(
                    "你是一个 Socratic 学习助手。根据用户关于这个 PR 的笔记，"
                    "用中文提一个能加深理解的问题。只问一个问题，不超过60字。",
                    content[:600],
                    max_tokens=100,
                )

            question = await asyncio.to_thread(_ask)
            self._current_note = note
            self._current_q = question
            log.write(f"[bold cyan]osmind:[/bold cyan] {question}\n")
        except Exception as e:
            self.notify(str(e), severity="error")
        finally:
            loader.display = False

    def action_review_all(self) -> None:
        if not self._notes:
            self.notify("还没有笔记", severity="warning")
            return
        self.run_worker(self._review_all(), exclusive=True)

    async def _review_all(self) -> None:
        from osmind.engine.llm import LLMClient
        log = self.query_one(RichLog)
        loader = self.query_one("#loader", LoadingIndicator)
        loader.display = True
        log.write("\n[bold cyan]全部笔记综合复习[/bold cyan]\n")
        try:
            llm_cfg = self.app.config.llm
            combined = "\n\n".join(
                f"PR #{n.pr_number} ({n.repo}): {n.content[:300]}"
                for n in self._notes[-5:]
            )

            def _ask():
                llm = LLMClient(llm_cfg)
                return llm.chat(
                    "你是一个 Socratic 学习助手。根据用户多篇 PR 笔记，"
                    "找出知识盲点或矛盾，用中文提一个综合性问题。只问一个问题，不超过60字。",
                    combined,
                    max_tokens=100,
                )

            question = await asyncio.to_thread(_ask)
            self._current_note = None
            self._current_q = question
            log.write(f"[bold cyan]osmind:[/bold cyan] {question}\n")
        except Exception as e:
            self.notify(str(e), severity="error")
        finally:
            loader.display = False

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if not event.value.strip() or not self._current_q:
            return
        log = self.query_one(RichLog)
        log.write(f"[bold green]你:[/bold green] {event.value}\n")

        if self._current_note is not None:
            from osmind.notes.vault import NotesVault
            vault = NotesVault(self.app.config.notes_vault)
            vault.append_answer(
                self._current_note.repo,
                self._current_note.pr_number,
                self._current_q,
                event.value,
            )

        event.input.value = ""
        self._current_q = None
        log.write("[dim]回答已保存。选一篇笔记继续，或按 a 综合复习。[/dim]\n")
