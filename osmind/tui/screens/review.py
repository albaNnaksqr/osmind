from __future__ import annotations
from textual.app import ComposeResult
from textual.widgets import Label, Input, RichLog
from textual.containers import Vertical


class ReviewScreen(Vertical):
    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[bold]Review[/bold] — osmind will ask about your notes", markup=True)
            yield RichLog(id="review-log", wrap=True, markup=True)
            yield Input(placeholder="你的回答...", id="review-input")

    def on_mount(self) -> None:
        self._load_next_question()

    def _load_next_question(self) -> None:
        from osmind.notes.vault import NotesVault
        from osmind.engine.llm import LLMClient

        vault = NotesVault(self.app.config.notes_vault)
        pending = vault.list_pending_questions()

        if pending:
            self._current_note, self._current_q = pending[0]
            log = self.query_one(RichLog)
            log.write(
                f"[bold cyan]osmind:[/bold cyan] 你的笔记里记了关于 "
                f"[italic]{self._current_note.pr_title}[/italic] 的内容，"
                f"但有个问题待确认：\n\n{self._current_q}\n"
            )
        else:
            llm = LLMClient(self.app.config.llm)
            notes = vault.list_all()
            if not notes:
                self.query_one(RichLog).write("[dim]还没有笔记，先去 Learn 模式读几个 PR 吧[/dim]")
                return
            combined = "\n\n".join(
                f"PR #{n.pr_number} ({n.repo}): {n.content[:300]}" for n in notes[-5:]
            )
            question = llm.chat(
                "你是一个 Socratic 学习助手。根据用户的笔记内容，用中文提一个能加深理解的问题。只问一个问题，不超过50字。",
                combined,
                max_tokens=80,
            )
            self._current_note = None
            self._current_q = question
            self.query_one(RichLog).write(f"[bold cyan]osmind:[/bold cyan] {question}\n")

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
        self._load_next_question()
