from __future__ import annotations
import asyncio
from textual.app import ComposeResult
from textual.widgets import Label, Input, LoadingIndicator, RichLog
from textual.containers import Vertical


class ReviewScreen(Vertical):
    DEFAULT_CSS = """
    ReviewScreen #loader { display: none; height: 3; }
    ReviewScreen RichLog { height: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield Label("[bold]Review[/bold] — osmind 会根据你的笔记提问", markup=True)
        yield LoadingIndicator(id="loader")
        yield RichLog(id="review-log", wrap=True, markup=True)
        yield Input(placeholder="你的回答…", id="review-input")

    def on_mount(self) -> None:
        self.run_worker(self._load_next_question(), exclusive=True)

    async def _load_next_question(self) -> None:
        from osmind.notes.vault import NotesVault
        from osmind.engine.llm import LLMClient

        loader = self.query_one("#loader", LoadingIndicator)
        loader.display = True
        try:
            vault = NotesVault(self.app.config.notes_vault)
            pending = vault.list_pending_questions()

            if pending:
                self._current_note, self._current_q = pending[0]
                self.query_one(RichLog).write(
                    f"[bold cyan]osmind:[/bold cyan] 你的笔记里关于 "
                    f"[italic]{self._current_note.pr_title}[/italic] 有个问题待确认：\n\n"
                    f"{self._current_q}\n"
                )
            else:
                notes = vault.list_all()
                if not notes:
                    self.query_one(RichLog).write(
                        "[dim]还没有笔记，先去 Learn 模式读几个 PR 吧[/dim]"
                    )
                    return

                llm_cfg = self.app.config.llm
                combined = "\n\n".join(
                    f"PR #{n.pr_number} ({n.repo}): {n.content[:300]}" for n in notes[-5:]
                )

                def _ask():
                    llm = LLMClient(llm_cfg)
                    return llm.chat(
                        "你是一个 Socratic 学习助手。根据用户的笔记内容，用中文提一个能加深理解的问题。只问一个问题，不超过50字。",
                        combined,
                        max_tokens=80,
                    )

                question = await asyncio.to_thread(_ask)
                self._current_note = None
                self._current_q = question
                self.query_one(RichLog).write(f"[bold cyan]osmind:[/bold cyan] {question}\n")
        except Exception as e:
            self.notify(str(e), severity="error")
        finally:
            loader.display = False

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if not event.value.strip():
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
        self.run_worker(self._load_next_question(), exclusive=True)
