from __future__ import annotations

import shutil
import subprocess


def macos_notify(title: str, message: str, subtitle: str = "") -> bool:
    """Best-effort macOS notification. Returns True if dispatched, False otherwise."""
    if not shutil.which("osascript"):
        return False
    script = f'display notification {_quote(message)} with title {_quote(title)}'
    if subtitle:
        script += f' subtitle {_quote(subtitle)}'
    try:
        subprocess.run(["osascript", "-e", script], check=True, capture_output=True, timeout=10)
        return True
    except (subprocess.SubprocessError, OSError):
        return False


def _quote(text: str) -> str:
    # AppleScript string literal: wrap in quotes, escape backslash and quote.
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
