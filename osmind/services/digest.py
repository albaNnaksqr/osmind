from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from osmind.services.radar import RadarError, RadarService

RADAR_DIR_RELATIVE = Path("Sources/Issue_Radar")


def run_digest(service: RadarService, limit: int = 30) -> dict:
    if service.config.vault is None:
        raise RadarError("digest needs `vault:` in profile.yaml (the Obsidian vault root)")

    sync_result = service.sync(limit=limit)
    queue_all = service.queue("all")
    by_key = {(item["repo"], item["number"]): item for item in queue_all}

    new_items: list[dict] = []
    changed_continue: list[dict] = []
    for repo_summary in sync_result["repos"]:
        for number in repo_summary["new"]:
            item = by_key.get((repo_summary["repo"], number))
            if item is not None:
                new_items.append(item)
        for number in repo_summary["changed"]:
            item = by_key.get((repo_summary["repo"], number))
            if item is not None and item["status"] == "continue":
                changed_continue.append(item)
    resurfaced = [item for item in queue_all if item["status"] == "resurfaced"]

    counts = {
        "active": sum(1 for item in queue_all if item["status"] in {"undecided", "continue", "resurfaced"}),
        "undecided": sum(1 for item in queue_all if item["status"] == "undecided"),
        "continue": sum(1 for item in queue_all if item["status"] == "continue"),
        "resurfaced": len(resurfaced),
    }

    today = date.today()
    path = _weekly_path(service.config.vault, today)
    section = _render_section(
        today, service, new_items, resurfaced, changed_continue, counts, sync_result.get("errors", [])
    )
    _write_section(path, today, section)

    return {
        "path": str(path),
        "date": today.isoformat(),
        "new": len(new_items),
        "resurfaced": len(resurfaced),
        "continue_changed": len(changed_continue),
        "counts": counts,
        "errors": sync_result.get("errors", []),
    }


def _weekly_path(vault: Path, today: date) -> Path:
    year, week, _ = today.isocalendar()
    return vault / RADAR_DIR_RELATIVE / f"{year}-W{week:02d}.md"


def _render_section(
    today: date,
    service: RadarService,
    new_items: list[dict],
    resurfaced: list[dict],
    changed_continue: list[dict],
    counts: dict,
    errors: list[dict],
) -> str:
    lines = [
        f"## {today.isoformat()}",
        "",
        f"Active 队列 {counts['active']}（undecided {counts['undecided']} · continue {counts['continue']} · resurfaced {counts['resurfaced']}）",
        "",
    ]
    if errors:
        lines.append("### 抓取失败（本次未更新）")
        lines.append("")
        for error in errors:
            lines.append(f"- {error['repo']}: {error['error']}")
        lines.append("")
    if not new_items and not resurfaced and not changed_continue:
        lines.extend(["本次 sync 无新增、无复活、continue 项无变化。", ""])
        return "\n".join(lines)

    if resurfaced:
        lines.extend(["### 复活（值得重看）", ""])
        for item in resurfaced:
            lines.extend(_render_entry(service, item, show_decision=True))
    if new_items:
        lines.extend(["### 新增", ""])
        for item in new_items:
            lines.extend(_render_entry(service, item))
    if changed_continue:
        lines.extend(["### Continue 项有更新", ""])
        for item in changed_continue:
            lines.extend(_render_entry(service, item))
    return "\n".join(lines)


def _render_entry(service: RadarService, item: dict, *, show_decision: bool = False) -> list[str]:
    ref = f"{item['repo']}#{item['number']}"
    lines = [
        f"#### {ref} {item['title']}",
        f"- Link: {item['url']}",
        f"- Labels: {', '.join(item['labels']) or 'none'}",
        f"- Interest match: {_interest_match(service, item)}",
    ]
    if show_decision and item["decision"]:
        decision = item["decision"]
        lines.append(f"- 原决策: {decision['decision']} — {decision['reason']}（{decision['decided_at']}）")
        lines.append(f"- 变化: {', '.join(item['resurfaced_because'])}")
    lines.extend([f"- Inspect: `osmind show {ref}`", ""])
    return lines


def _interest_match(service: RadarService, item: dict) -> str:
    haystack = " ".join([item["title"], *item["labels"]]).lower()
    matched = [interest for interest in service.config.interests if interest.lower() in haystack]
    return ", ".join(matched) if matched else "none（关键词级判断，仅供参考）"


def _write_section(path: Path, today: date, section: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    year, week, _ = today.isocalendar()
    if not path.exists():
        header = f"# Issue Radar - {year}-W{week:02d}\n\n> 由 `osmind digest` 生成；判断和决策请通过 agent 或 `osmind decide` 进行。\n\n"
        path.write_text(header + section.rstrip() + "\n", encoding="utf-8")
        return

    text = path.read_text(encoding="utf-8")
    pattern = re.compile(rf"(?ms)^## {re.escape(today.isoformat())}\s*$.*?(?=^## |\Z)")
    replacement = section.rstrip() + "\n\n"
    if pattern.search(text):
        text = pattern.sub(lambda _: replacement, text)
    else:
        text = text.rstrip() + "\n\n" + replacement
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
