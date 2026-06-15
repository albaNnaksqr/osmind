from __future__ import annotations

import json

from osmind.config import LLMConfig
from osmind.llm import chat_json

SERENDIPITY_MIN = 1
SERENDIPITY_MAX = 2
BODY_TRUNCATE = 600

SYSTEM_PROMPT = """\
你是一个开源贡献顾问。用户长期关注若干仓库，想知道现在有哪些 issue 值得自己去贡献。
你要结合三类信息做判断，而不是只看 issue 和兴趣是否字面匹配：

1. 用户的资源约束（GPU、时间）——需要的资源远超用户拥有的，即使再相关也要降级。
2. 用户的兴趣和技能——匹配的优先，但不是唯一标准。
3. 客观事实——是否已经有 open PR 在做（has_open_pr）、是否已指派（assignees）、参与人数（participant_count）、是否长期没人动（stale）。已经有人在做或已指派的，贡献价值低，要降级或标注。

排序给出一个推荐贡献列表。每条要有具体理由和资源判断，证据不足就直说，不要硬推。

额外要求：必须包含 1-2 个 serendipity 项——刻意挑用户兴趣点之外、但你认为有意思或值得贡献的 issue，帮用户跳出自己的兴趣茧房。这些项标 serendipity=true。

只输出 JSON，结构：
{
  "summary": "一句话总览",
  "recommendations": [
    {
      "repo": "owner/name",
      "number": 123,
      "priority": "high|medium|low",
      "reason": "为什么推荐，中文",
      "resource_note": "资源是否够，中文",
      "occupied": true/false,
      "serendipity": true/false
    }
  ]
}
按 priority 从高到低排序。不要推荐 occupied 且无独特价值的项。"""


def build_user_prompt(profile: dict, candidates: list[dict]) -> str:
    lines = [
        "## 用户画像",
        f"- 兴趣: {', '.join(profile.get('interests', [])) or '未填写'}",
        f"- 技能: {', '.join(profile.get('skills', [])) or '未填写'}",
        f"- 资源: {_format_resources(profile.get('resources', {}))}",
        "",
        f"## 候选 issue（{len(candidates)} 条，未按兴趣预筛，serendipity 请从这里挑）",
        "",
    ]
    for item in candidates:
        signals = item["signals"]
        lines.append(f"### {item['repo']}#{item['number']} {item['title']}")
        lines.append(f"- labels: {', '.join(signals['labels']) or 'none'}")
        lines.append(
            f"- 客观信号: comments={signals['comment_count']}, participants={signals['participant_count']}, "
            f"assignees={', '.join(signals['assignees']) or 'none'}, "
            f"open_pr={'yes #' + ','.join(map(str, signals['linked_open_prs'])) if signals['linked_open_prs'] else 'no'}, "
            f"last_update={signals['updated_at'] or 'unknown'}"
        )
        if item.get("prior_decision"):
            prior = item["prior_decision"]
            lines.append(f"- 历史决策: 你以前 {prior['decision']} 过 — {prior['reason']}")
        body = (item.get("body") or "").strip().replace("\r", "")
        if body:
            lines.append(f"- 摘要: {body[:BODY_TRUNCATE]}")
        lines.append("")
    return "\n".join(lines)


def recommend(llm: LLMConfig, profile: dict, candidates: list[dict]) -> dict:
    if not candidates:
        return {"summary": "没有候选 issue", "recommendations": []}
    result = chat_json(llm, SYSTEM_PROMPT, build_user_prompt(profile, candidates))
    return _normalize(result, candidates)


def _normalize(result: dict, candidates: list[dict]) -> dict:
    valid_keys = {(c["repo"], c["number"]) for c in candidates}
    recommendations = []
    for raw in result.get("recommendations", []) or []:
        try:
            repo = str(raw["repo"])
            number = int(raw["number"])
        except (KeyError, TypeError, ValueError):
            continue
        if (repo, number) not in valid_keys:
            continue  # never invent issues the model hallucinated
        recommendations.append(
            {
                "repo": repo,
                "number": number,
                "priority": str(raw.get("priority", "medium")).lower(),
                "reason": str(raw.get("reason", "")).strip(),
                "resource_note": str(raw.get("resource_note", "")).strip(),
                "occupied": bool(raw.get("occupied", False)),
                "serendipity": bool(raw.get("serendipity", False)),
            }
        )
    return {
        "summary": str(result.get("summary", "")).strip(),
        "recommendations": recommendations,
        "serendipity_count": sum(1 for r in recommendations if r["serendipity"]),
    }


def _format_resources(resources: dict) -> str:
    if not resources:
        return "未指定"
    return ", ".join(f"{k}={v}" for k, v in resources.items())
