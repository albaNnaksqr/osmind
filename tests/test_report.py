from pathlib import Path

import pytest

from osmind.config import Config, LLMConfig
from osmind.github.models import GHIssue
from osmind.services.report import ReportError, run_report
from osmind.services.recommend import _normalize


def make_issue(number, *, repo="sgl-project/sglang", title="Fix cache", body="body", labels=None,
               assignees=None, comment_count=0, updated_at="2026-06-10T00:00:00"):
    return GHIssue(
        number=number, title=title, body=body, labels=labels or ["bug"],
        url=f"https://github.com/{repo}/issues/{number}", repo=repo, state="open",
        updated_at=updated_at, assignees=assignees or [], comment_count=comment_count,
    )


def make_config(tmp_path, with_llm=True, watching=None):
    return Config(
        interests=["sglang"], skills=["python"], resources={"gpus": "1 x Spark"},
        watching=watching or [{"repo": "sgl-project/sglang"}],
        notes_vault=tmp_path / "out", output_dir=tmp_path / "out",
        llm=LLMConfig(base_url="http://x/v1", model="m", api_key="k") if with_llm else None,
    )


class FakeClient:
    def __init__(self, issues_by_repo, linked=None, fail_repos=None):
        self.issues_by_repo = issues_by_repo
        self.linked = linked or {}
        self.fail_repos = fail_repos or set()

    def get_issues(self, repo, state="open", limit=30, include_comments=False):
        if repo in self.fail_repos:
            raise RuntimeError("403 API rate limit exceeded")
        return self.issues_by_repo.get(repo, [])

    def linked_open_prs(self, repo, number):
        return self.linked.get(number, [])


def _reco(raw):
    return lambda llm, profile, candidates: _normalize(raw, candidates)


def test_report_requires_llm(tmp_path):
    config = make_config(tmp_path, with_llm=False)
    client = FakeClient({"sgl-project/sglang": [make_issue(1)]})
    with pytest.raises(ReportError):
        run_report(config, client, notify=False)


def test_report_writes_ranked_recommendations(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    client = FakeClient(
        {"sgl-project/sglang": [make_issue(1, title="Tokenizer leak"), make_issue(2, title="Add API", assignees=["bob"])]},
        linked={2: [99]},
    )
    raw = {
        "summary": "ignored",
        "recommendations": [
            {"repo": "sgl-project/sglang", "number": 1, "priority": "high", "reason": "相关", "resource_note": "够", "serendipity": False},
            {"repo": "sgl-project/sglang", "number": 2, "priority": "low", "reason": "扩展", "resource_note": "已占", "occupied": True, "serendipity": True},
        ],
    }
    monkeypatch.setattr("osmind.services.report.recommend", _reco(raw))

    result = run_report(config, client, notify=False)
    assert result["recommendations"] == 2
    assert result["serendipity"] == 1
    text = Path(result["path"]).read_text(encoding="utf-8")
    assert "## 推荐贡献" in text
    assert "## 跳出兴趣（serendipity）" in text
    assert "[已有人在做]" in text
    assert "Tokenizer leak" in text
    assert Path(result["path"]).parent.name == "reports"


def test_report_renders_skipped_summary(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    client = FakeClient({"sgl-project/sglang": [make_issue(1), make_issue(2), make_issue(3)]})
    raw = {
        "recommendations": [{"repo": "sgl-project/sglang", "number": 1, "priority": "high", "reason": "r", "serendipity": False}],
        "skipped": [
            {"repo": "sgl-project/sglang", "number": 2, "category": "resource"},
            {"repo": "sgl-project/sglang", "number": 3, "category": "occupied"},
        ],
    }
    monkeypatch.setattr("osmind.services.report.recommend", _reco(raw))
    result = run_report(config, client, notify=False)
    text = Path(result["path"]).read_text(encoding="utf-8")
    assert "## 已跳过（2）" in text
    assert "需要你没有的硬件/资源（1）: sgl-project/sglang#2" in text


def test_deterministic_summary_replaces_llm_summary(tmp_path, monkeypatch):
    config = make_config(tmp_path)
    client = FakeClient({"sgl-project/sglang": [make_issue(1, title="A")]})
    raw = {
        "summary": "含 iatrogenic 项",
        "recommendations": [{"repo": "sgl-project/sglang", "number": 1, "priority": "high", "reason": "r", "serendipity": False}],
    }
    monkeypatch.setattr("osmind.services.report.recommend", _reco(raw))
    result = run_report(config, client, notify=False)
    text = Path(result["path"]).read_text(encoding="utf-8")
    assert "iatrogenic" not in text
    assert "推荐 1 条 · serendipity 0 条 · 跳过 0 条" in text


def test_report_degrades_on_llm_failure(tmp_path, monkeypatch):
    from osmind.llm import LLMError

    config = make_config(tmp_path)
    client = FakeClient({"sgl-project/sglang": [make_issue(1, title="Tokenizer leak")]})

    def boom(llm, profile, candidates):
        raise LLMError("endpoint down")

    monkeypatch.setattr("osmind.services.report.recommend", boom)
    result = run_report(config, client, notify=False)
    assert result["llm_error"] == "endpoint down"
    text = Path(result["path"]).read_text(encoding="utf-8")
    assert "判断失败" in text
    assert "Tokenizer leak" in text


def test_report_skips_failed_repo_but_continues(tmp_path, monkeypatch):
    config = make_config(tmp_path, watching=[{"repo": "sgl-project/sglang"}, {"repo": "THUDM/slime"}])
    client = FakeClient(
        {"sgl-project/sglang": [make_issue(1, title="Doable")]},
        fail_repos={"THUDM/slime"},
    )
    monkeypatch.setattr("osmind.services.report.recommend", _reco({"recommendations": [], "skipped": []}))
    result = run_report(config, client, notify=False)
    text = Path(result["path"]).read_text(encoding="utf-8")
    assert "⚠️ 抓取失败 THUDM/slime" in text


def test_report_raises_when_all_repos_fail(tmp_path):
    config = make_config(tmp_path)
    client = FakeClient({}, fail_repos={"sgl-project/sglang"})
    with pytest.raises(ReportError, match="all repo fetches failed"):
        run_report(config, client, notify=False)


def test_report_balances_across_repos(tmp_path, monkeypatch):
    config = make_config(tmp_path, watching=[{"repo": "a/x"}, {"repo": "b/y"}])
    busy = [make_issue(n, repo="a/x", updated_at=f"2026-06-{n:02d}") for n in range(1, 21)]
    quiet = [make_issue(n, repo="b/y", updated_at=f"2026-06-{n:02d}") for n in (1, 2, 3)]
    client = FakeClient({"a/x": busy, "b/y": quiet})

    captured = {}
    monkeypatch.setattr(
        "osmind.services.report.recommend",
        lambda llm, profile, candidates: captured.update(c=candidates) or {"recommendations": [], "skipped": {}, "serendipity_count": 0, "skipped_count": 0},
    )
    run_report(config, client, notify=False)
    repos = {c["repo"] for c in captured["c"]}
    assert repos == {"a/x", "b/y"}  # quiet repo not crowded out
    assert sum(1 for c in captured["c"] if c["repo"] == "b/y") == 3
