from __future__ import annotations
import asyncio
from dataclasses import dataclass
from pathlib import Path
import re
from textual.app import ComposeResult
from textual.widgets import DataTable, Input, Label, LoadingIndicator, RichLog
from textual.containers import Horizontal, Vertical


@dataclass(frozen=True)
class ReviewAnswer:
    question: str
    answer: str


@dataclass(frozen=True)
class _ReviewAnswerSpan:
    question: str
    answer: str
    start: int
    end: int


_NOTES_HEADING_RE = re.compile(r"(?m)^## Notes\s*$")
_SECTION_HEADING_RE = re.compile(r"(?m)^##\s+.+\s*$")
_QUESTION_RE = re.compile(r"(?m)^\*\*Q: (?P<question>.+?)\*\*\s*$")


class ReviewScreen(Vertical):
    DEFAULT_CSS = """
    ReviewScreen #notes-pane { width: 38; border-right: solid $panel; }
    ReviewScreen #notes-table { height: 1fr; }
    ReviewScreen #qa-pane { width: 1fr; }
    ReviewScreen #review-log { height: 1fr; border-bottom: solid $panel; }
    ReviewScreen #answers-table { height: 9; }
    ReviewScreen #loader { display: none; height: 3; }
    """
    BINDINGS = [
        ("a", "review_all", "Review All"),
        ("v", "focus_answers", "Answers"),
        ("e", "rewrite_answer", "Rewrite Answer"),
        ("delete", "delete_selected_answer", "Delete Answer"),
    ]

    def compose(self) -> ComposeResult:
        with Horizontal():
            with Vertical(id="notes-pane"):
                yield Label("[bold]Contribution Packets[/bold]", markup=True)
                yield DataTable(id="notes-table", cursor_type="row")
                yield Label(
                    "[dim]Enter: review pack  a: review all  v: answers[/dim]",
                    markup=True,
                )
            with Vertical(id="qa-pane"):
                yield LoadingIndicator(id="loader")
                yield RichLog(id="review-log", wrap=True, markup=True)
                yield Label("[bold]Saved Review Q/A[/bold]", markup=True)
                yield DataTable(id="answers-table", cursor_type="row")
                yield Label(
                    "[dim]e: rewrite selected  Delete: delete selected/latest[/dim]",
                    markup=True,
                )
                yield Input(placeholder="你的回答…", id="review-input")

    def on_mount(self) -> None:
        table = self.query_one("#notes-table", DataTable)
        table.add_columns("Item", "Repo")
        answers = self.query_one("#answers-table", DataTable)
        answers.add_columns("#", "Question", "Answer")
        self._notes = []
        self._current_note = None
        self._current_q = None
        self._answer_note = None
        self._editing_answer_index = None
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
        self._clear_answers()

        if not self._notes:
            log.write("[dim]还没有 Contribution Packet。先在 Discover 里生成，或去 Packs 查看已生成内容。[/dim]")
            self._current_note = None
            self._current_q = None
            self._answer_note = None
            self._editing_answer_index = None
            return

        for idx, note in enumerate(self._notes):
            item_label = "PR" if note["source_type"] == "pr" else "Issue"
            table.add_row(
                f"{item_label} #{note['number']}",
                note["repo"].split("/")[-1],
                key=str(idx),
            )
        table.cursor_coordinate = (0, 0)
        log.write(
            f"[bold]{len(self._notes)} 个 Contribution Packet[/bold]\n\n"
            "选中一个 pack 按 [bold]Enter[/bold] 开始针对性复习，\n"
            "或按 [bold]a[/bold] 让 osmind 从所有 pack 里找知识盲点提问。\n"
        )
        self._current_note = self._notes[0]
        self._current_q = None
        self._answer_note = self._notes[0]
        self._editing_answer_index = None
        self._load_answers_for_note(self._notes[0])

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
        if event.data_table.id == "answers-table":
            return

        idx = int(event.row_key.value)
        note = self._notes[idx]
        self._current_note = note
        self._answer_note = note
        self._editing_answer_index = None
        self._load_answers_for_note(note)
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

    def action_focus_answers(self) -> None:
        answers = self.query_one("#answers-table", DataTable)
        if answers.row_count == 0:
            self.notify("当前 pack 没有 Review 回答", severity="warning")
            return
        self.app.set_focus(answers)

    def action_delete_selected_answer(self) -> None:
        index = self._selected_answer_index()
        note = self._answer_note if index is not None else self._current_note or self._selected_note()
        if note is None:
            self.notify("先选中一个 Contribution Packet", severity="warning")
            return

        path = Path(note["path"])
        if index is None:
            deleted = _delete_last_answer_from_pack(path)
        else:
            deleted = _delete_answer_from_pack(path, index)

        if not deleted:
            self.notify("没有可删除的 Review 回答", severity="warning")
            return

        self._current_q = None
        self._editing_answer_index = None
        self._answer_note = note
        self._load_answers_for_note(note)
        log = self.query_one(RichLog)
        log.clear()
        if index is None:
            log.write("[dim]已删除最近一条 Review 回答。选中 pack 继续，或按 a 综合复习。[/dim]\n")
        else:
            log.write("[dim]已删除选中的 Review 回答。选中 pack 继续，或按 a 综合复习。[/dim]\n")

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
        self._editing_answer_index = None
        self._answer_note = note
        self._load_answers_for_note(note)
        log = self.query_one(RichLog)
        log.clear()
        log.write("[dim]已删除最近一条 Review 回答。选中 pack 继续，或按 a 综合复习。[/dim]\n")

    def action_rewrite_answer(self) -> None:
        note = self._answer_note or self._current_note or self._selected_note()
        if note is None:
            self.notify("先选中一个 Contribution Packet", severity="warning")
            return

        index = self._selected_answer_index()
        if index is None:
            self.notify("先选中一条 Review 回答", severity="warning")
            return

        answers = _review_answers_from_pack(Path(note["path"]))
        if index >= len(answers):
            self.notify("先选中一条 Review 回答", severity="warning")
            return

        answer = answers[index]
        self._current_note = note
        self._answer_note = note
        self._current_q = answer.question
        self._editing_answer_index = index
        review_input = self.query_one("#review-input", Input)
        review_input.value = answer.answer
        review_input.focus()
        self.app.set_focus(review_input)
        log = self.query_one(RichLog)
        log.write(f"[bold cyan]改写:[/bold cyan] {answer.question}\n")

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
            path = Path(self._current_note["path"])
            if self._editing_answer_index is None:
                _append_answer_to_pack(
                    path,
                    self._current_q,
                    event.value,
                )
            elif _replace_answer_in_pack(path, self._editing_answer_index, event.value):
                self._editing_answer_index = None
            self._answer_note = self._current_note
            self._load_answers_for_note(self._current_note)

        event.input.value = ""
        self._current_q = None
        log.write("[dim]回答已保存。选一个 pack 继续，或按 a 综合复习。[/dim]\n")

    def _clear_answers(self) -> None:
        answers = self.query_one("#answers-table", DataTable)
        answers.clear()

    def _load_answers_for_note(self, note: dict) -> None:
        answers_table = self.query_one("#answers-table", DataTable)
        answers_table.clear()
        answers = _review_answers_from_pack(Path(note["path"]))
        for idx, answer in enumerate(answers):
            preview = " ".join(answer.answer.split())
            if len(preview) > 80:
                preview = f"{preview[:77]}..."
            answers_table.add_row(str(idx + 1), answer.question, preview, key=str(idx))
        if answers:
            answers_table.cursor_coordinate = (len(answers) - 1, 0)

    def _selected_answer_index(self) -> int | None:
        answers_table = self.query_one("#answers-table", DataTable)
        if answers_table.cursor_row is None or answers_table.cursor_row >= len(answers_table.ordered_rows):
            return None
        row_key = answers_table.ordered_rows[answers_table.cursor_row].key
        try:
            return int(row_key.value)
        except (TypeError, ValueError):
            return None


def _append_answer_to_pack(path: Path, question: str, answer: str) -> None:
    if not path.exists():
        return

    text = path.read_text(encoding="utf-8").rstrip()
    entry = f"**Q: {question}**\n\n{answer.strip()}"
    notes_matches = list(_NOTES_HEADING_RE.finditer(text))
    if notes_matches:
        insert_at = _notes_insert_index(text, notes_matches[-1])
        before = text[:insert_at].rstrip()
        after = text[insert_at:].lstrip("\n")
        updated = f"{before}\n\n{entry}\n"
        if after:
            updated = f"{updated}\n{after.rstrip()}\n"
    else:
        updated = f"{text}\n\n## Notes\n\n{entry}\n"
    path.write_text(updated, encoding="utf-8")


def _delete_last_answer_from_pack(path: Path) -> bool:
    answers = _review_answer_spans_from_path(path)
    if not answers:
        return False
    return _delete_answer_from_pack(path, len(answers) - 1)


def _review_answers_from_pack(path: Path) -> list[ReviewAnswer]:
    return [
        ReviewAnswer(question=span.question, answer=span.answer)
        for span in _review_answer_spans_from_path(path)
    ]


def _delete_answer_from_pack(path: Path, index: int) -> bool:
    if not path.exists():
        return False

    text = path.read_text(encoding="utf-8").rstrip()
    spans = _review_answer_spans(text)
    if index < 0 or index >= len(spans):
        return False

    span = spans[index]
    updated = _replace_text_range(text, span.start, span.end, "")
    path.write_text(updated, encoding="utf-8")
    return True


def _replace_answer_in_pack(path: Path, index: int, answer: str) -> bool:
    if not path.exists():
        return False

    text = path.read_text(encoding="utf-8").rstrip()
    spans = _review_answer_spans(text)
    if index < 0 or index >= len(spans):
        return False

    span = spans[index]
    entry = f"**Q: {span.question}**\n\n{answer.strip()}"
    updated = _replace_text_range(text, span.start, span.end, entry)
    path.write_text(updated, encoding="utf-8")
    return True


def _review_answer_spans_from_path(path: Path) -> list[_ReviewAnswerSpan]:
    if not path.exists():
        return []
    return _review_answer_spans(path.read_text(encoding="utf-8").rstrip())


def _review_answer_spans(text: str) -> list[_ReviewAnswerSpan]:
    notes_matches = list(_NOTES_HEADING_RE.finditer(text))
    if not notes_matches:
        return []

    notes_start = notes_matches[-1].end()
    question_matches = [
        match for match in _QUESTION_RE.finditer(text) if match.start() >= notes_start
    ]
    if not question_matches:
        return []

    spans: list[_ReviewAnswerSpan] = []
    for idx, match in enumerate(question_matches):
        next_question_start = (
            question_matches[idx + 1].start() if idx + 1 < len(question_matches) else None
        )
        next_section_start = _next_section_start(text, match.end())
        end_candidates = [
            candidate
            for candidate in (next_question_start, next_section_start, len(text))
            if candidate is not None
        ]
        entry_end = min(end_candidates)
        spans.append(
            _ReviewAnswerSpan(
                question=match.group("question").strip(),
                answer=text[match.end() : entry_end].strip(),
                start=match.start(),
                end=entry_end,
            )
        )
    return spans


def _notes_insert_index(text: str, notes_match: re.Match[str]) -> int:
    next_section = _next_section_start(text, notes_match.end())
    if next_section is None:
        return len(text)
    return next_section


def _next_section_start(text: str, start: int) -> int | None:
    match = _SECTION_HEADING_RE.search(text, pos=start)
    if match is None:
        return None
    return match.start()


def _replace_text_range(text: str, start: int, end: int, replacement: str) -> str:
    before = text[:start].rstrip()
    after = text[end:].lstrip("\n")
    parts = [part for part in (before, replacement.strip(), after.rstrip()) if part]
    return "\n\n".join(parts).rstrip() + "\n"
