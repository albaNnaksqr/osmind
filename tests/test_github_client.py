from datetime import datetime, timezone
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
    m.updated_at = datetime(2026, 5, 15, 1, 2, 3, tzinfo=timezone.utc)
    m.get_comments.return_value = []
    return m


def _make_mock_comment():
    m = MagicMock()
    m.user.login = "reviewer"
    m.body = "This issue is still active."
    m.html_url = "https://github.com/sgl-project/sglang/issues/42#issuecomment-1"
    m.created_at = datetime(2026, 5, 15, 2, 3, 4, tzinfo=timezone.utc)
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


def test_get_issues_includes_updated_at_and_up_to_five_comments(client):
    mock_issue = _make_mock_issue()
    mock_issue.get_comments.return_value = [_make_mock_comment() for _ in range(6)]

    mock_repo = MagicMock()
    mock_repo.get_issues.return_value = [mock_issue]
    client._gh.get_repo.return_value = mock_repo

    issues = client.get_issues("sgl-project/sglang", state="open", limit=10)

    assert issues[0].updated_at == "2026-05-15T01:02:03+00:00"
    assert len(issues[0].comments) == 5
    assert issues[0].comments[0].author == "reviewer"
    assert issues[0].comments[0].body == "This issue is still active."
    assert issues[0].comments[0].url.endswith("#issuecomment-1")
    assert issues[0].comments[0].created_at == "2026-05-15T02:03:04+00:00"


def test_get_pr_with_files(client):
    mock_file = MagicMock()
    mock_file.filename = "model/qwen3.py"
    mock_file.patch = "@@ -0,0 +1,10 @@\n+class Qwen3MoE:\n+    pass"
    mock_file.status = "modified"
    mock_file.additions = 10
    mock_file.deletions = 0

    mock_pr = MagicMock()
    mock_pr.number = 99
    mock_pr.title = "feat: add Qwen3MoE adapter"
    mock_pr.body = "Implements the MoE adapter."
    mock_pr.html_url = "https://github.com/sgl-project/sglang/pull/99"
    mock_pr.updated_at = datetime(2026, 5, 15, 3, 4, 5, tzinfo=timezone.utc)
    mock_pr.get_files.return_value = [mock_file]

    mock_repo = MagicMock()
    mock_repo.get_pull.return_value = mock_pr
    client._gh.get_repo.return_value = mock_repo

    pr = client.get_pr("sgl-project/sglang", 99)

    assert pr.number == 99
    assert len(pr.files) == 1
    assert pr.files[0].filename == "model/qwen3.py"
    assert "Qwen3MoE" in pr.files[0].patch


def test_get_pr_includes_updated_at_and_file_metadata(client):
    mock_file = MagicMock()
    mock_file.filename = "model/qwen3.py"
    mock_file.patch = "@@ -0,0 +1,10 @@\n+class Qwen3MoE:\n+    pass"
    mock_file.status = "modified"
    mock_file.additions = 10
    mock_file.deletions = 0

    mock_pr = MagicMock()
    mock_pr.number = 99
    mock_pr.title = "feat: add Qwen3MoE adapter"
    mock_pr.body = "Implements the MoE adapter."
    mock_pr.html_url = "https://github.com/sgl-project/sglang/pull/99"
    mock_pr.updated_at = datetime(2026, 5, 15, 3, 4, 5, tzinfo=timezone.utc)
    mock_pr.get_files.return_value = [mock_file]

    mock_repo = MagicMock()
    mock_repo.get_pull.return_value = mock_pr
    client._gh.get_repo.return_value = mock_repo

    pr = client.get_pr("sgl-project/sglang", 99)

    assert pr.updated_at == "2026-05-15T03:04:05+00:00"
    assert pr.files[0].status == "modified"
    assert pr.files[0].additions == 10
    assert pr.files[0].deletions == 0


def test_get_merged_prs_includes_updated_at(client):
    mock_pr = MagicMock()
    mock_pr.number = 99
    mock_pr.title = "feat: add Qwen3MoE adapter"
    mock_pr.body = "Implements the MoE adapter."
    mock_pr.html_url = "https://github.com/sgl-project/sglang/pull/99"
    mock_pr.updated_at = datetime(2026, 5, 15, 3, 4, 5, tzinfo=timezone.utc)
    mock_pr.merged = True

    mock_repo = MagicMock()
    mock_repo.get_pulls.return_value = [mock_pr]
    client._gh.get_repo.return_value = mock_repo

    prs = client.get_merged_prs("sgl-project/sglang", limit=10)

    assert prs[0].updated_at == "2026-05-15T03:04:05+00:00"
