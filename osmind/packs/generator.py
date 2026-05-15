from __future__ import annotations

from osmind.github.models import GHIssue, GHPR, PRFile
from osmind.packs.models import LearningPack, PackSection, SourceRef


DIFF_SNIPPET_MAX_CHARS = 4000

REQUIRED_PR_SECTIONS = [
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


class PackGenerator:
    @staticmethod
    def from_pr(pr: GHPR) -> LearningPack:
        source = SourceRef(
            source_type="pr",
            repo=pr.repo,
            number=pr.number,
            title=pr.title,
            url=pr.url,
            updated_at=pr.updated_at,
        )
        files = pr.files or []
        sections = [
            PackSection(
                "Why This Is Worth Reading",
                _why_this_is_worth_reading(pr),
            ),
            PackSection("What Changed", _what_changed(pr)),
            PackSection("Files To Read First", _files_to_read_first(files)),
            PackSection("Diff Map", _diff_map(files)),
            PackSection("Reading Path", _reading_path(files)),
            PackSection("Socratic Questions", _socratic_questions(pr)),
            PackSection("Agent Exploration Prompt", _agent_exploration_prompt(pr)),
            PackSection("If You Want To Contribute Next", _contribute_next(pr)),
            PackSection("Review Later", _review_later(files)),
            PackSection("Notes", ""),
        ]
        return LearningPack(
            source=source,
            modules=_modules_from_files(files),
            sections=sections,
        )

    @staticmethod
    def from_issue(issue: GHIssue) -> LearningPack:
        raise NotImplementedError("Issue learning packs are planned for Task 6.")


def _modules_from_files(files: list[PRFile]) -> list[str]:
    modules: list[str] = []
    seen: set[str] = set()
    for file in files:
        module = file.filename.split("/", 1)[0]
        if module and module not in seen:
            seen.add(module)
            modules.append(module)
    return modules


def _file_summary(file: PRFile) -> str:
    details: list[str] = []
    if file.status:
        details.append(file.status)
    if file.additions or file.deletions:
        details.append(f"+{file.additions}/-{file.deletions}")
    suffix = f" ({', '.join(details)})" if details else ""
    return f"`{file.filename}`{suffix}"


def _why_this_is_worth_reading(pr: GHPR) -> str:
    changed_count = len(pr.files or [])
    body = (pr.body or "").strip()
    parts = [
        f"PR #{pr.number} changes {changed_count} file"
        f"{'' if changed_count == 1 else 's'} in `{pr.repo}`.",
    ]
    if body:
        parts.append(body)
    return "\n\n".join(parts)


def _what_changed(pr: GHPR) -> str:
    if not pr.files:
        return "No changed files were included in the PR payload."
    lines = [f"- {_file_summary(file)}" for file in pr.files]
    return "\n".join(lines)


def _files_to_read_first(files: list[PRFile]) -> str:
    if not files:
        return "No changed files were included in the PR payload."
    return "\n".join(f"{index}. {_file_summary(file)}" for index, file in enumerate(files, 1))


def _diff_map(files: list[PRFile]) -> str:
    if not files:
        return "No diff files were included in the PR payload."

    blocks: list[str] = []
    for file in files[:8]:
        patch = (file.patch or "").strip()
        if not patch:
            patch = "No patch text available."
            blocks.append(f"### `{file.filename}`\n\n{patch}")
            continue

        snippet = _truncate_diff(patch)
        fence = _markdown_fence(snippet)
        blocks.append(f"### `{file.filename}`\n\n{fence}diff\n{snippet}\n{fence}")
    return "\n\n".join(blocks)


def _truncate_diff(patch: str) -> str:
    if len(patch) <= DIFF_SNIPPET_MAX_CHARS:
        return patch
    return f"{patch[:DIFF_SNIPPET_MAX_CHARS].rstrip()}\n... [diff truncated]"


def _markdown_fence(text: str) -> str:
    longest_run = 0
    current_run = 0
    for char in text:
        if char == "`":
            current_run += 1
            longest_run = max(longest_run, current_run)
        else:
            current_run = 0
    return "`" * max(3, longest_run + 1)


def _reading_path(files: list[PRFile]) -> str:
    if not files:
        return "1. Start from the PR description and linked discussion."
    first_files = files[:5]
    lines = [
        f"{index}. Read {_file_summary(file)} to understand the main flow."
        for index, file in enumerate(first_files, 1)
    ]
    if len(files) > len(first_files):
        lines.append(f"{len(first_files) + 1}. Skim the remaining files for edge cases.")
    return "\n".join(lines)


def _socratic_questions(pr: GHPR) -> str:
    return "\n".join(
        [
            f"- What problem does PR #{pr.number} solve for `{pr.repo}`?",
            "- Which changed file carries the main behavior change?",
            "- What tests or review checks would catch a regression here?",
        ]
    )


def _agent_exploration_prompt(pr: GHPR) -> str:
    return (
        f"Explore PR #{pr.number} in `{pr.repo}` titled \"{pr.title}\". "
        "Summarize the intent, identify the highest-signal files, explain the diff "
        "module by module, and propose one practical follow-up contribution."
    )


def _contribute_next(pr: GHPR) -> str:
    return (
        f"Look for tests, docs, or follow-up issues related to PR #{pr.number}. "
        "Prefer a small contribution that strengthens the changed behavior."
    )


def _review_later(files: list[PRFile]) -> str:
    if not files:
        return "- Revisit this pack after fetching the PR file list."
    return "\n".join(f"- {_file_summary(file)}" for file in files[:5])
