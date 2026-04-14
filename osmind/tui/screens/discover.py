from __future__ import annotations
from textual.app import ComposeResult
from textual.widgets import Label, Select, Static
from textual.containers import Vertical, Horizontal
from osmind.tui.widgets.issue_list import IssueTable


class DiscoverScreen(Vertical):
    BINDINGS = [
        ("f", "fetch", "Fetch Issues"),
        ("c", "launch_claude", "Claude Code"),
        ("x", "launch_codex", "Codex"),
    ]

    def __init__(self):
        super().__init__()
        self._issues_by_number: dict[str, object] = {}

    def compose(self) -> ComposeResult:
        with Vertical():
            with Horizontal(id="toolbar"):
                yield Select(
                    [(r["repo"], r["repo"]) for r in self.app.config.watching],
                    id="repo-select",
                    prompt="Select repo",
                )
                yield Label("  Press f to fetch issues", id="hint")
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
        import os
        from osmind.github.client import GitHubClient
        from osmind.engine.llm import LLMClient
        from osmind.engine.ranker import Ranker

        repo_select = self.query_one("#repo-select", Select)
        if repo_select.value is Select.BLANK:
            return
        repo = str(repo_select.value)

        self.query_one("#hint", Label).update("Fetching...")
        gh = GitHubClient(token=os.environ.get("GITHUB_TOKEN", ""))
        llm = LLMClient(self.app.config.llm)
        ranker = Ranker(llm, self.app.config.interests, self.app.config.skills)

        issues = gh.get_issues(repo, limit=30)
        ranked = ranker.rank(issues)
        self._issues_by_number = {str(i.number): i for i in ranked}

        table = self.query_one(IssueTable)
        table.populate(ranked)
        self.query_one("#hint", Label).update(f"{len(ranked)} issues loaded")
        table.focus()

    def _get_selected_issue(self):
        table = self.query_one(IssueTable)
        if table.cursor_row is None:
            return None
        try:
            row_data = table.get_row_at(table.cursor_row)
            issue_number = str(row_data[1])  # column 1 = issue number
            return self._issues_by_number.get(issue_number)
        except Exception:
            return None

    def action_launch_claude(self) -> None:
        issue = self._get_selected_issue()
        if issue:
            from osmind.agents.launcher import AgentLauncher
            launcher = AgentLauncher(
                self.app.config.external_agents.claude_code,
                self.app.config.external_agents.codex,
            )
            launcher.launch_claude(issue)

    def action_launch_codex(self) -> None:
        issue = self._get_selected_issue()
        if issue:
            from osmind.agents.launcher import AgentLauncher
            launcher = AgentLauncher(
                self.app.config.external_agents.claude_code,
                self.app.config.external_agents.codex,
            )
            launcher.launch_codex(issue)
