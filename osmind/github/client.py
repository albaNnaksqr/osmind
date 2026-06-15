from __future__ import annotations
from github import Github
from osmind.github.models import GHComment, GHIssue, GHPR, PRFile


GITHUB_TIMEOUT_SECONDS = 30
GITHUB_RETRY_ATTEMPTS = 3


def _iso(dt) -> str:
    return dt.isoformat() if dt else ""


class GitHubClient:
    def __init__(self, token: str):
        if token:
            self._gh = Github(token, timeout=GITHUB_TIMEOUT_SECONDS, retry=GITHUB_RETRY_ATTEMPTS)
        else:
            # unauthenticated: public repos, 60 req/hr
            self._gh = Github(timeout=GITHUB_TIMEOUT_SECONDS, retry=GITHUB_RETRY_ATTEMPTS)

    def get_issues(
        self,
        repo: str,
        state: str = "open",
        limit: int = 30,
        include_comments: bool = False,
    ) -> list[GHIssue]:
        r = self._gh.get_repo(repo)
        issues = []
        for i in r.get_issues(state=state):
            if len(issues) >= limit:
                break
            if getattr(i, "pull_request", None):
                continue
            comments = []
            if include_comments:
                for c in i.get_comments():
                    if len(comments) >= 5:
                        break
                    comments.append(GHComment(
                        author=c.user.login if c.user else "",
                        body=c.body or "",
                        url=c.html_url,
                        created_at=_iso(c.created_at),
                    ))
            issues.append(GHIssue(
                number=i.number,
                title=i.title,
                body=i.body or "",
                labels=[l.name for l in i.labels],
                url=i.html_url,
                repo=repo,
                state=i.state,
                updated_at=_iso(i.updated_at),
                comments=comments,
                assignees=[a.login for a in (i.assignees or []) if a],
                comment_count=i.comments or 0,
            ))
        return issues

    def linked_open_prs(self, repo: str, number: int) -> list[int]:
        """Open PRs that cross-reference this issue — i.e. someone may already be on it."""
        issue = self._gh.get_repo(repo).get_issue(number)
        found: list[int] = []
        try:
            for event in issue.get_timeline():
                if getattr(event, "event", "") != "cross-referenced":
                    continue
                source = getattr(event, "source", None)
                source_issue = getattr(source, "issue", None) if source else None
                if source_issue is None or getattr(source_issue, "pull_request", None) is None:
                    continue
                if getattr(source_issue, "state", "") == "open":
                    found.append(source_issue.number)
        except Exception:
            # timeline is best-effort; absence of PR data must not fail the report
            pass
        return sorted(set(found))

    def get_pr(self, repo: str, number: int) -> GHPR:
        r = self._gh.get_repo(repo)
        p = r.get_pull(number)
        files = [
            PRFile(
                filename=f.filename,
                patch=f.patch or "",
                status=f.status or "",
                additions=f.additions or 0,
                deletions=f.deletions or 0,
            )
            for f in p.get_files()
        ]
        return GHPR(
            number=p.number,
            title=p.title,
            body=p.body or "",
            url=p.html_url,
            repo=repo,
            files=files,
            updated_at=_iso(p.updated_at),
        )

    def get_merged_prs(self, repo: str, limit: int = 20) -> list[GHPR]:
        r = self._gh.get_repo(repo)
        prs = []
        for p in r.get_pulls(state="closed", sort="updated", direction="desc"):
            if len(prs) >= limit:
                break
            if p.merged:
                prs.append(GHPR(
                    number=p.number,
                    title=p.title,
                    body=p.body or "",
                    url=p.html_url,
                    repo=repo,
                    updated_at=_iso(p.updated_at),
                ))
        return prs
