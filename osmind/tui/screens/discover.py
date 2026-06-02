from __future__ import annotations
import asyncio
import os
import re
from pathlib import Path
from textual.app import ComposeResult
from textual.css.query import NoMatches
from textual.widgets import Label, LoadingIndicator, Select, Static
from textual.containers import Vertical, Horizontal, VerticalScroll
from osmind.decision import format_decision_panel
from osmind.logs import log_exception
from osmind.packs.opener import open_path
from osmind.tui.decision_dialog import DecisionDialog
from osmind.tui.lifecycle import resources_hash
from osmind.tui.recommendation import action_reason, recommended_action
from osmind.tui.suspend import suspend_if_supported
from osmind.tui.update_dialog import QueueUpdateDialog
from osmind.tui.widgets.issue_list import IssueTable
from osmind.tui.workflow import format_start_work_from_packet


DEFAULT_ISSUE_FETCH_LIMIT = 30


class DiscoverScreen(Vertical):
    ACTION_FILTERS = [
        ("Active", "active"),
        ("Do now", "do_now"),
        ("Inspect", "inspect"),
        ("Rec Defer", "rec_defer"),
        ("Skip", "skip"),
        ("Packeted", "packeted"),
        ("Deferred", "deferred"),
        ("Discarded", "discarded"),
        ("Changed", "changed"),
        ("All", "all"),
    ]
    DEFAULT_CSS = """
    DiscoverScreen #breadcrumb { height: 1; padding: 0 1; color: $text-muted; background: $panel; }
    DiscoverScreen #toolbar { height: 3; }
    DiscoverScreen #repo-select { width: 32; height: 3; }
    DiscoverScreen #action-filter { width: 18; height: 3; }
    DiscoverScreen #hint { width: 52; height: 3; content-align: left middle; }
    DiscoverScreen #freshness-status { width: 1fr; height: 3; content-align: left middle; padding: 0 1; }
    DiscoverScreen #loader { display: none; height: 3; }
    DiscoverScreen #issue-list-view { height: 1fr; }
    DiscoverScreen #issue-detail-view { display: none; height: 1fr; }
    DiscoverScreen #start-work-view { display: none; height: 1fr; }
    DiscoverScreen #issue-detail-content { height: 1fr; }
    DiscoverScreen IssueTable { height: 1fr; }
    DiscoverScreen #issue-summary-panel { height: 4; padding: 0 1; }
    DiscoverScreen #start-work-panel {
        height: 1fr;
        padding: 0 1;
        border: round $panel;
        overflow-y: auto;
    }
    DiscoverScreen #start-work-panel:focus { border: round $accent; }
    DiscoverScreen #issue-analysis-panel {
        width: 38%;
        min-width: 32;
        height: 1fr;
        padding: 0 1;
        border: round $panel;
        overflow-y: auto;
    }
    DiscoverScreen #issue-source-panel {
        width: 1fr;
        height: 1fr;
        padding: 0 1;
        border: round $panel;
        overflow-y: auto;
    }
    DiscoverScreen #issue-analysis-panel:focus,
    DiscoverScreen #issue-source-panel:focus {
        border: round $accent;
    }
    """
    BINDINGS = [
        ("enter", "view_issue", "View"),
        ("space", "decide", "Decide"),
        ("tab", "toggle_detail_focus", "Switch Pane"),
        ("u", "update", "Update"),
        ("escape", "back_to_list", "Back"),
        ("q", "back_to_list", "Back"),
    ]

    def __init__(self):
        super().__init__()
        self._issues_by_number: dict[str, object] = {}
        self._pack_paths_by_key: dict[tuple[str, str, int], str] = {}
        self._issue_brief_tasks: dict[tuple[str, str, int], asyncio.Task] = {}
        self._action_filter = "active"
        self._issue_detail_request_id = 0

    def compose(self) -> ComposeResult:
        watching = self.app.config.watching
        options = [(r["repo"], r["repo"]) for r in watching]
        initial = watching[0]["repo"] if watching else Select.BLANK
        yield Static("Discover", id="breadcrumb")
        with Horizontal(id="toolbar"):
            yield Select(options, id="repo-select", value=initial)
            yield Select(self.ACTION_FILTERS, id="action-filter", value="active")
            yield Label("  Ready", id="hint")
            yield Static("Filter: Active | No opportunities loaded", id="freshness-status")
        yield LoadingIndicator(id="loader")
        with Vertical(id="issue-list-view"):
            yield IssueTable(id="issue-table")
            yield Static(
                "[dim]查看[/dim]  [b cyan]Enter[/b cyan] 详情     "
                "[dim]决策[/dim]  [b yellow]Space[/b yellow] → [b green]Start Work[/b green] / Defer / Discard     "
                "[dim]?[/dim] 帮助   [dim](生成的 Packet 在 [b]p[/b] Packs 标签打开)[/dim]",
                id="issue-summary-panel",
            )
        with Vertical(id="issue-detail-view"):
            with Horizontal(id="issue-detail-content"):
                with VerticalScroll(id="issue-analysis-panel") as analysis_scroll:
                    analysis_scroll.border_title = "Analysis"
                    yield Static("", id="issue-analysis-content")
                with VerticalScroll(id="issue-source-panel") as source_scroll:
                    source_scroll.border_title = "Source"
                    yield Static("", id="issue-source-content", markup=False)
        with Vertical(id="start-work-view"):
            with VerticalScroll(id="start-work-panel") as start_work_scroll:
                start_work_scroll.border_title = "Start Work"
                yield Static("", id="start-work-content")

    def on_mount(self) -> None:
        self._set_breadcrumb(self._selected_repo(notify=False) or "")
        self.call_after_refresh(self._load_cached_queue_if_available)

    def _load_cached_queue_if_available(self) -> None:
        repo = self._selected_repo(notify=False)
        if repo is None:
            return
        try:
            cached_issues = self._cached_issues_for_repo(repo)
        except Exception:
            log_exception(self.app.config.notes_vault, f"Failed to load cached issues for {repo}")
            return
        if not cached_issues:
            return
        self._show_cached_issues(cached_issues)

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
                "[dim]正在判断这个 issue 是否值得现在投入… 按 Enter 可先查看原文。[/dim]"
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

    async def on_data_table_row_selected(self, event) -> None:
        if event.data_table.id != "issue-table":
            return
        event.stop()
        await self.action_view_issue()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "action-filter" or event.value is Select.BLANK:
            return
        event.stop()
        self._set_action_filter(str(event.value))

    async def action_fetch(self) -> None:
        repo = self._selected_repo()
        if repo is None:
            return

        loader = self.query_one("#loader", LoadingIndicator)
        self._set_busy(f"  Loading {repo}…")
        self._show_list()

        try:
            cached_issues = self._cached_issues_for_repo(repo)
            if cached_issues:
                self._show_cached_issues(cached_issues)
                return

            await self._fetch_from_github_and_score(repo)
        except Exception as e:
            log_path = log_exception(self.app.config.notes_vault, f"Failed to fetch issues for {repo}")
            self.query_one("#hint", Label).update("  Error — press u to retry")
            self.notify(f"{e} (log: {log_path})", severity="error")
            loader.display = False

    async def action_update(self) -> None:
        repo = self._selected_repo()
        if repo is None:
            return
        try:
            cached_issues = self._cached_issues_for_repo(repo)
            if cached_issues:
                async def handle_choice(choice: str | None) -> None:
                    await self._handle_update_choice(repo, cached_issues, choice)

                self.app.push_screen(QueueUpdateDialog(len(cached_issues)), handle_choice)
                return
            self._show_list()
            await self._fetch_from_github_and_score(repo)
        except Exception as e:
            log_path = log_exception(self.app.config.notes_vault, f"Failed to update issues for {repo}")
            self.query_one("#hint", Label).update("  Update failed — press u to retry")
            self.notify(f"{e} (log: {log_path})", severity="error")
            self.query_one("#loader", LoadingIndicator).display = False

    async def _handle_update_choice(self, repo: str, cached_issues, choice: str | None) -> None:
        if choice == "cache":
            self._show_list()
            self._show_cached_issues(cached_issues)
            return
        if choice != "fetch":
            return
        self._show_list()
        try:
            await self._fetch_from_github_and_score(repo)
        except Exception as e:
            log_path = log_exception(self.app.config.notes_vault, f"Failed to update issues for {repo}")
            self.query_one("#hint", Label).update("  Update failed — press u to retry")
            self.notify(_format_github_fetch_error(repo, e, log_path), severity="error")
            self.query_one("#loader", LoadingIndicator).display = False

    def _cached_issues_for_repo(self, repo: str):
        cache_path = self.app.config.notes_vault / "osmind" / ".cache" / "osmind.db"
        if not cache_path.exists():
            return []
        return self._cache().list_issues(repo)

    def _show_cached_issues(self, cached_issues) -> None:
        self._show_issues(cached_issues)
        self.query_one("#hint", Label).update(
            f"  {len(cached_issues)} cached opportunities"
        )
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
                hint.update("  No opportunities loaded yet — press u to load or fetch")
                self.notify("没有缓存 issue，先按 u 读取或更新机会队列", severity="warning")
                loader.display = False
                return
            self._show_issues(cached_issues)
            await self._score_progressively(cached_issues, repo, "")
        except Exception as e:
            log_path = log_exception(self.app.config.notes_vault, f"Failed to re-rank issues for {repo}")
            hint.update("  Re-rank failed")
            self.notify(f"{e} (log: {log_path})", severity="error")
            loader.display = False

    def _selected_repo(self, *, notify: bool = True) -> str | None:
        try:
            repo_select = self.query_one("#repo-select", Select)
        except NoMatches:
            return None
        if repo_select.value is Select.BLANK:
            if notify:
                self.notify("请先选择 repo", severity="warning")
            return None
        return str(repo_select.value)

    def _set_busy(self, message: str) -> None:
        self.query_one("#loader", LoadingIndicator).display = True
        self.query_one("#hint", Label).update(message)

    def _show_issues(self, issues) -> None:
        self._issues_by_number = {str(i.number): i for i in issues}
        self._refresh_issue_table(focus=True)

    def _refresh_issue_table(self, *, focus: bool = False) -> None:
        table = self.query_one(IssueTable)
        table.populate(self._filtered_issues())
        if focus:
            table.focus()
        self._update_freshness_status()

    def _filtered_issues(self):
        issues = list(self._issues_by_number.values())
        if self._action_filter == "active":
            return [issue for issue in issues if self._issue_lifecycle(issue) in {"active", "changed"}]
        if self._action_filter == "all":
            return issues
        if self._action_filter == "packeted":
            return [issue for issue in issues if self._pack_path_for_issue(issue) is not None]
        if self._action_filter == "deferred":
            return [issue for issue in issues if self._issue_lifecycle(issue) == "defer"]
        if self._action_filter == "discarded":
            return [issue for issue in issues if self._issue_lifecycle(issue) == "discard"]
        if self._action_filter == "changed":
            return [issue for issue in issues if self._issue_lifecycle(issue) == "changed"]

        expected_action = {
            "do_now": "Do now",
            "inspect": "Inspect",
            "rec_defer": "Defer",
            "skip": "Skip",
        }.get(self._action_filter)
        if expected_action is None:
            return issues
        return [
            issue
            for issue in issues
            if self._issue_lifecycle(issue) in {"active", "changed"} and recommended_action(issue) == expected_action
        ]

    def _set_action_filter(self, value: str) -> None:
        valid_values = {filter_value for _, filter_value in self.ACTION_FILTERS}
        if value not in valid_values:
            value = "all"
        self._action_filter = value
        try:
            filter_select = self.query_one("#action-filter", Select)
            if filter_select.value != value:
                filter_select.value = value
        except Exception:
            pass
        self._refresh_issue_table()

    def action_cycle_action_filter(self) -> None:
        values = [filter_value for _, filter_value in self.ACTION_FILTERS]
        current_index = values.index(self._action_filter) if self._action_filter in values else 0
        self._set_action_filter(values[(current_index + 1) % len(values)])

    def _filter_label(self) -> str:
        labels = {value: label for label, value in self.ACTION_FILTERS}
        return labels.get(self._action_filter, "All")

    def _update_freshness_status(self) -> None:
        status = self.query_one("#freshness-status", Static)
        repo = self._selected_repo(notify=False)
        visible_count = len(self._filtered_issues())
        total_count = len(self._issues_by_number)
        if total_count == 0:
            status.update(f"Filter: {self._filter_label()} | No opportunities loaded")
            return
        if repo is None:
            status.update(f"Filter: {self._filter_label()} | No repo selected")
            return
        try:
            activity = self._cache().issue_activity(repo)
        except Exception:
            status.update(f"{visible_count} visible / {total_count} issues | Filter: {self._filter_label()}")
            return
        issue_count = activity["issue_count"] or total_count
        fetched = activity["last_fetched_at"] or "never"
        ranked = activity["last_ranked_at"] or "never"
        unranked = activity["unranked_count"]
        packets = activity["packet_count"]
        deferred, discarded, changed = self._lifecycle_counts()
        status.update(
            f"{visible_count} visible / {issue_count} issues | Filter: {self._filter_label()} | "
            f"Last fetched: {fetched} | Last ranked: {ranked} | Unranked: {unranked} | Packets: {packets} | "
            f"Deferred: {deferred} | Discarded: {discarded} | Changed: {changed}"
        )

    def _lifecycle_counts(self) -> tuple[int, int, int]:
        states = [self._issue_lifecycle(issue) for issue in self._issues_by_number.values()]
        return states.count("defer"), states.count("discard"), states.count("changed")

    def _issue_lifecycle(self, issue) -> str:
        cached_pack = self._cached_pack_for_issue(issue)
        if cached_pack is None:
            return "active"

        decision = str(cached_pack.get("decision") or "undecided")
        if decision not in {"defer", "discard"}:
            return "active"
        if self._decision_context_changed(issue, cached_pack):
            return "changed"
        return decision

    def _decision_context_changed(self, issue, cached_pack: dict) -> bool:
        source_updated_at = str(cached_pack.get("source_updated_at") or "")
        issue_updated_at = str(getattr(issue, "updated_at", "") or "")
        if source_updated_at and issue_updated_at and source_updated_at != issue_updated_at:
            return True

        decision_resource_hash = str(cached_pack.get("decision_resource_hash") or "")
        return bool(decision_resource_hash and decision_resource_hash != resources_hash(self.app.config.resources))

    def _cached_pack_for_issue(self, issue) -> dict | None:
        try:
            return self._cache().get_pack(issue.repo, "issue", issue.number)
        except Exception:
            return None

    async def _fetch_from_github_and_score(self, repo: str) -> None:
        self._set_busy(f"  Updating {repo} from GitHub…")
        token = os.environ.get("GITHUB_TOKEN", "")
        issue_limit = _issue_limit_for_repo(self.app.config.watching, repo)
        issues = await asyncio.to_thread(
            lambda: __import__("osmind.github.client", fromlist=["GitHubClient"])
            .GitHubClient(token=token)
            .get_issues(repo, limit=issue_limit, include_comments=False)
        )
        cache = self._cache()
        for issue in issues:
            cache.upsert_issue(issue)
        self._show_issues(issues)
        self.query_one("#hint", Label).update(f"  {len(issues)} opportunities • ranking…")
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
                self._refresh_issue_table()

            hint = self.query_one("#hint", Label)
            hint.update(
                "  Enter: Detail  Space: Decide / Start Work  u: Update"
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
        self._issue_detail_request_id += 1
        request_id = self._issue_detail_request_id

        analysis = self.query_one("#issue-analysis-content", Static)
        source = self.query_one("#issue-source-content", Static)
        self._show_detail()
        self._set_breadcrumb(issue.repo, f"Issue #{issue.number}")
        analysis.update(_format_issue_analysis(issue, self.app.config.resources))
        source.update(_format_issue_source(issue, "正在生成 Issue Brief…"))
        self.query_one("#issue-source-panel", VerticalScroll).focus()

        loader = self.query_one("#loader", LoadingIndicator)
        loader.display = True
        try:
            from osmind.engine.issue_brief import render_issue_brief_markdown

            brief = await self._load_or_generate_issue_brief(issue)
            brief_markdown = render_issue_brief_markdown(brief)
            if self._is_current_issue_detail_request(request_id):
                source.update(_format_issue_source(issue, brief_markdown))
        except Exception as e:
            log_path = log_exception(
                self.app.config.notes_vault,
                f"Failed to generate Issue Brief for {issue.repo}#{issue.number}",
            )
            if self._is_current_issue_detail_request(request_id):
                source.update(_format_issue_source(issue, f"Issue Brief 生成失败，详情见 {log_path}"))
            self.notify(f"Issue Brief 生成失败: {e}", severity="warning")
        finally:
            loader.display = False

    def _is_current_issue_detail_request(self, request_id: int) -> bool:
        return (
            request_id == self._issue_detail_request_id
            and bool(self.query_one("#issue-detail-view").display)
        )

    def action_back_to_list(self) -> None:
        detail_view = self.query_one("#issue-detail-view")
        work_view = self.query_one("#start-work-view")
        if detail_view.display or work_view.display:
            self._show_list()
            self.query_one(IssueTable).focus()

    def _set_breadcrumb(self, *parts: str) -> None:
        try:
            crumb = self.query_one("#breadcrumb", Static)
        except NoMatches:
            return
        segments = ["Discover", *[p for p in parts if p]]
        crumb.update("  " + "  ›  ".join(segments))

    def _show_detail(self) -> None:
        self.query_one("#issue-list-view").display = False
        self.query_one("#issue-detail-view").display = True
        self.query_one("#start-work-view").display = False
        self.query_one(IssueTable).can_focus = False
        self.query_one("#repo-select", Select).can_focus = False
        self.query_one("#action-filter", Select).can_focus = False
        self.query_one("#issue-analysis-panel", VerticalScroll).can_focus = True
        self.query_one("#issue-source-panel", VerticalScroll).can_focus = True
        self.query_one("#hint", Label).update(
            "  Detail — Tab 在 Analysis / Source 间切换并滚动"
        )

    def _show_list(self) -> None:
        self._set_breadcrumb(self._selected_repo(notify=False) or "")
        self.query_one("#issue-list-view").display = True
        self.query_one("#issue-detail-view").display = False
        self.query_one("#start-work-view").display = False
        self.query_one(IssueTable).can_focus = True
        self.query_one("#repo-select", Select).can_focus = True
        self.query_one("#action-filter", Select).can_focus = True
        self.query_one("#issue-analysis-panel", VerticalScroll).can_focus = False
        self.query_one("#issue-source-panel", VerticalScroll).can_focus = False
        self.query_one("#start-work-panel", VerticalScroll).can_focus = False

    def action_toggle_detail_focus(self) -> None:
        detail_view = self.query_one("#issue-detail-view")
        if not detail_view.display:
            return
        analysis = self.query_one("#issue-analysis-panel", VerticalScroll)
        source = self.query_one("#issue-source-panel", VerticalScroll)
        if self.app.focused is source:
            analysis.focus()
        else:
            source.focus()

    def _library(self):
        from osmind.services.library import PackLibrary

        cache_path = self.app.config.notes_vault / "osmind" / ".cache" / "osmind.db"
        return PackLibrary(
            self.app.config.notes_vault,
            cache_path,
            resources=self.app.config.resources,
            repo_paths=_repo_paths_from_watching(self.app.config.watching),
        )

    def _cache(self):
        from osmind.cache.store import CacheStore

        cache_path = self.app.config.notes_vault / "osmind" / ".cache" / "osmind.db"
        return CacheStore(cache_path)

    def _issue_brief_profile_context(self):
        from osmind.engine.issue_brief import IssueBriefProfileContext

        return IssueBriefProfileContext(
            interests=list(self.app.config.interests),
            skills=list(self.app.config.skills),
            resources=dict(self.app.config.resources),
        )

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

    def _cached_issue_brief(self, issue):
        from osmind.engine.issue_brief import is_issue_brief_current, issue_brief_from_json

        cached_json = self._cache().get_issue_brief(issue.repo, issue.number)
        if not cached_json:
            return None
        try:
            brief = issue_brief_from_json(cached_json)
        except Exception:
            return None
        if not is_issue_brief_current(
            brief,
            issue,
            issue.reason,
            self._issue_brief_profile_context(),
        ):
            return None
        return brief

    async def _load_or_generate_issue_brief(self, issue):
        cached = self._cached_issue_brief(issue)
        if cached is not None:
            return cached

        pack_key = self._pack_key(issue)
        existing_task = self._issue_brief_tasks.get(pack_key)
        if existing_task is not None:
            return await existing_task

        def _generate():
            from osmind.engine.issue_brief import IssueBriefGenerator
            from osmind.engine.llm import LLMClient

            llm = LLMClient(self.app.config.llm)
            brief = IssueBriefGenerator(llm).generate(
                issue,
                reason=issue.reason,
                profile_context=self._issue_brief_profile_context(),
            )
            self._cache().update_issue_brief(issue.repo, issue.number, brief.to_json())
            return brief

        task = asyncio.create_task(asyncio.to_thread(_generate))
        self._issue_brief_tasks[pack_key] = task
        try:
            return await task
        finally:
            self._issue_brief_tasks.pop(pack_key, None)

    async def action_start_work(self) -> None:
        issue = self._get_selected_issue()
        if not issue:
            self.notify("先选中一个 issue", severity="warning")
            return
        try:
            pack_was_missing = self._pack_path_for_issue(issue) is None
            path = await self._set_issue_decision(issue, "continue")
            if pack_was_missing:
                self._update_freshness_status()
            markdown = path.read_text(encoding="utf-8")
            self.query_one("#start-work-content", Static).update(
                format_start_work_from_packet(markdown, self.app.config.resources)
            )
            self._show_start_work()
            self._set_breadcrumb(issue.repo, f"Issue #{issue.number}", "Start Work")
            if pack_was_missing:
                self.notify(
                    f"✓ Packet 已生成并标记 continue — 按 p 在 Packs 标签查看",
                    timeout=5,
                )
            else:
                self.notify("✓ 已进入 Start Work — 按 p 可在 Packs 标签管理", timeout=4)
        except Exception as e:
            log_path = log_exception(
                self.app.config.notes_vault,
                f"Failed to start work for {issue.repo}#{issue.number}",
            )
            self.notify(f"{e} (log: {log_path})", severity="error")

    def _show_start_work(self) -> None:
        self.query_one("#issue-list-view").display = False
        self.query_one("#issue-detail-view").display = False
        self.query_one("#start-work-view").display = True
        self.query_one(IssueTable).can_focus = False
        self.query_one("#repo-select", Select).can_focus = False
        self.query_one("#action-filter", Select).can_focus = False
        panel = self.query_one("#start-work-panel", VerticalScroll)
        panel.can_focus = True
        panel.focus()
        self.query_one("#hint", Label).update("  Start Work — packet 已就绪，按 p 到 Packs 打开")

    async def _set_issue_decision(self, issue, decision: str) -> Path:
        path = self._pack_path_for_issue(issue)
        brief = None
        try:
            brief = await self._load_or_generate_issue_brief(issue)
        except Exception:
            log_exception(
                self.app.config.notes_vault,
                f"Failed to generate Issue Brief before writing pack for {issue.repo}#{issue.number}",
            )
        if brief is not None or path is None:
            path = await asyncio.to_thread(lambda: self._library().write_issue_pack(issue, brief=brief))
            self._pack_paths_by_key[self._pack_key(issue)] = str(path)
        path = await asyncio.to_thread(
            lambda: self._library().set_pack_decision(
                issue.repo,
                "issue",
                issue.number,
                decision,
                decision_resource_hash=resources_hash(self.app.config.resources),
            )
        )
        self._pack_paths_by_key[self._pack_key(issue)] = str(path)
        return path

    async def action_generate_pack(self) -> None:
        issue = self._get_selected_issue()
        if not issue:
            self.notify("先选中一个 issue", severity="warning")
            return
        try:
            brief = None
            try:
                brief = await self._load_or_generate_issue_brief(issue)
            except Exception:
                log_exception(
                    self.app.config.notes_vault,
                    f"Failed to generate Issue Brief before writing pack for {issue.repo}#{issue.number}",
                )
            path = await asyncio.to_thread(lambda: self._library().write_issue_pack(issue, brief=brief))
            self._pack_paths_by_key[self._pack_key(issue)] = str(path)
            self.notify(f"Contribution Packet saved: {path}", timeout=5)
            self._update_freshness_status()
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

    async def action_decide(self) -> None:
        issue = self._get_selected_issue()
        if not issue:
            self.notify("先选中一个 issue", severity="warning")
            return
        async def handle_decision(decision: str | None) -> None:
            if decision == "continue":
                await self.action_start_work()
                return
            if decision not in {"defer", "discard"}:
                return
            await self._mark_issue_decision(issue, str(decision))

        self.app.push_screen(DecisionDialog(include_start_work=True), handle_decision)

    async def _mark_issue_decision(self, issue, decision: str) -> None:
        if decision not in {"defer", "discard"}:
            return
        try:
            path = await self._set_issue_decision(issue, decision)
            self.notify(f"Marked {decision}: {path}", timeout=5)
            self._refresh_issue_table(focus=True)
        except Exception as e:
            log_path = log_exception(
                self.app.config.notes_vault,
                f"Failed to mark Contribution Packet decision for {issue.repo}#{issue.number}",
            )
            self.notify(f"{e} (log: {log_path})", severity="error")

    async def _mark_selected_issue_decision(self, decision: str) -> None:
        issue = self._get_selected_issue()
        if not issue:
            self.notify("先选中一个 issue", severity="warning")
            return
        await self._mark_issue_decision(issue, decision)

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
        f"{format_decision_panel(issue, resources)}\n\n"
        f"[bold]继续/放弃判断[/bold]\n{criteria}"
    )


def _format_issue_source(issue, brief_markdown: str) -> str:
    labels = ", ".join(issue.labels) or "none"
    comments = "\n".join(
        f"- {comment.author}: {_plain_markdown_for_source(comment.body).strip()}"
        for comment in issue.comments[:5]
    ) or "- No cached comments."
    return (
        f"Issue #{issue.number}: {issue.title}\n"
        f"{issue.repo} | labels: {labels} | {issue.url}\n\n"
        f"{_plain_markdown_for_source(brief_markdown).rstrip()}\n\n"
        f"Original Issue\n{_plain_markdown_for_source(issue.body or '(empty)').strip()}\n\n"
        f"Comments\n{comments}"
    )


def _format_issue_detail(issue, brief_markdown: str, resources: dict | None = None) -> str:
    return f"{_format_issue_analysis(issue, resources)}\n\n{_format_issue_source(issue, brief_markdown)}"


def _format_github_fetch_error(repo: str, error: Exception, log_path: Path) -> str:
    text = f"{type(error).__name__}: {error}"
    lower = text.lower()
    if any(token in lower for token in ("ssl", "ssleoferror", "connection", "timeout", "max retries")):
        return (
            f"GitHub 网络/SSL 连接失败: {repo}。这通常不是 token 问题；"
            f"请检查代理/VPN/网络后重试。（log: {log_path}）"
        )
    if any(token in lower for token in ("badcredentials", "401", "requires authentication", "rate limit")):
        return f"GitHub 认证或限流失败: {repo}。请检查 GITHUB_TOKEN。（log: {log_path}）"
    return f"{error} (log: {log_path})"


def _plain_markdown_for_source(markdown: str) -> str:
    lines: list[str] = []
    in_code_block = False
    for raw_line in str(markdown or "").splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            lines.append(raw_line)
            continue
        if not in_code_block:
            heading = re.match(r"^\s*#{1,6}\s+(?P<title>.+?)\s*$", raw_line)
            if heading:
                if lines and lines[-1] != "":
                    lines.append("")
                lines.append(heading.group("title").strip())
                continue
        lines.append(raw_line)
    return "\n".join(lines).strip()


def _repo_paths_from_watching(watching: list[dict]) -> dict[str, Path]:
    repo_paths: dict[str, Path] = {}
    for entry in watching:
        repo = str(entry.get("repo") or "").strip()
        path = entry.get("path") or entry.get("local_path") or entry.get("checkout_path")
        if repo and path:
            repo_paths[repo] = Path(str(path)).expanduser()
    return repo_paths


def _issue_limit_for_repo(watching: list[dict], repo: str) -> int:
    for entry in watching:
        if str(entry.get("repo") or "").strip() != repo:
            continue
        try:
            limit = int(entry.get("issue_limit", DEFAULT_ISSUE_FETCH_LIMIT))
        except (TypeError, ValueError):
            return DEFAULT_ISSUE_FETCH_LIMIT
        return limit if limit > 0 else DEFAULT_ISSUE_FETCH_LIMIT
    return DEFAULT_ISSUE_FETCH_LIMIT


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
