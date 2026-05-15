from __future__ import annotations

import os
import subprocess
from pathlib import Path


def open_path(path: Path, command: str | None = None) -> None:
    if command is not None:
        opener = command
    elif "EDITOR" in os.environ:
        opener = os.environ["EDITOR"]
    else:
        opener = "xdg-open"
    subprocess.run([opener, str(path)], check=False)
