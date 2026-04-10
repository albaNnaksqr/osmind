from __future__ import annotations
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
import yaml


@dataclass
class Note:
    repo: str
    pr_number: int
    pr_title: str
    modules: list[str]
    tags: list[str]
    content: str
    pending_questions: list[str] = field(default_factory=list)


def _slug(repo: str, pr_number: int) -> str:
    safe = repo.replace("/", "_")
    return f"{safe}_pr{pr_number}.md"


def _serialize(note: Note) -> str:
    frontmatter = {
        "date": str(date.today()),
        "repo": note.repo,
        "pr": note.pr_number,
        "pr_title": note.pr_title,
        "modules": note.modules,
        "tags": note.tags,
        "pending_questions": note.pending_questions,
    }
    fm_str = yaml.dump(frontmatter, allow_unicode=True, default_flow_style=False)
    return f"---\n{fm_str}---\n\n{note.content}\n"


def _parse(text: str) -> Note:
    match = re.match(r"---\n(.*?)---\n\n(.*)", text, re.DOTALL)
    if not match:
        raise ValueError("Invalid note format")
    fm = yaml.safe_load(match.group(1))
    return Note(
        repo=fm["repo"],
        pr_number=fm["pr"],
        pr_title=fm.get("pr_title", ""),
        modules=fm.get("modules", []),
        tags=fm.get("tags", []),
        pending_questions=fm.get("pending_questions", []),
        content=match.group(2).strip(),
    )


class NotesVault:
    def __init__(self, vault_path: Path):
        self._path = vault_path / "osmind"
        self._path.mkdir(parents=True, exist_ok=True)

    def save(self, note: Note) -> None:
        f = self._path / _slug(note.repo, note.pr_number)
        f.write_text(_serialize(note), encoding="utf-8")

    def load_for_pr(self, repo: str, pr_number: int) -> Note | None:
        f = self._path / _slug(repo, pr_number)
        if not f.exists():
            return None
        return _parse(f.read_text(encoding="utf-8"))

    def list_all(self) -> list[Note]:
        notes = []
        for f in self._path.glob("*.md"):
            try:
                notes.append(_parse(f.read_text(encoding="utf-8")))
            except ValueError:
                continue
        return notes

    def list_pending_questions(self) -> list[tuple[Note, str]]:
        result = []
        for note in self.list_all():
            for q in note.pending_questions:
                result.append((note, q))
        return result

    def append_answer(self, repo: str, pr_number: int, question: str, answer: str) -> None:
        note = self.load_for_pr(repo, pr_number)
        if note is None:
            return
        note.pending_questions = [q for q in note.pending_questions if q != question]
        note.content += f"\n\n**Q: {question}**\n\n{answer}"
        self.save(note)
