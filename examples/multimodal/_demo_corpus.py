"""Shared synthetic corpus for the multimodal examples.

Five UMP contact cards across ORNL, ANL, PPPL, FNAL, LBNL covering
battery/fusion/particle-physics topics. Each example imports
:func:`build_demo_corpus` to get an indexed DB path it can query.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from ump_memory.multimodal import build_index

DEMO_CARDS: list[dict] = [
    {
        "id": "contact:alice@ornl.gov",
        "kind": "contact",
        "scope": {"owner": "did:demo", "project": "demo/contacts", "visibility": "private"},
        "body": {
            "text": "Alice — ORNL battery cathode researcher. Lithium-ion chemistry, layered oxides.",
            "structured": {
                "primary_lab": "ORNL", "primary_name": "Alice Researcher",
                "email": "alice@ornl.gov", "paper_count": 87,
                "contact_kind": "individual",
                "labs": ["ORNL"], "names": ["Alice Researcher"],
                "topics": ["Batteries", "Cathodes", "Lithium-Ion"],
            },
        },
    },
    {
        "id": "contact:bob@anl.gov",
        "kind": "contact",
        "scope": {"owner": "did:demo", "project": "demo/contacts", "visibility": "private"},
        "body": {
            "text": "Bob — ANL fusion physicist. Tokamak plasma confinement, ITER.",
            "structured": {
                "primary_lab": "ANL", "primary_name": "Bob Plasma",
                "email": "bob@anl.gov", "paper_count": 142,
                "contact_kind": "individual",
                "labs": ["ANL"], "names": ["Bob Plasma"],
                "topics": ["Fusion", "Tokamak", "Plasma"],
            },
        },
    },
    {
        "id": "contact:carol@pppl.gov",
        "kind": "contact",
        "scope": {"owner": "did:demo", "project": "demo/contacts", "visibility": "private"},
        "body": {
            "text": "Carol — PPPL fusion theorist. MHD simulations, stellarator design.",
            "structured": {
                "primary_lab": "PPPL", "primary_name": "Carol Theorist",
                "email": "carol@pppl.gov", "paper_count": 14,
                "contact_kind": "individual",
                "labs": ["PPPL"], "names": ["Carol Theorist"],
                "topics": ["Fusion", "MHD", "Stellarator"],
            },
        },
    },
    {
        "id": "contact:cms-team@cern.ch",
        "kind": "contact",
        "scope": {"owner": "did:demo", "project": "demo/contacts", "visibility": "private"},
        "body": {
            "text": "CMS publication committee chair — collaboration mailer for 989 papers.",
            "structured": {
                "primary_lab": "FNAL", "primary_name": "CMS Publication Committee",
                "email": "cms-publication-committee-chair@cern.ch", "paper_count": 989,
                "contact_kind": "collaboration",
                "labs": ["FNAL", "CERN"], "names": ["CMS Publication Committee"],
                "topics": ["Particle Physics", "Higgs"],
            },
        },
    },
    {
        "id": "contact:dave@lbnl.gov",
        "kind": "contact",
        "scope": {"owner": "did:demo", "project": "demo/contacts", "visibility": "private"},
        "body": {
            "text": "Dave — LBNL battery scientist. Solid-state electrolytes, cathode interfaces.",
            "structured": {
                "primary_lab": "LBNL", "primary_name": "Dave Electrolyte",
                "email": "dave@lbnl.gov", "paper_count": 56,
                "contact_kind": "individual",
                "labs": ["LBNL"], "names": ["Dave Electrolyte"],
                "topics": ["Batteries", "Solid-State", "Cathodes"],
            },
        },
    },
]


def _write_card(store_dir: Path, card: dict) -> Path:
    safe_id = card["id"].replace(":", "_").replace("/", "_")
    path = store_dir / f"{safe_id}.ump.md"
    fm = json.dumps(card, indent=2)
    path.write_text(f"---\n{fm}\n---\n{card['body']['text']}\n", encoding="utf-8")
    return path


def build_demo_corpus(tmp_root: Path | None = None) -> tuple[Path, Path]:
    """Materialize the 5-card demo corpus and return ``(store_dir, db_path)``."""
    root = Path(tmp_root) if tmp_root else Path(tempfile.mkdtemp(prefix="ump-demo-"))
    store = root / "store"
    store.mkdir(parents=True, exist_ok=True)
    for card in DEMO_CARDS:
        _write_card(store, card)
    db_path = root / "index.db"
    stats = build_index(store, db_path)
    assert stats["indexed"] == len(DEMO_CARDS), stats
    return store, db_path
