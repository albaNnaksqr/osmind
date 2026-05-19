from __future__ import annotations

from osmind.engine.llm import LLMClient
from osmind.github.models import GHIssue


_SYSTEM = """\
你是一个帮助开发者判断开源 issue 是否值得投入的助手。
用中文总结 issue 的真实诉求、可能涉及的技术模块、适合切入的第一步、主要风险。
不要写空泛建议，不要超过 180 字。"""


class IssueExplainer:
    def __init__(self, llm: LLMClient):
        self._llm = llm

    def summarize(self, issue: GHIssue) -> str:
        prompt = _format_issue(issue)
        return self._llm.chat(_SYSTEM, prompt, max_tokens=256).strip()


def _format_issue(issue: GHIssue) -> str:
    comments = "\n".join(
        f"- {comment.author}: {comment.body[:500]}"
        for comment in issue.comments[:5]
    ) or "- No cached comments."
    labels = ", ".join(issue.labels) or "none"
    return (
        f"Repo: {issue.repo}\n"
        f"Issue #{issue.number}: {issue.title}\n"
        f"URL: {issue.url}\n"
        f"Labels: {labels}\n\n"
        f"Body:\n{issue.body[:2500] or '(empty)'}\n\n"
        f"Comments:\n{comments}\n\n"
        "请输出中文摘要："
    )
