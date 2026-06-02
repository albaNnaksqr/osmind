from __future__ import annotations
import argparse
import os
from pathlib import Path
import shutil
import sys
import yaml

from textual.app import App, ComposeResult
from textual.containers import Center, Middle, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Header, Input, Static, TabbedContent, TabPane

from osmind.config import Config, ConfigError
from osmind.tui.screens.discover import DiscoverScreen
from osmind.tui.screens.packs import PacksScreen
from osmind.tui.screens.settings import SettingsScreen
from osmind.tui.widgets.issue_list import IssueTable


HELP_TEXT = """[b]Osmind — 快捷键与工作流[/b]

[b cyan]标签切换（任意界面可用）[/b cyan]
  [b]d[/b] Discover · [b]p[/b] Packs · [b]t[/b] Settings

[b cyan]Discover — 发现与决策[/b cyan]
  [b cyan]Enter[/b cyan]  查看详情（只读，生成 Issue Brief）
  [b yellow]Space[/b yellow]  决策，三选一：
          [b green]Start Work[/b green] 生成 Packet 并标记 continue
          Defer  暂时搁置 · Discard  丢弃
  [b]Tab[/b]    详情视图中在 Analysis / Source 两栏间切换并滚动
  [b]u[/b]      刷新 / 更新机会队列

[b cyan]Packs — 管理与打开[/b cyan]
  [b cyan]Enter[/b cyan] 阅读 Packet · [b blue]o[/b blue] 用外部程序打开 · [b yellow]Space[/b yellow] 决策

[b cyan]流向[/b cyan]
  Discover 按 [b yellow]Space[/b yellow] → [b green]Start Work[/b green] 生成 Packet → 在 [b]p[/b] Packs 打开/管理 → 交给 Codex / Claude / 编辑器继续

[b cyan]通用[/b cyan]
  [b]Esc[/b] / [b]q[/b] 返回上一层 · [b]?[/b] 帮助 · [b]Ctrl+Q[/b] 退出

[dim]按 Esc、? 或 q 关闭[/dim]"""


class HelpScreen(ModalScreen):
    DEFAULT_CSS = """
    HelpScreen { align: center middle; background: $background 60%; }
    HelpScreen #help-card {
        width: 72;
        max-width: 90%;
        height: auto;
        max-height: 90%;
        padding: 1 2;
        border: round $accent;
        background: $surface;
    }
    """
    BINDINGS = [
        ("escape", "dismiss", "Close"),
        ("question_mark", "dismiss", "Close"),
        ("q", "dismiss", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with Middle():
            with Center():
                with VerticalScroll(id="help-card"):
                    yield Static(HELP_TEXT)


class OsmindApp(App):
    CSS = """
    TabbedContent { height: 1fr; }
    """
    BINDINGS = [
        ("d", "switch_tab('discover')", "Discover"),
        ("p", "switch_tab('packs')", "Packs"),
        ("t", "switch_tab('settings')", "Settings"),
        ("question_mark", "help", "Help"),
        ("escape", "leave_input", "Back"),
        ("ctrl+q", "quit", "Quit"),
    ]

    def __init__(self, config: Config):
        super().__init__()
        self.config = config

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="discover"):
            with TabPane("Discover", id="discover"):
                yield DiscoverScreen()
            with TabPane("Packs", id="packs"):
                yield PacksScreen()
            with TabPane("Settings", id="settings"):
                yield SettingsScreen()
        yield Footer()

    def action_help(self) -> None:
        if isinstance(self.focused, Input):
            return
        if isinstance(self.screen, HelpScreen):
            return
        self.push_screen(HelpScreen())

    def action_switch_tab(self, tab: str) -> None:
        if tab not in {"discover", "packs", "settings"}:
            return
        self.query_one(TabbedContent).active = tab
        self._focus_active_tab_after_refresh(tab)

    def action_leave_input(self) -> None:
        if not isinstance(self.focused, Input):
            return

        active_tab = self.query_one(TabbedContent).active
        if active_tab == "discover":
            self.query_one(IssueTable).focus()
        elif active_tab == "packs":
            self.query_one("#packs-table", DataTable).focus()
        else:
            self.set_focus(None)

    def on_key(self, event) -> None:
        if event.key != "q" or isinstance(self.focused, Input):
            return
        if self._context_back():
            event.prevent_default()
            event.stop()

    def _context_back(self) -> bool:
        try:
            active_tab = self.query_one(TabbedContent).active
            if active_tab == "discover" and self._discover_back_if_open():
                return True
            if active_tab == "packs" and self._packs_back_if_open():
                return True
            return self._discover_back_if_open() or self._packs_back_if_open()
        except NoMatches:
            return False

    def _discover_back_if_open(self) -> bool:
        discover = self.query_one(DiscoverScreen)
        if (
            discover.query_one("#issue-detail-view").display
            or discover.query_one("#start-work-view").display
        ):
            discover.action_back_to_list()
            return True
        return False

    def _packs_back_if_open(self) -> bool:
        packs = self.query_one(PacksScreen)
        if (
            packs.query_one("#packet-reader-view").display
            or packs.query_one("#pack-start-work-view").display
        ):
            packs.action_back_to_list()
            return True
        return False

    def on_tabbed_content_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        if event.pane.id:
            self.call_after_refresh(lambda pane_id=event.pane.id: self._activate_tab_if_current(pane_id))

    def _activate_tab_if_current(self, tab: str) -> None:
        try:
            tabs = self.query_one(TabbedContent)
        except NoMatches:
            return
        if tabs.active != tab:
            return
        self._activate_tab(tab)

    def _activate_tab(self, tab: str) -> None:
        try:
            if tab == "packs":
                self.query_one(PacksScreen).action_reload()
            elif tab == "settings":
                self.query_one(SettingsScreen).action_reload()
            self._focus_active_tab(tab)
        except NoMatches:
            return

    def _focus_active_tab_after_refresh(self, tab: str) -> None:
        self.call_after_refresh(lambda: self._focus_active_tab(tab))

    def _focus_active_tab(self, tab: str) -> None:
        if tab == "discover":
            self.query_one(IssueTable).focus()
        elif tab == "packs":
            self.query_one("#packs-table", DataTable).focus()
        elif tab == "settings":
            self.query_one("#settings-health").focus()


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    profile_path = args.profile

    if args.command == "init":
        _run_init(profile_path)
        return
    if args.command == "doctor":
        _run_doctor(profile_path)
        return

    if not profile_path.exists():
        print("profile.yaml not found. Run `osmind init` to create it.")
        sys.exit(1)
    config = Config.from_file(profile_path)
    app = OsmindApp(config)
    app.run()


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="osmind")
    parser.add_argument("--profile", type=Path, default=Path("profile.yaml"), help="Path to profile.yaml")
    subparsers = parser.add_subparsers(dest="command")

    init_parser = subparsers.add_parser("init", help="Create a profile.yaml interactively")
    init_parser.add_argument("--profile", type=Path, default=argparse.SUPPRESS, help="Path to write")

    doctor_parser = subparsers.add_parser("doctor", help="Check profile and local runtime prerequisites")
    doctor_parser.add_argument("--profile", type=Path, default=argparse.SUPPRESS, help="Path to check")

    return parser.parse_args(argv)


def _run_init(profile_path: Path) -> None:
    if profile_path.exists():
        print(f"{profile_path} already exists; remove it or pass --profile to write elsewhere.")
        return

    interests = _prompt_csv("Interests (comma-separated)", ["open source", "systems"])
    skills = _prompt_csv("Skills (comma-separated)", ["Python"])
    resources = {
        "gpus": _prompt("GPUs/resources", "none"),
        "time": _prompt("Time budget", "part-time"),
    }
    watching = [{"repo": repo} for repo in _prompt_lines("Repositories to watch, one per line")]
    if not watching:
        watching = [{"repo": "owner/repo"}]

    output_dir = _prompt("Output dir", "~/workspace/osmind-packets")
    llm = {
        "base_url": _prompt("LLM base_url", "http://localhost:30000/v1"),
        "model": _prompt("LLM model", "Qwen3.5-27B"),
        "api_key": _prompt("LLM api_key", "placeholder"),
    }
    external_agents = {
        "claude_code": _prompt("Claude Code command", "claude"),
        "codex": _prompt("Codex command", "codex"),
    }

    profile = {
        "interests": interests,
        "skills": skills,
        "resources": resources,
        "watching": watching,
        "output_dir": output_dir,
        "llm": llm,
        "external_agents": external_agents,
    }
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(yaml.safe_dump(profile, sort_keys=False, allow_unicode=True))
    print(f"Wrote {profile_path}")
    print("Next: run `osmind doctor` to verify GitHub token, LLM config, and agent commands.")


def _run_doctor(profile_path: Path) -> None:
    if not profile_path.exists():
        print(f"Profile: Missing {profile_path}")
        print("Run `osmind init` to create a profile.")
        return

    try:
        config = Config.from_file(profile_path)
    except ConfigError as exc:
        print(f"Profile: Invalid {profile_path} ({exc})")
        return

    output_dir = config.output_dir or config.notes_vault
    print(f"Profile: OK {profile_path}")
    print(f"Output dir: {_plain_status('OK' if output_dir.exists() else 'Will create')} {output_dir}")
    print(f"GitHub token: {_plain_status('OK' if os.environ.get('GITHUB_TOKEN') else 'Missing')} GITHUB_TOKEN")
    print(
        f"LLM: {_plain_status('Configured' if config.llm.base_url and config.llm.model else 'Missing')} "
        f"{config.llm.model} @ {config.llm.base_url}"
    )
    print(f"Claude Code: {_plain_command_status(config.external_agents.claude_code)}")
    print(f"Codex: {_plain_command_status(config.external_agents.codex)}")


def _prompt(label: str, default: str) -> str:
    value = input(f"{label} [{default}]: ").strip()
    return value or default


def _prompt_csv(label: str, default: list[str]) -> list[str]:
    value = _prompt(label, ", ".join(default))
    return [item.strip() for item in value.split(",") if item.strip()]


def _prompt_lines(label: str) -> list[str]:
    print(f"{label}; submit an empty line when done:")
    values: list[str] = []
    while True:
        value = input("> ").strip()
        if not value:
            return values
        values.append(value)


def _plain_status(label: str) -> str:
    return label


def _plain_command_status(command: str) -> str:
    return f"found `{command}`" if shutil.which(command) else f"not found `{command}`"


if __name__ == "__main__":
    main()
