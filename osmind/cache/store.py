from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class CacheStore:
    def __init__(self, db_path: Path):
        self._path = db_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self._path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript(
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
            );

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
            );
            """
        )
        self._create_packs_table()
        self._migrate_packs_schema()
        self._conn.commit()

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
        if {"id", "version"}.issubset(columns):
            return

        legacy_rows = self._conn.execute(
            """
            SELECT repo, source_type, number, path, status, confidence, source_updated_at, generated_at, stale
            FROM packs
            ORDER BY generated_at ASC, rowid ASC
            """
        ).fetchall()
        self._conn.execute("ALTER TABLE packs RENAME TO packs_old")
        self._create_packs_table()
        for version, row in enumerate(legacy_rows, start=1):
            self._conn.execute(
                """
                INSERT INTO packs
                    (repo, source_type, number, path, status, confidence, source_updated_at, generated_at, stale, version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["repo"],
                    row["source_type"],
                    row["number"],
                    row["path"],
                    row["status"],
                    row["confidence"],
                    row["source_updated_at"],
                    row["generated_at"],
                    row["stale"],
                    version,
                ),
            )
        self._conn.execute("DROP TABLE packs_old")

    def _pack_columns(self, table_name: str) -> set[str]:
        rows = self._conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {row["name"] for row in rows}

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

    def upsert_pack(
        self,
        repo: str,
        source_type: str,
        number: int,
        path: Path,
        status: str,
        confidence: str,
        source_updated_at: str,
    ) -> None:
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            next_version = self._next_pack_version()
            self._conn.execute(
                """
                INSERT INTO packs
                    (repo, source_type, number, path, status, confidence, source_updated_at, stale, version)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
                ON CONFLICT(repo, source_type, number) DO UPDATE SET
                    path = excluded.path,
                    status = excluded.status,
                    confidence = excluded.confidence,
                    source_updated_at = excluded.source_updated_at,
                    generated_at = CURRENT_TIMESTAMP,
                    stale = 0,
                    version = excluded.version
                """,
                (repo, source_type, number, str(path), status, confidence, source_updated_at, next_version),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

    def _next_pack_version(self) -> int:
        row = self._conn.execute("SELECT COALESCE(MAX(version), 0) + 1 AS next_version FROM packs").fetchone()
        return int(row["next_version"])

    def list_packs(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT repo, source_type, number, path, status, confidence, source_updated_at, generated_at, stale
            FROM packs
            ORDER BY version DESC, id DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]
