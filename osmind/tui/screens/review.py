from __future__ import annotations
import asyncio
from pathlib import Path
import re
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
        ("delete", "delete_last_answer", "Delete Last Answer"),
    ]

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="notes-pane"):
                yield Label("[bold]Contribution Packets[/bold]", markup=True)
                yield DataTable(id="notes-table", cursor_type="row")
                yield Label("[dim]Enter: review pack  a: review all  Delete: remove last answer[/dim]", markup=True)
            with Vertical(id="qa-pane"):
                yield LoadingIndicator(id="loader")
                yield RichLog(id="review-log", wrap=True, markup=True)
                yield Input(placeholder="你的回答…", id="review-input")

    def on_mount(self) -> None:
        table = self.query_one("#notes-table", DataTable)
        table.add_columns("Item", "Repo")
        self._load_notes_list()

    def _load_notes_list(self) -> None:
        cache_path = self.app.config.notes_vault / "osmind" / ".cache" / "osmind.db"
        if cache_path.exists():
            from osmind.services.library import PackLibrary

            library = PackLibrary(self.app.config.notes_vault, cache_path)
            self._notes = library.list_packs()
        else:
            self._notes = []

        table = self.query_one("#notes-table", DataTable)
        table.clear()
        log = self.query_one(RichLog)
        log.clear()

        if not self._notes:
            log.write("[dim]还没有 Contribution Packet。先在 Discover 里生成，或去 Packs 查看已生成内容。[/dim]")
            return

        for idx, note in enumerate(self._notes):
            item_label = "PR" if note["source_type"] == "pr" else "Issue"
            table.add_row(
                f"{item_label} #{note['number']}",
                note["repo"].split("/")[-1],
                key=str(idx),
            )
        log.write(
            f"[bold]{len(self._notes)} 个 Contribution Packet[/bold]\n\n"
            "选中一个 pack 按 [bold]Enter[/bold] 开始针对性复习，\n"
            "或按 [bold]a[/bold] 让 osmind 从所有 pack 里找知识盲点提问。\n"
        )
        self._current_note = None
        self._current_q = None

    def action_reload(self) -> None:
        self._load_notes_list()

    def _selected_note(self) -> dict | None:
        table = self.query_one("#notes-table", DataTable)
        if table.cursor_row is None or table.cursor_row >= len(table.ordered_rows):
            return None
        row_key = table.ordered_rows[table.cursor_row].key
        try:
            return self._notes[int(row_key.value)]
        except (IndexError, TypeError, ValueError):
            return None

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        idx = int(event.row_key.value)
        note = self._notes[idx]
        self.run_worker(self._start_note_review(note), exclusive=True)

    async def _start_note_review(self, note) -> None:
        from osmind.engine.llm import LLMClient
        from osmind.packs.renderer import parse_pack_frontmatter

        log = self.query_one(RichLog)
        loader = self.query_one("#loader", LoadingIndicator)
        loader.display = True
        try:
            llm_cfg = self.app.config.llm
            content = Path(note["path"]).read_text(encoding="utf-8")
            frontmatter = parse_pack_frontmatter(content)
            item_label = "PR" if note["source_type"] == "pr" else "Issue"
            log.write(
                f"\n[bold cyan]复习 {item_label} #{note['number']}:[/bold cyan] {frontmatter.get('title', '')}\n"
            )

            def _ask():
                llm = LLMClient(llm_cfg)
                return llm.chat(
                    "你是一个 Socratic 学习助手。根据用户关于这个开源仓库条目的 Contribution Packet，"
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

    def action_delete_last_answer(self) -> None:
        note = self._current_note or self._selected_note()
        if note is None:
            self.notify("先选中一个 Contribution Packet", severity="warning")
            return

        path = Path(note["path"])
        if not _delete_last_answer_from_pack(path):
            self.notify("没有可删除的 Review 回答", severity="warning")
            return

        self._current_q = None
        log = self.query_one(RichLog)
        log.clear()
        log.write("[dim]已删除最近一条 Review 回答。选中 pack 继续，或按 a 综合复习。[/dim]\n")

    async def _review_all(self) -> None:
        from osmind.engine.llm import LLMClient
        log = self.query_one(RichLog)
        loader = self.query_one("#loader", LoadingIndicator)
        loader.display = True
        log.write("\n[bold cyan]全部笔记综合复习[/bold cyan]\n")
        try:
            llm_cfg = self.app.config.llm
            snippets = []
            for note in self._notes[-5:]:
                path = Path(note["path"])
                if not path.exists():
                    continue
                content = path.read_text(encoding="utf-8")
                item_label = "PR" if note["source_type"] == "pr" else "Issue"
                snippets.append(f"{item_label} #{note['number']} ({note['repo']}): {content[:300]}")
            combined = "\n\n".join(snippets)
            if not combined:
                self.notify("没有可读取的 Contribution Packet", severity="warning")
                return

            def _ask():
                llm = LLMClient(llm_cfg)
                return llm.chat(
                    "你是一个 Socratic 学习助手。根据用户多个 Contribution Packet，"
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
            _append_answer_to_pack(
                Path(self._current_note["path"]),
                self._current_q,
                event.value,
            )

        event.input.value = ""
        self._current_q = None
        log.write("[dim]回答已保存。选一个 pack 继续，或按 a 综合复习。[/dim]\n")


def _append_answer_to_pack(path: Path, question: str, answer: str) -> None:
    if not path.exists():
        return

    text = path.read_text(encoding="utf-8").rstrip()
    entry = f"**Q: {question}**\n\n{answer.strip()}"
    if "\n## Notes\n" in f"\n{text}\n":
        updated = f"{text}\n\n{entry}\n"
    else:
        updated = f"{text}\n\n## Notes\n\n{entry}\n"
    path.write_text(updated, encoding="utf-8")


def _delete_last_answer_from_pack(path: Path) -> bool:
    if not path.exists():
        return False

    text = path.read_text(encoding="utf-8").rstrip()
    notes_matches = list(re.finditer(r"(?m)^## Notes\s*$", text))
    if not notes_matches:
        return False

    notes_start = notes_matches[-1].end()
    question_matches = [
        match
        for match in re.finditer(r"(?m)^\*\*Q: .+\*\*\s*$", text)
        if match.start() >= notes_start
    ]
    if not question_matches:
        return False

    updated = text[: question_matches[-1].start()].rstrip() + "\n"
    path.write_text(updated, encoding="utf-8")
    return True
