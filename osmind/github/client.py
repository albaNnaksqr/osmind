from __future__ import annotations
from github import Github
from osmind.github.models import GHIssue, GHPR, PRFile


class GitHubClient:
    def __init__(self, token: str):
        self._gh = Github(token)

    def get_issues(self, repo: str, state: str = "open", limit: int = 30) -> list[GHIssue]:
        r = self._gh.get_repo(repo)
        issues = []
        for i in r.get_issues(state=state):
            if len(issues) >= limit:
                break
            issues.append(GHIssue(
                number=i.number,
                title=i.title,
                body=i.body or "",
                labels=[l.name for l in i.labels],
                url=i.html_url,
                repo=repo,
                state=i.state,
            ))
        return issues

    def get_pr(self, repo: str, number: int) -> GHPR:
        r = self._gh.get_repo(repo)
        p = r.get_pull(number)
        files = [
            PRFile(filename=f.filename, patch=f.patch or "")
            for f in p.get_files()
        ]
        return GHPR(
            number=p.number,
            title=p.title,
            body=p.body or "",
            url=p.html_url,
            repo=repo,
            files=files,
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
                ))
        return prs
