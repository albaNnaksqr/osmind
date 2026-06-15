from __future__ import annotations

from dataclasses import asdict
from datetime import date
from pathlib import Path

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
    candidates = _gather_candidates(service)

    llm_error: str | None = None
    recommendation = {"summary": "", "recommendations": [], "serendipity_count": 0}
    if candidates:
        try:
            recommendation = recommend(service.config.llm, service.profile(), candidates)
        except LLMError as error:
            llm_error = str(error)

    today = date.today()
    path = _report_path(service.config.output_dir, today)
    markdown = _render_report(today, service.profile(), candidates, recommendation, llm_error, sync_result)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")

    notified = False
    if notify:
        notified = _notify(today, recommendation, llm_error, path)

    return {
        "path": str(path),
        "date": today.isoformat(),
        "candidates": len(candidates),
        "recommendations": len(recommendation["recommendations"]),
        "serendipity": recommendation.get("serendipity_count", 0),
        "llm_error": llm_error,
        "notified": notified,
    }


def _gather_candidates(service: RadarService) -> list[dict]:
    items = _balanced_candidates(service.queue("active"), MAX_CANDIDATES)
    candidates: list[dict] = []
    client = service._client
    for item in items:
        repo, number = item["repo"], item["number"]
        try:
            signals = client.issue_signals(repo, number)
        except Exception:
            continue  # one flaky issue must not sink the report
        full = service.store.get_item(repo, "issue", number)
        candidates.append(
            {
                "repo": repo,
                "number": number,
                "title": item["title"],
                "body": full["body"] if full else "",
                "signals": asdict(signals),
                "prior_decision": item["decision"],
            }
        )
    return candidates


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


def _render_report(today, profile, candidates, recommendation, llm_error, sync_result) -> str:
    by_key = {(c["repo"], c["number"]): c for c in candidates}
    lines = [
        f"# 贡献推荐 - {today.isoformat()}",
        "",
        f"> 关注仓库: {', '.join(profile.get('watching', []))} | 候选 {len(candidates)} 条 | 资源: {_resources(profile)}",
        "",
    ]
    for error in sync_result.get("errors", []):
        lines.append(f"> ⚠️ 抓取失败 {error['repo']}: {error['error']}")
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

    if recommendation.get("summary"):
        lines.extend([recommendation["summary"], ""])

    main = [r for r in recommendation["recommendations"] if not r["serendipity"]]
    serendipity = [r for r in recommendation["recommendations"] if r["serendipity"]]
    main.sort(key=lambda r: PRIORITY_ORDER.get(r["priority"], 1))

    if main:
        lines.extend(["## 推荐贡献", ""])
        for rec in main:
            lines.extend(_render_rec(rec, by_key.get((rec["repo"], rec["number"]))))
    if serendipity:
        lines.extend(["## 跳出兴趣（serendipity）", ""])
        for rec in serendipity:
            lines.extend(_render_rec(rec, by_key.get((rec["repo"], rec["number"]))))
    if not recommendation["recommendations"]:
        lines.append("本次没有产出推荐。")
    lines.extend(_render_skipped(recommendation.get("skipped", {})))
    return "\n".join(lines).rstrip() + "\n"


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


def _notify(today, recommendation, llm_error, path) -> bool:
    if llm_error:
        return macos_notify("osmind 贡献报告", "判断失败，已写原始候选", f"{today.isoformat()} · 见报告")
    recs = recommendation["recommendations"]
    if not recs:
        return macos_notify("osmind 贡献报告", "本次无推荐", today.isoformat())
    top = recs[0]
    high = sum(1 for r in recs if r["priority"] == "high")
    message = f"{len(recs)} 条推荐（{high} 高优）· 首推 {top['repo']}#{top['number']}"
    return macos_notify("osmind 贡献报告", message, today.isoformat())


def _resources(profile: dict) -> str:
    resources = profile.get("resources", {})
    return ", ".join(f"{k}={v}" for k, v in resources.items()) or "未指定"
