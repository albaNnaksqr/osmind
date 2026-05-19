from __future__ import annotations
import asyncio
import os
from pathlib import Path
from textual.app import ComposeResult
from textual.widgets import Label, LoadingIndicator, Select, Static
from textual.containers import Vertical, Horizontal
from osmind.logs import log_exception
from osmind.packs.opener import open_path
from osmind.tui.recommendation import action_reason, next_step_for_action, recommended_action
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
    DiscoverScreen #issue-detail-content { height: 1fr; }
    DiscoverScreen IssueTable { height: 1fr; }
    DiscoverScreen #issue-summary-panel { height: 4; padding: 0 1; }
    DiscoverScreen #issue-analysis-panel {
        width: 38%;
        min-width: 32;
        height: 1fr;
        padding: 0 1;
        border-right: solid $panel;
        overflow-y: auto;
    }
    DiscoverScreen #issue-source-panel {
        width: 1fr;
        height: 1fr;
        padding: 0 1;
        overflow-y: auto;
    }
    """
    BINDINGS = [
        ("f", "fetch", "Fetch Issues"),
        ("u", "update", "Update from GitHub"),
        ("s", "rescore", "Re-rank"),
        ("tab", "toggle_detail_focus", "Switch Pane"),
        ("enter", "view_issue", "View Issue"),
        ("v", "view_issue", "View Issue"),
        ("escape", "back_to_list", "Back"),
        ("g", "generate_pack", "Generate Packet"),
        ("o", "open_pack", "Open Packet"),
        ("y", "mark_continue", "Continue"),
        ("l", "mark_defer", "Defer"),
        ("n", "mark_discard", "Discard"),
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
            yield Label("  f: Open opportunities  u: Update from GitHub  s: Re-rank", id="hint")
        yield LoadingIndicator(id="loader")
        with Vertical(id="issue-list-view"):
            yield IssueTable(id="issue-table")
            yield Static("[dim]选中 issue 后按 Enter/v 查看推荐动作、资源解释和原文。[/dim]", id="issue-summary-panel")
        with Vertical(id="issue-detail-view"):
            yield Static(
                "[dim]Tab 切换 Analysis/Source。Esc 返回列表。g 生成 Packet。o 打开 Packet。u 从 GitHub 更新。s 用当前 profile 重排。y/l/n 标记决策。[/dim]",
                id="issue-detail-hint",
            )
            with Horizontal(id="issue-detail-content"):
                yield Static("", id="issue-analysis-panel")
                yield Static("", id="issue-source-panel")

    def on_data_table_row_highlighted(self, event) -> None:
        row_key = event.row_key.value if event.row_key else None
        if row_key is None:
            return
        issue = self._issues_by_number.get(str(row_key))
        if issue and issue.reason:
            self.query_one("#issue-summary-panel", Static).update(
                f"[bold]推荐动作:[/bold] {recommended_action(issue)} — {action_reason(issue)}\n"
                f"[dim]{issue.reason}[/dim]"
            )
        elif issue:
            self.query_one("#issue-summary-panel", Static).update(
                "[dim]正在判断这个 issue 是否值得现在投入… 按 Enter/v 可先查看原文。[/dim]"
            )

    def on_key(self, event) -> None:
        if event.key != "tab":
            return
        detail_view = self.query_one("#issue-detail-view")
        if not detail_view.display:
            return
        event.prevent_default()
        event.stop()
        self.action_toggle_detail_focus()

    async def action_fetch(self) -> None:
        repo = self._selected_repo()
        if repo is None:
            return

        loader = self.query_one("#loader", LoadingIndicator)
        hint = self.query_one("#hint", Label)
        self._set_busy(f"  Loading {repo}…")
        self._show_list()

        try:
            cached_issues = self._cache().list_issues(repo)
            if cached_issues:
                self._show_issues(cached_issues)
                hint.update(
                    f"  {len(cached_issues)} opportunities  ↑↓ navigate  Enter/v: details  u: update from GitHub  s: re-rank"
                )
                loader.display = False
                return

            await self._fetch_from_github_and_score(repo)
        except Exception as e:
            log_path = log_exception(self.app.config.notes_vault, f"Failed to fetch issues for {repo}")
            hint.update("  Error — press f to retry")
            self.notify(f"{e} (log: {log_path})", severity="error")
            loader.display = False

    async def action_update(self) -> None:
        repo = self._selected_repo()
        if repo is None:
            return
        self._show_list()
        try:
            await self._fetch_from_github_and_score(repo)
        except Exception as e:
            log_path = log_exception(self.app.config.notes_vault, f"Failed to update issues for {repo}")
            self.query_one("#hint", Label).update("  Update failed — press u to retry")
            self.notify(f"{e} (log: {log_path})", severity="error")
            self.query_one("#loader", LoadingIndicator).display = False

    async def action_rescore(self) -> None:
        repo = self._selected_repo()
        if repo is None:
            return
        self._show_list()
        loader = self.query_one("#loader", LoadingIndicator)
        hint = self.query_one("#hint", Label)
        self._set_busy(f"  Re-ranking {repo} with current profile…")
        try:
            cached_issues = self._cache().list_issues(repo)
            if not cached_issues:
                hint.update("  No opportunities loaded yet — press u to update from GitHub")
                self.notify("没有缓存 issue，先按 u 从 GitHub 更新", severity="warning")
                loader.display = False
                return
            self._show_issues(cached_issues)
            await self._score_progressively(cached_issues, repo, "")
        except Exception as e:
            log_path = log_exception(self.app.config.notes_vault, f"Failed to re-rank issues for {repo}")
            hint.update("  Re-rank failed — press s to retry")
            self.notify(f"{e} (log: {log_path})", severity="error")
            loader.display = False

    def _selected_repo(self) -> str | None:
        repo_select = self.query_one("#repo-select", Select)
        if repo_select.value is Select.BLANK:
            self.notify("请先选择 repo", severity="warning")
            return None
        return str(repo_select.value)

    def _set_busy(self, message: str) -> None:
        self.query_one("#loader", LoadingIndicator).display = True
        self.query_one("#hint", Label).update(message)

    def _show_issues(self, issues) -> None:
        self._issues_by_number = {str(i.number): i for i in issues}
        table = self.query_one(IssueTable)
        table.populate(issues)
        table.focus()

    async def _fetch_from_github_and_score(self, repo: str) -> None:
        self._set_busy(f"  Updating {repo} from GitHub…")
        token = os.environ.get("GITHUB_TOKEN", "")
        issues = await asyncio.to_thread(
            lambda: __import__("osmind.github.client", fromlist=["GitHubClient"])
            .GitHubClient(token=token)
            .get_issues(repo, limit=30, include_comments=False)
        )
        cache = self._cache()
        for issue in issues:
            cache.upsert_issue(issue)
        self._show_issues(issues)
        self.query_one("#hint", Label).update(f"  {len(issues)} opportunities • ranking…  ↑↓ navigate  Enter/v: details")
        self.query_one("#loader", LoadingIndicator).display = False
        await self._score_progressively(issues, repo, token)

    async def _score_progressively(self, issues, repo: str, token: str) -> None:
        from osmind.engine.llm import LLMClient
        from osmind.engine.ranker import Ranker

        llm_cfg = self.app.config.llm
        interests = self.app.config.interests
        skills = self.app.config.skills
        resources = self.app.config.resources

        try:
            llm = LLMClient(llm_cfg)
            ranker = Ranker(llm, interests, skills, resources)

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
                    priority=scored.priority,
                    fit=scored.fit,
                    resource_fit=scored.resource_fit,
                    actionability=scored.actionability,
                )
                self.query_one(IssueTable).populate(list(self._issues_by_number.values()))

            hint = self.query_one("#hint", Label)
            hint.update(
                "  ↑↓ navigate  Enter/v: Details  g: Packet  o: Open  u: Update from GitHub  s: Re-rank  y/l/n: Decision"
            )
            self.query_one("#loader", LoadingIndicator).display = False
            if failures:
                self.notify(
                    f"{failures} 个 issue 评分失败，详情见 osmind.log",
                    severity="warning",
                )
        except Exception as e:
            log_path = log_exception(self.app.config.notes_vault, f"Failed to score issues for {repo}")
            self.notify(f"评分出错: {e} (log: {log_path})", severity="warning")
            self.query_one("#loader", LoadingIndicator).display = False

    def _get_selected_issue(self):
        table = self.query_one(IssueTable)
        if table.cursor_row is None:
            return None
        try:
            row_key = table.ordered_rows[table.cursor_row].key
            issue_number = str(row_key.value)
            return self._issues_by_number.get(issue_number)
        except Exception:
            return None

    async def action_view_issue(self) -> None:
        issue = self._get_selected_issue()
        if not issue:
            self.notify("先选中一个 issue", severity="warning")
            return

        analysis = self.query_one("#issue-analysis-panel", Static)
        source = self.query_one("#issue-source-panel", Static)
        self._show_detail()
        analysis.update(_format_issue_analysis(issue, self.app.config.resources))
        source.update(_format_issue_source(issue, "正在生成中文摘要…"))
        analysis.can_focus = True
        source.can_focus = True
        source.focus()

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
            source.update(_format_issue_source(issue, summary))
        except Exception as e:
            log_path = log_exception(
                self.app.config.notes_vault,
                f"Failed to summarize issue {issue.repo}#{issue.number}",
            )
            source.update(_format_issue_source(issue, f"摘要失败，详情见 {log_path}"))
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
        self.query_one(IssueTable).can_focus = False
        self.query_one("#repo-select", Select).can_focus = False
        self.query_one("#issue-analysis-panel", Static).can_focus = True
        self.query_one("#issue-source-panel", Static).can_focus = True
        self.query_one("#hint", Label).update(
            "  Tab: Analysis/Source  Esc: Back  g: Packet  o: Open  u: Update from GitHub  s: Re-rank  y/l/n: Decision"
        )

    def _show_list(self) -> None:
        self.query_one("#issue-list-view").display = True
        self.query_one("#issue-detail-view").display = False
        self.query_one(IssueTable).can_focus = True
        self.query_one("#repo-select", Select).can_focus = True
        self.query_one("#issue-analysis-panel", Static).can_focus = False
        self.query_one("#issue-source-panel", Static).can_focus = False

    def action_toggle_detail_focus(self) -> None:
        detail_view = self.query_one("#issue-detail-view")
        if not detail_view.display:
            return
        analysis = self.query_one("#issue-analysis-panel", Static)
        source = self.query_one("#issue-source-panel", Static)
        if self.app.focused is source:
            analysis.focus()
        else:
            source.focus()

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

    async def _mark_selected_issue_decision(self, decision: str) -> None:
        issue = self._get_selected_issue()
        if not issue:
            self.notify("先选中一个 issue", severity="warning")
            return
        try:
            path = self._pack_path_for_issue(issue)
            if path is None:
                path = await asyncio.to_thread(lambda: self._library().write_issue_pack(issue))
                self._pack_paths_by_key[self._pack_key(issue)] = str(path)
            path = await asyncio.to_thread(
                lambda: self._library().set_pack_decision(issue.repo, "issue", issue.number, decision)
            )
            self._pack_paths_by_key[self._pack_key(issue)] = str(path)
            self.notify(f"Marked {decision}: {path}", timeout=5)
        except Exception as e:
            log_path = log_exception(
                self.app.config.notes_vault,
                f"Failed to mark Contribution Packet decision for {issue.repo}#{issue.number}",
            )
            self.notify(f"{e} (log: {log_path})", severity="error")

    async def action_mark_continue(self) -> None:
        await self._mark_selected_issue_decision("continue")

    async def action_mark_defer(self) -> None:
        await self._mark_selected_issue_decision("defer")

    async def action_mark_discard(self) -> None:
        await self._mark_selected_issue_decision("discard")

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


def _format_issue_analysis(issue, resources: dict | None = None) -> str:
    criteria = _issue_continue_stop_criteria(issue)
    return (
        "[bold]Analysis[/bold]\n\n"
        f"[bold]推荐动作[/bold]\n{_format_recommendation(issue, resources)}\n\n"
        f"[bold]继续/放弃判断[/bold]\n{criteria}"
    )


def _format_issue_source(issue, summary: str) -> str:
    labels = ", ".join(issue.labels) or "none"
    comments = "\n".join(
        f"- {comment.author}: {comment.body.strip()}"
        for comment in issue.comments[:5]
    ) or "- No cached comments."
    return (
        "[bold]Source[/bold]\n\n"
        f"[bold]Issue #{issue.number}: {issue.title}[/bold]\n"
        f"[dim]{issue.repo} | labels: {labels} | {issue.url}[/dim]\n\n"
        f"[bold]Summary[/bold]\n{summary}\n\n"
        f"[bold]Original Issue[/bold]\n{(issue.body or '(empty)').strip()}\n\n"
        f"[bold]Comments[/bold]\n{comments}"
    )


def _format_issue_detail(issue, summary: str, resources: dict | None = None) -> str:
    return f"{_format_issue_analysis(issue, resources)}\n\n{_format_issue_source(issue, summary)}"


def _format_recommendation(issue, resources: dict | None = None) -> str:
    action = recommended_action(issue)
    why = action_reason(issue)
    next_step = next_step_for_action(action)
    priority = _display_dimension(getattr(issue, "priority", "unknown"), kind="priority", score=getattr(issue, "score", 0.0))
    fit = _display_dimension(getattr(issue, "fit", "unknown"))
    resource_fit = _display_dimension(getattr(issue, "resource_fit", "unknown"), kind="resource")
    actionability = _display_dimension(getattr(issue, "actionability", "unknown"))
    resources_text = _format_resources(resources or {})
    reason = getattr(issue, "reason", "") or "评分尚未产生推荐理由。"
    return (
        f"Action: {action}\n"
        f"Why: {why}\n"
        f"Next: {next_step}\n"
        f"Priority: {priority}\n"
        f"Fit: {fit}\n"
        f"Resource Fit: {resource_fit}\n"
        f"Actionability: {actionability}\n"
        f"用户资源: {resources_text}\n"
        f"Reason: {reason}"
    )


def _format_resources(resources: dict) -> str:
    if not resources:
        return "unspecified"
    return ", ".join(f"{key}: {value}" for key, value in resources.items())


def _display_dimension(value: str, *, kind: str = "level", score: float = 0.0) -> str:
    normalized = str(value or "unknown").lower()
    if kind == "priority" and normalized == "unknown":
        if score >= 0.7:
            normalized = "high"
        elif score >= 0.4:
            normalized = "medium"
    labels = {
        "high": "Hi" if kind != "priority" else "High",
        "medium": "Med",
        "low": "Low",
        "ok": "OK",
        "risk": "Risk",
        "blocked": "Blocked",
        "unknown": "--",
    }
    return labels.get(normalized, "--")


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
