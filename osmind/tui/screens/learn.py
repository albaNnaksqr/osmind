from __future__ import annotations
import asyncio
import os
from textual.app import ComposeResult
from textual.widgets import Input, LoadingIndicator, Select
from textual.containers import Horizontal, Vertical
from osmind.tui.widgets.diff_viewer import DiffViewer
from osmind.tui.widgets.chat_panel import ChatPanel


class LearnScreen(Vertical):
    DEFAULT_CSS = """
    LearnScreen #loader { display: none; height: 3; }
    LearnScreen #main-pane { height: 1fr; }
    LearnScreen DiffViewer { width: 1fr; }
    LearnScreen ChatPanel { width: 1fr; }
    """
    BINDINGS = [
        ("ctrl+s", "save_note", "Save Note"),
    ]

    def compose(self) -> ComposeResult:
        watching = self.app.config.watching
        options = [(r["repo"], r["repo"]) for r in watching]
        initial = watching[0]["repo"] if watching else Select.BLANK
        with Horizontal(id="pr-input-bar"):
            yield Select(options, id="repo-select", value=initial)
            yield Input(placeholder="PR number, e.g. 2341", id="pr-input")
        yield LoadingIndicator(id="loader")
        with Horizontal(id="main-pane"):
            yield DiffViewer("PR Diff", id="diff-viewer")
            yield ChatPanel(id="chat-panel")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "pr-input":
            self.run_worker(self._load_pr(event.value.strip()), exclusive=True)
        elif event.input.id == "chat-input":
            text = event.value.strip()
            event.input.value = ""
            if text:
                self.run_worker(self._handle_user_reply(text), exclusive=True)

    async def _load_pr(self, value: str) -> None:
        import re
        from osmind.github.client import GitHubClient
        from osmind.engine.llm import LLMClient
        from osmind.engine.socratic import SocraticEngine

        match = re.search(r"\d+", value)
        if not match:
            self.notify("请输入有效的 PR 编号", severity="warning")
            return
        number = int(match.group())

        from textual.widgets import Select as TSelect
        repo_select = self.query_one("#repo-select", TSelect)
        if repo_select.value is TSelect.BLANK:
            self.notify("请先选择 repo", severity="warning")
            return
        repo = str(repo_select.value)

        loader = self.query_one("#loader", LoadingIndicator)
        loader.display = True
        self.query_one(ChatPanel).add_message(
            "assistant", f"Loading PR #{number} from {repo}…"
        )
        try:
            token = os.environ.get("GITHUB_TOKEN", "")
            llm_cfg = self.app.config.llm

            def _blocking():
                gh = GitHubClient(token=token)
                pr = gh.get_pr(repo, number)
                llm = LLMClient(llm_cfg)
                engine = SocraticEngine(llm)
                first_q = engine.first_question(pr)
                return pr, engine, first_q

            pr, engine, first_q = await asyncio.to_thread(_blocking)
            self._pr = pr
            self._socratic = engine
            self._history: list[dict] = [{"role": "assistant", "content": first_q}]

            self.query_one(DiffViewer).load_pr(pr)
            self.query_one(ChatPanel).add_message("assistant", first_q)
        except Exception as e:
            msg = str(e)
            if "404" in msg:
                hint = (
                    f"PR #{number} 在 {repo} 中不存在。\n"
                    "注意：Discover 里显示的是 issue 编号，"
                    "Learn 需要输入 PR 编号（merged PR 才有 diff）。"
                )
                self.notify(hint, severity="error", timeout=8)
                self.query_one(ChatPanel).add_message("assistant", f"[错误] {hint}")
            else:
                self.notify(msg, severity="error")
                self.query_one(ChatPanel).add_message("assistant", f"[错误] {msg}")
        finally:
            loader.display = False

    async def _handle_user_reply(self, text: str) -> None:
        if not hasattr(self, "_socratic"):
            return
        self._history.append({"role": "user", "content": text})
        self.query_one(ChatPanel).add_message("user", text)

        loader = self.query_one("#loader", LoadingIndicator)
        loader.display = True
        try:
            history = list(self._history)
            socratic = self._socratic

            followup = await asyncio.to_thread(socratic.followup, history)
            self._history.append({"role": "assistant", "content": followup})
            self.query_one(ChatPanel).add_message("assistant", followup)
        except Exception as e:
            self.notify(str(e), severity="error")
        finally:
            loader.display = False

    def action_save_note(self) -> None:
        if not hasattr(self, "_pr"):
            self.notify("先加载一个 PR", severity="warning")
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
        self.notify(f"Note saved for PR #{self._pr.number}", severity="information")
