from __future__ import annotations

from osmind.decision import format_decision_markdown
from osmind.engine.issue_brief import IssueBrief
from osmind.engine import issue_brief as issue_brief_module

try:
    from osmind.engine.issue_brief import render_agent_prompt
except ImportError:
    render_agent_prompt = getattr(issue_brief_module, "render_agent_prompt", None)

    if render_agent_prompt is None:
        def render_agent_prompt(issue: GHIssue, brief: IssueBrief) -> str:  # type: ignore[no-redef]
            return f"请在 {issue.repo} 中分析 {brief.one_liner} issue"

from osmind.github.models import GHIssue, GHPR, PRFile
from osmind.packs.models import LearningPack, PackSection, SourceRef


DIFF_SNIPPET_MAX_CHARS = 4000

REQUIRED_PR_SECTIONS = [
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
            PackSection("What This Is", _pr_what_this_is(pr)),
            PackSection("Why It May Fit You", _why_this_is_worth_reading(pr)),
            PackSection("Continue Or Stop Criteria", _pr_continue_stop_criteria(files)),
            PackSection("First 10 Minutes", _pr_first_ten_minutes(files)),
            PackSection("Files And Symbols To Inspect", _files_to_read_first(files)),
            PackSection("Validation Path", _pr_validation_path(files)),
            PackSection("What Changed", _what_changed(pr)),
            PackSection("Diff Map", _diff_map(files)),
            PackSection("Agent Exploration Prompt", _agent_exploration_prompt(pr)),
            PackSection("Follow-Up Contribution Ideas", _contribute_next(pr)),
            PackSection("Decision Log", _decision_log()),
            PackSection("Notes", ""),
        ]
        return LearningPack(
            source=source,
            modules=_modules_from_files(files),
            sections=sections,
        )

    @staticmethod
    def from_issue(issue: GHIssue, resources: dict | None = None, brief: IssueBrief | None = None) -> LearningPack:
        source = SourceRef(
            source_type="issue",
            repo=issue.repo,
            number=issue.number,
            title=issue.title,
            url=issue.url,
            updated_at=issue.updated_at,
        )
        sections = [
            PackSection("What This Is", _issue_what_this_is(issue)),
            PackSection("Recommendation Snapshot", format_decision_markdown(issue, resources)),
        ]
        if brief is not None:
            sections.extend(
                [
                    PackSection("Issue Brief", _issue_brief_summary(brief)),
                    PackSection("Why It May Fit You", _brief_why_it_may_fit(brief, issue)),
                    PackSection("Risks And Missing Evidence", _issue_brief_risks(brief)),
                    PackSection("First 30 Minutes", _numbered_list(brief.next_steps)),
                    PackSection("Validation Path", _numbered_list(brief.agent_questions)),
                    PackSection("Agent Prompt", _issue_brief_agent_prompt(issue, brief)),
                ]
            )
        else:
            sections.extend(
                [
                    PackSection("Why It May Fit You", _why_issue_may_fit(issue)),
                    PackSection("First 10 Minutes", _issue_first_ten_minutes(issue)),
                    PackSection("Validation Path", _issue_validation_path(issue)),
                    PackSection("Agent Exploration Prompt", _issue_agent_prompt(issue)),
                ]
            )
        sections.extend(
            [
                PackSection("Continue Or Stop Criteria", _issue_continue_stop_criteria(issue)),
                PackSection("Files And Symbols To Inspect", _issue_search_targets(issue)),
                PackSection("Known Facts", _issue_known_context(issue)),
                PackSection("Missing Context", _issue_missing_context(issue)),
                PackSection("Reproduction Hypothesis", _issue_reproduction_hypothesis(issue)),
                PackSection("Maintainer Signals", _issue_maintainer_signals(issue)),
                PackSection("Decision Log", _decision_log()),
                PackSection("Notes", ""),
            ]
        )
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


def _plain_list(items: list[str]) -> str:
    if not items:
        return "- None identified."
    return "\n".join(f"- {item}" for item in items)


def _numbered_list(items: list[str]) -> str:
    if not items:
        return "1. None identified."
    return "\n".join(f"{index}. {item}" for index, item in enumerate(items, 1))


def _extract_fact_lines(value: str, key: str) -> list[str]:
    lowered_key = key.lower()
    lines = []
    for line in value.splitlines():
        line = line.strip()
        if not line:
            continue
        lower = line.lower()
        if lower.startswith(f"{lowered_key}:") or lower.startswith(f"{lowered_key}："):
            lines.append(line)
    return lines


def _tagged_items(items: list[str], label: str) -> list[str]:
    if not items:
        return []
    normalized: list[str] = []
    for item in items:
        stripped = item.strip()
        if not stripped:
            continue
        if stripped.lower().startswith(label.lower() + ":"):
            normalized.append(stripped)
        elif stripped.lower().startswith("interest") or stripped.lower().startswith("skill"):
            normalized.append(stripped)
        else:
            normalized.append(f"{label}: {stripped}")
    return normalized


def _brief_ranker_reason(issue: GHIssue) -> str:
    if not issue.reason:
        return ""
    reason_lines = [line.strip() for line in issue.reason.splitlines() if line.strip()]
    evidence_lines = [
        line for line in reason_lines if not _is_structured_reason_line(line)
    ]
    if not evidence_lines:
        return ""
    return "\n\n### Ranker Reason\n" + "\n".join("- " + line for line in evidence_lines)


def _is_structured_reason_line(line: str) -> bool:
    lowered = line.lower()
    return lowered.startswith(("interest:", "interest：", "skill:", "skill：", "兴趣:", "技能:"))


def _issue_brief_summary(brief: IssueBrief) -> str:
    background = list(dict.fromkeys(brief.project_context + brief.background_to_learn))
    background = _plain_list(background)
    return "\n".join(
        [
            "### One-Liner",
            brief.one_liner,
            "",
            "### Problem Summary",
            brief.plain_explanation,
            "",
            "### Background",
            background,
        ]
    )


def _brief_why_it_may_fit(brief: IssueBrief, issue: GHIssue) -> str:
    interests = brief.matched_interests or _extract_fact_lines(issue.reason, "Interest")
    if not interests:
        interests = ["Interest: unknown"]

    skills = brief.matched_skills or _extract_fact_lines(issue.reason, "Skill")
    if not skills:
        skills = ["Skill: unknown"]

    return "\n".join(
        [
            "### Matched Interests",
            _plain_list(_tagged_items(interests, "Interest")),
            "",
            "### Matched Skills",
            _plain_list(_tagged_items(skills, "Skill")),
            "",
            "### Resource Assessment",
            f"- {brief.resource_assessment}",
            f"- Fit: {issue.fit or 'unknown'}",
            f"- Actionability: {issue.actionability or 'unknown'}",
            f"- Priority: {issue.priority or 'unknown'}",
            "",
            "### Evidence",
            _plain_list(_tagged_evidence(issue, brief)),
        ]
    ) + _brief_ranker_reason(issue)


def _tagged_evidence(issue: GHIssue, brief: IssueBrief) -> list[str]:
    evidence = list(brief.evidence)
    if not evidence and issue.body:
        evidence.append(issue.body.strip()[:240] or "No issue body captured.")
    if issue.labels:
        evidence.append(f"Labels: {', '.join(issue.labels)}")
    return evidence or ["No explicit evidence provided."]


def _issue_brief_risks(brief: IssueBrief) -> str:
    return "\n".join(["### Risks", _plain_list(brief.risks)])


def _issue_brief_agent_prompt(issue: GHIssue, brief: IssueBrief) -> str:
    if render_agent_prompt is None:
        return f"请在 {issue.repo} 中分析 {issue.title} issue"
    try:
        return render_agent_prompt(brief)
    except TypeError:
        return render_agent_prompt(issue, brief)


def _file_summary(file: PRFile) -> str:
    details: list[str] = []
    if file.status:
        details.append(file.status)
    if file.additions or file.deletions:
        details.append(f"+{file.additions}/-{file.deletions}")
    suffix = f" ({', '.join(details)})" if details else ""
    return f"`{file.filename}`{suffix}"


def _pr_what_this_is(pr: GHPR) -> str:
    changed_count = len(pr.files or [])
    body = (pr.body or "").strip()
    summary = (
        f"PR #{pr.number} in `{pr.repo}` is titled \"{pr.title}\" and changes "
        f"{changed_count} file{'' if changed_count == 1 else 's'}."
    )
    if body:
        return f"{summary}\n\nSource description:\n\n{body}"
    return f"{summary}\n\nNo PR description was included in the fetched metadata."


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


def _pr_continue_stop_criteria(files: list[PRFile]) -> str:
    test_files = [file.filename for file in files if "test" in file.filename.lower()]
    continue_lines = [
        "Continue if the changed files map to modules you want to understand.",
        "Continue if you can explain the intent after reading the PR description and first changed file.",
    ]
    if test_files:
        continue_lines.append(f"Continue if `{test_files[0]}` gives a concrete validation path.")
    stop_lines = [
        "Stop if the diff depends on project context you cannot recover in a short reading session.",
        "Stop if there is no clear behavior, test, or design question to carry forward.",
    ]
    return "\n".join(
        ["### Continue", *[f"- {line}" for line in continue_lines], "", "### Stop", *[f"- {line}" for line in stop_lines]]
    )


def _pr_first_ten_minutes(files: list[PRFile]) -> str:
    if not files:
        return "\n".join(
            [
                "1. Read the PR title and description.",
                "2. Open the GitHub conversation for maintainer context.",
                "3. Decide whether to fetch file metadata before spending more time.",
            ]
        )
    first = files[0].filename
    lines = [
        "1. Read the PR description and restate the intended behavior change.",
        f"2. Read `{first}` first and identify the main code path.",
    ]
    if len(files) > 1:
        lines.append("3. Skim the remaining changed files to separate behavior, tests, and documentation.")
    else:
        lines.append("3. Check whether this single-file change needs tests or docs.")
    return "\n".join(lines)


def _pr_validation_path(files: list[PRFile]) -> str:
    test_files = [file for file in files if "test" in file.filename.lower()]
    if test_files:
        return "\n".join(
            [
                f"- Start from {_file_summary(test_files[0])}.",
                "- Identify the command the project uses to run that test file.",
                "- Use the test behavior as the evidence for whether this PR is safe to learn from or extend.",
            ]
        )
    return "\n".join(
        [
            "- No obvious test file was included in the fetched PR metadata.",
            "- Search the repository for tests around the first changed module.",
            "- Treat the packet as low confidence until you identify a validation command or review discussion.",
        ]
    )


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


def _decision_log() -> str:
    return "- Decision: undecided\n- Reason:\n- Next check:"


def _issue_what_this_is(issue: GHIssue) -> str:
    body = (issue.body or "").strip()
    summary = f"Issue #{issue.number} in `{issue.repo}` is titled \"{issue.title}\"."
    if body:
        return f"{summary}\n\nSource report:\n\n{body}"
    return f"{summary}\n\nThe issue body is empty, so this packet starts with low confidence."


def _why_issue_may_fit(issue: GHIssue) -> str:
    labels = ", ".join(issue.labels) if issue.labels else "none"
    parts = [
        f"Issue #{issue.number}: {issue.title}",
        f"Labels: {labels}",
    ]
    if issue.reason:
        parts.append(f"推荐理由: {issue.reason}")
    parts.append(
        "Use this issue to judge whether the problem is understandable, scoped, "
        "and worth deeper exploration before attempting a contribution."
    )
    return "\n\n".join(parts)


def _issue_continue_stop_criteria(issue: GHIssue) -> str:
    body = (issue.body or "").lower()
    labels = {label.lower() for label in issue.labels}
    has_repro_hint = any(word in body for word in ("reproduce", "repro", "steps", "error", "traceback", "stack"))
    has_help_label = bool(labels & {"good first issue", "help wanted", "bug"})
    continue_lines = [
        "Continue if you can restate the problem without copying the issue text.",
        "Continue if repository search points to one likely module or symbol.",
    ]
    if has_repro_hint:
        continue_lines.append("Continue if the report's reproduction or error details can be turned into a validation check.")
    if has_help_label:
        continue_lines.append("Continue because the labels suggest maintainers may accept external help.")
    stop_lines = [
        "Stop if the issue lacks reproduction details and no maintainer comment narrows the scope.",
        "Stop if you cannot identify evidence that would prove a fix worked.",
    ]
    return "\n".join(
        ["### Continue", *[f"- {line}" for line in continue_lines], "", "### Stop", *[f"- {line}" for line in stop_lines]]
    )


def _issue_first_ten_minutes(issue: GHIssue) -> str:
    targets = _issue_search_terms(issue)
    first_target = targets[0] if targets else issue.title
    return "\n".join(
        [
            "1. Reproduce or restate the report in one sentence.",
            f"2. Search the repository for `{first_target}` and nearby module names.",
            "3. Find the smallest file or test that could validate the behavior.",
            "4. Decide continue/defer/discard before attempting implementation.",
        ]
    )


def _issue_validation_path(issue: GHIssue) -> str:
    body = (issue.body or "").lower()
    if any(word in body for word in ("test", "pytest", "unittest", "regression")):
        return "\n".join(
            [
                "- The issue text mentions tests or regression evidence.",
                "- Search for the named test path or nearby module tests.",
                "- Prefer writing or running the smallest failing validation before implementation.",
            ]
        )
    return "\n".join(
        [
            "- No concrete test command was detected in the fetched issue text.",
            "- Search for existing tests around the title terms and labels.",
            "- If no validation path appears in 10 minutes, defer or ask an agent to investigate first.",
        ]
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
    targets = _issue_search_terms(issue)
    lines = [f"- `{target}`" for target in targets]
    if issue.labels:
        lines.append(f"- Labels: {', '.join(issue.labels)}")
    return "\n".join(lines) if lines else "- Search exact phrases from the issue title and body."


def _issue_search_terms(issue: GHIssue) -> list[str]:
    title_words = [word.strip(".,:;()[]{}").lower() for word in issue.title.split()]
    return [word for word in title_words if len(word) > 3][:6]


def _issue_reproduction_hypothesis(issue: GHIssue) -> str:
    if not (issue.body or "").strip():
        return "No reproduction hypothesis yet; the issue body is empty."
    return (
        "Initial hypothesis: the behavior described in the issue can be reproduced or validated "
        "by following exact terms from the report, then narrowing to the smallest affected module."
    )


def _issue_maintainer_signals(issue: GHIssue) -> str:
    signals: list[str] = []
    if issue.labels:
        signals.append(f"- Labels: {', '.join(issue.labels)}")
    for comment in issue.comments[:3]:
        author = comment.author or "unknown"
        body = " ".join((comment.body or "").split())
        if len(body) > 180:
            body = f"{body[:180].rstrip()}..."
        signals.append(f"- {author}: {body}")
    return "\n".join(signals) if signals else "- No cached labels or maintainer comments beyond the issue body."


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
