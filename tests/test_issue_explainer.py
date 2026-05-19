from unittest.mock import MagicMock

from osmind.engine.issue_explainer import IssueExplainer
from osmind.github.models import GHComment, GHIssue


def test_issue_explainer_summarizes_issue_with_comments():
    llm = MagicMock()
    llm.chat.return_value = "这是一个模型适配问题，风险在测试覆盖。"
    issue = GHIssue(
        number=42,
        title="Add Qwen3MoE support",
        body="Need to add Qwen3MoE model support.",
        labels=["good first issue"],
        url="https://github.com/o/r/issues/42",
        repo="o/r",
        state="open",
        comments=[
            GHComment(
                author="maintainer",
                body="Please follow existing Qwen2 implementation.",
                url="https://github.com/o/r/issues/42#issuecomment-1",
                created_at="2026-05-15T02:03:04+00:00",
            )
        ],
    )

    summary = IssueExplainer(llm).summarize(issue)

    assert summary == "这是一个模型适配问题，风险在测试覆盖。"
    system, prompt = llm.chat.call_args.args
    assert "中文" in system
    assert "Add Qwen3MoE support" in prompt
    assert "good first issue" in prompt
    assert "maintainer: Please follow existing Qwen2 implementation." in prompt
