import pytest
from unittest.mock import MagicMock, patch
from osmind.github.client import GitHubClient
from osmind.github.models import GHIssue, GHPR, PRFile


@pytest.fixture
def client():
    with patch("osmind.github.client.Github") as mock_gh:
        c = GitHubClient(token="fake-token")
        c._gh = mock_gh.return_value
        return c


def _make_mock_issue():
    m = MagicMock()
    m.number = 42
    m.title = "Add Qwen3MoE support"
    m.body = "We need Qwen3MoE support."
    m.labels = [MagicMock(name="good first issue")]
    m.html_url = "https://github.com/sgl-project/sglang/issues/42"
    m.state = "open"
    return m


def test_get_issues_returns_list(client):
    mock_repo = MagicMock()
    mock_repo.get_issues.return_value = [_make_mock_issue()]
    client._gh.get_repo.return_value = mock_repo

    issues = client.get_issues("sgl-project/sglang", state="open", limit=10)

    assert len(issues) == 1
    assert issues[0].number == 42
    assert issues[0].title == "Add Qwen3MoE support"
    assert issues[0].repo == "sgl-project/sglang"


def test_get_pr_with_files(client):
    mock_file = MagicMock()
    mock_file.filename = "model/qwen3.py"
    mock_file.patch = "@@ -0,0 +1,10 @@\n+class Qwen3MoE:\n+    pass"

    mock_pr = MagicMock()
    mock_pr.number = 99
    mock_pr.title = "feat: add Qwen3MoE adapter"
    mock_pr.body = "Implements the MoE adapter."
    mock_pr.html_url = "https://github.com/sgl-project/sglang/pull/99"
    mock_pr.get_files.return_value = [mock_file]

    mock_repo = MagicMock()
    mock_repo.get_pull.return_value = mock_pr
    client._gh.get_repo.return_value = mock_repo

    pr = client.get_pr("sgl-project/sglang", 99)

    assert pr.number == 99
    assert len(pr.files) == 1
    assert pr.files[0].filename == "model/qwen3.py"
    assert "Qwen3MoE" in pr.files[0].patch
