from __future__ import annotations
from osmind.engine.llm import LLMClient
from osmind.github.models import GHPR

_SYSTEM = """\
You are a Socratic learning guide helping a developer understand a GitHub PR.
Ask ONE question in Chinese that makes them think — do not summarize or explain.
The question should probe WHY the code was changed, not just what changed.
Keep it under 60 words."""

_FOLLOWUP_SYSTEM = """\
You are a Socratic learning guide. Based on the conversation so far, ask ONE follow-up question in Chinese.
Dig deeper into the user's last answer. Do not repeat previous questions. Under 60 words."""


def _format_diff_summary(pr: GHPR) -> str:
    files = "\n".join(f"- {f.filename}" for f in pr.files[:8])
    sample_patch = pr.files[0].patch[:300] if pr.files else ""
    return f"PR #{pr.number}: {pr.title}\n\nFiles changed:\n{files}\n\nSample diff:\n{sample_patch}"


class SocraticEngine:
    def __init__(self, llm: LLMClient):
        self._llm = llm

    def first_question(self, pr: GHPR) -> str:
        return self._llm.chat(_SYSTEM, _format_diff_summary(pr), max_tokens=128)

    def followup(self, history: list[dict]) -> str:
        conv = "\n".join(
            f"{'osmind' if m['role'] == 'assistant' else '用户'}: {m['content']}"
            for m in history
        )
        return self._llm.chat(_FOLLOWUP_SYSTEM, conv, max_tokens=128)
