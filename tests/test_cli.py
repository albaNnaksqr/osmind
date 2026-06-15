import json

from osmind import cli


def write_profile(tmp_path, with_llm=True):
    lines = [
        "interests: [sglang]",
        "skills: [python]",
        "resources:",
        "  gpus: 1 x Spark",
        "watching:",
        "  - repo: sgl-project/sglang",
        f"output_dir: {tmp_path / 'out'}",
    ]
    if with_llm:
        lines += ["llm:", "  base_url: http://x/v1", "  model: m", "  api_key: k"]
    profile = tmp_path / "profile.yaml"
    profile.write_text("\n".join(lines) + "\n")
    return profile


def run_cli(capsys, *argv):
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_profile_json(tmp_path, capsys):
    profile = write_profile(tmp_path)
    code, out, _ = run_cli(capsys, "--profile", str(profile), "profile", "--json")
    assert code == 0
    data = json.loads(out)
    assert data["watching"] == ["sgl-project/sglang"]
    assert data["resources"] == {"gpus": "1 x Spark"}


def test_missing_profile_errors_cleanly(tmp_path, capsys):
    code, out, err = run_cli(capsys, "--profile", str(tmp_path / "missing.yaml"), "profile")
    assert code == 1
    assert out == ""
    assert "profile not found" in err


def test_report_without_llm_errors_cleanly(tmp_path, capsys):
    profile = write_profile(tmp_path, with_llm=False)
    code, _, err = run_cli(capsys, "--profile", str(profile), "report", "--no-notify")
    assert code == 1
    assert "llm:" in err


def test_profile_discovery_via_env(tmp_path, capsys, monkeypatch):
    profile = write_profile(tmp_path)
    monkeypatch.setenv("OSMIND_PROFILE", str(profile))
    code, out, _ = run_cli(capsys, "profile", "--json")
    assert code == 0
    assert json.loads(out)["interests"] == ["sglang"]
