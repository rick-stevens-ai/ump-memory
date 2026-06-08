"""SQLite FTS5 + structured field indexer for UMP cards.

Reads a directory of UMP records (``*.ump.md`` or ``*.json``), parses JSON
frontmatter + markdown body, and populates a SQLite database with:

- ``ump_card``       : one row per record (path, mtime, primary fields)
- ``ump_card_field`` : multi-value field index (labs, names, topics, ...)
- ``ump_card_tag``   : tag index
- ``ump_fts``        : FTS5 virtual table with ``@.-_+`` as tokenchars (so
                       emails stay as single tokens, not split on ``@``)
- ``ump_fts_trigram``: FTS5 trigram tokenizer for substring matching

Incremental: tracks per-file mtime, re-indexes only changed cards.
Idempotent: safe to re-run.

Production stats: 36,026 cards indexed in ~110s on M1 (full rebuild),
seconds-level for typical incremental ticks.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)

# Default multi-value field names hoisted into ump_card_field. Override via
# IndexBuilder(multi_value_fields=...).
DEFAULT_MULTI_VALUE_FIELDS: tuple[str, ...] = (
    "labs",
    "names",
    "topics",
    "affiliations",
    "paper_ids",
)


def _as_list(v: Any) -> list[str]:
    """Normalize list-or-string-or-bracketed-string to a list of strings.

    Handles three common shapes seen in real UMP corpora:
    - ``["FNAL", "ANL"]``        → ``["FNAL", "ANL"]``
    - ``"FNAL"``                  → ``["FNAL"]``
    - ``"[FNAL, ANL]"``           → ``["FNAL", "ANL"]`` (bracket-string)
    """
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x) for x in v if x is not None]
    s = str(v).strip()
    if not s:
        return []
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1]
        return [p.strip().strip('"\'') for p in inner.split(",") if p.strip()]
    return [s]


def parse_card(path: Path) -> dict[str, Any] | None:
    """Parse a UMP card file. Frontmatter is JSON, body is markdown.

    Returns a dict with keys ``id``, ``path``, ``mtime``, ``meta``, ``text``.
    Returns ``None`` if the file cannot be read.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None

    m = FRONTMATTER_RE.match(raw)
    if not m:
        # No frontmatter — treat whole file as opaque text
        return {
            "id": path.stem.replace(".ump", ""),
            "path": str(path),
            "mtime": path.stat().st_mtime,
            "meta": {},
            "text": raw,
        }

    fm_block, body = m.group(1), m.group(2)
    try:
        record = json.loads(fm_block)
    except json.JSONDecodeError:
        # Legacy YAML-ish fallback for non-UMP cards
        record = _parse_yaml_ish(fm_block)

    # Hoist scope.* and body.structured.* up so the field extractor finds them
    meta: dict[str, Any] = {
        "id": record.get("id"),
        "kind": record.get("kind"),
    }
    scope = record.get("scope") or {}
    meta["owner"] = scope.get("owner")
    meta["project"] = scope.get("project")
    meta["visibility"] = scope.get("visibility")
    meta["topic_scope"] = scope.get("topic")

    structured = (record.get("body") or {}).get("structured") or {}
    for k, v in structured.items():
        meta[k] = v

    meta["tags"] = (
        record.get("tags")
        or (record.get("lifecycle") or {}).get("tags")
        or []
    )

    # Body text for FTS: prefer body.text, fall back to markdown body, fall
    # back to JSON dump of structured (so structured-only cards still hit FTS)
    body_obj = record.get("body") or {}
    text_parts: list[str] = []
    if body_obj.get("text"):
        text_parts.append(str(body_obj["text"]))
    if body.strip():
        text_parts.append(body.strip())
    if structured:
        text_parts.append(json.dumps(structured, default=str))
    text = "\n\n".join(text_parts)

    card_id = meta.get("id") or path.stem.replace(".ump", "")
    return {
        "id": str(card_id),
        "path": str(path),
        "mtime": path.stat().st_mtime,
        "meta": meta,
        "text": text,
    }


def _parse_yaml_ish(fm_block: str) -> dict[str, Any]:
    """Minimal YAML-ish parser for legacy / non-UMP frontmatter."""
    record: dict[str, Any] = {}
    cur_list_key: str | None = None
    for line in fm_block.splitlines():
        if not line.strip():
            cur_list_key = None
            continue
        if line.startswith("  - ") and cur_list_key:
            record.setdefault(cur_list_key, []).append(
                line[4:].strip().strip('"\'')
            )
            continue
        if ":" in line and not line.startswith(" "):
            k, _, v = line.partition(":")
            k = k.strip()
            v = v.strip()
            if not v:
                cur_list_key = k
                record[k] = []
            else:
                cur_list_key = None
                record[k] = v.strip('"\'')
    return record


_SCHEMA_SQL = """
create table if not exists ump_card (
    id text primary key,
    path text not null,
    mtime real not null,
    kind text,
    owner text,
    project text,
    visibility text,
    primary_lab text,
    primary_name text,
    email text,
    paper_count integer,
    contact_kind text,
    indexed_at real not null
);
create index if not exists idx_card_lab on ump_card(primary_lab);
create index if not exists idx_card_email on ump_card(email);
create index if not exists idx_card_kind on ump_card(kind);
create index if not exists idx_card_papers on ump_card(paper_count);

create table if not exists ump_card_tag (
    id text not null,
    tag text not null,
    primary key (id, tag)
);
create index if not exists idx_tag on ump_card_tag(tag);

create table if not exists ump_card_field (
    id text not null,
    field text not null,
    value text not null,
    primary key (id, field, value)
);
create index if not exists idx_field on ump_card_field(field, value);

create virtual table if not exists ump_fts using fts5(
    id unindexed,
    text,
    meta_blob,
    tokenize = 'unicode61 remove_diacritics 2 tokenchars ''@.-_+'''
);

create virtual table if not exists ump_fts_trigram using fts5(
    id unindexed,
    text,
    tokenize = 'trigram'
);
"""


@dataclass
class IndexBuilder:
    """Incremental FTS5 + structured index over a UMP store directory.

    Parameters
    ----------
    store_dir
        Directory containing ``*.ump.md`` (or ``*.json``) UMP records.
    db_path
        Destination SQLite file. Will be created with WAL journal mode.
    multi_value_fields
        Tuple of meta-field names to hoist into ``ump_card_field`` for
        structured-axis JOINs. Defaults cover the OSTI corpus shape; override
        for other domains.
    glob
        File pattern. Default ``*.ump.md``.

    Examples
    --------
    >>> from pathlib import Path
    >>> from ump_memory.multimodal import IndexBuilder
    >>> builder = IndexBuilder(
    ...     store_dir=Path("/var/ump/store"),
    ...     db_path=Path("/var/ump/index.db"),
    ... )
    >>> stats = builder.rebuild()
    >>> stats["indexed"]
    36026
    """

    store_dir: Path
    db_path: Path
    multi_value_fields: tuple[str, ...] = DEFAULT_MULTI_VALUE_FIELDS
    glob: str = "*.ump.md"
    _commit_every: int = 2000

    def init_db(self, db: sqlite3.Connection) -> None:
        db.executescript(_SCHEMA_SQL)
        db.commit()

    def upsert(self, db: sqlite3.Connection, card: dict[str, Any]) -> None:
        meta = card["meta"]
        cid = card["id"]
        text = card["text"]

        # Multi-value extraction
        field_values: dict[str, list[str]] = {
            f: _as_list(meta.get(f)) for f in self.multi_value_fields
        }
        labs_list = field_values.get("labs", [])
        names_list = field_values.get("names", [])

        primary_lab = meta.get("primary_lab") or (labs_list[0] if labs_list else None)
        primary_name = meta.get("primary_name") or (names_list[0] if names_list else None)

        pc_raw = meta.get("paper_count")
        try:
            paper_count = int(pc_raw) if pc_raw not in (None, "") else None
        except (TypeError, ValueError):
            paper_count = None

        db.execute(
            """
            insert into ump_card(id, path, mtime, kind, owner, project, visibility,
                                 primary_lab, primary_name, email, paper_count,
                                 contact_kind, indexed_at)
            values (?,?,?,?,?,?,?,?,?,?,?,?,?)
            on conflict(id) do update set
                path=excluded.path, mtime=excluded.mtime, kind=excluded.kind,
                owner=excluded.owner, project=excluded.project, visibility=excluded.visibility,
                primary_lab=excluded.primary_lab, primary_name=excluded.primary_name,
                email=excluded.email, paper_count=excluded.paper_count,
                contact_kind=excluded.contact_kind, indexed_at=excluded.indexed_at
            """,
            (
                cid,
                card["path"],
                card["mtime"],
                meta.get("kind"),
                meta.get("owner"),
                meta.get("project"),
                meta.get("visibility"),
                primary_lab,
                primary_name,
                meta.get("email"),
                paper_count,
                meta.get("contact_kind"),
                time.time(),
            ),
        )

        # Tags
        db.execute("delete from ump_card_tag where id = ?", (cid,))
        tags = meta.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",")]
        for t in tags:
            db.execute(
                "insert or ignore into ump_card_tag(id, tag) values (?, ?)",
                (cid, str(t)),
            )

        # Multi-value fields
        db.execute("delete from ump_card_field where id = ?", (cid,))
        for fname, vals in field_values.items():
            for v in vals:
                db.execute(
                    "insert or ignore into ump_card_field(id, field, value) values (?, ?, ?)",
                    (cid, fname, str(v)),
                )

        # FTS rows
        meta_blob = json.dumps(meta, default=str)
        db.execute("delete from ump_fts where id = ?", (cid,))
        db.execute(
            "insert into ump_fts(id, text, meta_blob) values (?, ?, ?)",
            (cid, text, meta_blob),
        )
        db.execute("delete from ump_fts_trigram where id = ?", (cid,))
        db.execute(
            "insert into ump_fts_trigram(id, text) values (?, ?)",
            (cid, text),
        )

    def rebuild(self, full: bool = False, progress: bool = False) -> dict[str, int]:
        """Scan ``store_dir`` and upsert any changed cards.

        Parameters
        ----------
        full
            If True, ignore mtime and reindex every card.
        progress
            If True, print a progress line every ``_commit_every`` upserts.
        """
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(str(self.db_path))
        db.execute("pragma journal_mode=wal")
        db.execute("pragma synchronous=normal")
        self.init_db(db)

        known: dict[str, float] = {}
        if not full:
            for row in db.execute("select id, mtime from ump_card"):
                known[row[0]] = row[1]

        files = sorted(self.store_dir.glob(self.glob))
        stats: dict[str, Any] = {"total": len(files), "indexed": 0, "skipped": 0, "errors": 0}
        t0 = time.time()

        db.execute("begin")
        for i, path in enumerate(files, 1):
            try:
                mt = path.stat().st_mtime
                card = parse_card(path)
                if card is None:
                    stats["errors"] += 1
                    continue
                if not full and known.get(card["id"]) == mt:
                    stats["skipped"] += 1
                    continue
                self.upsert(db, card)
                stats["indexed"] += 1
                if stats["indexed"] % self._commit_every == 0:
                    db.execute("commit")
                    db.execute("begin")
                    if progress:
                        elapsed = time.time() - t0
                        rate = stats["indexed"] / elapsed if elapsed else 0
                        eta = (stats["total"] - i) / rate if rate else 0
                        print(
                            f"  [{i}/{stats['total']}] indexed={stats['indexed']} "
                            f"skipped={stats['skipped']} err={stats['errors']} "
                            f"rate={rate:.0f}/s eta={eta/60:.1f}min",
                            flush=True,
                        )
            except Exception as e:
                stats["errors"] += 1
                if stats["errors"] <= 5:
                    print(f"  err on {path.name}: {e}", file=sys.stderr)

        db.execute("commit")
        db.close()
        stats["elapsed_s"] = round(time.time() - t0, 2)
        return stats


def build_index(
    store_dir: Path | str,
    db_path: Path | str,
    *,
    full: bool = False,
    progress: bool = False,
    multi_value_fields: Iterable[str] | None = None,
    glob: str = "*.ump.md",
) -> dict[str, int]:
    """One-shot convenience wrapper around :class:`IndexBuilder.rebuild`."""
    builder = IndexBuilder(
        store_dir=Path(store_dir),
        db_path=Path(db_path),
        multi_value_fields=tuple(multi_value_fields) if multi_value_fields else DEFAULT_MULTI_VALUE_FIELDS,
        glob=glob,
    )
    return builder.rebuild(full=full, progress=progress)


def _cli() -> None:
    ap = argparse.ArgumentParser(
        prog="ump-memory-index",
        description="Build the UMP multi-modal SQLite index.",
    )
    ap.add_argument("--store", required=True, type=Path, help="UMP store directory")
    ap.add_argument("--db", required=True, type=Path, help="SQLite index database path")
    ap.add_argument("--full", action="store_true", help="rebuild from scratch (ignore mtime)")
    ap.add_argument("--glob", default="*.ump.md", help="card filename glob (default: *.ump.md)")
    ap.add_argument("--quiet", action="store_true", help="suppress progress output")
    args = ap.parse_args()

    stats = build_index(
        args.store, args.db,
        full=args.full,
        progress=not args.quiet,
        glob=args.glob,
    )
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    _cli()
