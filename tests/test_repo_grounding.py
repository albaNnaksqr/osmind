from osmind.engine.repo_grounding import (
    extract_issue_terms,
    ground_issue_checkout,
    render_repo_first_steps,
    render_repo_grounding,
)
from osmind.github.models import GHIssue


def _issue(**kwargs) -> GHIssue:
    base = dict(
        number=26790,
        title="Bug: Qwen tool call parser returns empty tool_calls list",
        body="`qwen25` returns empty `tool_calls` for <tool_call><function=location>New York</function></tool_call>.",
        labels=["bug"],
        url="https://github.com/sgl-project/sglang/issues/26790",
        repo="sgl-project/sglang",
        state="open",
    )
    base.update(kwargs)
    return GHIssue(**base)


def test_extract_issue_terms_prefers_code_and_identifier_terms():
    terms = extract_issue_terms(_issue())

    assert "qwen25" in terms
    assert "tool_calls" in terms
    assert any(term.startswith("function") for term in terms)


def test_ground_issue_checkout_finds_source_tests_and_docs(tmp_path):
    repo = tmp_path / "sglang"
    source = repo / "python" / "sglang" / "srt"
    tests = repo / "test" / "srt"
    docs = repo / "docs"
    source.mkdir(parents=True)
    tests.mkdir(parents=True)
    docs.mkdir(parents=True)
    (source / "function_call_parser.py").write_text(
        "PARSER = 'qwen25'\n"
        "def parse_tool_calls(text):\n"
        "    return []\n",
        encoding="utf-8",
    )
    (tests / "test_function_call_parser.py").write_text(
        "def test_qwen25_tool_calls():\n"
        "    assert 'tool_calls'\n",
        encoding="utf-8",
    )
    (docs / "tool-calling.md").write_text("qwen25 tool_calls docs\n", encoding="utf-8")

    report = ground_issue_checkout(_issue(), repo)

    assert report.has_hits
    assert "python/sglang/srt/function_call_parser.py" in report.source_files
    assert "test/srt/test_function_call_parser.py" in report.test_files
    assert "docs/tool-calling.md" in report.doc_files
    assert "function_call_parser.py" in render_repo_grounding(report)
    assert "test_function_call_parser.py" in render_repo_first_steps(report)


def test_ground_issue_checkout_warns_when_path_missing(tmp_path):
    report = ground_issue_checkout(_issue(), tmp_path / "missing")

    assert not report.has_hits
    assert any("missing" in warning for warning in report.warnings)
