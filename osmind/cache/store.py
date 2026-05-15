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

            CREATE TABLE IF NOT EXISTS packs (
                repo TEXT NOT NULL,
                source_type TEXT NOT NULL,
                number INTEGER NOT NULL,
                path TEXT NOT NULL,
                status TEXT NOT NULL,
                confidence TEXT NOT NULL,
                source_updated_at TEXT NOT NULL,
                generated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                stale INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (repo, source_type, number)
            );
            """
        )
        self._conn.commit()

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
        self._conn.execute(
            """
            INSERT INTO packs
                (repo, source_type, number, path, status, confidence, source_updated_at, stale)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0)
            ON CONFLICT(repo, source_type, number) DO UPDATE SET
                path = excluded.path,
                status = excluded.status,
                confidence = excluded.confidence,
                source_updated_at = excluded.source_updated_at,
                generated_at = CURRENT_TIMESTAMP,
                stale = 0
            """,
            (repo, source_type, number, str(path), status, confidence, source_updated_at),
        )
        self._conn.commit()

    def list_packs(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT repo, source_type, number, path, status, confidence, source_updated_at, generated_at, stale
            FROM packs
            ORDER BY generated_at DESC
            """
        ).fetchall()
        return [dict(row) for row in rows]
