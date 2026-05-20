from __future__ import annotations

import os
import shutil

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static


class SettingsScreen(Vertical):
    DEFAULT_CSS = """
    SettingsScreen #settings-health { height: 1fr; padding: 1 2; overflow-y: auto; }
    """
    BINDINGS = [
        ("u", "reload", "Reload"),
    ]

    def compose(self) -> ComposeResult:
        health = Static("", id="settings-health")
        health.can_focus = True
        yield health

    def on_mount(self) -> None:
        self.action_reload()

    def action_reload(self) -> None:
        self.query_one("#settings-health", Static).update(_format_health(self.app.config))


def _format_health(config) -> str:
    token = os.environ.get("GITHUB_TOKEN", "")
    vault = config.notes_vault
    cache_path = vault / "osmind" / ".cache" / "osmind.db"
    resources = _format_mapping(config.resources) if config.resources else "not configured"
    watching = ", ".join(repo["repo"] for repo in config.watching) if config.watching else "none"
    claude_status = _command_status(config.external_agents.claude_code)
    codex_status = _command_status(config.external_agents.codex)

    return "\n".join(
        [
            "[bold]Settings / Health[/bold]",
            "",
            f"GitHub token: {_status('OK' if token else 'Missing')} GITHUB_TOKEN",
            f"LLM: {_status('Configured' if config.llm.base_url and config.llm.model else 'Missing')} "
            f"{config.llm.model} @ {config.llm.base_url}",
            f"Notes vault: {_status('OK' if vault.exists() else 'Will create')} {vault}",
            f"Cache: {cache_path}",
            f"Resources: {resources}",
            f"Watching: {watching}",
            f"Claude Code: {claude_status}",
            f"Codex: {codex_status}",
            "",
            "[dim]u: reload health status[/dim]",
        ]
    )


def _status(label: str) -> str:
    if label in {"OK", "Configured"}:
        return f"[green]{label}[/green]"
    if label == "Will create":
        return f"[yellow]{label}[/yellow]"
    return f"[red]{label}[/red]"


def _command_status(command: str) -> str:
    return f"[green]found[/green] `{command}`" if shutil.which(command) else f"[yellow]not found[/yellow] `{command}`"


def _format_mapping(values: dict) -> str:
    return ", ".join(f"{key}: {value}" for key, value in values.items())
