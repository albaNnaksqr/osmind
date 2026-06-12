from pathlib import Path

import pytest

from osmind.cache.store import CacheStore
from osmind.config import Config
from osmind.github.models import GHComment, GHIssue
from osmind.services.radar import RadarError, RadarService, parse_item_ref


def make_issue(number: int, *, title: str = "Fix tokenizer cache", body: str = "body", labels=None, comments=None, updated_at: str = "2026-06-01T00:00:00") -> GHIssue:
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


def make_config(tmp_path: Path, resources=None, vault=None) -> Config:
    return Config(
        interests=["sglang"],
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


def service_with(store, config, issues=None):
    return RadarService(config, store, FakeClient(issues or []))


def test_sync_reports_new_changed_unchanged(tmp_path, store):
    config = make_config(tmp_path)
    service = service_with(store, config, issues=[make_issue(1), make_issue(2)])
    first = service.sync()
    assert first["repos"][0]["new"] == [1, 2]

    service._client.issues = [make_issue(1), make_issue(2, body="edited body")]
    second = service.sync()
    repo_summary = second["repos"][0]
    assert repo_summary["new"] == []
    assert repo_summary["changed"] == [2]
    assert repo_summary["unchanged"] == 1


def test_queue_marks_undecided_and_continue(tmp_path, store):
    config = make_config(tmp_path)
    service = service_with(store, config, issues=[make_issue(1), make_issue(2)])
    service.sync()
    service.decide("sgl-project/sglang", 1, "continue", "worth doing")

    statuses = {item["number"]: item["status"] for item in service.queue("active")}
    assert statuses == {1: "continue", 2: "undecided"}


def test_deferred_item_leaves_active_queue(tmp_path, store):
    config = make_config(tmp_path)
    service = service_with(store, config, issues=[make_issue(1)])
    service.sync()
    service.decide("sgl-project/sglang", 1, "defer", "no H20 cluster")

    assert service.queue("active") == []
    deferred = service.queue("deferred")
    assert deferred[0]["decision"]["reason"] == "no H20 cluster"


def test_content_change_resurfaces_deferred_item(tmp_path, store):
    config = make_config(tmp_path)
    service = service_with(store, config, issues=[make_issue(1)])
    service.sync()
    service.decide("sgl-project/sglang", 1, "defer", "missing repro")

    comment = GHComment(author="maintainer", body="repro added", url="", created_at="2026-06-10")
    service._client.issues = [make_issue(1, comments=[comment], updated_at="2026-06-10T00:00:00")]
    service.sync()

    items = service.queue("active")
    assert len(items) == 1
    assert items[0]["status"] == "resurfaced"
    assert items[0]["resurfaced_because"] == ["content_changed"]


def test_resource_change_resurfaces_discarded_item(tmp_path, store):
    config = make_config(tmp_path)
    service = service_with(store, config, issues=[make_issue(1)])
    service.sync()
    service.decide("sgl-project/sglang", 1, "discard", "needs 8 GPUs")

    richer = make_config(tmp_path, resources={"gpus": "8 x H100"})
    later = RadarService(richer, store, None)
    items = later.queue("active")
    assert items[0]["status"] == "resurfaced"
    assert items[0]["resurfaced_because"] == ["resources_changed"]


def test_show_includes_body_comments_and_decision_log(tmp_path, store):
    config = make_config(tmp_path)
    comment = GHComment(author="alice", body="same here", url="", created_at="2026-06-02")
    service = service_with(store, config, issues=[make_issue(1, comments=[comment])])
    service.sync()
    service.decide("sgl-project/sglang", 1, "defer", "wait for repro")
    service.decide("sgl-project/sglang", 1, "continue", "repro confirmed")

    shown = service.show("sgl-project/sglang", 1)
    assert shown["body"] == "body"
    assert shown["comments"][0]["author"] == "alice"
    assert [entry["decision"] for entry in shown["decision_log"]] == ["defer", "continue"]
    assert shown["status"] == "continue"


def test_decide_validates_input(tmp_path, store):
    config = make_config(tmp_path)
    service = service_with(store, config, issues=[make_issue(1)])
    service.sync()

    with pytest.raises(RadarError):
        service.decide("sgl-project/sglang", 1, "maybe", "reason")
    with pytest.raises(RadarError):
        service.decide("sgl-project/sglang", 1, "defer", "   ")
    with pytest.raises(RadarError):
        service.decide("sgl-project/sglang", 999, "defer", "not synced")


def test_decide_mirrors_to_vault_log(tmp_path, store):
    vault = tmp_path / "Note"
    config = make_config(tmp_path, vault=vault)
    service = service_with(store, config, issues=[make_issue(1)])
    service.sync()

    result = service.decide("sgl-project/sglang", 1, "defer", "需要 H20 集群")
    log_path = vault / "Sources" / "Issue_Radar" / "Decision_Log.md"
    assert result["mirrored_to"] == str(log_path)
    text = log_path.read_text(encoding="utf-8")
    assert text.startswith("# Issue Radar Decision Log")
    assert "sgl-project/sglang#1 → defer — 需要 H20 集群" in text

    service.decide("sgl-project/sglang", 1, "continue", "repro landed")
    text = log_path.read_text(encoding="utf-8")
    assert text.count("# Issue Radar Decision Log") == 1
    assert "→ continue — repro landed" in text


def test_decide_without_vault_skips_mirror(tmp_path, store):
    config = make_config(tmp_path)
    service = service_with(store, config, issues=[make_issue(1)])
    service.sync()
    result = service.decide("sgl-project/sglang", 1, "defer", "later")
    assert result["mirrored_to"] is None


def test_legacy_pack_decisions_seed_decision_history(tmp_path):
    db_path = tmp_path / "cache.db"
    legacy = CacheStore(db_path)
    issue = make_issue(7)
    legacy.upsert_issue(issue)
    legacy.upsert_pack(
        "sgl-project/sglang", "issue", 7, tmp_path / "pack.md", "inspecting", "low", issue.updated_at, decision="defer"
    )
    legacy._conn.execute("DROP TABLE decisions")
    legacy._conn.commit()

    reopened = CacheStore(db_path)
    log = reopened.decision_log("sgl-project/sglang", "issue", 7)
    assert len(log) == 1
    assert log[0]["decision"] == "defer"
    assert log[0]["reason"] == "migrated from contribution packet"

    config = make_config(tmp_path)
    service = RadarService(config, reopened, None)
    items = service.queue("all")
    assert items[0]["status"] == "deferred"


def test_parse_item_ref():
    assert parse_item_ref("sgl-project/sglang#42") == ("sgl-project/sglang", 42)
    for bad in ("sglang#42", "sgl-project/sglang", "sgl-project/sglang#x"):
        with pytest.raises(RadarError):
            parse_item_ref(bad)
