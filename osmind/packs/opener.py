from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path


def open_path(path: Path, command: str | None = None) -> None:
    if command is not None:
        opener_args = shlex.split(command)
    elif os.environ.get("EDITOR"):
        opener_args = shlex.split(os.environ["EDITOR"])
    else:
        opener_args = ["xdg-open"]
    if not opener_args:
        opener_args = ["xdg-open"]
    subprocess.run([*opener_args, str(path)], check=False)
