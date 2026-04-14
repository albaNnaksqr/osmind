from __future__ import annotations
from osmind.engine.llm import LLMClient
from osmind.github.models import GHPR

_SYSTEM = """\
你是一个帮助开发者理解 GitHub PR 的 Socratic 学习引导者。
直接用中文提出一个问题，不要解释，不要总结。
问题应该探究代码为什么这样改，而不只是改了什么。
不超过60字。直接输出问题，不要有任何前缀。"""

_FOLLOWUP_SYSTEM = """\
你是一个 Socratic 学习引导者。根据对话内容，用中文提一个追问。
深入挖掘用户上一个回答，不要重复之前的问题。不超过60字。直接输出问题。"""


def _format_diff_summary(pr: GHPR) -> str:
    files = "\n".join(f"- {f.filename}" for f in pr.files[:8])
    sample_patch = pr.files[0].patch[:400] if pr.files else ""
    return (
        f"PR #{pr.number}: {pr.title}\n\n"
        f"改动文件：\n{files}\n\n"
        f"diff 片段：\n{sample_patch}\n\n"
        f"请直接提出你的 Socratic 问题："
    )


def _clean(line: str) -> str:
    """Remove leading numbering, quotes, asterisks from a line."""
    import re
    line = re.sub(r'^\d+\.\s*', '', line)   # strip "1. " "2. "
    line = line.strip('"\'""')               # strip surrounding quotes
    line = line.strip('*')                   # strip markdown bold
    return line.strip()


def _extract_question(raw: str) -> str:
    """Extract the actual Socratic question from model output.

    Models often prepend analysis blocks; the real question is typically
    the last paragraph containing a Chinese question mark ？.
    """
    # Strip markdown bold markers and common prefixes
    text = raw.replace("**Socratic Question:**", "").replace("**问题：**", "")
    text = text.replace("**Socratic 问题：**", "").replace("<analysis>", "").replace("</analysis>", "")

    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]

    # Prefer the last line containing a Chinese ？ — that's the actual question
    for line in reversed(lines):
        if "\uff1f" in line:  # Chinese ？
            return _clean(line)

    # Fallback: last line containing ASCII ?
    for line in reversed(lines):
        if "?" in line:
            return line

    # Final fallback: last non-empty line
    return lines[-1] if lines else raw.strip()


class SocraticEngine:
    def __init__(self, llm: LLMClient):
        self._llm = llm

    def first_question(self, pr: GHPR) -> str:
        raw = self._llm.chat(_SYSTEM, _format_diff_summary(pr), max_tokens=512)
        return _extract_question(raw)

    def followup(self, history: list[dict]) -> str:
        conv = "\n".join(
            f"{'osmind' if m['role'] == 'assistant' else '用户'}: {m['content']}"
            for m in history
        )
        raw = self._llm.chat(_FOLLOWUP_SYSTEM, conv + "\n\n请直接提出你的追问：", max_tokens=512)
        return _extract_question(raw)
