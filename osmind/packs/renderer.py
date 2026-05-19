from __future__ import annotations

from datetime import date

import yaml

from osmind.packs.models import LearningPack

PACK_TYPE = "osmind-contribution-packet"
LEGACY_PACK_TYPE = "osmind-learning-pack"


def _heading(pack: LearningPack) -> str:
    label = "PR" if pack.source.source_type == "pr" else "Issue"
    return f"# {label} #{pack.source.number}: {pack.source.title}"


def render_pack(pack: LearningPack) -> str:
    frontmatter = {
        "type": PACK_TYPE,
        "source_type": pack.source.source_type,
        "repo": pack.source.repo,
        "number": pack.source.number,
        "title": pack.source.title,
        "url": pack.source.url,
        "status": pack.status,
        "decision": pack.decision,
        "confidence": pack.confidence,
        "generated_at": str(date.today()),
        "source_updated_at": pack.source.updated_at,
        "modules": pack.modules,
        "tags": pack.tags,
    }
    lines = [
        "---",
        yaml.dump(frontmatter, allow_unicode=True, sort_keys=False).strip(),
        "---",
        "",
        _heading(pack),
        "",
    ]
    for section in pack.sections:
        lines.append(f"## {section.title}")
        lines.append("")
        lines.append(section.body.strip())
        lines.append("")
    return "\n".join(lines) + "\n"


def parse_pack_frontmatter(text: str) -> dict:
    if not text.startswith("---\n"):
        raise ValueError("Pack is missing YAML frontmatter")

    try:
        _prefix, raw, _body = text.split("---", 2)
    except ValueError as exc:
        raise ValueError("Pack is missing YAML frontmatter") from exc

    data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict) or data.get("type") not in {PACK_TYPE, LEGACY_PACK_TYPE}:
        raise ValueError("Not an osmind Contribution Packet")
    return data
