from pathlib import Path

import pytest

from osmind.cache.store import CacheStore
from osmind.config import Config, LLMConfig
from osmind.github.models import GHIssue, IssueSignals
from osmind.services.radar import RadarService
from osmind.services.report import run_report


def make_issue(number, *, title="Fix cache", body="body", labels=None, updated_at="2026-06-10T00:00:00"):
    return GHIssue(
        number=number,
        title=title,
        body=body,
        labels=labels or ["bug"],
        url=f"https://github.com/sgl-project/sglang/issues/{number}",
        repo="sgl-project/sglang",
        state="open",
        updated_at=updated_at,
        comments=[],
    )


def make_config(tmp_path, with_llm=True):
    return Config(
        interests=["sglang"],
        skills=["python"],
        resources={"gpus": "1 x Spark"},
        watching=[{"repo": "sgl-project/sglang"}],
        notes_vault=tmp_path / "out",
        output_dir=tmp_path / "out",
        llm=LLMConfig(base_url="http://x/v1", model="m", api_key="k") if with_llm else None,
    )


class FakeClient:
    def __init__(self, issues, signals=None):
        self.issues = issues
        self._signals = signals or {}

    def get_issues(self, repo, state="open", limit=30, include_comments=False):
        return self.issues

    def issue_signals(self, repo, number):
        return self._signals.get(number, IssueSignals(number=number, labels=["bug"]))


@pytest.fixture
def store(tmp_path):
    return CacheStore(tmp_path / "cache.db")


def service_with(store, config, issues, signals=None):
    return RadarService(config, store, FakeClient(issues, signals))


def test_report_requires_llm(tmp_path, store):
    config = make_config(tmp_path, with_llm=False)
    service = service_with(store, config, [make_issue(1)])
    with pytest.raises(Exception):
        run_report(service, notify=False)


def test_report_writes_ranked_recommendations(tmp_path, store, monkeypatch):
    config = make_config(tmp_path)
    signals = {
        1: IssueSignals(number=1, labels=["bug"], assignees=[], comment_count=5, participant_count=3, linked_open_prs=[]),
        2: IssueSignals(number=2, labels=["feature"], assignees=["bob"], linked_open_prs=[99]),
    }
    service = service_with(store, config, [make_issue(1, title="Tokenizer leak"), make_issue(2, title="Add API")], signals)

    fake_reco = {
        "summary": "本周有一个高优 bug",
        "recommendations": [
            {"repo": "sgl-project/sglang", "number": 1, "priority": "high", "reason": "和 sglang 推理相关",
             "resource_note": "1 张卡够", "occupied": False, "serendipity": False},
            {"repo": "sgl-project/sglang", "number": 2, "priority": "low", "reason": "扩展眼界",
             "resource_note": "已被认领", "occupied": True, "serendipity": True},
        ],
    }
    monkeypatch.setattr("osmind.services.report.recommend", lambda llm, profile, candidates: _normalized(fake_reco, candidates))

    result = run_report(service, notify=False)
    assert result["recommendations"] == 2
    assert result["serendipity"] == 1
    assert result["llm_error"] is None

    text = Path(result["path"]).read_text(encoding="utf-8")
    assert "# 贡献推荐" in text
    assert "## 推荐贡献" in text
    assert "## 跳出兴趣（serendipity）" in text
    assert "[high]" in text
    assert "[已有人在做]" in text  # issue 2 occupied
    assert "Tokenizer leak" in text
    assert Path(result["path"]).parent.name == "reports"


def test_report_renders_skipped_summary(tmp_path, store, monkeypatch):
    config = make_config(tmp_path)
    service = service_with(
        store, config,
        [make_issue(1, title="Doable"), make_issue(2, title="Needs H20"), make_issue(3, title="Taken")],
    )

    fake_reco = {
        "recommendations": [
            {"repo": "sgl-project/sglang", "number": 1, "priority": "high", "reason": "r", "serendipity": False},
        ],
        "skipped": [
            {"repo": "sgl-project/sglang", "number": 2, "category": "resource"},
            {"repo": "sgl-project/sglang", "number": 3, "category": "occupied"},
        ],
    }
    monkeypatch.setattr("osmind.services.report.recommend", lambda llm, profile, candidates: _normalized(fake_reco, candidates))

    result = run_report(service, notify=False)
    text = Path(result["path"]).read_text(encoding="utf-8")
    assert "## 已跳过（2）" in text
    assert "需要你没有的硬件/资源（1）: sgl-project/sglang#2" in text
    assert "已有人在做（1）: sgl-project/sglang#3" in text
    # skipped items must NOT get full recommendation cards
    assert "### " in text and "Needs H20" not in text.split("## 已跳过")[0]


def test_balanced_candidates_round_robins_repos():
    from osmind.services.report import _balanced_candidates

    items = [{"repo": "a/x", "number": n, "updated_at": f"2026-06-{n:02d}"} for n in range(1, 21)]
    items += [{"repo": "b/y", "number": n, "updated_at": f"2026-06-{n:02d}"} for n in (1, 2, 3)]
    picked = _balanced_candidates(items, cap=10)
    repos = {p["repo"] for p in picked}
    assert repos == {"a/x", "b/y"}  # quiet repo not crowded out
    assert sum(1 for p in picked if p["repo"] == "b/y") == 3  # all of the quiet repo's items present


def test_report_degrades_on_llm_failure(tmp_path, store, monkeypatch):
    from osmind.llm import LLMError

    config = make_config(tmp_path)
    service = service_with(store, config, [make_issue(1, title="Tokenizer leak")])

    def boom(llm, profile, candidates):
        raise LLMError("endpoint down")

    monkeypatch.setattr("osmind.services.report.recommend", boom)

    result = run_report(service, notify=False)
    assert result["llm_error"] == "endpoint down"
    text = Path(result["path"]).read_text(encoding="utf-8")
    assert "判断失败" in text
    assert "Tokenizer leak" in text  # raw candidates still listed


def test_report_excludes_discarded_unchanged_items(tmp_path, store, monkeypatch):
    config = make_config(tmp_path)
    service = service_with(store, config, [make_issue(1), make_issue(2)])
    service.sync()
    service.decide("sgl-project/sglang", 1, "discard", "out of scope")

    captured = {}
    monkeypatch.setattr(
        "osmind.services.report.recommend",
        lambda llm, profile, candidates: captured.update(c=candidates) or {"summary": "", "recommendations": [], "serendipity_count": 0},
    )
    run_report(service, notify=False)
    numbers = {c["number"] for c in captured["c"]}
    assert numbers == {2}  # discarded #1 is gone from candidates


def _normalized(raw, candidates):
    from osmind.services.recommend import _normalize
    return _normalize(raw, candidates)
