"""Example 1: build the index.

Demonstrates the incremental SQLite/FTS5 indexer over a UMP store directory.
Run it once → 5 cards indexed. Run it again → 5 skipped (mtime unchanged).
Touch a card → next run reindexes only that one.
"""
from __future__ import annotations

from pathlib import Path

from _demo_corpus import build_demo_corpus
from ump_memory.multimodal import build_index


def main() -> None:
    store, db = build_demo_corpus()
    print(f"Store dir : {store}")
    print(f"Index DB  : {db}")
    print()

    print("First incremental pass (cards already indexed by fixture):")
    stats = build_index(store, db)
    print(f"  total={stats['total']} indexed={stats['indexed']} "
          f"skipped={stats['skipped']} errors={stats['errors']} "
          f"elapsed={stats['elapsed_s']}s")

    print()
    print("Touch one card and re-run:")
    sample = next(store.glob("*.ump.md"))
    sample.touch()
    stats = build_index(store, db)
    print(f"  total={stats['total']} indexed={stats['indexed']} "
          f"skipped={stats['skipped']}  ← only the touched one")

    print()
    print("Force full rebuild:")
    stats = build_index(store, db, full=True)
    print(f"  total={stats['total']} indexed={stats['indexed']} "
          f"skipped={stats['skipped']}")


if __name__ == "__main__":
    main()
