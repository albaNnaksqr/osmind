from pathlib import Path

from osmind.tui import app as app_module


def test_main_init_writes_profile_with_output_dir(tmp_path, monkeypatch):
    profile = tmp_path / "profile.yaml"
    output_dir = tmp_path / "packets"
    inputs = iter(
        [
            "RL post-training, SGLang",
            "Python, distributed systems",
            "4x RTX 4090",
            "part-time",
            "sgl-project/sglang",
            "",
            str(output_dir),
            "http://localhost:30000/v1",
            "Qwen3.5-27B",
            "placeholder",
            "claude",
            "codex",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda *_: next(inputs))

    app_module.main(["init", "--profile", str(profile)])

    text = profile.read_text()
    assert "output_dir:" in text
    assert "notes_vault:" not in text
    assert "sgl-project/sglang" in text


def test_main_doctor_reports_profile_and_runtime_status(tmp_path, monkeypatch, capsys):
    profile = tmp_path / "profile.yaml"
    profile.write_text(
        "\n".join(
            [
                "interests: [SGLang]",
                "skills: [Python]",
                "resources:",
                "  gpus: 4x RTX 4090",
                "watching:",
                "  - repo: sgl-project/sglang",
                f"output_dir: {tmp_path / 'out'}",
                "llm:",
                "  base_url: http://localhost:30000/v1",
                "  model: test-model",
                "  api_key: placeholder",
                "external_agents:",
                "  claude_code: definitely-missing-claude",
                "  codex: definitely-missing-codex",
                "",
            ]
        )
    )
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    app_module.main(["doctor", "--profile", str(profile)])

    output = capsys.readouterr().out
    assert "Profile: OK" in output
    assert "Output dir:" in output
    assert "GitHub token: Missing" in output
    assert "LLM: Configured" in output
    assert "Claude Code:" in output
    assert "Codex:" in output


def test_main_uses_selected_profile_path(tmp_path, monkeypatch):
    profile = tmp_path / "custom.yaml"
    profile.write_text(
        "\n".join(
            [
                "interests: [SGLang]",
                "skills: [Python]",
                "resources: {}",
                "watching:",
                "  - repo: sgl-project/sglang",
                f"output_dir: {tmp_path / 'out'}",
                "llm:",
                "  base_url: http://localhost:30000/v1",
                "  model: test-model",
                "  api_key: placeholder",
                "external_agents:",
                "  claude_code: claude",
                "  codex: codex",
                "",
            ]
        )
    )
    launched = []
    monkeypatch.setattr(app_module.OsmindApp, "run", lambda self: launched.append(self.config))

    app_module.main(["--profile", str(profile)])

    assert launched
    assert launched[0].output_dir == tmp_path / "out"
