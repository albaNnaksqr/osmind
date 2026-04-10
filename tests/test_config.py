import pytest
from pathlib import Path
from osmind.config import Config, ConfigError

SAMPLE = """
interests: [RL post-training, data synthesis]
skills: [Python]
resources:
  gpus: "4x RTX 4090"
  time: part-time
watching:
  - repo: THUDM/slime
notes_vault: ~/workspace/Note
llm:
  base_url: http://localhost:30000/v1
  model: test-model
  api_key: sk-test
external_agents:
  claude_code: claude
  codex: codex
"""

def test_load_valid_config(tmp_path):
    p = tmp_path / "profile.yaml"
    p.write_text(SAMPLE)
    cfg = Config.from_file(p)
    assert cfg.interests == ["RL post-training", "data synthesis"]
    assert cfg.skills == ["Python"]
    assert cfg.watching == [{"repo": "THUDM/slime"}]
    assert cfg.llm.base_url == "http://localhost:30000/v1"
    assert cfg.llm.model == "test-model"
    assert cfg.external_agents.claude_code == "claude"

def test_missing_required_field(tmp_path):
    p = tmp_path / "profile.yaml"
    # Use most of SAMPLE but omit watching
    content = """
interests: [foo]
skills: [Python]
resources: {}
notes_vault: ~/workspace/Note
llm:
  base_url: http://localhost:30000/v1
  model: test-model
  api_key: sk-test
external_agents:
  claude_code: claude
  codex: codex
"""
    p.write_text(content)
    with pytest.raises(ConfigError, match="watching"):
        Config.from_file(p)

def test_notes_vault_expanded(tmp_path):
    p = tmp_path / "profile.yaml"
    p.write_text(SAMPLE)
    cfg = Config.from_file(p)
    assert not str(cfg.notes_vault).startswith("~")
