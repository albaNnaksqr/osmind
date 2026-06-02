from __future__ import annotations
from textual.widgets import DataTable

from osmind.github.models import GHIssue
from osmind.tui.recommendation import action_from_score, recommended_action


class IssueTable(DataTable):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("cursor_type", "row")
        super().__init__(*args, **kwargs)

    def populate(self, issues: list[GHIssue]) -> None:
        self.clear(columns=True)
        self.add_column("Action", width=8)
        self.add_column("#", width=8)
        self.add_column("Title")
        for issue in sorted(issues, key=lambda item: item.score, reverse=True):
            self.add_row(
                recommended_action(issue),
                str(issue.number),
                issue.title,
                key=str(issue.number),
            )

    def update_score(self, issue_number: str, score: float) -> None:
        """Update the score cell for a given issue number (called during background scoring)."""
        try:
            self.update_cell(issue_number, "Action", action_from_score(score))
        except Exception:
            pass
