from osmind.github.models import GHComment, GHIssue, GHPR, PRFile
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
        "What This Is",
        "Why It May Fit You",
        "Continue Or Stop Criteria",
        "First 10 Minutes",
        "Files And Symbols To Inspect",
        "Validation Path",
        "What Changed",
        "Diff Map",
        "Agent Exploration Prompt",
        "Follow-Up Contribution Ideas",
        "Decision Log",
        "Notes",
    ]
    assert "src/runner.py" in sections["Files And Symbols To Inspect"]
    assert "modified" in sections["Files And Symbols To Inspect"]
    assert "+2/-1" in sections["Files And Symbols To Inspect"]
    assert "tests/test_runner.py" in sections["Files And Symbols To Inspect"]
    assert "added" in sections["Files And Symbols To Inspect"]
    assert "+8/-0" in sections["Files And Symbols To Inspect"]
    assert "Continue" in sections["Continue Or Stop Criteria"]
    assert "Stop" in sections["Continue Or Stop Criteria"]


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


def test_from_pr_diff_map_truncates_long_patch_snippets():
    long_patch = "\n".join(f"+line {index}" for index in range(600))
    pr = GHPR(
        number=9,
        title="Long patch",
        body="",
        url="https://github.com/o/r/pull/9",
        repo="o/r",
        files=[PRFile(filename="pkg/large.py", patch=long_patch)],
    )

    pack = PackGenerator().from_pr(pr)
    diff_map = {section.title: section.body for section in pack.sections}["Diff Map"]

    assert "... [diff truncated]" in diff_map
    assert "+line 0" in diff_map
    assert "+line 599" not in diff_map


def test_from_pr_diff_map_uses_safe_fence_for_patch_containing_backticks():
    patch = "@@ -1 +1 @@\n+before\n+```\n+inside\n+```"
    pr = GHPR(
        number=10,
        title="Fence patch",
        body="",
        url="https://github.com/o/r/pull/10",
        repo="o/r",
        files=[PRFile(filename="pkg/fence.md", patch=patch)],
    )

    pack = PackGenerator().from_pr(pr)
    diff_map = {section.title: section.body for section in pack.sections}["Diff Map"]

    assert "````diff\n" in diff_map
    assert "\n````" in diff_map
    assert "+```" in diff_map


def test_from_pr_agent_prompt_mentions_pr_number_repo_and_title():
    pack = PackGenerator().from_pr(_sample_pr())
    prompt = {section.title: section.body for section in pack.sections}[
        "Agent Exploration Prompt"
    ]

    assert "PR #7" in prompt
    assert "o/r" in prompt
    assert "Refactor runner" in prompt


def test_from_issue_includes_required_sections_and_issue_context():
    issue = GHIssue(
        number=42,
        title="Tokenizer leak",
        body="Long sequences leak memory.",
        labels=["bug", "tokenizer"],
        url="https://github.com/o/r/issues/42",
        repo="o/r",
        state="open",
        updated_at="2026-05-16T01:02:03+00:00",
        comments=[
            GHComment(
                author="maintainer",
                body="Likely related to the tokenizer cache.",
                url="https://github.com/o/r/issues/42#issuecomment-1",
                created_at="2026-05-16T02:03:04+00:00",
            )
        ],
    )

    pack = PackGenerator().from_issue(issue)
    sections = {section.title: section.body for section in pack.sections}

    assert pack.source.source_type == "issue"
    assert pack.source.repo == "o/r"
    assert pack.source.number == 42
    assert pack.source.title == "Tokenizer leak"
    assert pack.source.url == "https://github.com/o/r/issues/42"
    assert pack.source.updated_at == "2026-05-16T01:02:03+00:00"
    assert list(sections) == [
        "What This Is",
        "Why It May Fit You",
        "Continue Or Stop Criteria",
        "First 10 Minutes",
        "Files And Symbols To Inspect",
        "Validation Path",
        "Known Facts",
        "Missing Context",
        "Reproduction Hypothesis",
        "Maintainer Signals",
        "Agent Exploration Prompt",
        "Decision Log",
        "Notes",
    ]
    assert "Tokenizer leak" in sections["Why It May Fit You"]
    assert "bug, tokenizer" in sections["Why It May Fit You"]
    assert "Long sequences leak memory." in sections["Known Facts"]
    assert "maintainer" in sections["Missing Context"]
    assert "tokenizer cache" in sections["Missing Context"]
    assert "reproduce" in sections["First 10 Minutes"].lower()
    assert "Continue" in sections["Continue Or Stop Criteria"]
    assert "Stop" in sections["Continue Or Stop Criteria"]
    assert "issue #42" in sections["Agent Exploration Prompt"].lower()
    assert "o/r" in sections["Agent Exploration Prompt"]
    assert "Tokenizer leak" in sections["Agent Exploration Prompt"]
    assert "Do not implement" in sections["Agent Exploration Prompt"]


def test_from_issue_uses_discover_recommendation_reason_in_fit_section():
    issue = GHIssue(
        number=42,
        title="Tokenizer leak",
        body="Body",
        labels=["bug"],
        url="https://github.com/o/r/issues/42",
        repo="o/r",
        state="open",
        reason="涉及 tokenizer cache，与用户的推理优化兴趣高度相关。",
    )

    pack = PackGenerator().from_issue(issue)
    sections = {section.title: section.body for section in pack.sections}

    assert "涉及 tokenizer cache" in sections["Why It May Fit You"]
