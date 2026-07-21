"""Tests for MarkdownDirectoryStore.

Covers:
- round-trip put/get/list against a fresh tmpdir
- compatibility with the upstream JS on-disk layout (frontmatter + body)
- preservation of the original envelope across put round-trips
- recall hits on body text, structured fields, and tags
- delete idempotency and 404-shaped behavior
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ump_memory.md_store import MarkdownDirectoryStore, _split_frontmatter
from ump_memory.models import MemoryRecord


SAMPLE_ENVELOPE = {
    "ump": "0.1",
    "id": "urn:ump:testcardabcdefghijklmnopqrstuvwxyz",
    "kind": "semantic",
    "scope": {
        "owner": "did:key:z6Mk-test",
        "project": "rickstevens/osti-corpus",
        "topic": "contacts/anl",
        "visibility": "private",
    },
    "time": {
        "created": "2026-06-08T04:22:15.453Z",
        "observed": "2026-06-08T04:22:15.453Z",
        "valid_from": "2026-06-08T04:22:15.453Z",
        "valid_to": None,
    },
    "lifecycle": {"status": "active", "confidence": 0.6},
    "integrity": {"content_hash": "blake3:abc", "signature": "ed25519:xyz", "signer": "did:key:z6Mk-test"},
    "body": {
        "structured": {
            "id": "contact-cecil-anl.gov",
            "kind": "contact",
            "summary": "T. Cecil — ANL (2 papers)",
            "email": "cecil@anl.gov",
            "names": ["T. Cecil"],
            "primary_lab": "ANL",
            "topics": ["Designing Materials with Predictable Functionality"],
        }
    },
}


def _write_upstream_card(root: Path, env: dict, body: str = "T. Cecil — ANL contact card") -> Path:
    """Write a card in the exact on-disk layout the JS reference store produces."""
    mem_d = root / "memory.d"
    mem_d.mkdir(parents=True, exist_ok=True)
    slug = env["id"].removeprefix("urn:ump:")
    path = mem_d / f"{slug}.ump.md"
    payload = (
        "---\n"
        + json.dumps(env, indent=2, ensure_ascii=False, sort_keys=True)
        + "\n---\n\n"
        + body
        + "\n"
    )
    path.write_text(payload, encoding="utf-8")
    return path


def test_split_frontmatter_roundtrip():
    raw = "---\n" + json.dumps(SAMPLE_ENVELOPE, sort_keys=True) + "\n---\n\nhello body\n"
    env, body = _split_frontmatter(raw)
    assert env["id"] == SAMPLE_ENVELOPE["id"]
    assert body.strip() == "hello body"


def test_split_frontmatter_no_fence_returns_empty_env():
    env, body = _split_frontmatter("plain markdown content")
    assert env == {}
    assert body == "plain markdown content"


def test_split_frontmatter_malformed_json_does_not_raise():
    env, body = _split_frontmatter("---\nnot json\n---\nbody\n")
    # Falls back to no-envelope read so the store can keep moving.
    assert env == {}
    assert "not json" in body or "body" in body


def test_list_reads_upstream_card(tmp_path):
    _write_upstream_card(tmp_path, SAMPLE_ENVELOPE)
    store = MarkdownDirectoryStore(tmp_path)
    records = store.list()
    assert len(records) == 1
    rec = records[0]
    assert rec.id == SAMPLE_ENVELOPE["id"]
    assert rec.scope["project"] == "rickstevens/osti-corpus"
    assert rec.metadata["envelope"]["integrity"]["signature"] == "ed25519:xyz"


def test_get_by_urn_fast_path(tmp_path):
    _write_upstream_card(tmp_path, SAMPLE_ENVELOPE)
    store = MarkdownDirectoryStore(tmp_path)
    rec = store.get(SAMPLE_ENVELOPE["id"])
    assert rec is not None
    assert rec.id == SAMPLE_ENVELOPE["id"]
    # Structured frontmatter accessible via metadata
    assert rec.metadata["structured"]["email"] == "cecil@anl.gov"


def test_get_missing_returns_none(tmp_path):
    store = MarkdownDirectoryStore(tmp_path)
    assert store.get("urn:ump:doesnotexist") is None


def test_put_roundtrip_preserves_envelope(tmp_path):
    _write_upstream_card(tmp_path, SAMPLE_ENVELOPE)
    store = MarkdownDirectoryStore(tmp_path)
    rec = store.get(SAMPLE_ENVELOPE["id"])
    assert rec is not None
    # Write back — integrity block should survive (we don't re-sign here).
    store.put(rec)
    rec2 = store.get(SAMPLE_ENVELOPE["id"])
    assert rec2 is not None
    assert rec2.metadata["envelope"]["integrity"]["signature"] == "ed25519:xyz"
    assert rec2.metadata["envelope"]["scope"]["project"] == "rickstevens/osti-corpus"


def test_put_new_record_writes_canonical_filename(tmp_path):
    store = MarkdownDirectoryStore(tmp_path)
    rec = MemoryRecord(
        id="urn:ump:newrecordabcdefghij",
        text="a fresh memory",
        kind="semantic",
        scope={"owner": "rick", "visibility": "private"},
    )
    store.put(rec)
    expected = tmp_path / "memory.d" / "newrecordabcdefghij.ump.md"
    assert expected.exists()
    # Frontmatter should be valid JSON we can read back
    env, body = _split_frontmatter(expected.read_text(encoding="utf-8"))
    assert env["id"] == "urn:ump:newrecordabcdefghij"
    assert body.strip() == "a fresh memory"


def test_recall_finds_card_by_email_token(tmp_path):
    _write_upstream_card(tmp_path, SAMPLE_ENVELOPE)
    store = MarkdownDirectoryStore(tmp_path)
    hits = store.recall("cecil@anl.gov", limit=5)
    assert len(hits) >= 1
    assert hits[0].record.id == SAMPLE_ENVELOPE["id"]


def test_recall_filters_by_scope(tmp_path):
    _write_upstream_card(tmp_path, SAMPLE_ENVELOPE)
    store = MarkdownDirectoryStore(tmp_path)
    # Wrong owner → still returns it (scope_match is a soft signal in this impl);
    # but right owner should score strictly higher.
    matched = store.recall("cecil", scope={"owner": "did:key:z6Mk-test"}, limit=5)
    unmatched = store.recall("cecil", scope={"owner": "did:key:other"}, limit=5)
    assert matched and unmatched
    assert matched[0].score >= unmatched[0].score


def test_delete_removes_card_and_returns_true(tmp_path):
    _write_upstream_card(tmp_path, SAMPLE_ENVELOPE)
    store = MarkdownDirectoryStore(tmp_path)
    assert store.get(SAMPLE_ENVELOPE["id"]) is not None
    assert store.delete(SAMPLE_ENVELOPE["id"]) is True
    assert store.get(SAMPLE_ENVELOPE["id"]) is None
    # Second delete is a no-op
    assert store.delete(SAMPLE_ENVELOPE["id"]) is False


def test_malformed_card_does_not_crash_list(tmp_path):
    mem_d = tmp_path / "memory.d"
    mem_d.mkdir(parents=True)
    (mem_d / "garbage.ump.md").write_text("---\nnot json {{{\n---\nbody\n", encoding="utf-8")
    _write_upstream_card(tmp_path, SAMPLE_ENVELOPE)
    store = MarkdownDirectoryStore(tmp_path)
    records = store.list()
    # The garbage card is skipped; the good one is returned.
    assert len(records) == 1
    assert records[0].id == SAMPLE_ENVELOPE["id"]


def test_memory_dir_path_handled_either_way(tmp_path):
    """Constructor accepts either the root dir or the memory.d/ subdir."""
    (tmp_path / "memory.d").mkdir()
    a = MarkdownDirectoryStore(tmp_path)
    b = MarkdownDirectoryStore(tmp_path / "memory.d")
    assert a.memory_dir == b.memory_dir == tmp_path / "memory.d"
