import pytest
from unittest.mock import patch, MagicMock
from osmind.agents.launcher import AgentLauncher
from osmind.github.models import GHIssue


@pytest.fixture
def launcher():
    return AgentLauncher(claude_cmd="claude", codex_cmd="codex")


def test_build_claude_prompt_for_issue(launcher):
    issue = GHIssue(
        number=42, title="Add Qwen3MoE support",
        body="We need to support MoE models in the adapter.",
        labels=["good first issue"], url="https://github.com/x/y/issues/42",
        repo="sgl-project/sglang", state="open",
    )
    prompt = launcher._build_prompt(issue)
    assert "42" in prompt
    assert "Qwen3MoE" in prompt
    assert "sgl-project/sglang" in prompt


def test_launch_claude_calls_subprocess(launcher):
    issue = GHIssue(42, "Add Qwen3MoE", "Body", [], "u", "sgl-project/sglang", "open")
    with patch("osmind.agents.launcher.subprocess.Popen") as mock_popen:
        mock_popen.return_value = MagicMock()
        launcher.launch_claude(issue)
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        assert args[0] == "claude"
