from __future__ import annotations
import asyncio
import os
from textual.app import ComposeResult
from textual.widgets import Label, LoadingIndicator, Select, Static
from textual.containers import Vertical, Horizontal
from osmind.tui.widgets.issue_list import IssueTable


class DiscoverScreen(Vertical):
    DEFAULT_CSS = """
    DiscoverScreen #loader { display: none; height: 3; }
    DiscoverScreen #reason-panel { height: 3; padding: 0 1; }
    """
    BINDINGS = [
        ("f", "fetch", "Fetch Issues"),
        ("c", "launch_claude", "Claude Code"),
        ("x", "launch_codex", "Codex"),
    ]

    def __init__(self):
        super().__init__()
        self._issues_by_number: dict[str, object] = {}

    def compose(self) -> ComposeResult:
        watching = self.app.config.watching
        options = [(r["repo"], r["repo"]) for r in watching]
        initial = watching[0]["repo"] if watching else Select.BLANK
        with Horizontal(id="toolbar"):
            yield Select(options, id="repo-select", value=initial)
            yield Label("  Press f to fetch issues", id="hint")
        yield LoadingIndicator(id="loader")
        yield IssueTable(id="issue-table")
        yield Static("", id="reason-panel")

    def on_data_table_row_highlighted(self, event) -> None:
        row_key = event.row_key.value if event.row_key else None
        if row_key is None:
            return
        issue = self._issues_by_number.get(str(row_key))
        if issue and issue.reason:
            self.query_one("#reason-panel", Static).update(
                f"[bold]推荐理由:[/bold] {issue.reason}"
            )
        elif issue:
            self.query_one("#reason-panel", Static).update(
                "[dim]评分中…[/dim]"
            )

    async def action_fetch(self) -> None:
        repo_select = self.query_one("#repo-select", Select)
        if repo_select.value is Select.BLANK:
            self.notify("请先选择 repo", severity="warning")
            return
        repo = str(repo_select.value)

        loader = self.query_one("#loader", LoadingIndicator)
        hint = self.query_one("#hint", Label)
        loader.display = True
        hint.update(f"  Fetching {repo}…")

        try:
            token = os.environ.get("GITHUB_TOKEN", "")

            # Phase 1: fetch issues immediately, show without scores
            issues = await asyncio.to_thread(
                lambda: __import__("osmind.github.client", fromlist=["GitHubClient"])
                .GitHubClient(token=token)
                .get_issues(repo, limit=30)
            )
            self._issues_by_number = {str(i.number): i for i in issues}
            table = self.query_one(IssueTable)
            table.populate(issues)
            table.focus()
            hint.update(f"  {len(issues)} issues • 评分中…  ↑↓ navigate")
            loader.display = False

            # Phase 2: score each issue in background, update table as we go
            self.run_worker(
                self._score_progressively(issues, repo, token),
                exclusive=False,
            )
        except Exception as e:
            hint.update("  Error — press f to retry")
            self.notify(str(e), severity="error")
            loader.display = False

    async def _score_progressively(self, issues, repo: str, token: str) -> None:
        from osmind.engine.llm import LLMClient
        from osmind.engine.ranker import Ranker

        llm_cfg = self.app.config.llm
        interests = self.app.config.interests
        skills = self.app.config.skills

        try:
            llm = LLMClient(llm_cfg)
            ranker = Ranker(llm, interests, skills)

            for issue in issues:
                scored = await asyncio.to_thread(ranker.score_one, issue)
                self._issues_by_number[str(scored.number)] = scored
                self.query_one(IssueTable).update_score(str(scored.number), scored.score)

            hint = self.query_one("#hint", Label)
            hint.update("  ↑↓ navigate  c: Claude  x: Codex")
        except Exception as e:
            self.notify(f"评分出错: {e}", severity="warning")

    def _get_selected_issue(self):
        table = self.query_one(IssueTable)
        if table.cursor_row is None:
            return None
        try:
            row_data = table.get_row_at(table.cursor_row)
            issue_number = str(row_data[1])
            return self._issues_by_number.get(issue_number)
        except Exception:
            return None

    async def action_launch_claude(self) -> None:
        issue = self._get_selected_issue()
        if not issue:
            self.notify("先选中一个 issue", severity="warning")
            return
        from osmind.agents.launcher import AgentLauncher
        launcher = AgentLauncher(
            self.app.config.external_agents.claude_code,
            self.app.config.external_agents.codex,
        )
        # Suspend TUI, hand terminal to Claude Code, resume when done
        with self.app.suspend():
            launcher.launch_claude(issue)

    async def action_launch_codex(self) -> None:
        issue = self._get_selected_issue()
        if not issue:
            self.notify("先选中一个 issue", severity="warning")
            return
        from osmind.agents.launcher import AgentLauncher
        launcher = AgentLauncher(
            self.app.config.external_agents.claude_code,
            self.app.config.external_agents.codex,
        )
        with self.app.suspend():
            launcher.launch_codex(issue)
