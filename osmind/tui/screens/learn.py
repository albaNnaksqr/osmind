from __future__ import annotations
import asyncio
import os
from textual.app import ComposeResult
from textual.widgets import DataTable, Input, Label, LoadingIndicator, Select, Static
from textual.containers import Horizontal, Vertical
from osmind.tui.widgets.diff_viewer import DiffViewer
from osmind.tui.widgets.chat_panel import ChatPanel


class LearnScreen(Vertical):
    DEFAULT_CSS = """
    LearnScreen { height: 1fr; }
    LearnScreen #main-area { height: 1fr; }
    LearnScreen #left-pane { width: 35; border-right: solid $panel; }
    LearnScreen #pr-table { height: 1fr; }
    LearnScreen #right-pane { width: 1fr; }
    LearnScreen #diff-chat { height: 1fr; }
    LearnScreen DiffViewer { width: 1fr; height: 1fr; }
    LearnScreen ChatPanel { width: 1fr; }
    LearnScreen ChatPanel RichLog { height: 1fr; }
    LearnScreen #loader { display: none; height: 3; }
    LearnScreen #pr-hint { height: 1; padding: 0 1; color: $text-muted; }
    """
    BINDINGS = [
        ("f", "fetch_prs", "Fetch PRs"),
        ("ctrl+s", "save_note", "Save Note"),
    ]

    def compose(self) -> ComposeResult:
        watching = self.app.config.watching
        options = [(r["repo"], r["repo"]) for r in watching]
        initial = watching[0]["repo"] if watching else Select.BLANK
        with Horizontal(id="main-area"):
            with Vertical(id="left-pane"):
                yield Select(options, id="repo-select", value=initial)
                yield Label("Press f to load PRs", id="pr-hint")
                yield DataTable(id="pr-table", cursor_type="row")
            with Vertical(id="right-pane"):
                yield LoadingIndicator(id="loader")
                with Horizontal(id="diff-chat"):
                    yield DiffViewer("PR Diff", id="diff-viewer")
                    yield ChatPanel(id="chat-panel")

    def on_mount(self) -> None:
        table = self.query_one("#pr-table", DataTable)
        table.add_columns("  #", "Title")

    def action_fetch_prs(self) -> None:
        self.run_worker(self._fetch_prs(), exclusive=True)

    async def _fetch_prs(self) -> None:
        repo_select = self.query_one("#repo-select", Select)
        if repo_select.value is Select.BLANK:
            self.notify("请先选择 repo", severity="warning")
            return
        repo = str(repo_select.value)

        hint = self.query_one("#pr-hint", Label)
        hint.update(f"Loading PRs from {repo}…")
        try:
            token = os.environ.get("GITHUB_TOKEN", "")

            prs = await asyncio.to_thread(
                lambda: __import__("osmind.github.client", fromlist=["GitHubClient"])
                .GitHubClient(token=token)
                .get_merged_prs(repo, limit=30)
            )
            self._prs_by_row: dict[int, object] = {}
            table = self.query_one("#pr-table", DataTable)
            table.clear()
            for idx, pr in enumerate(prs):
                table.add_row(f"#{pr.number}", pr.title[:28], key=str(idx))
                self._prs_by_row[idx] = pr
            hint.update(f"{len(prs)} PRs — Enter to load")
            table.focus()
        except Exception as e:
            hint.update("Error — press f to retry")
            self.notify(str(e), severity="error")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table.id != "pr-table":
            return
        row_idx = int(event.row_key.value)
        pr = self._prs_by_row.get(row_idx)
        if pr:
            self.run_worker(self._load_pr_object(pr), exclusive=True)

    async def _load_pr_object(self, pr_stub) -> None:
        """Load a PR stub (from merged list) — fetch full diff then start Socratic."""
        loader = self.query_one("#loader", LoadingIndicator)
        chat = self.query_one(ChatPanel)
        loader.display = True
        chat.add_message("assistant", f"正在加载 PR #{pr_stub.number}: {pr_stub.title}…")
        try:
            token = os.environ.get("GITHUB_TOKEN", "")
            llm_cfg = self.app.config.llm
            repo = pr_stub.repo

            def _blocking():
                from osmind.github.client import GitHubClient
                from osmind.engine.llm import LLMClient
                from osmind.engine.socratic import SocraticEngine
                gh = GitHubClient(token=token)
                pr = gh.get_pr(repo, pr_stub.number)
                # Load diff first (fast), so user sees it immediately
                return pr, llm_cfg

            pr, llm_cfg = await asyncio.to_thread(_blocking)
            self._pr = pr
            self.query_one(DiffViewer).load_pr(pr)
            chat.add_message("assistant",
                f"Diff 已加载（{len(pr.files)} 个文件）。正在生成 Socratic 问题…"
            )

            # Now call LLM for first question
            def _ask():
                from osmind.engine.llm import LLMClient
                from osmind.engine.socratic import SocraticEngine
                llm = LLMClient(llm_cfg)
                engine = SocraticEngine(llm)
                return engine, engine.first_question(pr)

            try:
                engine, first_q = await asyncio.to_thread(_ask)
                self._socratic = engine
                self._history: list[dict] = [{"role": "assistant", "content": first_q}]
                chat.add_message("assistant", first_q)
            except Exception as llm_err:
                err_msg = str(llm_err)
                base_url = llm_cfg.base_url
                chat.add_message("assistant",
                    f"⚠️  LLM 无法连接（{base_url}）\n\n"
                    f"错误：{err_msg[:200]}\n\n"
                    "你仍然可以查看左侧 diff。如需 Socratic 提问，请检查：\n"
                    "  • profile.yaml 里的 llm.base_url 是否正确\n"
                    "  • 本地模型是否已启动（如 SGLang）\n"
                    "  • 或将 base_url 改为 https://api.openai.com/v1"
                )
        except Exception as e:
            msg = str(e)
            self.notify(msg, severity="error")
            chat.add_message("assistant", f"[错误] {msg}")
        finally:
            loader.display = False

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "chat-input":
            text = event.value.strip()
            event.input.value = ""
            if text:
                self.run_worker(self._handle_user_reply(text), exclusive=True)

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
            self.notify("先选一个 PR", severity="warning")
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
