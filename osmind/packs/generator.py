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
        source = SourceRef(
            source_type="issue",
            repo=issue.repo,
            number=issue.number,
            title=issue.title,
            url=issue.url,
            updated_at=issue.updated_at,
        )
        sections = [
            PackSection("Why This May Fit You", _why_issue_may_fit(issue)),
            PackSection("What Is Known", _issue_known_context(issue)),
            PackSection("Missing Context", _issue_missing_context(issue)),
            PackSection("Investigation Path", _issue_investigation_path()),
            PackSection("Files Or Symbols To Search", _issue_search_targets(issue)),
            PackSection("Agent Exploration Prompt", _issue_agent_prompt(issue)),
            PackSection("Human Checkpoints", _issue_human_checkpoints()),
            PackSection("Learning Questions", _issue_learning_questions()),
            PackSection("Notes", ""),
        ]
        return LearningPack(source=source, modules=[], sections=sections)


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


def _why_issue_may_fit(issue: GHIssue) -> str:
    labels = ", ".join(issue.labels) if issue.labels else "none"
    return (
        f"Issue #{issue.number}: {issue.title}\n\n"
        f"Labels: {labels}\n\n"
        "Use this issue to judge whether the problem is understandable, scoped, "
        "and worth deeper exploration before attempting a contribution."
    )


def _issue_known_context(issue: GHIssue) -> str:
    return (issue.body or "").strip() or "The issue body is empty. Use repository search and comments to recover context."


def _issue_missing_context(issue: GHIssue) -> str:
    if not issue.comments:
        return "- No cached issue comments are available."
    lines = []
    for comment in issue.comments[:5]:
        body = " ".join((comment.body or "").split())
        if len(body) > 300:
            body = f"{body[:300].rstrip()}..."
        author = comment.author or "unknown"
        lines.append(f"- {author}: {body}")
    return "\n".join(lines)


def _issue_investigation_path() -> str:
    return "\n".join(
        [
            "1. Reproduce or restate the bug or request in your own words.",
            "2. Search the repository for names from the title and issue body.",
            "3. Identify the smallest module likely involved.",
            "4. Find existing tests around that module.",
            "5. Decide whether the next step is reading, reproduction, or implementation.",
        ]
    )


def _issue_search_targets(issue: GHIssue) -> str:
    title_words = [word.strip(".,:;()[]{}").lower() for word in issue.title.split()]
    title_words = [word for word in title_words if len(word) > 3]
    targets = title_words[:6]
    lines = [f"- `{target}`" for target in targets]
    if issue.labels:
        lines.append(f"- Labels: {', '.join(issue.labels)}")
    return "\n".join(lines) if lines else "- Search exact phrases from the issue title and body."


def _issue_agent_prompt(issue: GHIssue) -> str:
    return (
        f"Help me investigate issue #{issue.number} in `{issue.repo}` titled \"{issue.title}\". "
        "First summarize the known facts, then search for likely files or symbols, then propose "
        "a minimal reproduction or validation path. Do not implement until the investigation path is clear."
    )


def _issue_human_checkpoints() -> str:
    return "\n".join(
        [
            "- [ ] I can explain the issue without copying the issue text.",
            "- [ ] I know which module is likely involved.",
            "- [ ] I know what evidence would prove a fix works.",
            "- [ ] I know whether this is suitable for agent assistance.",
        ]
    )


def _issue_learning_questions() -> str:
    return "\n".join(
        [
            "1. What existing behavior does this issue rely on?",
            "2. What project convention might constrain the fix?",
            "3. What would make this issue too risky for a first contribution?",
        ]
    )
