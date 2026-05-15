from osmind.github.models import GHPR, PRFile
from osmind.packs.generator import PackGenerator


def _sample_pr() -> GHPR:
    return GHPR(
        number=7,
        title="Refactor runner",
        body="This refactors task execution.",
        url="https://github.com/o/r/pull/7",
        repo="o/r",
        updated_at="2026-05-15T01:02:03+00:00",
        files=[
            PRFile(
                filename="src/runner.py",
                patch="@@ -1,2 +1,3 @@\n-old\n+new\n+extra",
                status="modified",
                additions=2,
                deletions=1,
            ),
            PRFile(
                filename="tests/test_runner.py",
                patch="@@ -4,2 +4,2 @@\n-before\n+after",
                status="added",
                additions=8,
                deletions=0,
            ),
            PRFile(
                filename="src/helpers/path.py",
                patch="",
                status="modified",
                additions=1,
                deletions=1,
            ),
        ],
    )


def test_from_pr_sets_source_ref_and_unique_modules_in_first_seen_order():
    pack = PackGenerator().from_pr(_sample_pr())

    assert pack.source.source_type == "pr"
    assert pack.source.repo == "o/r"
    assert pack.source.number == 7
    assert pack.source.title == "Refactor runner"
    assert pack.source.url == "https://github.com/o/r/pull/7"
    assert pack.source.updated_at == "2026-05-15T01:02:03+00:00"
    assert pack.modules == ["src", "tests"]


def test_from_pr_includes_required_sections_and_changed_file_details():
    pack = PackGenerator().from_pr(_sample_pr())
    sections = {section.title: section.body for section in pack.sections}

    assert list(sections) == [
        "Why This Is Worth Reading",
        "What Changed",
        "Files To Read First",
        "Diff Map",
        "Reading Path",
        "Socratic Questions",
        "Agent Exploration Prompt",
        "If You Want To Contribute Next",
        "Review Later",
        "Notes",
    ]
    assert "src/runner.py" in sections["Files To Read First"]
    assert "modified" in sections["Files To Read First"]
    assert "+2/-1" in sections["Files To Read First"]
    assert "tests/test_runner.py" in sections["Files To Read First"]
    assert "added" in sections["Files To Read First"]
    assert "+8/-0" in sections["Files To Read First"]


def test_from_pr_diff_map_includes_up_to_first_eight_file_snippets_and_missing_patch_text():
    pr = GHPR(
        number=8,
        title="Large cleanup",
        body="",
        url="https://github.com/o/r/pull/8",
        repo="o/r",
        files=[
            PRFile(filename=f"pkg/file_{index}.py", patch=f"@@ file {index} @@\n+line")
            for index in range(9)
        ]
        + [PRFile(filename="pkg/no_patch.py", patch="")],
    )
    pr.files[2].patch = ""

    pack = PackGenerator().from_pr(pr)
    diff_map = {section.title: section.body for section in pack.sections}["Diff Map"]

    assert "pkg/file_0.py" in diff_map
    assert "@@ file 0 @@" in diff_map
    assert "pkg/file_7.py" in diff_map
    assert "pkg/file_8.py" not in diff_map
    assert "pkg/no_patch.py" not in diff_map
    assert "pkg/file_2.py" in diff_map
    assert "No patch text available." in diff_map


def test_from_pr_agent_prompt_mentions_pr_number_repo_and_title():
    pack = PackGenerator().from_pr(_sample_pr())
    prompt = {section.title: section.body for section in pack.sections}[
        "Agent Exploration Prompt"
    ]

    assert "PR #7" in prompt
    assert "o/r" in prompt
    assert "Refactor runner" in prompt
