import sqlite3
from pathlib import Path

import pytest

from osmind.cache.store import CacheStore
from osmind.github.models import GHComment, GHIssue


def test_cache_marks_unchanged_item_fresh(tmp_path: Path):
    store = CacheStore(tmp_path / "osmind.db")
    store.upsert_item(
        repo="o/r",
        source_type="pr",
        number=7,
        title="Title",
        body_hash="body1",
        content_hash="files1",
        state="open",
        url="https://github.com/o/r/pull/7",
        updated_at="2026-05-15T01:02:03+00:00",
    )

    assert (
        store.is_item_stale(
            "o/r",
            "pr",
            7,
            "body1",
            "files1",
            "2026-05-15T01:02:03+00:00",
        )
        is False
    )


def test_cache_marks_changed_hash_stale(tmp_path: Path):
    store = CacheStore(tmp_path / "osmind.db")
    store.upsert_item("o/r", "issue", 42, "Title", "body1", "comments1", "open", "url", "u1")

    assert store.is_item_stale("o/r", "issue", 42, "body2", "comments1", "u1") is True


def test_cache_round_trips_issue_with_score_and_comments(tmp_path: Path):
    store = CacheStore(tmp_path / "osmind.db")
    issue = GHIssue(
        number=42,
        title="Tokenizer leak",
        body="The tokenizer cache keeps growing.",
        labels=["bug", "good first issue"],
        url="https://github.com/o/r/issues/42",
        repo="o/r",
        state="open",
        updated_at="u42",
        comments=[
            GHComment("maintainer", "Please add a regression test.", "u", "c1"),
        ],
    )

    store.upsert_issue(issue)
    store.update_issue_score("o/r", "issue", 42, 0.8, "适合做")

    cached = store.list_issues("o/r")

    assert len(cached) == 1
    assert cached[0].number == 42
    assert cached[0].title == "Tokenizer leak"
    assert cached[0].body == "The tokenizer cache keeps growing."
    assert cached[0].labels == ["bug", "good first issue"]
    assert cached[0].score == 0.8
    assert cached[0].reason == "适合做"
    assert cached[0].comments[0].author == "maintainer"


def test_cache_round_trips_issue_recommendation_dimensions(tmp_path: Path):
    store = CacheStore(tmp_path / "osmind.db")
    issue = GHIssue(
        number=7,
        title="DeepSeek V4Pro reproduction fails",
        body="Requires full model reproduction.",
        labels=["bug"],
        url="https://github.com/o/r/issues/7",
        repo="o/r",
        state="open",
        updated_at="u7",
    )

    store.upsert_issue(issue)
    store.update_issue_score(
        "o/r",
        "issue",
        7,
        0.2,
        "主题匹配，但当前 GPU 资源不足以复现",
        priority="low",
        fit="high",
        resource_fit="blocked",
        actionability="low",
    )

    cached = store.list_issues("o/r")

    assert cached[0].priority == "low"
    assert cached[0].fit == "high"
    assert cached[0].resource_fit == "blocked"
    assert cached[0].actionability == "low"


def test_content_hash_tracks_comment_count_without_comment_bodies(tmp_path: Path):
    from osmind.cache.store import issue_content_signature

    def issue(comment_count, updated_at):
        return GHIssue(
            number=42, title="Tokenizer leak", body="grows", labels=["bug"],
            url="https://github.com/o/r/issues/42", repo="o/r", state="open",
            updated_at=updated_at, comment_count=comment_count,
        )

    # no comment bodies fetched, yet a new comment (count bump) changes the hash
    base = issue_content_signature(issue(0, "u42"))[3]
    more_comments = issue_content_signature(issue(1, "u43"))[3]
    same_again = issue_content_signature(issue(0, "u42"))[3]

    assert base != more_comments
    assert base == same_again


def test_upsert_preserves_cached_comments_on_list_only_refresh(tmp_path: Path):
    store = CacheStore(tmp_path / "osmind.db")
    from osmind.github.models import GHComment

    with_comments = GHIssue(
        number=42, title="Tokenizer leak", body="grows", labels=["bug"],
        url="https://github.com/o/r/issues/42", repo="o/r", state="open",
        updated_at="u42", comment_count=1,
        comments=[GHComment(author="alice", body="same here", url="", created_at="t")],
    )
    list_only = GHIssue(
        number=42, title="Tokenizer leak", body="grows", labels=["bug"],
        url="https://github.com/o/r/issues/42", repo="o/r", state="open",
        updated_at="u43", comment_count=2, comments=[],  # no bodies fetched this round
    )

    store.upsert_issue(with_comments)
    store.upsert_issue(list_only)

    item = store.get_item("o/r", "issue", 42)
    assert "alice" in item["comments_json"]  # cached body kept, not wiped


def test_cache_migrates_legacy_github_items_with_comment_count_column(tmp_path: Path):
    db_path = tmp_path / "osmind.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE github_items (
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
            body TEXT NOT NULL DEFAULT '',
            labels_json TEXT NOT NULL DEFAULT '[]',
            comments_json TEXT NOT NULL DEFAULT '[]',
            score REAL NOT NULL DEFAULT 0,
            reason TEXT NOT NULL DEFAULT '',
            priority TEXT NOT NULL DEFAULT 'unknown',
            fit TEXT NOT NULL DEFAULT 'unknown',
            resource_fit TEXT NOT NULL DEFAULT 'unknown',
            actionability TEXT NOT NULL DEFAULT 'unknown',
            ranked_at TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (repo, source_type, number)
        )
        """
    )
    conn.execute(
        """
        INSERT INTO github_items
            (
                repo, source_type, number, title, body_hash, content_hash,
                state, url, updated_at, body
            )
        VALUES (?, 'issue', ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("o/r", 42, "Tokenizer leak", "body1", "comments1", "open", "url", "u42", "Body"),
    )
    conn.commit()
    conn.close()

    store = CacheStore(db_path)

    columns = {row["name"] for row in store._conn.execute("PRAGMA table_info(github_items)").fetchall()}
    assert "comment_count" in columns
    assert store.get_item("o/r", "issue", 42) is not None


def test_cache_reports_issue_fetch_and_rank_activity(tmp_path: Path):
    store = CacheStore(tmp_path / "osmind.db")
    issue = GHIssue(
        number=42,
        title="Tokenizer leak",
        body="Body",
        labels=["bug"],
        url="https://github.com/o/r/issues/42",
        repo="o/r",
        state="open",
        updated_at="u42",
    )

    store.upsert_issue(issue)
    before_rank = store.issue_activity("o/r")

    assert before_rank["issue_count"] == 1
    assert before_rank["last_fetched_at"]
    assert before_rank["last_ranked_at"] is None
    assert before_rank["unranked_count"] == 1

    store.update_issue_score("o/r", "issue", 42, 0.8, "ranked")
    after_rank = store.issue_activity("o/r")

    assert after_rank["issue_count"] == 1
    assert after_rank["last_fetched_at"]
    assert after_rank["last_ranked_at"]
    assert after_rank["unranked_count"] == 0


def test_cache_rolls_back_failed_item_write_before_pack_write(tmp_path: Path):
    store = CacheStore(tmp_path / "osmind.db")

    with pytest.raises(sqlite3.IntegrityError):
        store.upsert_item("o/r", "issue", 42, None, "body1", "comments1", "open", "url", "u1")  # type: ignore[arg-type]

    store.upsert_pack("o/r", "issue", 42, tmp_path / "pack.md", "unread", "unknown", "u1")

    packs = store.list_packs()
    assert len(packs) == 1
    assert packs[0]["number"] == 42


def test_cache_records_pack_metadata(tmp_path: Path):
    store = CacheStore(tmp_path / "osmind.db")
    pack_path = tmp_path / "pack.md"
    store.upsert_pack(
        repo="o/r",
        source_type="pr",
        number=7,
        path=pack_path,
        status="unread",
        confidence="unknown",
        source_updated_at="u1",
    )

    packs = store.list_packs()

    assert packs[0]["repo"] == "o/r"
    assert packs[0]["source_type"] == "pr"
    assert packs[0]["number"] == 7
    assert packs[0]["path"] == str(pack_path)
    assert packs[0]["decision"] == "undecided"


def test_cache_records_pack_decision(tmp_path: Path):
    store = CacheStore(tmp_path / "osmind.db")
    pack_path = tmp_path / "pack.md"
    store.upsert_pack(
        repo="o/r",
        source_type="issue",
        number=42,
        path=pack_path,
        status="inspecting",
        confidence="low",
        source_updated_at="u1",
        decision="continue",
    )

    pack = store.get_pack("o/r", "issue", 42)

    assert pack is not None
    assert pack["decision"] == "continue"


def test_cache_updates_pack_decision(tmp_path: Path):
    store = CacheStore(tmp_path / "osmind.db")
    store.upsert_pack(
        repo="o/r",
        source_type="issue",
        number=42,
        path=tmp_path / "pack.md",
        status="unread",
        confidence="unknown",
        source_updated_at="u1",
    )

    updated = store.update_pack_decision("o/r", "issue", 42, "defer")

    pack = store.get_pack("o/r", "issue", 42)
    assert updated is True
    assert pack is not None
    assert pack["decision"] == "defer"


def test_cache_records_decision_resource_hash(tmp_path: Path):
    store = CacheStore(tmp_path / "osmind.db")
    store.upsert_pack(
        repo="o/r",
        source_type="issue",
        number=42,
        path=tmp_path / "pack.md",
        status="unread",
        confidence="unknown",
        source_updated_at="u1",
        decision_resource_hash="resources-v1",
    )

    created = store.get_pack("o/r", "issue", 42)
    assert created is not None
    assert created["decision_resource_hash"] == "resources-v1"

    store.update_pack_decision("o/r", "issue", 42, "discard", decision_resource_hash="resources-v2")

    updated = store.get_pack("o/r", "issue", 42)
    assert updated is not None
    assert updated["decision"] == "discard"
    assert updated["decision_resource_hash"] == "resources-v2"


def test_cache_lists_same_second_packs_newest_first(tmp_path: Path):
    store = CacheStore(tmp_path / "osmind.db")
    store.upsert_pack("o/r", "issue", 1, tmp_path / "first.md", "unread", "unknown", "u1")
    store.upsert_pack("o/r", "issue", 2, tmp_path / "second.md", "unread", "unknown", "u2")

    store._conn.execute("UPDATE packs SET generated_at = '2026-05-15 01:02:03'")
    store._conn.commit()

    packs = store.list_packs()

    assert [pack["number"] for pack in packs] == [2, 1]


def test_cache_lists_same_second_updated_pack_newest_first(tmp_path: Path):
    store = CacheStore(tmp_path / "osmind.db")
    store.upsert_pack("o/r", "issue", 1, tmp_path / "first.md", "unread", "unknown", "u1")
    store.upsert_pack("o/r", "issue", 2, tmp_path / "second.md", "unread", "unknown", "u2")
    store._conn.execute("UPDATE packs SET generated_at = '2026-05-15 01:02:03'")
    store._conn.commit()

    store.upsert_pack("o/r", "issue", 1, tmp_path / "first-regenerated.md", "unread", "unknown", "u3")
    store._conn.execute("UPDATE packs SET generated_at = '2026-05-15 01:02:03'")
    store._conn.commit()

    packs = store.list_packs()

    assert [pack["number"] for pack in packs] == [1, 2]


def test_cache_migrates_old_pack_schema_without_id_or_version(tmp_path: Path):
    db_path = tmp_path / "osmind.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE packs (
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
        )
        """
    )
    conn.execute(
        """
        INSERT INTO packs
            (repo, source_type, number, path, status, confidence, source_updated_at, generated_at, stale)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("o/r", "issue", 1, str(tmp_path / "old.md"), "read", "high", "u1", "2026-05-15 01:02:03", 0),
    )
    conn.commit()
    conn.close()

    store = CacheStore(db_path)
    store.upsert_pack("o/r", "issue", 2, tmp_path / "new.md", "unread", "unknown", "u2")

    columns = {row["name"] for row in store._conn.execute("PRAGMA table_info(packs)").fetchall()}
    packs = store.list_packs()

    assert {"id", "version", "decision"}.issubset(columns)
    assert [pack["number"] for pack in packs] == [2, 1]
    assert packs[1]["path"] == str(tmp_path / "old.md")
    assert packs[1]["status"] == "read"
    assert packs[1]["decision"] == "undecided"


def test_cache_recovers_stranded_pack_rows_from_interrupted_migration(tmp_path: Path):
    db_path = tmp_path / "osmind.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE packs (
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
    conn.execute(
        """
        CREATE TABLE packs_old (
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
        )
        """
    )
    conn.execute(
        """
        INSERT INTO packs_old
            (repo, source_type, number, path, status, confidence, source_updated_at, generated_at, stale)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ("o/r", "issue", 1, str(tmp_path / "old.md"), "read", "high", "u1", "2026-05-15 01:02:03", 0),
    )
    conn.commit()
    conn.close()

    store = CacheStore(db_path)

    table_names = {
        row["name"]
        for row in store._conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    }
    packs = store.list_packs()

    assert "packs_old" not in table_names
    assert len(packs) == 1
    assert packs[0]["number"] == 1
    assert packs[0]["path"] == str(tmp_path / "old.md")


def test_cache_orders_pack_writes_across_connections(tmp_path: Path):
    db_path = tmp_path / "osmind.db"
    first_store = CacheStore(db_path)
    second_store = CacheStore(db_path)

    first_store.upsert_pack("o/r", "issue", 1, tmp_path / "first.md", "unread", "unknown", "u1")
    second_store.upsert_pack("o/r", "issue", 2, tmp_path / "second.md", "unread", "unknown", "u2")
    first_store.upsert_pack("o/r", "issue", 1, tmp_path / "first-regenerated.md", "unread", "unknown", "u3")

    packs = second_store.list_packs()

    assert [pack["number"] for pack in packs] == [1, 2]
    assert packs[0]["path"] == str(tmp_path / "first-regenerated.md")
