"""Five-axis search over the multi-modal UMP index.

Axes
----
- ``search_exact``      : SQLite FTS5 MATCH (phrase, boolean AND/OR/NOT, prefix)
- ``search_regex``      : Python ``re`` over indexed body text (linear scan)
- ``search_structured`` : SQL WHERE on structured columns + multi-value JOINs
- semantic              : delegated to the existing ``UMPStore.recall`` (call
                          it directly or wire it into ``search_hybrid``)
- ``search_hybrid``     : reciprocal-rank fusion (RRF) of the above

All axes return :class:`SearchResult` objects with a UMP-shaped record and an
axis-specific signals dict. RRF default ``k=60`` (per the standard formula
from Cormack et al., 2009).
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence


@dataclass
class SearchResult:
    """A search hit. ``record`` is a UMP-shaped dict, ``signals`` is axis-specific."""

    record: dict[str, Any]
    score: float
    signals: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _connect(db_path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(str(db_path))
    db.row_factory = sqlite3.Row
    return db


def _row_to_record(row: sqlite3.Row, body_text: str = "") -> dict[str, Any]:
    """Wrap a row from ``ump_card`` as a minimal UMP-shaped record."""
    return {
        "id": row["id"],
        "kind": row["kind"],
        "scope": {
            "owner": row["owner"],
            "project": row["project"],
            "visibility": row["visibility"],
        },
        "body": {
            "text": body_text,
            "structured": {
                "primary_lab": row["primary_lab"],
                "primary_name": row["primary_name"],
                "email": row["email"],
                "paper_count": row["paper_count"],
                "contact_kind": row["contact_kind"],
            },
        },
    }


def _load_body(db: sqlite3.Connection, id_: str) -> str:
    row = db.execute("select text from ump_fts where id = ?", (id_,)).fetchone()
    return row[0] if row else ""


# ---------------------------------------------------------------------------
# Axis 1: exact (FTS5)
# ---------------------------------------------------------------------------

def search_exact(
    db: sqlite3.Connection,
    query: str,
    limit: int = 10,
) -> list[SearchResult]:
    """FTS5 ``MATCH`` query. Supports phrases, booleans, prefixes.

    Examples
    --------
    >>> search_exact(db, '"junlu@anl.gov"')            # exact phrase
    >>> search_exact(db, "battery AND cathode AND ornl")  # boolean
    >>> search_exact(db, "neutrin*")                   # prefix
    """
    rows = db.execute(
        """
        select c.*, snippet(ump_fts, 1, '⟦', '⟧', '…', 16) as snip,
               rank as fts_rank
        from ump_fts
        join ump_card c on c.id = ump_fts.id
        where ump_fts match ?
        order by rank
        limit ?
        """,
        (query, limit),
    ).fetchall()

    results: list[SearchResult] = []
    for r in rows:
        rec = _row_to_record(r, body_text=_load_body(db, r["id"])[:2000])
        # FTS5 rank is negative (lower = better); normalize to (0, 1]
        score = 1.0 / (1.0 + abs(r["fts_rank"]))
        results.append(SearchResult(
            record=rec,
            score=score,
            signals={"fts_rank": r["fts_rank"], "snippet": r["snip"]},
        ))
    return results


# ---------------------------------------------------------------------------
# Axis 2: regex (Python re)
# ---------------------------------------------------------------------------

def search_regex(
    db: sqlite3.Connection,
    pattern: str,
    limit: int = 10,
    flags: int = re.IGNORECASE,
) -> list[SearchResult]:
    """Compile ``pattern`` and scan ``ump_fts.text``.

    Linear in #cards but fast in CPython. Stops at ``limit`` hits.
    """
    try:
        rx = re.compile(pattern, flags)
    except re.error as e:
        raise ValueError(f"bad regex: {e}") from e

    results: list[SearchResult] = []
    for id_, text in db.execute("select id, text from ump_fts"):
        m = rx.search(text or "")
        if not m:
            continue
        row = db.execute("select * from ump_card where id = ?", (id_,)).fetchone()
        if not row:
            continue
        s, e = m.start(), m.end()
        snip = (
            text[max(0, s - 60):s] + "⟦" + text[s:e] + "⟧" + text[e:e + 60]
        ).replace("\n", " ")
        rec = _row_to_record(row, body_text=text[:2000])
        results.append(SearchResult(
            record=rec,
            score=1.0,  # regex is binary
            signals={"match": m.group(0), "snippet": snip},
        ))
        if len(results) >= limit:
            break
    return results


# ---------------------------------------------------------------------------
# Axis 3: structured (SQL + JOINs)
# ---------------------------------------------------------------------------

_ORDER_BY_RE = re.compile(
    r"^[a-zA-Z_.]+(\s+(asc|desc))?(\s+nulls\s+(first|last))?$",
    re.IGNORECASE,
)


def search_structured(
    db: sqlite3.Connection,
    filters: dict[str, Any],
    limit: int = 10,
) -> list[SearchResult]:
    """SQL WHERE on ``ump_card`` + JOINs on ``ump_card_field``.

    Supported filter keys
    ---------------------
    primary_lab        : exact match on ``ump_card.primary_lab``
    email              : exact match on ``ump_card.email``
    email_like         : ``LIKE`` pattern on ``ump_card.email``
    paper_count_min    : ``ump_card.paper_count >= N``
    paper_count_max    : ``ump_card.paper_count <= N``
    contact_kind       : exact match
    topic_like         : ``LIKE`` against ``ump_card_field`` where field='topics'
    name_like          : ``LIKE`` against ``ump_card_field`` where field='names'
    lab_in             : list of labs to match in ``ump_card_field``
    order_by           : SQL fragment, whitelisted to ``COL [asc|desc] [nulls first|last]``
                         default: ``c.paper_count desc nulls last``

    Examples
    --------
    >>> search_structured(db, {"primary_lab": "ORNL", "paper_count_min": 50})
    >>> search_structured(db, {"lab_in": ["PPPL", "FNAL"], "topic_like": "%Fusion%"})
    """
    where: list[str] = []
    params: list[Any] = []
    joins: list[str] = []

    if filters.get("primary_lab"):
        where.append("c.primary_lab = ?")
        params.append(filters["primary_lab"])
    if filters.get("email"):
        where.append("c.email = ?")
        params.append(filters["email"])
    if filters.get("email_like"):
        where.append("c.email like ?")
        params.append(filters["email_like"])
    if filters.get("paper_count_min") is not None:
        where.append("c.paper_count >= ?")
        params.append(int(filters["paper_count_min"]))
    if filters.get("paper_count_max") is not None:
        where.append("c.paper_count <= ?")
        params.append(int(filters["paper_count_max"]))
    if filters.get("contact_kind"):
        where.append("c.contact_kind = ?")
        params.append(filters["contact_kind"])
    if filters.get("topic_like"):
        joins.append("join ump_card_field ft on ft.id=c.id and ft.field='topics'")
        where.append("ft.value like ?")
        params.append(filters["topic_like"])
    if filters.get("name_like"):
        joins.append("join ump_card_field fn on fn.id=c.id and fn.field='names'")
        where.append("fn.value like ?")
        params.append(filters["name_like"])
    if filters.get("lab_in"):
        joins.append("join ump_card_field fl on fl.id=c.id and fl.field='labs'")
        placeholders = ",".join("?" * len(filters["lab_in"]))
        where.append(f"fl.value in ({placeholders})")
        params.extend(filters["lab_in"])

    order = filters.get("order_by") or "c.paper_count desc nulls last"
    if not _ORDER_BY_RE.match(order):
        order = "c.paper_count desc nulls last"

    sql = f"""
        select distinct c.* from ump_card c
        {' '.join(joins)}
        where {' and '.join(where) if where else '1=1'}
        order by {order}
        limit ?
    """
    params.append(limit)

    rows = db.execute(sql, params).fetchall()
    results: list[SearchResult] = []
    for r in rows:
        rec = _row_to_record(r, body_text=_load_body(db, r["id"])[:1000])
        results.append(SearchResult(
            record=rec,
            score=1.0,
            signals={"filter": dict(filters)},
        ))
    return results


# ---------------------------------------------------------------------------
# Axis 4: hybrid (RRF over any subset of axes + optional semantic callable)
# ---------------------------------------------------------------------------

SemanticAxis = Callable[[str, int], Sequence[Any]]


def search_hybrid(
    db: sqlite3.Connection,
    query: str,
    *,
    filters: dict[str, Any] | None = None,
    semantic: SemanticAxis | None = None,
    limit: int = 10,
    k: int = 60,
    weights: dict[str, float] | None = None,
) -> list[SearchResult]:
    """Reciprocal-rank fusion of exact + (optional) semantic + (optional) structured.

    Parameters
    ----------
    semantic
        Callable ``(query, limit) -> sequence`` returning either
        :class:`SearchResult` instances or dicts with a ``record`` key. Lets
        callers plug in any semantic backend (the existing ``UMPStore.recall``,
        a vector DB, an HTTP proxy, etc.) without coupling this module to one.
    weights
        Per-axis multipliers. Defaults: ``exact=1.0, semantic=1.0,
        structured=1.5`` (precise filters weight higher).

    Notes
    -----
    RRF formula: ``score(doc) = Σ_axis weight_axis / (k + rank_axis)``.
    With ``k=60``, a doc at rank 1 in two axes scores ~0.032, a doc at rank 1
    in one axis scores ~0.016, a doc at rank 100 scores ~0.006 — i.e.
    multi-axis hits dominate rare deep hits, which is the desired behavior.
    """
    w = {"exact": 1.0, "semantic": 1.0, "structured": 1.5}
    if weights:
        w.update(weights)

    axes: list[tuple[str, list[Any], float]] = []

    # Exact axis (always)
    try:
        exact_hits = search_exact(db, query, limit=limit * 2)
        axes.append(("exact", list(exact_hits), w["exact"]))
    except sqlite3.OperationalError:
        pass  # FTS5 syntax error — caller passed something that isn't a MATCH query

    # Semantic axis (optional)
    if semantic is not None:
        try:
            sem_hits = list(semantic(query, limit * 2))
            axes.append(("semantic", sem_hits, w["semantic"]))
        except Exception as e:
            axes.append(("semantic", [{"error": str(e)}], 0.0))

    # Structured axis (only when filters given)
    if filters:
        struct_hits = search_structured(db, filters, limit=limit * 2)
        axes.append(("structured", list(struct_hits), w["structured"]))

    # RRF fusion
    fused: dict[str, dict[str, Any]] = {}
    for axis_name, hits, weight in axes:
        for rank, item in enumerate(hits, 1):
            rec = _extract_record(item)
            id_ = rec.get("id") if isinstance(rec, dict) else None
            if not id_:
                continue
            slot = fused.setdefault(id_, {
                "record": rec,
                "rrf_score": 0.0,
                "signals": {"axes": []},
            })
            slot["rrf_score"] += weight / (k + rank)
            slot["signals"]["axes"].append({
                "axis": axis_name,
                "rank": rank,
                "weight": weight,
                "axis_signals": _extract_signals(item),
            })

    ranked = sorted(fused.values(), key=lambda x: -x["rrf_score"])[:limit]
    return [SearchResult(record=x["record"], score=x["rrf_score"], signals=x["signals"]) for x in ranked]


def _extract_record(item: Any) -> dict[str, Any]:
    if isinstance(item, SearchResult):
        return item.record
    if isinstance(item, dict):
        rec = item.get("record")
        if isinstance(rec, dict):
            return rec
        # legacy shape: dict IS the record
        if "id" in item:
            return item
    return {}


def _extract_signals(item: Any) -> dict[str, Any]:
    if isinstance(item, SearchResult):
        return item.signals
    if isinstance(item, dict):
        return item.get("signals", {})
    return {}


# ---------------------------------------------------------------------------
# Stateful convenience wrapper
# ---------------------------------------------------------------------------

@dataclass
class MultiSearch:
    """Stateful handle that owns a SQLite connection and exposes the 4 axes.

    Examples
    --------
    >>> from pathlib import Path
    >>> from ump_memory.multimodal import MultiSearch
    >>> ms = MultiSearch(Path("/var/ump/index.db"))
    >>> hits = ms.exact('"junlu@anl.gov"', limit=5)
    >>> hits = ms.structured({"primary_lab": "ORNL", "paper_count_min": 50})
    >>> hits = ms.hybrid("battery cathode", filters={"primary_lab": "ORNL"})
    """

    db_path: Path
    _db: sqlite3.Connection | None = None

    def db(self) -> sqlite3.Connection:
        if self._db is None:
            self._db = _connect(self.db_path)
        return self._db

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None

    def __enter__(self) -> "MultiSearch":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def exact(self, query: str, limit: int = 10) -> list[SearchResult]:
        return search_exact(self.db(), query, limit=limit)

    def regex(self, pattern: str, limit: int = 10, flags: int = re.IGNORECASE) -> list[SearchResult]:
        return search_regex(self.db(), pattern, limit=limit, flags=flags)

    def structured(self, filters: dict[str, Any], limit: int = 10) -> list[SearchResult]:
        return search_structured(self.db(), filters, limit=limit)

    def hybrid(
        self,
        query: str,
        *,
        filters: dict[str, Any] | None = None,
        semantic: SemanticAxis | None = None,
        limit: int = 10,
        k: int = 60,
        weights: dict[str, float] | None = None,
    ) -> list[SearchResult]:
        return search_hybrid(
            self.db(), query,
            filters=filters, semantic=semantic, limit=limit, k=k, weights=weights,
        )

    def card_count(self) -> int:
        return self.db().execute("select count(*) from ump_card").fetchone()[0]
