from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from osmind.cache.store import CacheStore, issue_content_signature
from osmind.config import Config
from osmind.github.client import GitHubClient

VALID_DECISIONS = ("continue", "defer", "discard")
QUEUE_FILTERS = ("active", "undecided", "continue", "deferred", "discarded", "resurfaced", "all")

DECISION_LOG_RELATIVE = Path("Sources/Issue_Radar/Decision_Log.md")
DECISION_LOG_HEADER = (
    "# Issue Radar Decision Log\n"
    "\n"
    "> 由 `osmind decide` 自动追加。osmind 的 SQLite 是 canonical 状态源，此文件只是可检索的镜像。\n"
    "\n"
)


class RadarError(Exception):
    pass


class RadarService:
    def __init__(self, config: Config, store: CacheStore, client: GitHubClient | None = None):
        self.config = config
        self.store = store
        self._client = client

    def sync(self, limit: int = 30) -> dict:
        client = self._require_client()
        repos: list[dict] = []
        errors: list[dict] = []
        for watched in self.config.watching:
            repo = watched["repo"]
            try:
                # list-only: change detection keys off comment_count + updated_at,
                # so we skip the per-issue comment fetch that made sync fragile.
                issues = client.get_issues(repo, limit=limit, include_comments=False)
            except Exception as error:  # network, auth, rate limit — keep cron alive
                errors.append({"repo": repo, "error": _fetch_error_message(error)})
                continue
            new: list[int] = []
            changed: list[int] = []
            unchanged = 0
            for issue in issues:
                _, _, body_hash, content_hash = issue_content_signature(issue)
                existing = self.store.get_item(repo, "issue", issue.number)
                if existing is None:
                    new.append(issue.number)
                elif (
                    existing["body_hash"] != body_hash
                    or existing["content_hash"] != content_hash
                    or existing["updated_at"] != issue.updated_at
                ):
                    changed.append(issue.number)
                else:
                    unchanged += 1
                self.store.upsert_issue(issue)
            repos.append(
                {
                    "repo": repo,
                    "fetched": len(issues),
                    "new": new,
                    "changed": changed,
                    "unchanged": unchanged,
                }
            )
        if errors and not repos:
            detail = "; ".join(f"{e['repo']}: {e['error']}" for e in errors)
            raise RadarError(f"all repo fetches failed — {detail}")
        return {"synced_at": _now(), "repos": repos, "errors": errors}

    def queue(self, status_filter: str = "active") -> list[dict]:
        if status_filter not in QUEUE_FILTERS:
            raise RadarError(f"Unknown queue filter: {status_filter} (expected one of {', '.join(QUEUE_FILTERS)})")
        items: list[dict] = []
        for watched in self.config.watching:
            repo = watched["repo"]
            decisions = self.store.latest_decisions(repo)
            for row in self.store.list_item_rows(repo):
                if row["state"] != "open":
                    continue
                item = self._queue_item(row, decisions.get(int(row["number"])))
                if _matches_filter(item, status_filter):
                    items.append(item)
        return items

    def show(self, repo: str, number: int) -> dict:
        item = self.store.get_item(repo, "issue", number)
        if item is None:
            raise RadarError(f"{repo}#{number} is not in the local store. Run `osmind sync` first.")
        decisions = self.store.latest_decisions(repo)
        queue_item = self._queue_item(item, decisions.get(number))
        queue_item["body"] = item["body"]
        queue_item["comments"] = _parse_json(item["comments_json"], [])
        queue_item["decision_log"] = [
            _public_decision(entry) for entry in self.store.decision_log(repo, "issue", number)
        ]
        return queue_item

    def decide(self, repo: str, number: int, decision: str, reason: str) -> dict:
        if decision not in VALID_DECISIONS:
            raise RadarError(f"Unknown decision: {decision} (expected one of {', '.join(VALID_DECISIONS)})")
        if not reason.strip():
            raise RadarError("A decision needs a --reason; future-you will want to know why.")
        if self.store.get_item(repo, "issue", number) is None:
            raise RadarError(f"{repo}#{number} is not in the local store. Run `osmind sync` first.")
        recorded = self.store.record_decision(
            repo, "issue", number, decision, reason.strip(), self.config.resources
        )
        mirror_path = self._mirror_decision(repo, number, decision, reason.strip())
        result = _public_decision(recorded)
        result["repo"] = repo
        result["number"] = number
        result["mirrored_to"] = str(mirror_path) if mirror_path else None
        return result

    def profile(self) -> dict:
        return {
            "interests": self.config.interests,
            "skills": self.config.skills,
            "resources": self.config.resources,
            "watching": [watched["repo"] for watched in self.config.watching],
            "vault": str(self.config.vault) if self.config.vault else None,
        }

    def _queue_item(self, row: dict, decision: dict | None) -> dict:
        status, resurfaced_because = self._status_for(row, decision)
        return {
            "repo": row["repo"],
            "number": int(row["number"]),
            "title": row["title"],
            "state": row["state"],
            "url": row["url"],
            "labels": _parse_json(row["labels_json"], []),
            "updated_at": row["updated_at"],
            "status": status,
            "resurfaced_because": resurfaced_because,
            "decision": _public_decision(decision) if decision else None,
        }

    def _status_for(self, row: dict, decision: dict | None) -> tuple[str, list[str]]:
        if decision is None:
            return "undecided", []
        if decision["decision"] == "continue":
            return "continue", []
        because: list[str] = []
        if decision["content_hash"] and decision["content_hash"] != row["content_hash"]:
            because.append("content_changed")
        if decision["resources_json"]:
            current = json.dumps(self.config.resources, sort_keys=True, ensure_ascii=False)
            if decision["resources_json"] != current:
                because.append("resources_changed")
        if because:
            return "resurfaced", because
        return "deferred" if decision["decision"] == "defer" else "discarded", []

    def _mirror_decision(self, repo: str, number: int, decision: str, reason: str) -> Path | None:
        if self.config.vault is None:
            return None
        path = self.config.vault / DECISION_LOG_RELATIVE
        path.parent.mkdir(parents=True, exist_ok=True)
        resources = ", ".join(f"{key}={value}" for key, value in self.config.resources.items()) or "unspecified"
        line = f"- {_now()} {repo}#{number} → {decision} — {reason}（resources: {resources}）\n"
        if path.exists():
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line)
        else:
            path.write_text(DECISION_LOG_HEADER + line, encoding="utf-8")
        return path

    def _require_client(self) -> GitHubClient:
        if self._client is None:
            raise RadarError("No GitHub client configured")
        return self._client


def parse_item_ref(ref: str) -> tuple[str, int]:
    repo, separator, number = ref.partition("#")
    if not separator or "/" not in repo or not number.isdigit():
        raise RadarError(f"Expected <owner>/<name>#<number>, got: {ref}")
    return repo, int(number)


def _matches_filter(item: dict, status_filter: str) -> bool:
    if status_filter == "all":
        return True
    if status_filter == "active":
        return item["status"] in {"undecided", "continue", "resurfaced"}
    return item["status"] == status_filter


def _public_decision(decision: dict | None) -> dict | None:
    if decision is None:
        return None
    return {
        "decision": decision["decision"],
        "reason": decision["reason"],
        "decided_at": decision["decided_at"],
        "resources": _parse_json(decision["resources_json"], None),
    }


def _parse_json(raw: str, fallback):
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return fallback


def _fetch_error_message(error: Exception) -> str:
    text = str(error)
    if "rate limit" in text.lower() or "403" in text:
        return "GitHub rate limit hit — set GITHUB_TOKEN for a higher limit"
    return f"{type(error).__name__}: {text}".strip()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")
