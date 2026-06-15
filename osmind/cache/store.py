from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from osmind.github.models import GHComment, GHIssue


class CacheStore:
    def __init__(self, db_path: Path):
        self._path = db_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS github_items (
                    repo TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    number INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    body_hash TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    state TEXT NOT NULL,
                    url TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (repo, source_type, number)
                )
                """
            )
            self._migrate_github_items_schema()
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS analysis (
                    repo TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    number INTEGER NOT NULL,
                    model TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    input_hash TEXT NOT NULL,
                    scores_json TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    error TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (repo, source_type, number, model, prompt_version, input_hash)
                )
                """
            )
            self._create_packs_table()
            self._migrate_packs_schema()
            self._recover_interrupted_pack_migration()
            decisions_existed = self._table_exists("decisions")
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS decisions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo TEXT NOT NULL,
                    source_type TEXT NOT NULL DEFAULT 'issue',
                    number INTEGER NOT NULL,
                    decision TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    resources_json TEXT NOT NULL DEFAULT '',
                    content_hash TEXT NOT NULL DEFAULT '',
                    decided_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            if not decisions_existed:
                self._seed_decisions_from_packs()
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def _migrate_github_items_schema(self) -> None:
        columns = self._pack_columns("github_items")
        migrations = {
            "body": "TEXT NOT NULL DEFAULT ''",
            "labels_json": "TEXT NOT NULL DEFAULT '[]'",
            "comments_json": "TEXT NOT NULL DEFAULT '[]'",
            "score": "REAL NOT NULL DEFAULT 0",
            "reason": "TEXT NOT NULL DEFAULT ''",
            "priority": "TEXT NOT NULL DEFAULT 'unknown'",
            "fit": "TEXT NOT NULL DEFAULT 'unknown'",
            "resource_fit": "TEXT NOT NULL DEFAULT 'unknown'",
            "actionability": "TEXT NOT NULL DEFAULT 'unknown'",
            "ranked_at": "TEXT NOT NULL DEFAULT ''",
            "comment_count": "INTEGER NOT NULL DEFAULT 0",
        }
        for column, definition in migrations.items():
            if column not in columns:
                self._conn.execute(f"ALTER TABLE github_items ADD COLUMN {column} {definition}")

    def _create_packs_table(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS packs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repo TEXT NOT NULL,
                source_type TEXT NOT NULL,
                number INTEGER NOT NULL,
                path TEXT NOT NULL,
                status TEXT NOT NULL,
                decision TEXT NOT NULL DEFAULT 'undecided',
                decision_resource_hash TEXT NOT NULL DEFAULT '',
                confidence TEXT NOT NULL,
                source_updated_at TEXT NOT NULL,
                generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                stale INTEGER NOT NULL DEFAULT 0,
                version INTEGER NOT NULL DEFAULT 0,
                UNIQUE (repo, source_type, number)
            )
            """
        )

    def _migrate_packs_schema(self) -> None:
        columns = self._pack_columns("packs")
        if "decision" not in columns:
            self._conn.execute("ALTER TABLE packs ADD COLUMN decision TEXT NOT NULL DEFAULT 'undecided'")
            columns.add("decision")
        if "decision_resource_hash" not in columns:
            self._conn.execute("ALTER TABLE packs ADD COLUMN decision_resource_hash TEXT NOT NULL DEFAULT ''")
            columns.add("decision_resource_hash")
        if {"id", "version"}.issubset(columns):
            return

        legacy_rows = self._conn.execute(
            """
            SELECT
                repo, source_type, number, path, status, decision, decision_resource_hash,
                confidence, source_updated_at, generated_at, stale
            FROM packs
            ORDER BY generated_at ASC, rowid ASC
            """
        ).fetchall()
        self._conn.execute("ALTER TABLE packs RENAME TO packs_old")
        self._create_packs_table()
        self._copy_pack_rows(legacy_rows, start_version=1)
        self._conn.execute("DROP TABLE packs_old")

    def _recover_interrupted_pack_migration(self) -> None:
        if not self._table_exists("packs_old"):
            return

        old_columns = self._pack_columns("packs_old")
        decision_expr = "decision" if "decision" in old_columns else "'undecided' AS decision"
        decision_resource_expr = (
            "decision_resource_hash"
            if "decision_resource_hash" in old_columns
            else "'' AS decision_resource_hash"
        )
        current_version = self._conn.execute("SELECT COALESCE(MAX(version), 0) AS current_version FROM packs").fetchone()
        legacy_rows = self._conn.execute(
            f"""
            SELECT
                repo, source_type, number, path, status, {decision_expr}, {decision_resource_expr},
                confidence, source_updated_at, generated_at, stale
            FROM packs_old
            WHERE NOT EXISTS (
                SELECT 1
                FROM packs
                WHERE packs.repo = packs_old.repo
                    AND packs.source_type = packs_old.source_type
                    AND packs.number = packs_old.number
            )
            ORDER BY generated_at ASC, rowid ASC
            """
        ).fetchall()
        self._copy_pack_rows(legacy_rows, start_version=int(current_version["current_version"]) + 1)
        self._conn.execute("DROP TABLE packs_old")

    def _copy_pack_rows(self, rows: list[sqlite3.Row], start_version: int) -> None:
        for offset, row in enumerate(rows):
            self._conn.execute(
                """
                INSERT INTO packs
                    (
                        repo, source_type, number, path, status, decision, decision_resource_hash,
                        confidence, source_updated_at, generated_at, stale, version
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["repo"],
                    row["source_type"],
                    row["number"],
                    row["path"],
                    row["status"],
                    row["decision"],
                    row["decision_resource_hash"],
                    row["confidence"],
                    row["source_updated_at"],
                    row["generated_at"],
                    row["stale"],
                    start_version + offset,
                ),
            )

    def _seed_decisions_from_packs(self) -> None:
        if not self._table_exists("packs"):
            return
        rows = self._conn.execute(
            """
            SELECT
                p.repo, p.source_type, p.number, p.decision, p.generated_at,
                COALESCE(g.content_hash, '') AS content_hash
            FROM packs p
            LEFT JOIN github_items g
                ON g.repo = p.repo AND g.source_type = p.source_type AND g.number = p.number
            WHERE p.decision IN ('continue', 'defer', 'discard')
            ORDER BY p.version ASC
            """
        ).fetchall()
        for row in rows:
            self._conn.execute(
                """
                INSERT INTO decisions
                    (repo, source_type, number, decision, reason, resources_json, content_hash, decided_at)
                VALUES (?, ?, ?, ?, 'migrated from contribution packet', '', ?, ?)
                """,
                (
                    row["repo"],
                    row["source_type"],
                    row["number"],
                    row["decision"],
                    row["content_hash"],
                    row["generated_at"],
                ),
            )

    def record_decision(
        self,
        repo: str,
        source_type: str,
        number: int,
        decision: str,
        reason: str,
        resources: dict | None = None,
    ) -> dict[str, Any]:
        item = self._conn.execute(
            "SELECT content_hash FROM github_items WHERE repo = ? AND source_type = ? AND number = ?",
            (repo, source_type, number),
        ).fetchone()
        content_hash = item["content_hash"] if item is not None else ""
        resources_json = json.dumps(resources, sort_keys=True, ensure_ascii=False) if resources is not None else ""
        try:
            cursor = self._conn.execute(
                """
                INSERT INTO decisions (repo, source_type, number, decision, reason, resources_json, content_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (repo, source_type, number, decision, reason, resources_json, content_hash),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        row = self._conn.execute("SELECT * FROM decisions WHERE id = ?", (cursor.lastrowid,)).fetchone()
        return dict(row)

    def latest_decisions(self, repo: str, source_type: str = "issue") -> dict[int, dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT d.*
            FROM decisions d
            JOIN (
                SELECT MAX(id) AS max_id
                FROM decisions
                WHERE repo = ? AND source_type = ?
                GROUP BY number
            ) latest ON d.id = latest.max_id
            """,
            (repo, source_type),
        ).fetchall()
        return {int(row["number"]): dict(row) for row in rows}

    def decision_log(self, repo: str, source_type: str, number: int) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT * FROM decisions
            WHERE repo = ? AND source_type = ? AND number = ?
            ORDER BY id ASC
            """,
            (repo, source_type, number),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_item(self, repo: str, source_type: str, number: int) -> dict[str, Any] | None:
        row = self._conn.execute(
            """
            SELECT
                repo, source_type, number, title, body, body_hash, content_hash, state, url,
                updated_at, fetched_at, labels_json, comments_json
            FROM github_items
            WHERE repo = ? AND source_type = ? AND number = ?
            """,
            (repo, source_type, number),
        ).fetchone()
        return dict(row) if row is not None else None

    def list_item_rows(self, repo: str, source_type: str = "issue") -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT
                repo, source_type, number, title, state, url, updated_at, fetched_at,
                labels_json, content_hash
            FROM github_items
            WHERE repo = ? AND source_type = ?
            ORDER BY updated_at DESC, number DESC
            """,
            (repo, source_type),
        ).fetchall()
        return [dict(row) for row in rows]

    def _pack_columns(self, table_name: str) -> set[str]:
        rows = self._conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {row["name"] for row in rows}

    def _table_exists(self, table_name: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        return row is not None

    def upsert_item(
        self,
        repo: str,
        source_type: str,
        number: int,
        title: str,
        body_hash: str,
        content_hash: str,
        state: str,
        url: str,
        updated_at: str,
    ) -> None:
        try:
            self._conn.execute(
                """
                INSERT INTO github_items
                    (repo, source_type, number, title, body_hash, content_hash, state, url, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(repo, source_type, number) DO UPDATE SET
                    title = excluded.title,
                    body_hash = excluded.body_hash,
                    content_hash = excluded.content_hash,
                    state = excluded.state,
                    url = excluded.url,
                    updated_at = excluded.updated_at,
                    fetched_at = CURRENT_TIMESTAMP
                """,
                (repo, source_type, number, title, body_hash, content_hash, state, url, updated_at),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def is_item_stale(
        self,
        repo: str,
        source_type: str,
        number: int,
        body_hash: str,
        content_hash: str,
        updated_at: str,
    ) -> bool:
        row = self._conn.execute(
            """
            SELECT body_hash, content_hash, updated_at
            FROM github_items
            WHERE repo = ? AND source_type = ? AND number = ?
            """,
            (repo, source_type, number),
        ).fetchone()
        if row is None:
            return True

        return (
            row["body_hash"] != body_hash
            or row["content_hash"] != content_hash
            or row["updated_at"] != updated_at
        )

    def upsert_issue(self, issue: GHIssue) -> None:
        labels_json, comments_json, body_hash, content_hash = issue_content_signature(issue)
        try:
            self._conn.execute(
                """
                INSERT INTO github_items
                    (
                        repo, source_type, number, title, body_hash, content_hash,
                        state, url, updated_at, body, labels_json, comments_json,
                        comment_count, score, reason
                    )
                VALUES (?, 'issue', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(repo, source_type, number) DO UPDATE SET
                    title = excluded.title,
                    body_hash = excluded.body_hash,
                    content_hash = excluded.content_hash,
                    state = excluded.state,
                    url = excluded.url,
                    updated_at = excluded.updated_at,
                    body = excluded.body,
                    labels_json = excluded.labels_json,
                    -- keep cached comment bodies when this sync did not fetch them
                    comments_json = CASE
                        WHEN excluded.comments_json NOT IN ('[]', '')
                        THEN excluded.comments_json
                        ELSE github_items.comments_json
                    END,
                    comment_count = excluded.comment_count,
                    fetched_at = CURRENT_TIMESTAMP
                """,
                (
                    issue.repo,
                    issue.number,
                    issue.title,
                    body_hash,
                    content_hash,
                    issue.state,
                    issue.url,
                    issue.updated_at,
                    issue.body,
                    labels_json,
                    comments_json,
                    issue.comment_count or len(issue.comments),
                    issue.score,
                    issue.reason,
                ),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def update_issue_score(
        self,
        repo: str,
        source_type: str,
        number: int,
        score: float,
        reason: str,
        *,
        priority: str = "unknown",
        fit: str = "unknown",
        resource_fit: str = "unknown",
        actionability: str = "unknown",
    ) -> None:
        try:
            self._conn.execute(
                """
                UPDATE github_items
                SET score = ?,
                    reason = ?,
                    priority = ?,
                    fit = ?,
                    resource_fit = ?,
                    actionability = ?,
                    ranked_at = CURRENT_TIMESTAMP
                WHERE repo = ? AND source_type = ? AND number = ?
                """,
                (score, reason, priority, fit, resource_fit, actionability, repo, source_type, number),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def list_issues(self, repo: str) -> list[GHIssue]:
        rows = self._conn.execute(
            """
            SELECT
                repo, number, title, body, labels_json, comments_json, state, url, updated_at,
                score, reason, priority, fit, resource_fit, actionability
            FROM github_items
            WHERE repo = ? AND source_type = 'issue'
            ORDER BY fetched_at DESC, number DESC
            """,
            (repo,),
        ).fetchall()
        return [_issue_from_row(row) for row in rows]

    def issue_activity(self, repo: str) -> dict[str, Any]:
        row = self._conn.execute(
            """
            SELECT
                COUNT(*) AS issue_count,
                MAX(fetched_at) AS last_fetched_at,
                MAX(NULLIF(ranked_at, '')) AS last_ranked_at,
                SUM(CASE WHEN NULLIF(ranked_at, '') IS NULL THEN 1 ELSE 0 END) AS unranked_count
            FROM github_items
            WHERE repo = ? AND source_type = 'issue'
            """,
            (repo,),
        ).fetchone()
        pack_row = self._conn.execute(
            """
            SELECT COUNT(*) AS packet_count
            FROM packs
            WHERE repo = ? AND source_type = 'issue'
            """,
            (repo,),
        ).fetchone()
        return {
            "issue_count": int(row["issue_count"] or 0),
            "last_fetched_at": row["last_fetched_at"],
            "last_ranked_at": row["last_ranked_at"],
            "unranked_count": int(row["unranked_count"] or 0),
            "packet_count": int(pack_row["packet_count"] or 0),
        }

    def upsert_pack(
        self,
        repo: str,
        source_type: str,
        number: int,
        path: Path,
        status: str,
        confidence: str,
        source_updated_at: str,
        decision: str = "undecided",
        decision_resource_hash: str = "",
    ) -> None:
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            next_version = self._next_pack_version()
            self._conn.execute(
                """
                INSERT INTO packs
                    (
                        repo, source_type, number, path, status, decision, decision_resource_hash,
                        confidence, source_updated_at, stale, version
                    )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                ON CONFLICT(repo, source_type, number) DO UPDATE SET
                    path = excluded.path,
                    status = excluded.status,
                    decision = excluded.decision,
                    decision_resource_hash = CASE
                        WHEN excluded.decision_resource_hash != '' THEN excluded.decision_resource_hash
                        ELSE packs.decision_resource_hash
                    END,
                    confidence = excluded.confidence,
                    source_updated_at = excluded.source_updated_at,
                    generated_at = CURRENT_TIMESTAMP,
                    stale = 0,
                    version = excluded.version
                """,
                (
                    repo,
                    source_type,
                    number,
                    str(path),
                    status,
                    decision,
                    decision_resource_hash,
                    confidence,
                    source_updated_at,
                    next_version,
                ),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def update_pack_decision(
        self,
        repo: str,
        source_type: str,
        number: int,
        decision: str,
        *,
        decision_resource_hash: str = "",
    ) -> bool:
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            next_version = self._next_pack_version()
            cursor = self._conn.execute(
                """
                UPDATE packs
                SET decision = ?,
                    decision_resource_hash = ?,
                    version = ?
                WHERE repo = ? AND source_type = ? AND number = ?
                """,
                (decision, decision_resource_hash, next_version, repo, source_type, number),
            )
            self._conn.commit()
            return cursor.rowcount > 0
        except Exception:
            self._conn.rollback()
            raise

    def _next_pack_version(self) -> int:
        row = self._conn.execute("SELECT COALESCE(MAX(version), 0) + 1 AS next_version FROM packs").fetchone()
        return int(row["next_version"])

    def list_packs(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT
                repo, source_type, number, path, status, decision, decision_resource_hash,
                confidence, source_updated_at, generated_at, stale
            FROM packs
            ORDER BY version DESC, id DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]

    def get_pack(self, repo: str, source_type: str, number: int) -> dict[str, Any] | None:
        row = self._conn.execute(
            """
            SELECT
                repo, source_type, number, path, status, decision, decision_resource_hash,
                confidence, source_updated_at, generated_at, stale
            FROM packs
            WHERE repo = ? AND source_type = ? AND number = ?
            """,
            (repo, source_type, number),
        ).fetchone()
        return dict(row) if row is not None else None


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def issue_content_signature(issue: GHIssue) -> tuple[str, str, str, str]:
    labels_json = json.dumps(issue.labels, ensure_ascii=False)
    comments_json = json.dumps(
        [
            {
                "author": comment.author,
                "body": comment.body,
                "url": comment.url,
                "created_at": comment.created_at,
            }
            for comment in issue.comments
        ],
        ensure_ascii=False,
    )
    body_hash = _hash_text(issue.body)
    # Change-detection keys off comment count + freshness, not comment bodies, so a
    # fast list-only sync (no per-comment fetch) still resurfaces on new activity.
    comment_count = issue.comment_count or len(issue.comments)
    content_hash = _hash_text(f"{labels_json}\n{comment_count}\n{issue.updated_at}")
    return labels_json, comments_json, body_hash, content_hash


def _issue_from_row(row: sqlite3.Row) -> GHIssue:
    try:
        labels = json.loads(row["labels_json"] or "[]")
    except json.JSONDecodeError:
        labels = []
    try:
        comments_data = json.loads(row["comments_json"] or "[]")
    except json.JSONDecodeError:
        comments_data = []
    comments = [
        GHComment(
            author=str(comment.get("author", "")),
            body=str(comment.get("body", "")),
            url=str(comment.get("url", "")),
            created_at=str(comment.get("created_at", "")),
        )
        for comment in comments_data
        if isinstance(comment, dict)
    ]
    return GHIssue(
        number=int(row["number"]),
        title=str(row["title"]),
        body=str(row["body"]),
        labels=[str(label) for label in labels] if isinstance(labels, list) else [],
        url=str(row["url"]),
        repo=str(row["repo"]),
        state=str(row["state"]),
        score=float(row["score"]),
        reason=str(row["reason"]),
        priority=str(row["priority"]),
        fit=str(row["fit"]),
        resource_fit=str(row["resource_fit"]),
        actionability=str(row["actionability"]),
        updated_at=str(row["updated_at"]),
        comments=comments,
    )
