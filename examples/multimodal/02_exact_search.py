"""Example 2: exact search (SQLite FTS5).

The FTS5 virtual table uses a custom tokenizer with ``@.-_+`` as token
characters, so emails stay as single searchable tokens (the default
``unicode61`` tokenizer would split ``alice@ornl.gov`` into 3 useless
fragments).

Shows three idioms:
  - exact phrase (`"alice@ornl.gov"`)
  - boolean AND
  - prefix match (``toka*``)
"""
from __future__ import annotations

from _demo_corpus import build_demo_corpus
from ump_memory.multimodal import MultiSearch


def show(label: str, hits) -> None:
    print(f"\n[{label}]  {len(hits)} hits")
    for h in hits[:5]:
        struct = h.record["body"]["structured"]
        snippet = h.signals.get("snippet", "")
        print(f"  {h.score:.3f}  {struct.get('primary_name'):28} "
              f"{struct.get('primary_lab'):6}  papers={struct.get('paper_count')}")
        if snippet:
            print(f"          {snippet[:80]}")


def main() -> None:
    _, db = build_demo_corpus()

    with MultiSearch(db) as ms:
        # 1. Exact email — only works because of the custom tokenizer
        show('exact phrase: "alice@ornl.gov"',
             ms.exact('"alice@ornl.gov"', limit=5))

        # 2. Boolean AND — find docs mentioning BOTH terms
        show("boolean: battery AND cathode",
             ms.exact("battery AND cathode", limit=5))

        # 3. Prefix — useful when you know a word stem
        show("prefix: toka*",
             ms.exact("toka*", limit=5))

        # 4. Boolean with negation
        show("boolean: fusion NOT tokamak",
             ms.exact("fusion NOT tokamak", limit=5))


if __name__ == "__main__":
    main()
