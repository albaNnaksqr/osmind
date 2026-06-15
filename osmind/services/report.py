from __future__ import annotations

from dataclasses import asdict
from datetime import date
from pathlib import Path

from osmind.github.models import IssueSignals
from osmind.llm import LLMError
from osmind.notify import macos_notify
from osmind.services.recommend import recommend
from osmind.services.radar import RadarError, RadarService

MAX_CANDIDATES = 30
REPORTS_DIRNAME = "reports"
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def run_report(service: RadarService, limit: int = 30, notify: bool = True) -> dict:
    if service.config.llm is None:
        raise RadarError("report needs `llm:` in profile.yaml (the judgment endpoint)")

    sync_result = service.sync(limit=limit)
    active = service.queue("active")
    # Items the user already decided to work on bypass LLM judgment entirely —
    # the user's own decision is not up for re-litigation.
    continuing = [_enrich(service, i, with_change=True) for i in active if _is_continuing(i)]
    others = _balanced_candidates([i for i in active if not _is_continuing(i)], MAX_CANDIDATES)
    candidates = [_enrich(service, i) for i in others]

    llm_error: str | None = None
    recommendation = {"recommendations": [], "skipped": {}, "serendipity_count": 0, "skipped_count": 0}
    if candidates:
        try:
            recommendation = recommend(service.config.llm, service.profile(), candidates)
        except LLMError as error:
            llm_error = str(error)

    today = date.today()
    path = _report_path(service.config.output_dir, today)
    markdown = _render_report(
        today, service.profile(), candidates, continuing, recommendation, llm_error, sync_result
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")

    notified = False
    if notify:
        notified = _notify(today, continuing, recommendation, llm_error)

    return {
        "path": str(path),
        "date": today.isoformat(),
        "candidates": len(candidates),
        "continuing": len(continuing),
        "recommendations": len(recommendation["recommendations"]),
        "serendipity": recommendation.get("serendipity_count", 0),
        "skipped": recommendation.get("skipped_count", 0),
        "llm_error": llm_error,
        "notified": notified,
    }


def _is_continuing(item: dict) -> bool:
    return bool(item.get("decision")) and item["decision"]["decision"] == "continue"


def _enrich(service: RadarService, item: dict, *, with_change: bool = False) -> dict:
    repo, number = item["repo"], item["number"]
    try:
        signals = service._client.issue_signals(repo, number)
    except Exception:
        signals = IssueSignals(number=number)  # best-effort; never drop the item
    full = service.store.get_item(repo, "issue", number)
    card = {
        "repo": repo,
        "number": number,
        "title": item["title"],
        "body": full["body"] if full else "",
        "signals": asdict(signals),
        "prior_decision": item["decision"],
        "changed": False,
    }
    if with_change and full:
        decisions = service.store.latest_decisions(repo)
        raw = decisions.get(number)
        card["changed"] = bool(raw and raw["content_hash"] and raw["content_hash"] != full["content_hash"])
    return card


def _balanced_candidates(items: list[dict], cap: int) -> list[dict]:
    """Round-robin across repos so a busy repo can't crowd out a quiet one."""
    by_repo: dict[str, list[dict]] = {}
    for item in items:
        by_repo.setdefault(item["repo"], []).append(item)
    for repo_items in by_repo.values():
        repo_items.sort(key=lambda i: i["updated_at"], reverse=True)
    picked: list[dict] = []
    queues = list(by_repo.values())
    index = 0
    while len(picked) < cap and any(queues):
        queue = queues[index % len(queues)]
        if queue:
            picked.append(queue.pop(0))
        index += 1
        if all(not q for q in queues):
            break
    return picked


def _report_path(output_dir: Path, today: date) -> Path:
    return output_dir / REPORTS_DIRNAME / f"{today.isoformat()}.md"


def _render_report(today, profile, candidates, continuing, recommendation, llm_error, sync_result) -> str:
    by_key = {(c["repo"], c["number"]): c for c in candidates}
    lines = [
        f"# 贡献推荐 - {today.isoformat()}",
        "",
        f"> 关注仓库: {', '.join(profile.get('watching', []))} | 资源: {_resources(profile)}",
        "",
    ]
    for error in sync_result.get("errors", []):
        lines.append(f"> ⚠️ 抓取失败 {error['repo']}: {error['error']}")

    main = [r for r in recommendation["recommendations"] if not r["serendipity"]]
    serendipity = [r for r in recommendation["recommendations"] if r["serendipity"]]
    main.sort(key=lambda r: PRIORITY_ORDER.get(r["priority"], 1))

    # deterministic summary — never trust the model's free-text summary
    lines.append(
        f"推荐 {len(main)} 条 · serendipity {len(serendipity)} 条 · 跟进中 {len(continuing)} 条"
        f" · 跳过 {recommendation.get('skipped_count', 0)} 条"
    )
    lines.append("")

    if continuing:
        lines.extend(["## 你在跟进的（continue）", ""])
        for card in continuing:
            lines.extend(_render_continuing(card))

    if llm_error:
        lines.extend(
            [
                "## ⚠️ 判断失败",
                "",
                f"LLM 调用失败：{llm_error}",
                "",
                "下面是未排序的候选 issue（原始数据），可手动查看或稍后重跑 `osmind report`。",
                "",
                _render_raw_candidates(candidates),
            ]
        )
        return "\n".join(lines).rstrip() + "\n"

    if main:
        lines.extend(["## 推荐贡献", ""])
        for rec in main:
            lines.extend(_render_rec(rec, by_key.get((rec["repo"], rec["number"]))))
    if serendipity:
        lines.extend(["## 跳出兴趣（serendipity）", ""])
        for rec in serendipity:
            lines.extend(_render_rec(rec, by_key.get((rec["repo"], rec["number"]))))
    if not recommendation["recommendations"] and not continuing:
        lines.append("本次没有产出推荐。")
    lines.extend(_render_skipped(recommendation.get("skipped", {})))
    return "\n".join(lines).rstrip() + "\n"


def _render_continuing(card: dict) -> list[str]:
    ref = f"{card['repo']}#{card['number']}"
    flag = " ⚠️ 上游有更新" if card.get("changed") else ""
    s = card["signals"]
    pr = f"#{','.join(map(str, s['linked_open_prs']))}" if s["linked_open_prs"] else "无"
    lines = [f"### {ref} {card['title']}{flag}"]
    if card.get("prior_decision"):
        lines.append(f"- 你的决定: continue — {card['prior_decision']['reason']}")
    lines.append(
        f"- 客观信号: open PR {pr} · assignees {', '.join(s['assignees']) or '无'} · "
        f"评论 {s['comment_count']} · 参与 {s['participant_count']}"
    )
    lines.append(f"- Link: https://github.com/{card['repo']}/issues/{card['number']}")
    lines.append("")
    return lines


SKIP_LABELS = {
    "resource": "需要你没有的硬件/资源",
    "occupied": "已有人在做",
    "unclear": "信息不足，难判断",
}


def _render_skipped(skipped: dict) -> list[str]:
    groups = [(SKIP_LABELS[cat], skipped.get(cat, [])) for cat in ("resource", "occupied", "unclear")]
    groups = [(label, items) for label, items in groups if items]
    if not groups:
        return []
    total = sum(len(items) for _, items in groups)
    lines = ["", f"## 已跳过（{total}）", ""]
    for label, items in groups:
        refs = ", ".join(f"{i['repo']}#{i['number']}" for i in items)
        lines.append(f"- {label}（{len(items)}）: {refs}")
    return lines


def _render_rec(rec: dict, candidate: dict | None) -> list[str]:
    ref = f"{rec['repo']}#{rec['number']}"
    title = candidate["title"] if candidate else ""
    badges = f"[{rec['priority']}]"
    if rec["occupied"]:
        badges += " [已有人在做]"
    lines = [
        f"### {badges} {ref} {title}",
        f"- 推荐理由: {rec['reason'] or '—'}",
        f"- 资源判断: {rec['resource_note'] or '—'}",
    ]
    if candidate:
        s = candidate["signals"]
        pr = f"#{','.join(map(str, s['linked_open_prs']))}" if s["linked_open_prs"] else "无"
        lines.append(
            f"- 客观信号: open PR {pr} · assignees {', '.join(s['assignees']) or '无'} · "
            f"评论 {s['comment_count']} · 参与 {s['participant_count']}"
        )
        lines.append(f"- Link: https://github.com/{rec['repo']}/issues/{rec['number']}")
    if candidate and candidate.get("prior_decision"):
        prior = candidate["prior_decision"]
        lines.append(f"- 历史: 你以前 {prior['decision']} 过 — {prior['reason']}")
    lines.append("")
    return lines


def _render_raw_candidates(candidates: list[dict]) -> str:
    rows = []
    for c in candidates:
        s = c["signals"]
        occupied = "有人在做" if (s["assignees"] or s["linked_open_prs"]) else "无人认领"
        rows.append(f"- {c['repo']}#{c['number']} {c['title']} （{occupied}）")
    return "\n".join(rows)


def _notify(today, continuing, recommendation, llm_error) -> bool:
    if llm_error:
        return macos_notify("osmind 贡献报告", "判断失败，已写原始候选", f"{today.isoformat()} · 见报告")
    recs = recommendation["recommendations"]
    changed = sum(1 for c in continuing if c.get("changed"))
    tail = f" · 跟进中 {len(continuing)}（{changed} 项上游有更新）" if continuing else ""
    if not recs:
        return macos_notify("osmind 贡献报告", f"本次无新推荐{tail}", today.isoformat())
    high = sum(1 for r in recs if r["priority"] == "high")
    message = f"{len(recs)} 条推荐（{high} 高优）· 首推 {recs[0]['repo']}#{recs[0]['number']}{tail}"
    return macos_notify("osmind 贡献报告", message, today.isoformat())


def _resources(profile: dict) -> str:
    resources = profile.get("resources", {})
    return ", ".join(f"{k}={v}" for k, v in resources.items()) or "未指定"
