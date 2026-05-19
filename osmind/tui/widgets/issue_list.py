from __future__ import annotations
from textual.widgets import DataTable

from osmind.github.models import GHIssue
from osmind.tui.recommendation import action_from_score, action_why, recommended_action


class IssueTable(DataTable):
    def populate(self, issues: list[GHIssue]) -> None:
        self.clear(columns=True)
        self.add_columns("Action", "Why", "#", "Title", "Labels")
        for issue in sorted(issues, key=lambda item: item.score, reverse=True):
            labels = ", ".join(issue.labels[:3])
            self.add_row(
                recommended_action(issue),
                action_why(issue),
                str(issue.number),
                issue.title[:60],
                labels,
                key=str(issue.number),
            )

    def update_score(self, issue_number: str, score: float) -> None:
        """Update the score cell for a given issue number (called during background scoring)."""
        try:
            self.update_cell(issue_number, "Action", action_from_score(score))
        except Exception:
            pass
