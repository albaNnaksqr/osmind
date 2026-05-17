from __future__ import annotations


def test_log_exception_writes_traceback(tmp_path):
    from osmind.logs import log_exception

    try:
        raise RuntimeError("no connected db")
    except RuntimeError:
        log_path = log_exception(tmp_path, "fetch failed")

    text = log_path.read_text(encoding="utf-8")
    assert "fetch failed" in text
    assert "RuntimeError: no connected db" in text
