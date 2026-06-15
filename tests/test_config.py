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


def test_output_dir_is_preferred_and_notes_vault_remains_compatible(tmp_path):
    p = tmp_path / "profile.yaml"
    output_dir = tmp_path / "out"
    p.write_text(SAMPLE.replace("notes_vault: ~/workspace/Note", f"output_dir: {output_dir}"))

    cfg = Config.from_file(p)

    assert cfg.output_dir == output_dir
    assert cfg.notes_vault == output_dir


def test_legacy_notes_vault_sets_output_dir(tmp_path):
    p = tmp_path / "profile.yaml"
    p.write_text(SAMPLE)

    cfg = Config.from_file(p)

    assert cfg.output_dir == cfg.notes_vault


def test_llm_and_external_agents_are_optional(tmp_path):
    p = tmp_path / "profile.yaml"
    p.write_text(
        "interests: [foo]\n"
        "skills: [Python]\n"
        "watching:\n"
        "  - repo: THUDM/slime\n"
        f"output_dir: {tmp_path / 'out'}\n"
    )

    cfg = Config.from_file(p)

    assert cfg.llm is None
    assert cfg.external_agents is None


def test_vault_field_is_parsed_and_expanded(tmp_path):
    p = tmp_path / "profile.yaml"
    p.write_text(SAMPLE.replace("notes_vault: ~/workspace/Note", "output_dir: ~/out\nvault: ~/workspace/Note"))

    cfg = Config.from_file(p)

    assert cfg.vault is not None
    assert not str(cfg.vault).startswith("~")
    assert cfg.vault.name == "Note"


def test_vault_defaults_to_none(tmp_path):
    p = tmp_path / "profile.yaml"
    p.write_text(SAMPLE)

    cfg = Config.from_file(p)

    assert cfg.vault is None
