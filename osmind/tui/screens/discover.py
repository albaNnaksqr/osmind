from __future__ import annotations
import asyncio
import os
from pathlib import Path
from textual.app import ComposeResult
from textual.widgets import Label, LoadingIndicator, Select, Static
from textual.containers import Vertical, Horizontal
from osmind.logs import log_exception
from osmind.packs.opener import open_path
from osmind.tui.suspend import suspend_if_supported
from osmind.tui.widgets.issue_list import IssueTable


class DiscoverScreen(Vertical):
    DEFAULT_CSS = """
    DiscoverScreen #toolbar { height: 3; }
    DiscoverScreen #repo-select { width: 32; height: 3; }
    DiscoverScreen #hint { width: 1fr; height: 3; content-align: left middle; }
    DiscoverScreen #loader { display: none; height: 3; }
    DiscoverScreen #issue-list-view { height: 1fr; }
    DiscoverScreen #issue-detail-view { display: none; height: 1fr; }
    DiscoverScreen IssueTable { height: 1fr; }
    DiscoverScreen #issue-summary-panel { height: 4; padding: 0 1; }
    DiscoverScreen #issue-detail-panel { height: 1fr; padding: 0 1; overflow-y: auto; }
    """
    BINDINGS = [
        ("f", "fetch", "Fetch Issues"),
        ("enter", "view_issue", "View Issue"),
        ("v", "view_issue", "View Issue"),
        ("escape", "back_to_list", "Back"),
        ("g", "generate_pack", "Generate Packet"),
        ("o", "open_pack", "Open Packet"),
    ]

    def __init__(self):
        super().__init__()
        self._issues_by_number: dict[str, object] = {}
        self._pack_paths_by_key: dict[tuple[str, str, int], str] = {}

    def compose(self) -> ComposeResult:
        watching = self.app.config.watching
        options = [(r["repo"], r["repo"]) for r in watching]
        initial = watching[0]["repo"] if watching else Select.BLANK
        with Horizontal(id="toolbar"):
            yield Select(options, id="repo-select", value=initial)
            yield Label("  Press f to fetch issues", id="hint")
        yield LoadingIndicator(id="loader")
        with Vertical(id="issue-list-view"):
            yield IssueTable(id="issue-table")
            yield Static("[dim]选中 issue 后按 Enter/v 查看原文和中文摘要。[/dim]", id="issue-summary-panel")
        with Vertical(id="issue-detail-view"):
            yield Static("[dim]Esc 返回列表。g 生成 Contribution Packet。o 打开已有 Packet。[/dim]", id="issue-detail-hint")
            yield Static("", id="issue-detail-panel")

    def on_data_table_row_highlighted(self, event) -> None:
        row_key = event.row_key.value if event.row_key else None
        if row_key is None:
            return
        issue = self._issues_by_number.get(str(row_key))
        if issue and issue.reason:
            self.query_one("#issue-summary-panel", Static).update(
                f"[bold]推荐理由:[/bold] {issue.reason}\n[dim]按 Enter/v 查看 issue 原文和中文摘要。[/dim]"
            )
        elif issue:
            self.query_one("#issue-summary-panel", Static).update(
                "[dim]评分中… 按 Enter/v 可先查看原文。[/dim]"
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
        self._show_list()

        try:
            cached_issues = self._cache().list_issues(repo)
            if cached_issues:
                self._issues_by_number = {str(i.number): i for i in cached_issues}
                table = self.query_one(IssueTable)
                table.populate(cached_issues)
                table.focus()
                hint.update(
                    f"  {len(cached_issues)} cached issues  ↑↓ navigate  Enter/v: details"
                )
                loader.display = False
                return

            token = os.environ.get("GITHUB_TOKEN", "")

            # Phase 1: fetch issues immediately, show without scores
            issues = await asyncio.to_thread(
                lambda: __import__("osmind.github.client", fromlist=["GitHubClient"])
                .GitHubClient(token=token)
                .get_issues(repo, limit=30, include_comments=False)
            )
            cache = self._cache()
            for issue in issues:
                cache.upsert_issue(issue)
            self._issues_by_number = {str(i.number): i for i in issues}
            table = self.query_one(IssueTable)
            table.populate(issues)
            table.focus()
            hint.update(f"  {len(issues)} issues • 评分中…  ↑↓ navigate  Enter/v: details")
            loader.display = False

            # Phase 2: score each issue in background, update table as we go
            self.run_worker(
                self._score_progressively(issues, repo, token),
                exclusive=False,
            )
        except Exception as e:
            log_path = log_exception(self.app.config.notes_vault, f"Failed to fetch issues for {repo}")
            hint.update("  Error — press f to retry")
            self.notify(f"{e} (log: {log_path})", severity="error")
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

            failures = 0
            for issue in issues:
                try:
                    scored = await asyncio.to_thread(ranker.score_one, issue)
                except Exception:
                    failures += 1
                    log_exception(
                        self.app.config.notes_vault,
                        f"Failed to score issue {repo}#{issue.number}",
                    )
                    issue.score = 0.0
                    issue.reason = "评分失败，详情见 osmind.log"
                    scored = issue
                self._issues_by_number[str(scored.number)] = scored
                self._cache().update_issue_score(
                    scored.repo,
                    "issue",
                    scored.number,
                    scored.score,
                    scored.reason,
                )
                self.query_one(IssueTable).populate(list(self._issues_by_number.values()))

            hint = self.query_one("#hint", Label)
            hint.update("  ↑↓ navigate  Enter/v: Details  g: Generate Packet  o: Open Packet")
            if failures:
                self.notify(
                    f"{failures} 个 issue 评分失败，详情见 osmind.log",
                    severity="warning",
                )
        except Exception as e:
            log_path = log_exception(self.app.config.notes_vault, f"Failed to score issues for {repo}")
            self.notify(f"评分出错: {e} (log: {log_path})", severity="warning")

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

    async def action_view_issue(self) -> None:
        issue = self._get_selected_issue()
        if not issue:
            self.notify("先选中一个 issue", severity="warning")
            return

        detail = self.query_one("#issue-detail-panel", Static)
        self._show_detail()
        detail.update(_format_issue_detail(issue, "正在生成中文摘要…"))
        detail.can_focus = True
        detail.focus()

        loader = self.query_one("#loader", LoadingIndicator)
        loader.display = True
        try:
            from osmind.engine.issue_explainer import IssueExplainer
            from osmind.engine.llm import LLMClient

            llm_cfg = self.app.config.llm

            def _summarize():
                llm = LLMClient(llm_cfg)
                return IssueExplainer(llm).summarize(issue)

            summary = await asyncio.to_thread(_summarize)
            detail.update(_format_issue_detail(issue, summary))
        except Exception as e:
            log_path = log_exception(
                self.app.config.notes_vault,
                f"Failed to summarize issue {issue.repo}#{issue.number}",
            )
            detail.update(_format_issue_detail(issue, f"摘要失败，详情见 {log_path}"))
            self.notify(f"摘要失败: {e}", severity="warning")
        finally:
            loader.display = False

    def action_back_to_list(self) -> None:
        detail_view = self.query_one("#issue-detail-view")
        if detail_view.display:
            self._show_list()
            self.query_one(IssueTable).focus()

    def _show_detail(self) -> None:
        self.query_one("#issue-list-view").display = False
        self.query_one("#issue-detail-view").display = True
        self.query_one("#hint", Label).update(
            "  Esc: Back  g: Generate Packet  o: Open Packet"
        )

    def _show_list(self) -> None:
        self.query_one("#issue-list-view").display = True
        self.query_one("#issue-detail-view").display = False

    def _library(self):
        from osmind.services.library import PackLibrary

        cache_path = self.app.config.notes_vault / "osmind" / ".cache" / "osmind.db"
        return PackLibrary(self.app.config.notes_vault, cache_path)

    def _cache(self):
        from osmind.cache.store import CacheStore

        cache_path = self.app.config.notes_vault / "osmind" / ".cache" / "osmind.db"
        return CacheStore(cache_path)

    def _pack_key(self, issue) -> tuple[str, str, int]:
        return (issue.repo, "issue", issue.number)

    def _pack_path_for_issue(self, issue) -> Path | None:
        path = self._pack_paths_by_key.get(self._pack_key(issue))
        if path and Path(path).exists():
            return Path(path)

        cached_pack = self._library().cache.get_pack(issue.repo, "issue", issue.number)
        if cached_pack and cached_pack.get("path"):
            cached_path = Path(cached_pack["path"])
            if cached_path.exists():
                return cached_path

        return None

    async def action_generate_pack(self) -> None:
        issue = self._get_selected_issue()
        if not issue:
            self.notify("先选中一个 issue", severity="warning")
            return
        try:
            path = await asyncio.to_thread(lambda: self._library().write_issue_pack(issue))
            self._pack_paths_by_key[self._pack_key(issue)] = str(path)
            self.notify(f"Contribution Packet saved: {path}", timeout=5)
        except Exception as e:
            log_path = log_exception(
                self.app.config.notes_vault,
                f"Failed to generate Contribution Packet for {issue.repo}#{issue.number}",
            )
            self.notify(f"{e} (log: {log_path})", severity="error")

    def action_open_pack(self) -> None:
        issue = self._get_selected_issue()
        if not issue:
            self.notify("先选中一个 issue", severity="warning")
            return
        path = self._pack_path_for_issue(issue)
        if not path:
            self.notify("No packet generated for selected issue", severity="warning")
            return
        try:
            with suspend_if_supported(self.app):
                open_path(path)
        except Exception as e:
            log_path = log_exception(
                self.app.config.notes_vault,
                f"Failed to open Contribution Packet for {issue.repo}#{issue.number}",
            )
            self.notify(f"{e} (log: {log_path})", severity="error")

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

    async def key_c(self) -> None:
        await self.action_launch_claude()

    async def key_x(self) -> None:
        await self.action_launch_codex()


def _format_issue_detail(issue, summary: str) -> str:
    labels = ", ".join(issue.labels) or "none"
    comments = "\n".join(
        f"- {comment.author}: {comment.body.strip()}"
        for comment in issue.comments[:5]
    ) or "- No cached comments."
    criteria = _issue_continue_stop_criteria(issue)
    return (
        f"[bold]Issue #{issue.number}: {issue.title}[/bold]\n"
        f"[dim]{issue.repo} | labels: {labels} | {issue.url}[/dim]\n\n"
        f"[bold]中文摘要[/bold]\n{summary}\n\n"
        f"[bold]继续/放弃判断[/bold]\n{criteria}\n\n"
        f"[bold]原文[/bold]\n{(issue.body or '(empty)').strip()}\n\n"
        f"[bold]Comments[/bold]\n{comments}"
    )


def _issue_continue_stop_criteria(issue) -> str:
    body = (issue.body or "").lower()
    labels = {str(label).lower() for label in issue.labels}
    has_repro_hint = any(word in body for word in ("reproduce", "repro", "steps", "error", "traceback", "stack", "test"))
    has_help_label = bool(labels & {"bug", "good first issue", "help wanted"})

    continue_lines = [
        "Continue: 能用自己的话复述问题，并能搜到一个可能相关的模块或符号。",
    ]
    if issue.reason:
        continue_lines.append(f"Continue: 推荐理由有可检查证据：{issue.reason}")
    if has_repro_hint:
        continue_lines.append("Continue: issue 文本包含复现、错误、测试或验证线索。")
    if has_help_label:
        continue_lines.append("Continue: 标签暗示这是可行动条目。")

    stop_lines = [
        "Stop: 10 分钟内找不到复现路径、相关模块或可验证证据。",
        "Stop: 只能依赖泛泛描述，无法判断修复成功标准。",
    ]
    return "\n".join([*continue_lines, *stop_lines])
