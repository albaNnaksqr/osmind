from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class PacketSection:
    title: str
    start: int
    end: int


def packet_outline(markdown: str) -> list[PacketSection]:
    sections: list[PacketSection] = []
    first_heading = re.search(r"(?m)^# .+$", markdown)
    section_matches = list(re.finditer(r"(?m)^## (?P<title>.+?)\s*$", markdown))

    if first_heading is not None:
        first_section_end = section_matches[0].start() if section_matches else len(markdown)
        sections.append(PacketSection("Overview", first_heading.start(), first_section_end))

    for index, match in enumerate(section_matches):
        end = section_matches[index + 1].start() if index + 1 < len(section_matches) else len(markdown)
        sections.append(PacketSection(match.group("title").strip(), match.start(), end))

    return sections


def packet_section_markdown(markdown: str, index: int) -> str:
    outline = packet_outline(markdown)
    if index < 0 or index >= len(outline):
        return markdown.strip()
    section = outline[index]
    return markdown[section.start : section.end].strip()
