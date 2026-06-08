"""Example 5: hybrid search (reciprocal-rank fusion).

Combines exact + structured + (optional) semantic into a single ranked list,
where docs that hit multiple axes float to the top.

RRF formula: ``score(doc) = Σ_axes weight / (k + rank_in_axis)``  (k=60 default).

You supply the semantic axis as a callable — this keeps ``ump_memory.multimodal``
decoupled from any specific vector backend. Plug in:
  - The existing ``ump_memory.store.UMPStore.recall`` for Jaccard recall
  - A vector DB client (Qdrant / Weaviate / pgvector)
  - An HTTP proxy to a running ``ump-memory-server``
  - A no-op (just exact + structured fusion)
"""
from __future__ import annotations

from _demo_corpus import build_demo_corpus
from ump_memory.multimodal import MultiSearch


def show(label: str, hits) -> None:
    print(f"\n[{label}]  {len(hits)} hits")
    for h in hits[:5]:
        s = h.record["body"]["structured"]
        axes = [a["axis"] for a in h.signals.get("axes", [])]
        print(f"  rrf={h.score:.4f}  {s.get('primary_name'):28}  "
              f"{s.get('primary_lab'):6}  axes={axes}")


def fake_semantic(query: str, limit: int) -> list[dict]:
    """Toy semantic backend. In real use plug in UMPStore.recall(), Qdrant, etc."""
    # Pretend it always thinks Carol is most relevant to fusion-ish queries
    if "fusion" in query.lower() or "plasma" in query.lower():
        return [
            {"record": {"id": "contact:carol@pppl.gov", "kind": "contact"},
             "score": 0.9, "signals": {"backend": "fake"}},
            {"record": {"id": "contact:bob@anl.gov", "kind": "contact"},
             "score": 0.7, "signals": {"backend": "fake"}},
        ]
    return []


def main() -> None:
    _, db = build_demo_corpus()

    with MultiSearch(db) as ms:
        # Exact + structured fusion (no semantic) — Alice wins because she's
        # the only doc hitting BOTH "battery cathode" (exact) AND ORNL (filter)
        show("battery cathode + ORNL filter (exact ∪ structured)",
             ms.hybrid("battery cathode",
                       filters={"primary_lab": "ORNL"}, limit=5))

        # Exact + semantic (no filter) — semantic axis adds Carol/Bob even if
        # they don't lexically match all the same tokens
        show("fusion (exact ∪ fake_semantic)",
             ms.hybrid("fusion", semantic=fake_semantic, limit=5))

        # All three axes — semantic adds candidates, exact and structured
        # ratify them
        show("fusion + PPPL filter (exact ∪ semantic ∪ structured)",
             ms.hybrid("fusion",
                       semantic=fake_semantic,
                       filters={"primary_lab": "PPPL"},
                       limit=5))


if __name__ == "__main__":
    main()
