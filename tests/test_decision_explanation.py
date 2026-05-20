from osmind.github.models import GHIssue
from osmind.decision import format_decision_markdown, format_decision_panel


def test_decision_panel_explains_resource_blocked_issue_with_evidence():
    issue = GHIssue(
        number=42,
        title="DeepSeek V4Pro reproduction fails",
        body="Requires full model reproduction and includes a traceback.",
        labels=["bug"],
        url="https://github.com/o/r/issues/42",
        repo="o/r",
        state="open",
        score=0.2,
        reason="主题匹配，但当前 GPU 资源不足以复现",
        priority="low",
        fit="high",
        resource_fit="blocked",
        actionability="low",
    )

    panel = format_decision_panel(issue, resources={"gpus": "4x RTX 4090"})

    assert "Recommendation" in panel
    assert "Action: Defer" in panel
    assert "Why: resource blocked" in panel
    assert "Next Step: Defer until the required environment is available." in panel
    assert "Decision Factors" in panel
    assert "Priority: Low" in panel
    assert "Fit: High" in panel
    assert "Resource Fit: Blocked" in panel
    assert "Actionability: Low" in panel
    assert "Configured Resources: gpus: 4x RTX 4090" in panel
    assert "Evidence" in panel
    assert "- LLM: 主题匹配，但当前 GPU 资源不足以复现" in panel
    assert "- Labels: bug" in panel
    assert "- Source: issue text mentions reproduction, error, or test clues." in panel


def test_decision_markdown_uses_same_snapshot_for_packets():
    issue = GHIssue(
        number=7,
        title="Tokenizer leak",
        body="No test command yet.",
        labels=["tokenizer"],
        url="https://github.com/o/r/issues/7",
        repo="o/r",
        state="open",
        score=0.8,
        reason="涉及 tokenizer cache，与用户的推理优化兴趣高度相关。",
        priority="high",
        fit="high",
        resource_fit="ok",
        actionability="medium",
    )

    markdown = format_decision_markdown(issue, resources={"gpus": "4x RTX 4090"})

    assert "| Action | Do now |" in markdown
    assert "| Why | strong fit + resources OK |" in markdown
    assert "| Resource Fit | OK |" in markdown
    assert "| Configured Resources | gpus: 4x RTX 4090 |" in markdown
    assert "- LLM: 涉及 tokenizer cache，与用户的推理优化兴趣高度相关。" in markdown
