from datetime import date
from pathlib import Path

import pytest

from osmind.cache.store import CacheStore
from osmind.config import Config
from osmind.github.models import GHComment, GHIssue
from osmind.services.digest import run_digest
from osmind.services.radar import RadarError, RadarService


def make_issue(number, *, title="Fix tokenizer cache", body="body", labels=None, comments=None, updated_at="2026-06-01T00:00:00"):
    return GHIssue(
        number=number,
        title=title,
        body=body,
        labels=labels or ["bug"],
        url=f"https://github.com/sgl-project/sglang/issues/{number}",
        repo="sgl-project/sglang",
        state="open",
        updated_at=updated_at,
        comments=comments or [],
    )


def make_config(tmp_path, *, vault=None, resources=None, interests=None):
    return Config(
        interests=interests if interests is not None else ["sglang", "tokenizer"],
        skills=["python"],
        resources=resources if resources is not None else {"gpus": "1 x Spark"},
        watching=[{"repo": "sgl-project/sglang"}],
        notes_vault=tmp_path / "out",
        vault=vault,
    )


class FakeClient:
    def __init__(self, issues):
        self.issues = issues

    def get_issues(self, repo, state="open", limit=30, include_comments=False):
        return self.issues


@pytest.fixture
def store(tmp_path):
    return CacheStore(tmp_path / "cache.db")


def test_digest_requires_vault(tmp_path, store):
    config = make_config(tmp_path, vault=None)
    service = RadarService(config, store, FakeClient([make_issue(1)]))
    with pytest.raises(RadarError):
        run_digest(service)


def test_digest_writes_weekly_file_with_new_items(tmp_path, store):
    vault = tmp_path / "Note"
    config = make_config(tmp_path, vault=vault)
    service = RadarService(config, store, FakeClient([make_issue(1, title="Tokenizer cache leak")]))

    result = run_digest(service)
    path = Path(result["path"])
    assert path.exists()
    year, week, _ = date.today().isocalendar()
    assert path.name == f"{year}-W{week:02d}.md"

    text = path.read_text(encoding="utf-8")
    assert "# Issue Radar" in text
    assert "### 新增" in text
    assert "sgl-project/sglang#1 Tokenizer cache leak" in text
    assert "tokenizer" in text  # interest match surfaced
    assert "osmind show sgl-project/sglang#1" in text
    assert result["new"] == 1


def test_digest_surfaces_resurfaced_with_original_reason(tmp_path, store):
    vault = tmp_path / "Note"
    config = make_config(tmp_path, vault=vault)
    service = RadarService(config, store, FakeClient([make_issue(1)]))
    service.sync()
    service.decide("sgl-project/sglang", 1, "defer", "缺少复现步骤")

    comment = GHComment(author="maintainer", body="repro added", url="", created_at="2026-06-10")
    service._client.issues = [make_issue(1, comments=[comment], updated_at="2026-06-12T00:00:00")]

    result = run_digest(service)
    text = Path(result["path"]).read_text(encoding="utf-8")
    assert "### 复活" in text
    assert "缺少复现步骤" in text
    assert "content_changed" in text
    assert result["resurfaced"] == 1


def test_digest_rerun_same_day_replaces_section(tmp_path, store):
    vault = tmp_path / "Note"
    config = make_config(tmp_path, vault=vault)
    service = RadarService(config, store, FakeClient([make_issue(1)]))

    run_digest(service)
    service._client.issues = [make_issue(1), make_issue(2, title="Second issue")]
    result = run_digest(service)

    text = Path(result["path"]).read_text(encoding="utf-8")
    today = date.today().isoformat()
    assert text.count(f"## {today}") == 1
    assert "Second issue" in text


def test_digest_empty_sync_notes_no_changes(tmp_path, store):
    vault = tmp_path / "Note"
    config = make_config(tmp_path, vault=vault)
    service = RadarService(config, store, FakeClient([make_issue(1)]))
    service.sync()  # item already known
    service.decide("sgl-project/sglang", 1, "discard", "out of scope")

    result = run_digest(service)
    text = Path(result["path"]).read_text(encoding="utf-8")
    assert "无新增" in text
    assert result["new"] == 0
    assert result["resurfaced"] == 0
