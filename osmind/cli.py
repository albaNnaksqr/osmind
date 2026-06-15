from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from osmind.config import Config, ConfigError

DEFAULT_PROFILE_LOCATIONS = (
    Path("profile.yaml"),
    Path("~/.config/osmind/profile.yaml").expanduser(),
)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        config = _load_config(args.profile)
        result = _dispatch(args, config)
    except (ConfigError, FileNotFoundError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except Exception as error:  # report/LLM/network failures surface cleanly
        from osmind.services.report import ReportError

        if isinstance(error, ReportError):
            print(f"error: {error}", file=sys.stderr)
            return 1
        raise

    if getattr(args, "json", False):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(_format_text(args.command, result))
    return 0


def _dispatch(args: argparse.Namespace, config: Config):
    if args.command == "report":
        from osmind.github.client import GitHubClient
        from osmind.services.report import run_report

        client = GitHubClient(os.environ.get("GITHUB_TOKEN", ""))
        return run_report(config, client, limit=args.limit, notify=not args.no_notify)
    if args.command == "profile":
        return {
            "interests": config.interests,
            "skills": config.skills,
            "resources": config.resources,
            "watching": [w["repo"] for w in config.watching],
        }
    raise ValueError(f"Unknown command: {args.command}")


def _format_text(command: str, result) -> str:
    if command == "report":
        lines = [
            f"wrote {result['path']}",
            f"  recommendations: {result['recommendations']}  serendipity: {result['serendipity']}"
            f"  skipped: {result['skipped']}  (candidates judged: {result['candidates']})",
            f"  notified: {result['notified']}",
        ]
        if result["llm_error"]:
            lines.append(f"  LLM error: {result['llm_error']}")
        return "\n".join(lines)
    if command == "profile":
        return json.dumps(result, ensure_ascii=False, indent=2)
    return str(result)


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
    parser = argparse.ArgumentParser(prog="osmind", description="Push a contribution shortlist from watched repos.")
    parser.add_argument("--profile", type=Path, default=None, help="Path to profile.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    report = sub.add_parser("report", help="Fetch, judge contributability via LLM, write a report and notify")
    report.add_argument("--limit", type=int, default=30, help="Max open issues per repo")
    report.add_argument("--no-notify", action="store_true", help="Skip the macOS notification")
    report.add_argument("--json", action="store_true")

    profile = sub.add_parser("profile", help="Show interests, skills, resources, and watched repos")
    profile.add_argument("--json", action="store_true")

    return parser.parse_args(argv)


if __name__ == "__main__":
    sys.exit(main())
