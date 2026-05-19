from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from textual.app import App, SuspendNotSupported


@contextmanager
def suspend_if_supported(app: App) -> Iterator[None]:
    try:
        with app.suspend():
            yield
    except SuspendNotSupported:
        yield
