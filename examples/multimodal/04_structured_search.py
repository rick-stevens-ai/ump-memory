"""Example 4: structured search (SQL filters + multi-value JOINs).

Filters operate on:
  - Scalar columns of ``ump_card``        (primary_lab, email, paper_count, ...)
  - Multi-value rows in ``ump_card_field`` (labs, names, topics, ...) via JOIN

Combine them to slice the corpus precisely without scanning text at all.
This axis is the fastest for "give me all X in lab Y with > N papers" queries.
"""
from __future__ import annotations

from _demo_corpus import build_demo_corpus
from ump_memory.multimodal import MultiSearch


def show(label: str, hits) -> None:
    print(f"\n[{label}]  {len(hits)} hits")
    for h in hits[:5]:
        s = h.record["body"]["structured"]
        print(f"  {s.get('primary_name'):28}  {s.get('primary_lab'):6}  "
              f"papers={s.get('paper_count'):>4}  email={s.get('email')}")


def main() -> None:
    _, db = build_demo_corpus()

    with MultiSearch(db) as ms:
        # Single-column filter
        show("primary_lab = ORNL",
             ms.structured({"primary_lab": "ORNL"}))

        # Numeric range
        show("paper_count >= 100",
             ms.structured({"paper_count_min": 100}))

        # Combine columns
        show("ORNL + paper_count >= 50",
             ms.structured({"primary_lab": "ORNL", "paper_count_min": 50}))

        # Multi-value JOIN — topic from ump_card_field
        show("topic LIKE %Fusion%",
             ms.structured({"topic_like": "%Fusion%"}))

        # IN clause on multi-value labs (e.g. multi-lab collaborators)
        show("lab IN (PPPL, LBNL)",
             ms.structured({"lab_in": ["PPPL", "LBNL"]}))

        # Combine everything
        show("FNAL + papers >= 500 + Particle Physics topic",
             ms.structured({
                 "primary_lab": "FNAL",
                 "paper_count_min": 500,
                 "topic_like": "%Particle Physics%",
             }))


if __name__ == "__main__":
    main()
