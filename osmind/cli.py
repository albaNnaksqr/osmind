from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from osmind.cache.store import CacheStore
from osmind.config import Config, ConfigError
from osmind.services.radar import QUEUE_FILTERS, RadarError, RadarService, parse_item_ref

DEFAULT_PROFILE_LOCATIONS = (
    Path("profile.yaml"),
    Path("~/.config/osmind/profile.yaml").expanduser(),
)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    try:
        config = _load_config(args.profile)
        service = _build_service(config, with_client=args.command in {"sync", "digest"})
        result = _dispatch(args, service)
    except (ConfigError, RadarError, FileNotFoundError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if getattr(args, "json", False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(_format_text(args.command, result))
    return 0


def _dispatch(args: argparse.Namespace, service: RadarService):
    if args.command == "sync":
        return service.sync(limit=args.limit)
    if args.command == "digest":
        from osmind.services.digest import run_digest

        return run_digest(service, limit=args.limit)
    if args.command == "queue":
        return service.queue(args.filter)
    if args.command == "show":
        repo, number = parse_item_ref(args.item)
        return service.show(repo, number)
    if args.command == "decide":
        repo, number = parse_item_ref(args.item)
        return service.decide(repo, number, args.decision, args.reason)
    if args.command == "profile":
        return service.profile()
    raise RadarError(f"Unknown command: {args.command}")


def _format_text(command: str, result) -> str:
    if command == "digest":
        counts = result["counts"]
        lines = [
            f"wrote {result['path']}",
            f"  new: {result['new']}  resurfaced: {result['resurfaced']}  continue changed: {result['continue_changed']}",
            f"  active queue: {counts['active']} (undecided {counts['undecided']}, continue {counts['continue']}, resurfaced {counts['resurfaced']})",
        ]
        for error in result.get("errors", []):
            lines.append(f"  skipped {error['repo']}: {error['error']}")
        return "\n".join(lines)
    if command == "sync":
        lines = []
        for repo in result["repos"]:
            new = ", ".join(f"#{n}" for n in repo["new"]) or "none"
            changed = ", ".join(f"#{n}" for n in repo["changed"]) or "none"
            lines.append(
                f"{repo['repo']}: {repo['fetched']} fetched | new: {new} | changed: {changed} | {repo['unchanged']} unchanged"
            )
        for error in result.get("errors", []):
            lines.append(f"{error['repo']}: SKIPPED — {error['error']}")
        return "\n".join(lines) if lines else "nothing watched"
    if command == "queue":
        if not result:
            return "queue is empty"
        lines = []
        for item in result:
            marker = item["status"]
            if item["status"] == "resurfaced":
                marker += f" ({', '.join(item['resurfaced_because'])})"
            lines.append(f"{item['repo']}#{item['number']}  [{marker}]  {item['title']}")
        return "\n".join(lines)
    if command == "show":
        lines = [
            f"{result['repo']}#{result['number']}: {result['title']}",
            f"{result['url']}",
            f"status: {result['status']}  labels: {', '.join(result['labels']) or 'none'}  updated: {result['updated_at']}",
        ]
        for entry in result["decision_log"]:
            lines.append(f"  - {entry['decided_at']} {entry['decision']}: {entry['reason']}")
        lines.extend(["", result["body"] or "(no body)"])
        for comment in result["comments"]:
            lines.extend(["", f"--- {comment.get('author', '')} ({comment.get('created_at', '')})", comment.get("body", "")])
        return "\n".join(lines)
    if command == "decide":
        mirrored = f" (mirrored to {result['mirrored_to']})" if result.get("mirrored_to") else ""
        return f"{result['repo']}#{result['number']} → {result['decision']}: {result['reason']}{mirrored}"
    if command == "profile":
        return json.dumps(result, ensure_ascii=False, indent=2)
    return str(result)


def _build_service(config: Config, *, with_client: bool) -> RadarService:
    cache_path = config.output_dir / "osmind" / ".cache" / "osmind.db"
    store = CacheStore(cache_path)
    client = None
    if with_client:
        from osmind.github.client import GitHubClient

        client = GitHubClient(os.environ.get("GITHUB_TOKEN", ""))
    return RadarService(config, store, client)


def _load_config(profile: Path | None) -> Config:
    if profile is not None:
        if not profile.exists():
            raise ConfigError(f"profile not found: {profile}")
        return Config.from_file(profile)
    env_profile = os.environ.get("OSMIND_PROFILE")
    candidates = [Path(env_profile).expanduser()] if env_profile else list(DEFAULT_PROFILE_LOCATIONS)
    for candidate in candidates:
        if candidate.exists():
            return Config.from_file(candidate)
    raise ConfigError(
        "no profile.yaml found (looked at: "
        + ", ".join(str(c) for c in candidates)
        + "); pass --profile or set OSMIND_PROFILE"
    )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="osmind", description="Watch repos, remember decisions, feed agents.")
    parser.add_argument("--profile", type=Path, default=None, help="Path to profile.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    sync = sub.add_parser("sync", help="Fetch watched repos and update the local store")
    sync.add_argument("--limit", type=int, default=30, help="Max open issues per repo")
    sync.add_argument("--json", action="store_true")

    digest = sub.add_parser("digest", help="Sync, then write a Markdown digest into the vault")
    digest.add_argument("--limit", type=int, default=30, help="Max open issues per repo")
    digest.add_argument("--json", action="store_true")

    queue = sub.add_parser("queue", help="List watched items with decision state")
    queue.add_argument("--filter", choices=QUEUE_FILTERS, default="active")
    queue.add_argument("--json", action="store_true")

    show = sub.add_parser("show", help="Show one item with body, comments, and decision log")
    show.add_argument("item", help="<owner>/<name>#<number>")
    show.add_argument("--json", action="store_true")

    decide = sub.add_parser("decide", help="Record a decision for an item")
    decide.add_argument("item", help="<owner>/<name>#<number>")
    decide.add_argument("decision", choices=["continue", "defer", "discard"])
    decide.add_argument("--reason", required=True, help="Why — future-you will read this")
    decide.add_argument("--json", action="store_true")

    profile = sub.add_parser("profile", help="Show interests, skills, resources, and watched repos")
    profile.add_argument("--json", action="store_true")

    return parser.parse_args(argv)


if __name__ == "__main__":
    sys.exit(main())
