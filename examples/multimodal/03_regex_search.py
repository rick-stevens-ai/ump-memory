"""Example 3: regex search (Python ``re``).

Linear-in-#cards scan over the indexed body text, but fast enough for
tens of thousands of cards. Use this when you need pattern-shape that
FTS5 can't express — e.g. "all CERN collaboration mailer addresses" or
"all DOE.gov-style emails."
"""
from __future__ import annotations

from _demo_corpus import build_demo_corpus
from ump_memory.multimodal import MultiSearch


def show(label: str, hits) -> None:
    print(f"\n[{label}]  {len(hits)} hits")
    for h in hits[:5]:
        struct = h.record["body"]["structured"]
        m = h.signals.get("match", "")
        snip = h.signals.get("snippet", "")
        print(f"  {struct.get('primary_name'):30}  matched: {m!r}")
        print(f"     {snip[:90]}")


def main() -> None:
    _, db = build_demo_corpus()

    with MultiSearch(db) as ms:
        # Collaboration mailers (cms-, atlas-, alice-style addresses)
        show(r"pattern: cms-.*@cern\.ch",
             ms.regex(r"cms-.*@cern\.ch", limit=10))

        # All .gov lab addresses
        show(r"pattern: [a-z]+@[a-z]+\.gov",
             ms.regex(r"[a-z]+@[a-z]+\.gov", limit=10))

        # Capitalized lab acronyms (3-5 chars) — useful for spotting refs
        show(r"pattern: \b(ORNL|ANL|PPPL|LBNL|FNAL)\b",
             ms.regex(r"\b(ORNL|ANL|PPPL|LBNL|FNAL)\b", limit=10))


if __name__ == "__main__":
    main()
