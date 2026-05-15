from pathlib import Path

from osmind.cache.store import CacheStore


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


def test_cache_lists_same_second_packs_newest_first(tmp_path: Path):
    store = CacheStore(tmp_path / "osmind.db")
    store.upsert_pack("o/r", "issue", 1, tmp_path / "first.md", "unread", "unknown", "u1")
    store.upsert_pack("o/r", "issue", 2, tmp_path / "second.md", "unread", "unknown", "u2")

    store._conn.execute("UPDATE packs SET generated_at = '2026-05-15 01:02:03'")
    store._conn.commit()

    packs = store.list_packs()

    assert [pack["number"] for pack in packs] == [2, 1]
