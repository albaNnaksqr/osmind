import pytest
from unittest.mock import MagicMock
from osmind.engine.ranker import Ranker
from osmind.github.models import GHIssue


@pytest.fixture
def ranker():
    mock_llm = MagicMock()
    mock_llm.chat.return_value = '{"score": 0.85, "reason": "涉及模型适配，与用户 SGLang 经验高度匹配"}'
    return Ranker(llm=mock_llm, interests=["model adaptation", "SGLang"], skills=["Python"])


def test_rank_single_issue(ranker):
    issue = GHIssue(
        number=42, title="Add Qwen3MoE support",
        body="We need to add Qwen3MoE model support.",
        labels=["good first issue"], url="https://github.com/x/y/issues/42",
        repo="x/y", state="open",
    )
    scored = ranker.rank([issue])
    assert len(scored) == 1
    assert scored[0].score == pytest.approx(0.85)


def test_ranker_scores_resource_fit_and_includes_resources_in_prompt():
    mock_llm = MagicMock()
    mock_llm.chat.return_value = (
        '{"score": 0.2, "priority": "low", "fit": "high", '
        '"resource_fit": "blocked", "actionability": "low", '
        '"reason": "主题匹配，但当前 GPU 资源不足以复现"}'
    )
    ranker = Ranker(
        llm=mock_llm,
        interests=["large model inference"],
        skills=["Python"],
        resources={"gpus": "4x RTX 4090", "time": "part-time"},
    )
    issue = GHIssue(
        number=7,
        title="DeepSeek V4Pro reproduction fails",
        body="Requires reproducing with the full model.",
        labels=["bug"],
        url="https://github.com/x/y/issues/7",
        repo="x/y",
        state="open",
    )

    scored = ranker.score_one(issue)

    prompt = mock_llm.chat.call_args.args[1]
    assert "User resources:" in prompt
    assert "gpus: 4x RTX 4090" in prompt
    assert scored.priority == "low"
    assert scored.fit == "high"
    assert scored.resource_fit == "blocked"
    assert scored.actionability == "low"
    assert scored.reason == "主题匹配，但当前 GPU 资源不足以复现"


def test_rank_sorts_by_score(ranker):
    def side_effect(system, user, **kwargs):
        if "Qwen3" in user:
            return '{"score": 0.9, "reason": "high match"}'
        return '{"score": 0.3, "reason": "low match"}'

    ranker._llm.chat.side_effect = side_effect

    issues = [
        GHIssue(1, "Refactor scheduler", "Internal refactor", [], "u", "r", "open"),
        GHIssue(2, "Add Qwen3MoE", "Model adapter needed", ["good first issue"], "u", "r", "open"),
    ]
    scored = ranker.rank(issues)
    assert scored[0].number == 2  # higher score first
    assert scored[0].score > scored[1].score
