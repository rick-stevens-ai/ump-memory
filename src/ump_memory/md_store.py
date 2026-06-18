"""Markdown-directory UMP store.

Each record is a single ``*.ump.md`` file with JSON frontmatter (between ``---``
fences) and a free-text body. Frontmatter is the canonical record envelope as
produced by the upstream JS reference implementation; this Python store reads
and writes the same on-disk shape so the two implementations can interoperate.

Why a separate file from ``store.py``:
- ``UMPStore`` (JSONL) is the lightweight reference store used in tests and by
  the CLI for single-user workflows.
- ``MarkdownDirectoryStore`` is the production-shape store: one file per record,
  rich frontmatter, suitable for Dropbox/git sync.

Both stores expose the same minimal API surface (``capabilities``, ``list``,
``get``, ``put``, ``recall``) so the server can dispatch on configuration.
"""

from __future__ import annotations

import json
import math
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .models import MemoryRecord, utc_now
from .store import RecallResult, scope_match, tokenize

_FENCE = "---"
_ID_RE = re.compile(r"^urn:ump:([A-Za-z0-9_\-]+)$")


def _id_to_filename(record_id: str) -> str:
    """Map a UMP record id to a stable filesystem name.

    - ``urn:ump:<slug>`` → ``<slug>.ump.md`` (matches the JS impl on disk)
    - anything else      → sha-safe slug of the raw id
    """
    m = _ID_RE.match(record_id or "")
    if m:
        return f"{m.group(1)}.ump.md"
    safe = re.sub(r"[^A-Za-z0-9_\-]+", "_", record_id or "anon")
    return f"{safe}.ump.md"


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse ``---\\n{json}\\n---\\n<body>`` → (envelope, body).

    Returns ``({}, text)`` if no recognisable frontmatter is present so callers
    can still surface the body for lexical recall.
    """
    if not text.startswith(_FENCE):
        return {}, text
    lines = text.split("\n")
    # find closing fence
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == _FENCE:
            end = i
            break
    if end is None:
        return {}, text
    raw = "\n".join(lines[1:end])
    try:
        env = json.loads(raw)
    except json.JSONDecodeError:
        return {}, text
    body = "\n".join(lines[end + 1 :]).lstrip("\n")
    return env, body


def _envelope_to_record(env: dict[str, Any], body: str) -> MemoryRecord:
    """Best-effort projection of a UMP-spec envelope onto our flat MemoryRecord.

    The upstream envelope has more structure (time/lifecycle/integrity/superseded_by)
    than we model directly; we preserve it under ``metadata['envelope']`` so a
    caller that wants the full shape can still get it back.
    """
    scope = env.get("scope") or {}
    structured = (env.get("body") or {}).get("structured") or {}
    title = structured.get("summary") or structured.get("id") or env.get("title")
    text = body.strip() or title or json.dumps(structured, sort_keys=True)
    tags: list[str] = []
    topic = scope.get("topic")
    if topic:
        tags.append(f"topic:{topic}")
    if structured.get("kind"):
        tags.append(f"kind:{structured['kind']}")
    metadata = {
        "envelope": env,
        "structured": structured,
    }
    created = ((env.get("time") or {}).get("created")) or utc_now()
    return MemoryRecord(
        text=text or "(empty)",
        kind=env.get("kind", "semantic"),
        scope=scope,
        id=env.get("id"),
        title=title,
        tags=tags,
        metadata=metadata,
        source={"binding": "markdown_dir"},
        created_at=created,
        updated_at=created,
        salience=float((env.get("lifecycle") or {}).get("confidence", 0.5)),
    )


def _record_to_envelope(record: MemoryRecord) -> tuple[dict[str, Any], str]:
    """Inverse of :func:`_envelope_to_record`.

    Preserves an existing envelope in ``metadata['envelope']`` if one was loaded
    so round-trips through this store don't lose upstream-only fields.
    """
    env = dict((record.metadata or {}).get("envelope") or {})
    env.setdefault("ump", "0.1")
    env["id"] = record.id
    env["kind"] = record.kind
    env["scope"] = record.scope
    env.setdefault(
        "time",
        {"created": record.created_at, "observed": record.created_at,
         "valid_from": record.created_at, "valid_to": None},
    )
    env.setdefault("lifecycle", {"status": "active", "confidence": float(record.salience)})
    # body.structured can be supplied via metadata; otherwise keep prior or empty
    body_env = dict(env.get("body") or {})
    if "structured" in (record.metadata or {}):
        body_env["structured"] = record.metadata["structured"]
    if record.title and "summary" not in body_env:
        body_env.setdefault("structured", {})
        body_env["structured"].setdefault("summary", record.title)
    env["body"] = body_env
    return env, record.text


class MarkdownDirectoryStore:
    """One ``*.ump.md`` per record; JSON frontmatter + free-text body.

    Designed to interoperate on-disk with the JS reference store at
    ``~/.ump/memory.d/`` (or whatever ``UMP_DIR`` points to).

    No write-time signing is performed — that's an upstream concern when
    records originate from the JS server. Records written from here keep the
    existing ``integrity`` block if one was attached via metadata, otherwise
    omit it; callers can re-sign out-of-band.
    """

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser()
        self.memory_dir = self.root / "memory.d" if not str(self.root).endswith("memory.d") else self.root
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    # --- capabilities -------------------------------------------------------

    def capabilities(self) -> dict[str, Any]:
        return {
            "server": {"name": "ump-memory", "version": "0.1.0"},
            "ump": "0.1",
            "conformance": "L2-reference",
            "kinds": ["semantic", "episodic", "procedural", "working", "identity"],
            "bindings": ["file", "cli", "http", "markdown_dir"],
            "retrieval_signals": ["lexical", "scope_match", "recency", "salience"],
            "max_recall": 50,
            "writable": True,
            "path": str(self.memory_dir),
        }

    # --- iteration ----------------------------------------------------------

    def _iter_files(self) -> Iterator[Path]:
        if not self.memory_dir.exists():
            return iter(())
        return self.memory_dir.glob("*.ump.md")

    def list(self) -> list[MemoryRecord]:
        records: list[MemoryRecord] = []
        for p in self._iter_files():
            try:
                env, body = _split_frontmatter(p.read_text(encoding="utf-8"))
                if not env.get("id"):
                    continue
                records.append(_envelope_to_record(env, body))
            except Exception:
                # Skip unreadable / malformed cards; never crash the store.
                continue
        return records

    # --- single-record I/O --------------------------------------------------

    def get(self, record_id: str) -> MemoryRecord | None:
        """Look up by id with O(1) filename match before scanning.

        For canonical ``urn:ump:<slug>`` ids the lookup is a single
        ``Path.exists()`` + read. Falls back to a linear scan only when the
        candidate file is missing AND the id is non-canonical — this avoids
        the multi-second scan that O(36k) directories suffer on lookup-miss.
        """
        if not record_id:
            return None
        candidate = self.memory_dir / _id_to_filename(record_id)
        if candidate.exists():
            env, body = _split_frontmatter(candidate.read_text(encoding="utf-8"))
            if env.get("id") == record_id:
                return _envelope_to_record(env, body)
        # Only scan for non-canonical ids (legacy or non-URN-shaped). For
        # canonical URNs, "candidate doesn't exist" is the authoritative
        # answer — no point sweeping the directory.
        if _ID_RE.match(record_id or ""):
            return None
        for p in self._iter_files():
            try:
                env, body = _split_frontmatter(p.read_text(encoding="utf-8"))
                if env.get("id") == record_id:
                    return _envelope_to_record(env, body)
            except Exception:
                continue
        return None

    def put(self, record: MemoryRecord | dict[str, Any]) -> MemoryRecord:
        if isinstance(record, dict):
            record = MemoryRecord.from_dict(record)
        # MemoryRecord.__post_init__ always sets id, so this is non-None at runtime.
        record_id = record.id or ""
        env, body = _record_to_envelope(record)
        out_path = self.memory_dir / _id_to_filename(record_id)
        # Frontmatter + blank line + body (matches upstream layout)
        payload = (
            f"{_FENCE}\n"
            + json.dumps(env, indent=2, ensure_ascii=False, sort_keys=True)
            + f"\n{_FENCE}\n\n"
            + (body or "").rstrip("\n")
            + "\n"
        )
        tmp = out_path.with_suffix(out_path.suffix + ".tmp")
        with self._lock:
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(out_path)
        return record

    def delete(self, record_id: str) -> bool:
        """Best-effort delete; returns True if a card was removed."""
        candidate = self.memory_dir / _id_to_filename(record_id)
        if candidate.exists():
            candidate.unlink()
            return True
        for p in self._iter_files():
            try:
                env, _ = _split_frontmatter(p.read_text(encoding="utf-8"))
                if env.get("id") == record_id:
                    p.unlink()
                    return True
            except Exception:
                continue
        return False

    # --- recall -------------------------------------------------------------

    def recall(
        self,
        query: str,
        *,
        scope: dict[str, Any] | None = None,
        filter: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> list[RecallResult]:
        """Lexical recall identical in spirit to :class:`UMPStore.recall`.

        Iterates all cards on disk every call. For corpora >10k records,
        front this with the multimodal indexing layer (``ump_memory.indexing``).
        """
        q_tokens = tokenize(query)
        q_set = set(q_tokens)
        out: list[RecallResult] = []
        for r in self.list():
            if filter and not self._passes_filter(r, filter):
                continue
            structured = (r.metadata or {}).get("structured") or {}
            text = " ".join(
                [
                    r.title or "",
                    r.text,
                    " ".join(r.tags),
                    json.dumps(structured, sort_keys=True, ensure_ascii=False),
                ]
            )
            toks = tokenize(text)
            if not toks:
                continue
            t_set = set(toks)
            overlap = len(q_set & t_set)
            lexical = overlap / math.sqrt(max(1, len(q_set)) * max(1, len(t_set)))
            exact_bonus = 0.2 if query.lower() in text.lower() else 0.0
            sm = scope_match(r.scope, scope)
            sal = float(r.salience)
            score = (0.62 * min(1.0, lexical + exact_bonus)) + (0.25 * sm) + (0.13 * sal)
            if overlap == 0 and exact_bonus == 0 and sm < 1.0:
                continue
            out.append(RecallResult(r, score, {"lexical": lexical, "scope_match": sm, "salience": sal}))
        out.sort(key=lambda x: x.score, reverse=True)
        return out[: max(0, min(limit, 50))]

    @staticmethod
    def _passes_filter(record: MemoryRecord, filt: dict[str, Any]) -> bool:
        data = record.to_dict()
        for k, v in filt.items():
            if k == "tag":
                vals = v if isinstance(v, list) else [v]
                if not any(x in record.tags for x in vals):
                    return False
            elif k == "kind":
                vals = v if isinstance(v, list) else [v]
                if record.kind not in vals:
                    return False
            elif data.get(k) != v:
                return False
        return True
