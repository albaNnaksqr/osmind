from __future__ import annotations
from textual.widgets import Tree
from osmind.github.models import GHPR


class DiffViewer(Tree):
    def load_pr(self, pr: GHPR) -> None:
        self.clear()
        self.root.label = f"PR #{pr.number}: {pr.title[:40]}"
        for f in pr.files:
            node = self.root.add(f.filename, expand=False)
            for line in f.patch.splitlines()[:30]:
                node.add_leaf(line)
        self.root.expand()
