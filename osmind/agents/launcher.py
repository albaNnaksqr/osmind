from __future__ import annotations
import subprocess
from osmind.github.models import GHIssue

_PROMPT_TEMPLATE = """\
I want to contribute to {repo} by working on issue #{number}: "{title}"

Issue description:
{body}

Issue URL: {url}

Please help me understand this issue and implement a fix. Start by:
1. Exploring the relevant parts of the codebase
2. Explaining your understanding of what needs to be changed
3. Proposing an implementation approach before writing code
"""


class AgentLauncher:
    def __init__(self, claude_cmd: str, codex_cmd: str):
        self._claude = claude_cmd
        self._codex = codex_cmd

    def _build_prompt(self, issue: GHIssue) -> str:
        return _PROMPT_TEMPLATE.format(
            repo=issue.repo,
            number=issue.number,
            title=issue.title,
            body=issue.body[:800],
            url=issue.url,
        )

    def launch_claude(self, issue: GHIssue) -> subprocess.Popen:
        prompt = self._build_prompt(issue)
        return subprocess.Popen([self._claude, "--print", prompt])

    def launch_codex(self, issue: GHIssue) -> subprocess.Popen:
        prompt = self._build_prompt(issue)
        return subprocess.Popen([self._codex, prompt])
