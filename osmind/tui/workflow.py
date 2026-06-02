from __future__ import annotations

import re

from osmind.packs.renderer import parse_pack_frontmatter
from textual.markup import escape


START_WORK_SECTIONS = [
    ("First 10 Minutes", ("First 30 Minutes", "First 10 Minutes")),
    ("Files And Symbols To Inspect", ("Files And Symbols To Inspect",)),
    ("Validation Path", ("Validation Path",)),
    ("Continue Or Stop Criteria", ("Continue Or Stop Criteria",)),
    ("Agent Exploration Prompt", ("Agent Prompt", "Agent Exploration Prompt")),
]


def format_start_work_from_packet(markdown: str, resources: dict | None = None) -> str:
    frontmatter = parse_pack_frontmatter(markdown)
    sections = _packet_sections(markdown)
    label = "PR" if frontmatter.get("source_type") == "pr" else "Issue"
    number = frontmatter.get("number", "?")
    title = frontmatter.get("title", "Untitled")
    decision = str(frontmatter.get("decision") or "undecided")
    resources_text = _format_resources(resources or {})

    lines = [
        "[bold]Start Work[/bold]",
        "",
        f"[bold]{label} #{number}: {title}[/bold]",
        f"[dim]{frontmatter.get('repo', '')} | {frontmatter.get('url', '')}[/dim]",
        "",
        f"Decision: {decision}",
        f"Resources: {resources_text}",
    ]
    if decision in {"defer", "discard"}:
        lines.extend(
            [
                "",
                "[bold red]Do not start yet[/bold red]",
                "This packet is not marked Continue. Re-check resources, upstream context, or decision notes before spending implementation time.",
            ]
        )

    preferred_sections = _workflow_sections_for_packet(frontmatter, sections)
    for section, aliases in preferred_sections:
        body = ""
        for alias in aliases:
            body = sections.get(alias, "").strip()
            if body:
                break
        if not body:
            body = _missing_section_text(section)
        lines.extend(["", f"[bold]{section}[/bold]", _format_section_body(body)])

    return "\n".join(lines).rstrip()


def _workflow_sections_for_packet(frontmatter: dict[str, object], sections: dict[str, str]) -> list[tuple[str, tuple[str, ...]]]:
    source_type = frontmatter.get("source_type")
    has_brief_sections = (
        source_type == "issue"
        and any(title in sections for title in ("Issue Brief", "First 30 Minutes", "Agent Prompt"))
    )
    if has_brief_sections:
        workflow = [
            ("First 30 Minutes", ("First 30 Minutes", "First 10 Minutes")),
        ]
        if "Repo Grounding" in sections:
            workflow.append(("Repo Grounding", ("Repo Grounding",)))
        workflow.extend(
            [
                ("Files And Symbols To Inspect", ("Files And Symbols To Inspect",)),
                ("Validation Path", ("Validation Path",)),
                ("Continue Or Stop Criteria", ("Continue Or Stop Criteria",)),
                ("Agent Prompt", ("Agent Prompt", "Agent Exploration Prompt")),
            ]
        )
        return workflow
    return START_WORK_SECTIONS


def _packet_sections(markdown: str) -> dict[str, str]:
    matches = list(re.finditer(r"(?m)^## (?P<title>.+?)\s*$", markdown))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        sections[match.group("title").strip()] = markdown[start:end].strip()
    return sections


def _format_resources(resources: dict) -> str:
    if not resources:
        return "unspecified"
    return ", ".join(f"{key}: {value}" for key, value in resources.items())


def _format_section_body(body: str) -> str:
    formatted: list[str] = []
    in_code_block = False
    for raw_line in body.splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            formatted.append(escape(raw_line))
            continue
        if not in_code_block:
            heading = re.match(r"^#{3,6}\s+(?P<title>.+?)\s*$", stripped)
            if heading:
                if formatted and formatted[-1] != "":
                    formatted.append("")
                formatted.append(f"[bold]{escape(heading.group('title'))}[/bold]")
                continue
        formatted.append(escape(raw_line))
    return "\n".join(formatted).strip()


def _missing_section_text(section: str) -> str:
    if section in {"First 10 Minutes", "First 30 Minutes"}:
        return "Open the packet and identify the first concrete read or reproduction step."
    if section == "Files And Symbols To Inspect":
        return "No explicit files or symbols were captured. Search from the title and source text first."
    if section == "Validation Path":
        return "No validation path was captured. Do not implement until you can name the smallest check."
    if section == "Continue Or Stop Criteria":
        return "Continue only if the problem, likely module, and validation evidence are clear."
    if section in {"Agent Exploration Prompt", "Agent Prompt"}:
        return "Ask an agent to summarize known facts, likely files, and a minimal validation path before implementation."
    return "Not captured in this packet."
