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
        with Horizontal(id="toolbar"):
            yield Select(
                [(r["repo"], r["repo"]) for r in self.app.config.watching],
                id="repo-select",
                prompt="Select repo",
            )
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

    async def action_fetch(self) -> None:
        from osmind.github.client import GitHubClient
        from osmind.engine.llm import LLMClient
        from osmind.engine.ranker import Ranker

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
            interests = self.app.config.interests
            skills = self.app.config.skills
            llm_cfg = self.app.config.llm

            def _blocking() -> list:
                gh = GitHubClient(token=token)
                llm = LLMClient(llm_cfg)
                ranker = Ranker(llm, interests, skills)
                issues = gh.get_issues(repo, limit=30)
                return ranker.rank(issues)

            ranked = await asyncio.to_thread(_blocking)
            self._issues_by_number = {str(i.number): i for i in ranked}
            self.query_one(IssueTable).populate(ranked)
            self.query_one(IssueTable).focus()
            self.notify(f"{len(ranked)} issues loaded", severity="information")
            hint.update("  ↑↓ navigate  c: Claude  x: Codex")
        except Exception as e:
            self.notify(str(e), severity="error")
            hint.update("  Error — press f to retry")
        finally:
            loader.display = False

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

    def action_launch_claude(self) -> None:
        issue = self._get_selected_issue()
        if not issue:
            self.notify("先选中一个 issue", severity="warning")
            return
        from osmind.agents.launcher import AgentLauncher
        launcher = AgentLauncher(
            self.app.config.external_agents.claude_code,
            self.app.config.external_agents.codex,
        )
        launcher.launch_claude(issue)
        self.notify(f"Claude Code launched for #{issue.number}")

    def action_launch_codex(self) -> None:
        issue = self._get_selected_issue()
        if not issue:
            self.notify("先选中一个 issue", severity="warning")
            return
        from osmind.agents.launcher import AgentLauncher
        launcher = AgentLauncher(
            self.app.config.external_agents.claude_code,
            self.app.config.external_agents.codex,
        )
        launcher.launch_codex(issue)
        self.notify(f"Codex launched for #{issue.number}")
