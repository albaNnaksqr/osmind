from __future__ import annotations

from dataclasses import asdict
from datetime import date
from pathlib import Path

from osmind.config import Config
from osmind.github.client import GitHubClient
from osmind.github.models import GHIssue, IssueSignals
from osmind.llm import LLMError
from osmind.notify import macos_notify
from osmind.services.recommend import recommend

MAX_CANDIDATES = 30
REPORTS_DIRNAME = "reports"
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


class ReportError(Exception):
    pass


def run_report(config: Config, client: GitHubClient, limit: int = 30, notify: bool = True) -> dict:
    if config.llm is None:
        raise ReportError("report needs `llm:` in profile.yaml (the judgment endpoint)")

    issues, errors = _fetch_issues(config, client, limit)
    if errors and not issues:
        detail = "; ".join(f"{e['repo']}: {e['error']}" for e in errors)
        raise ReportError(f"all repo fetches failed — {detail}")

    candidates = [_enrich(client, issue) for issue in _balanced(issues, MAX_CANDIDATES)]

    llm_error: str | None = None
    recommendation = {"recommendations": [], "skipped": {}, "serendipity_count": 0, "skipped_count": 0}
    if candidates:
        try:
            recommendation = recommend(config.llm, _profile(config), candidates)
        except LLMError as error:
            llm_error = str(error)

    today = date.today()
    path = config.output_dir / REPORTS_DIRNAME / f"{today.isoformat()}.md"
    markdown = _render(today, _profile(config), candidates, recommendation, llm_error, errors)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")

    notified = _notify(today, recommendation, llm_error) if notify else False
    return {
        "path": str(path),
        "date": today.isoformat(),
        "candidates": len(candidates),
        "recommendations": len(recommendation["recommendations"]),
        "serendipity": recommendation.get("serendipity_count", 0),
        "skipped": recommendation.get("skipped_count", 0),
        "llm_error": llm_error,
        "notified": notified,
    }


def _fetch_issues(config: Config, client: GitHubClient, limit: int) -> tuple[list[GHIssue], list[dict]]:
    issues: list[GHIssue] = []
    errors: list[dict] = []
    for watched in config.watching:
        repo = watched["repo"]
        try:
            issues.extend(client.get_issues(repo, limit=limit, include_comments=False))
        except Exception as error:  # network / rate limit — keep cron alive
            errors.append({"repo": repo, "error": _fetch_error_message(error)})
    return issues, errors


def _balanced(issues: list[GHIssue], cap: int) -> list[GHIssue]:
    """Round-robin across repos so a busy repo can't crowd out a quiet one."""
    by_repo: dict[str, list[GHIssue]] = {}
    for issue in issues:
        by_repo.setdefault(issue.repo, []).append(issue)
    for repo_issues in by_repo.values():
        repo_issues.sort(key=lambda i: i.updated_at, reverse=True)
    picked: list[GHIssue] = []
    queues = list(by_repo.values())
    index = 0
    while len(picked) < cap and any(queues):
        queue = queues[index % len(queues)]
        if queue:
            picked.append(queue.pop(0))
        index += 1
    return picked


def _enrich(client: GitHubClient, issue: GHIssue) -> dict:
    try:
        linked = client.linked_open_prs(issue.repo, issue.number)
    except Exception:
        linked = []  # best-effort; thin the detail, never drop the candidate
    signals = IssueSignals(
        number=issue.number,
        labels=issue.labels,
        assignees=issue.assignees,
        comment_count=issue.comment_count,
        linked_open_prs=linked,
        updated_at=issue.updated_at,
    )
    return {
        "repo": issue.repo,
        "number": issue.number,
        "title": issue.title,
        "body": issue.body,
        "signals": asdict(signals),
    }


def _profile(config: Config) -> dict:
    return {
        "interests": config.interests,
        "skills": config.skills,
        "resources": config.resources,
        "watching": [w["repo"] for w in config.watching],
    }


def _render(today, profile, candidates, recommendation, llm_error, errors) -> str:
    by_key = {(c["repo"], c["number"]): c for c in candidates}
    lines = [
        f"# 贡献推荐 - {today.isoformat()}",
        "",
        f"> 关注仓库: {', '.join(profile.get('watching', []))} | 资源: {_resources(profile)}",
        "",
    ]
    for error in errors:
        lines.append(f"> ⚠️ 抓取失败 {error['repo']}: {error['error']}")

    main = [r for r in recommendation["recommendations"] if not r["serendipity"]]
    serendipity = [r for r in recommendation["recommendations"] if r["serendipity"]]
    main.sort(key=lambda r: PRIORITY_ORDER.get(r["priority"], 1))

    lines.append(
        f"推荐 {len(main)} 条 · serendipity {len(serendipity)} 条 · 跳过 {recommendation.get('skipped_count', 0)} 条"
    )
    lines.append("")

    if llm_error:
        lines.extend(
            [
                "## ⚠️ 判断失败",
                "",
                f"LLM 调用失败：{llm_error}",
                "",
                "下面是未排序的候选 issue（原始数据），可稍后重跑 `osmind report`。",
                "",
                _render_raw(candidates),
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
            f"- 客观信号: open PR {pr} · assignees {', '.join(s['assignees']) or '无'} · 评论 {s['comment_count']}"
        )
        lines.append(f"- Link: https://github.com/{rec['repo']}/issues/{rec['number']}")
    lines.append("")
    return lines


def _render_raw(candidates: list[dict]) -> str:
    rows = []
    for c in candidates:
        s = c["signals"]
        occupied = "有人在做" if (s["assignees"] or s["linked_open_prs"]) else "无人认领"
        rows.append(f"- {c['repo']}#{c['number']} {c['title']} （{occupied}）")
    return "\n".join(rows)


def _notify(today, recommendation, llm_error) -> bool:
    if llm_error:
        return macos_notify("osmind 贡献报告", "判断失败，已写原始候选", f"{today.isoformat()} · 见报告")
    recs = recommendation["recommendations"]
    if not recs:
        return macos_notify("osmind 贡献报告", "本次无推荐", today.isoformat())
    high = sum(1 for r in recs if r["priority"] == "high")
    message = f"{len(recs)} 条推荐（{high} 高优）· 首推 {recs[0]['repo']}#{recs[0]['number']}"
    return macos_notify("osmind 贡献报告", message, today.isoformat())


def _resources(profile: dict) -> str:
    resources = profile.get("resources", {})
    return ", ".join(f"{k}={v}" for k, v in resources.items()) or "未指定"


def _fetch_error_message(error: Exception) -> str:
    text = str(error)
    if "rate limit" in text.lower() or "403" in text:
        return "GitHub rate limit hit — set GITHUB_TOKEN for a higher limit"
    return f"{type(error).__name__}: {text}".strip()
