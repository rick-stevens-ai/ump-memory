"""Multi-modal indexing layer for UMP memory stores.

Builds a SQLite FTS5 + structured field index from a UMP store directory,
enabling four orthogonal retrieval axes alongside the native semantic
``recall()`` path of the base ``UMPStore``:

- exact      : SQLite FTS5 MATCH (phrase, boolean, prefix)
- regex      : Python ``re`` over indexed body text
- structured : SQL filter on structured columns + JOINs on multi-value fields
- hybrid     : reciprocal-rank fusion of the above + an optional semantic axis

The semantic axis remains the existing UMPStore.recall() — this layer does
not replace it, it augments it. See ``docs/multimodal-indexing.md`` and the
``examples/multimodal/`` directory for worked examples.

Validated against a 36,026-card OSTI author-contact corpus (Jun 2026).
"""

from .indexer import IndexBuilder, build_index, parse_card
from .search import (
    MultiSearch,
    SearchResult,
    search_exact,
    search_hybrid,
    search_regex,
    search_structured,
)
from .server import MultiSearchServer, run_server

__all__ = [
    "IndexBuilder",
    "MultiSearch",
    "MultiSearchServer",
    "SearchResult",
    "build_index",
    "parse_card",
    "run_server",
    "search_exact",
    "search_hybrid",
    "search_regex",
    "search_structured",
]
