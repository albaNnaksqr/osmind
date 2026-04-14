from __future__ import annotations
from textual.app import ComposeResult
from textual.widgets import Input, Label, Select
from textual.containers import Horizontal, Vertical
from osmind.tui.widgets.diff_viewer import DiffViewer
from osmind.tui.widgets.chat_panel import ChatPanel


class LearnScreen(Vertical):
    BINDINGS = [
        ("ctrl+s", "save_note", "Save Note"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical():
            with Horizontal(id="pr-input-bar"):
                yield Select(
                    [(r["repo"], r["repo"]) for r in self.app.config.watching],
                    id="repo-select",
                    prompt="Select repo",
                )
                yield Input(placeholder="PR number, e.g. 2341", id="pr-input")
            with Horizontal(id="main-pane"):
                yield DiffViewer("PR Diff", id="diff-viewer")
                yield ChatPanel(id="chat-panel")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "pr-input":
            self._load_pr(event.value.strip())
        elif event.input.id == "chat-input":
            self._handle_user_reply(event.value.strip())
            event.input.value = ""

    def _load_pr(self, value: str) -> None:
        import os
        import re
        from osmind.github.client import GitHubClient
        from osmind.engine.llm import LLMClient
        from osmind.engine.socratic import SocraticEngine

        match = re.search(r"\d+", value)
        if not match:
            return
        number = int(match.group())

        from textual.widgets import Select as TSelect
        repo_select = self.query_one("#repo-select", TSelect)
        if repo_select.value is TSelect.BLANK:
            return
        repo = str(repo_select.value)
        gh = GitHubClient(token=os.environ.get("GITHUB_TOKEN", ""))
        self._pr = gh.get_pr(repo, number)
        self.query_one(DiffViewer).load_pr(self._pr)

        llm = LLMClient(self.app.config.llm)
        self._socratic = SocraticEngine(llm)
        self._history: list[dict] = []

        first_q = self._socratic.first_question(self._pr)
        self._history.append({"role": "assistant", "content": first_q})
        self.query_one(ChatPanel).add_message("assistant", first_q)

    def _handle_user_reply(self, text: str) -> None:
        if not text or not hasattr(self, "_socratic"):
            return
        self._history.append({"role": "user", "content": text})
        self.query_one(ChatPanel).add_message("user", text)

        followup = self._socratic.followup(self._history)
        self._history.append({"role": "assistant", "content": followup})
        self.query_one(ChatPanel).add_message("assistant", followup)

    def action_save_note(self) -> None:
        if not hasattr(self, "_pr"):
            return
        from osmind.notes.vault import NotesVault, Note
        vault = NotesVault(self.app.config.notes_vault)
        content = "\n\n".join(
            f"{'osmind' if m['role'] == 'assistant' else '我'}: {m['content']}"
            for m in self._history
        )
        modules = list({f.filename.split("/")[0] for f in self._pr.files})
        note = Note(
            repo=self._pr.repo,
            pr_number=self._pr.number,
            pr_title=self._pr.title,
            modules=modules,
            tags=[],
            content=content,
        )
        vault.save(note)
        self.notify(f"Note saved for PR #{self._pr.number}")
