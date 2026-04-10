from __future__ import annotations
from textual.widgets import DataTable
from osmind.github.models import GHIssue


STARS = {(0.7, 1.01): "★★★", (0.4, 0.7): "★★☆", (0.0, 0.4): "★☆☆"}


def _star(score: float) -> str:
    for (lo, hi), label in STARS.items():
        if lo <= score < hi:
            return label
    return "☆☆☆"


class IssueTable(DataTable):
    def populate(self, issues: list[GHIssue]) -> None:
        self.clear(columns=True)
        self.add_columns("Score", "#", "Title", "Labels")
        for issue in issues:
            labels = ", ".join(issue.labels[:3])
            self.add_row(
                _star(issue.score),
                str(issue.number),
                issue.title[:60],
                labels,
                key=str(issue.number),
            )
