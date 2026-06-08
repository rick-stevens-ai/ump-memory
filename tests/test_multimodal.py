"""End-to-end tests for the multi-modal indexing layer.

Builds a tiny synthetic UMP corpus, indexes it, and exercises each axis.
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pytest

from ump_memory.multimodal import (
    IndexBuilder,
    MultiSearch,
    build_index,
    parse_card,
    search_exact,
    search_hybrid,
    search_regex,
    search_structured,
)


# ---------------------------------------------------------------------------
# Fixture: synthetic 5-card UMP corpus
# ---------------------------------------------------------------------------

CARDS: list[dict] = [
    {
        "id": "contact:alice@ornl.gov",
        "kind": "contact",
        "scope": {"owner": "did:test", "project": "test/corpus", "visibility": "private"},
        "body": {
            "text": "Alice is an ORNL researcher working on battery cathode materials and lithium-ion chemistry.",
            "structured": {
                "primary_lab": "ORNL",
                "primary_name": "Alice Researcher",
                "email": "alice@ornl.gov",
                "paper_count": 87,
                "contact_kind": "individual",
                "labs": ["ORNL"],
                "names": ["Alice Researcher"],
                "topics": ["Batteries", "Cathodes", "Lithium-Ion"],
                "affiliations": ["Oak Ridge National Laboratory"],
                "paper_ids": ["ostiid:1", "ostiid:2"],
            },
        },
    },
    {
        "id": "contact:bob@anl.gov",
        "kind": "contact",
        "scope": {"owner": "did:test", "project": "test/corpus", "visibility": "private"},
        "body": {
            "text": "Bob is an ANL fusion physicist. Tokamak, plasma confinement, ITER.",
            "structured": {
                "primary_lab": "ANL",
                "primary_name": "Bob Plasma",
                "email": "bob@anl.gov",
                "paper_count": 142,
                "contact_kind": "individual",
                "labs": ["ANL"],
                "names": ["Bob Plasma"],
                "topics": ["Fusion", "Tokamak", "Plasma"],
                "paper_ids": ["ostiid:3"],
            },
        },
    },
    {
        "id": "contact:carol@pppl.gov",
        "kind": "contact",
        "scope": {"owner": "did:test", "project": "test/corpus", "visibility": "private"},
        "body": {
            "text": "Carol at PPPL — fusion theory, MHD simulations, stellarator design.",
            "structured": {
                "primary_lab": "PPPL",
                "primary_name": "Carol Theorist",
                "email": "carol@pppl.gov",
                "paper_count": 14,
                "contact_kind": "individual",
                "labs": ["PPPL"],
                "names": ["Carol Theorist"],
                "topics": ["Fusion", "MHD", "Stellarator"],
                "paper_ids": ["ostiid:4"],
            },
        },
    },
    {
        "id": "contact:cms-team@cern.ch",
        "kind": "contact",
        "scope": {"owner": "did:test", "project": "test/corpus", "visibility": "private"},
        "body": {
            "text": "CMS publication committee chair — collaboration mailer for 989 papers.",
            "structured": {
                "primary_lab": "FNAL",
                "primary_name": "CMS Publication Committee",
                "email": "cms-publication-committee-chair@cern.ch",
                "paper_count": 989,
                "contact_kind": "collaboration",
                "labs": ["FNAL", "CERN"],
                "names": ["CMS Publication Committee"],
                "topics": ["Particle Physics", "Higgs"],
            },
        },
    },
    {
        "id": "contact:dave@lbnl.gov",
        "kind": "contact",
        "scope": {"owner": "did:test", "project": "test/corpus", "visibility": "private"},
        "body": {
            "text": "Dave is an LBNL battery scientist focused on solid-state electrolytes and cathode interfaces.",
            "structured": {
                "primary_lab": "LBNL",
                "primary_name": "Dave Electrolyte",
                "email": "dave@lbnl.gov",
                "paper_count": 56,
                "contact_kind": "individual",
                "labs": ["LBNL"],
                "names": ["Dave Electrolyte"],
                "topics": ["Batteries", "Solid-State", "Cathodes"],
            },
        },
    },
]


def _write_card(store_dir: Path, card: dict) -> Path:
    """Serialize a card to a ``*.ump.md`` file (JSON frontmatter + markdown body)."""
    text = card["body"]["text"]
    path = store_dir / f"{card['id'].replace(':', '_').replace('/', '_')}.ump.md"
    fm = json.dumps(card, indent=2)
    path.write_text(f"---\n{fm}\n---\n{text}\n", encoding="utf-8")
    return path


@pytest.fixture
def indexed_corpus(tmp_path: Path) -> Path:
    """Build a 5-card corpus and return the DB path."""
    store = tmp_path / "store"
    store.mkdir()
    for card in CARDS:
        _write_card(store, card)

    db_path = tmp_path / "index.db"
    stats = build_index(store, db_path)
    assert stats["indexed"] == 5, stats
    assert stats["errors"] == 0, stats
    return db_path


# ---------------------------------------------------------------------------
# parse_card
# ---------------------------------------------------------------------------

def test_parse_card_hoists_structured_fields(tmp_path: Path) -> None:
    store = tmp_path / "store"
    store.mkdir()
    path = _write_card(store, CARDS[0])

    card = parse_card(path)
    assert card is not None
    assert card["id"] == "contact:alice@ornl.gov"
    assert card["meta"]["primary_lab"] == "ORNL"
    assert card["meta"]["email"] == "alice@ornl.gov"
    assert card["meta"]["paper_count"] == 87
    assert "ORNL" in card["meta"]["labs"]
    assert "Batteries" in card["meta"]["topics"]


def test_parse_card_handles_missing_frontmatter(tmp_path: Path) -> None:
    path = tmp_path / "raw.ump.md"
    path.write_text("just some markdown, no frontmatter\n")
    card = parse_card(path)
    assert card is not None
    assert "just some markdown" in card["text"]
    assert card["meta"] == {}


# ---------------------------------------------------------------------------
# indexing
# ---------------------------------------------------------------------------

def test_index_is_incremental(tmp_path: Path) -> None:
    store = tmp_path / "store"
    store.mkdir()
    for card in CARDS:
        _write_card(store, card)
    db = tmp_path / "i.db"

    s1 = build_index(store, db)
    assert s1["indexed"] == 5
    assert s1["skipped"] == 0

    # Re-run without touching files
    s2 = build_index(store, db)
    assert s2["indexed"] == 0
    assert s2["skipped"] == 5


def test_index_populates_field_table(indexed_corpus: Path) -> None:
    conn = sqlite3.connect(str(indexed_corpus))
    n_labs = conn.execute(
        "select count(distinct value) from ump_card_field where field='labs'"
    ).fetchone()[0]
    n_topics = conn.execute(
        "select count(distinct value) from ump_card_field where field='topics'"
    ).fetchone()[0]
    conn.close()
    # ORNL, ANL, PPPL, FNAL, CERN, LBNL = 6
    assert n_labs == 6
    # Batteries, Cathodes, Lithium-Ion, Fusion, Tokamak, Plasma, MHD,
    # Stellarator, Particle Physics, Higgs, Solid-State = 11
    assert n_topics == 11


# ---------------------------------------------------------------------------
# axis: exact (FTS5)
# ---------------------------------------------------------------------------

def test_exact_email_as_single_token(indexed_corpus: Path) -> None:
    """The custom tokenizer must keep ``alice@ornl.gov`` as one token."""
    with MultiSearch(indexed_corpus) as ms:
        hits = ms.exact('"alice@ornl.gov"', limit=5)
    ids = [h.record["id"] for h in hits]
    assert "contact:alice@ornl.gov" in ids


def test_exact_boolean_and(indexed_corpus: Path) -> None:
    with MultiSearch(indexed_corpus) as ms:
        hits = ms.exact("battery AND cathode", limit=10)
    ids = {h.record["id"] for h in hits}
    assert ids >= {"contact:alice@ornl.gov", "contact:dave@lbnl.gov"}
    assert "contact:bob@anl.gov" not in ids


def test_exact_prefix(indexed_corpus: Path) -> None:
    with MultiSearch(indexed_corpus) as ms:
        hits = ms.exact("toka*", limit=10)
    ids = {h.record["id"] for h in hits}
    assert "contact:bob@anl.gov" in ids


# ---------------------------------------------------------------------------
# axis: regex
# ---------------------------------------------------------------------------

def test_regex_finds_collab_mailers(indexed_corpus: Path) -> None:
    with MultiSearch(indexed_corpus) as ms:
        hits = ms.regex(r"cms-.*@cern\.ch", limit=5)
    ids = {h.record["id"] for h in hits}
    assert "contact:cms-team@cern.ch" in ids


def test_regex_bad_pattern_raises(indexed_corpus: Path) -> None:
    with MultiSearch(indexed_corpus) as ms:
        with pytest.raises(ValueError):
            ms.regex(r"(unclosed", limit=5)


# ---------------------------------------------------------------------------
# axis: structured
# ---------------------------------------------------------------------------

def test_structured_primary_lab(indexed_corpus: Path) -> None:
    with MultiSearch(indexed_corpus) as ms:
        hits = ms.structured({"primary_lab": "ORNL"})
    ids = {h.record["id"] for h in hits}
    assert ids == {"contact:alice@ornl.gov"}


def test_structured_paper_count_min(indexed_corpus: Path) -> None:
    with MultiSearch(indexed_corpus) as ms:
        hits = ms.structured({"paper_count_min": 100})
    ids = {h.record["id"] for h in hits}
    # Bob (142) and cms-team (989) are >= 100
    assert ids == {"contact:bob@anl.gov", "contact:cms-team@cern.ch"}


def test_structured_topic_join(indexed_corpus: Path) -> None:
    with MultiSearch(indexed_corpus) as ms:
        hits = ms.structured({"topic_like": "%Fusion%"})
    ids = {h.record["id"] for h in hits}
    assert ids == {"contact:bob@anl.gov", "contact:carol@pppl.gov"}


def test_structured_lab_in(indexed_corpus: Path) -> None:
    with MultiSearch(indexed_corpus) as ms:
        hits = ms.structured({"lab_in": ["PPPL", "LBNL"]})
    ids = {h.record["id"] for h in hits}
    assert ids == {"contact:carol@pppl.gov", "contact:dave@lbnl.gov"}


def test_structured_excludes_sql_injection(indexed_corpus: Path) -> None:
    """order_by must be whitelisted and reject anything but a column-direction spec."""
    with MultiSearch(indexed_corpus) as ms:
        hits = ms.structured({
            "primary_lab": "ORNL",
            "order_by": "1; drop table ump_card",
        })
    # Should fall back to default and still return the ORNL hit
    assert any(h.record["id"] == "contact:alice@ornl.gov" for h in hits)


# ---------------------------------------------------------------------------
# axis: hybrid (RRF)
# ---------------------------------------------------------------------------

def test_hybrid_exact_plus_structured(indexed_corpus: Path) -> None:
    """Hybrid should rank docs that hit BOTH axes above docs that hit one."""
    with MultiSearch(indexed_corpus) as ms:
        hits = ms.hybrid(
            "battery cathode",
            filters={"primary_lab": "ORNL"},
            limit=5,
        )
    assert hits, "expected at least one hybrid hit"
    # Alice should be #1: matches exact (battery+cathode) AND structured (ORNL)
    assert hits[0].record["id"] == "contact:alice@ornl.gov"
    # Multi-axis signal carried through
    axes_for_alice = [a["axis"] for a in hits[0].signals["axes"]]
    assert "exact" in axes_for_alice
    assert "structured" in axes_for_alice


def test_hybrid_with_custom_semantic(indexed_corpus: Path) -> None:
    """Caller supplies their own semantic backend; hybrid fuses it in."""
    def fake_semantic(q: str, lim: int) -> list[dict]:
        # Always returns Carol first
        return [{
            "record": {"id": "contact:carol@pppl.gov", "kind": "contact"},
            "score": 0.9,
            "signals": {"backend": "fake"},
        }]

    with MultiSearch(indexed_corpus) as ms:
        hits = ms.hybrid("fusion", semantic=fake_semantic, limit=5)

    axes_seen = {a["axis"] for h in hits for a in h.signals["axes"]}
    assert "semantic" in axes_seen


# ---------------------------------------------------------------------------
# CLI / convenience
# ---------------------------------------------------------------------------

def test_card_count(indexed_corpus: Path) -> None:
    with MultiSearch(indexed_corpus) as ms:
        assert ms.card_count() == 5
