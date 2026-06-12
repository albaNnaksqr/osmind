import json

import pytest

from osmind import cli
from osmind.cache.store import CacheStore
from osmind.github.models import GHIssue


def write_profile(tmp_path, vault=None):
    lines = [
        "interests: [sglang]",
        "skills: [python]",
        "resources:",
        "  gpus: 1 x Spark",
        "watching:",
        "  - repo: sgl-project/sglang",
        f"output_dir: {tmp_path / 'out'}",
    ]
    if vault is not None:
        lines.append(f"vault: {vault}")
    profile = tmp_path / "profile.yaml"
    profile.write_text("\n".join(lines) + "\n")
    return profile


def seed_issue(tmp_path, number=1, title="Fix cache growth"):
    store = CacheStore(tmp_path / "out" / "osmind" / ".cache" / "osmind.db")
    store.upsert_issue(
        GHIssue(
            number=number,
            title=title,
            body="long body",
            labels=["bug"],
            url=f"https://github.com/sgl-project/sglang/issues/{number}",
            repo="sgl-project/sglang",
            state="open",
            updated_at="2026-06-01T00:00:00",
        )
    )


def run_cli(capsys, *argv):
    code = cli.main(list(argv))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_queue_json_boundary(tmp_path, capsys):
    profile = write_profile(tmp_path)
    seed_issue(tmp_path)

    code, out, _ = run_cli(capsys, "--profile", str(profile), "queue", "--json")
    assert code == 0
    items = json.loads(out)
    assert items[0]["repo"] == "sgl-project/sglang"
    assert items[0]["number"] == 1
    assert items[0]["status"] == "undecided"
    assert items[0]["decision"] is None


def test_decide_then_show_roundtrip(tmp_path, capsys):
    profile = write_profile(tmp_path, vault=tmp_path / "Note")
    seed_issue(tmp_path)

    code, out, _ = run_cli(
        capsys, "--profile", str(profile), "decide", "sgl-project/sglang#1", "defer", "--reason", "no cluster", "--json"
    )
    assert code == 0
    decision = json.loads(out)
    assert decision["decision"] == "defer"
    assert decision["mirrored_to"].endswith("Decision_Log.md")

    code, out, _ = run_cli(capsys, "--profile", str(profile), "show", "sgl-project/sglang#1", "--json")
    assert code == 0
    shown = json.loads(out)
    assert shown["status"] == "deferred"
    assert shown["decision_log"][0]["reason"] == "no cluster"
    assert shown["body"] == "long body"


def test_profile_json(tmp_path, capsys):
    profile = write_profile(tmp_path)
    code, out, _ = run_cli(capsys, "--profile", str(profile), "profile", "--json")
    assert code == 0
    data = json.loads(out)
    assert data["watching"] == ["sgl-project/sglang"]
    assert data["resources"] == {"gpus": "1 x Spark"}


def test_errors_go_to_stderr_with_nonzero_exit(tmp_path, capsys):
    profile = write_profile(tmp_path)
    code, out, err = run_cli(capsys, "--profile", str(profile), "show", "sgl-project/sglang#999")
    assert code == 1
    assert out == ""
    assert "not in the local store" in err

    code, _, err = run_cli(capsys, "--profile", str(tmp_path / "missing.yaml"), "queue")
    assert code == 1
    assert "profile not found" in err


def test_profile_discovery_via_env(tmp_path, capsys, monkeypatch):
    profile = write_profile(tmp_path)
    monkeypatch.setenv("OSMIND_PROFILE", str(profile))
    (tmp_path / "out").mkdir(exist_ok=True)
    monkeypatch.chdir(tmp_path / "out")

    code, out, _ = run_cli(capsys, "profile", "--json")
    assert code == 0
    assert json.loads(out)["interests"] == ["sglang"]


def test_queue_text_output_is_scannable(tmp_path, capsys):
    profile = write_profile(tmp_path)
    seed_issue(tmp_path, number=3, title="Tokenizer leak")
    code, out, _ = run_cli(capsys, "--profile", str(profile), "queue")
    assert code == 0
    assert "sgl-project/sglang#3  [undecided]  Tokenizer leak" in out
