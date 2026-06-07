from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import json
import math
import re
import threading

from .models import MemoryRecord, utc_now

_TOKEN_RE = re.compile(r"[A-Za-z0-9_./:-]+")


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def scope_match(record_scope: dict[str, Any], query_scope: dict[str, Any] | None) -> float:
    if not query_scope:
        return 1.0
    if not record_scope:
        return 0.0
    total = 0
    hits = 0
    for k, v in query_scope.items():
        if v is None:
            continue
        total += 1
        rv = record_scope.get(k)
        if rv == v:
            hits += 1
        elif k == "visibility" and rv == "public":
            hits += 0.75
        elif k == "visibility" and rv == "shared" and v in {"shared", "private"}:
            hits += 0.5
    return hits / total if total else 1.0


@dataclass
class RecallResult:
    record: MemoryRecord
    score: float
    signals: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        d = self.record.to_dict()
        d["score"] = self.score
        d["signals"] = self.signals
        return d


class UMPStore:
    """Append-friendly JSONL UMP store with deterministic lexical recall.

    This reference implementation deliberately avoids external vector DBs. It
    is good enough for tests, local agents, and protocol development. A future
    adapter can replace `recall()` scoring with embeddings while preserving
    the record schema and API.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def capabilities(self) -> dict[str, Any]:
        return {
            "server": {"name": "ump-memory", "version": "0.1.0"},
            "ump": "0.1",
            "conformance": "L2-reference",
            "kinds": ["semantic", "episodic", "procedural", "working", "identity"],
            "bindings": ["file", "cli", "http"],
            "retrieval_signals": ["lexical", "scope_match", "recency", "salience"],
            "max_recall": 50,
            "writable": True,
            "path": str(self.path),
        }

    def list(self) -> list[MemoryRecord]:
        if not self.path.exists():
            return []
        records: list[MemoryRecord] = []
        with self.path.open("r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                records.append(MemoryRecord.from_dict(json.loads(raw)))
        return records

    def put(self, record: MemoryRecord | dict[str, Any], *, upsert: bool = True) -> MemoryRecord:
        if isinstance(record, dict):
            record = MemoryRecord.from_dict(record)
        with self._lock:
            records = self.list()
            if upsert:
                replaced = False
                out = []
                for r in records:
                    if r.id == record.id:
                        record.created_at = r.created_at
                        record.updated_at = utc_now()
                        out.append(record)
                        replaced = True
                    else:
                        out.append(r)
                if not replaced:
                    out.append(record)
                self._rewrite(out)
            else:
                with self.path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
        return record

    def get(self, id: str) -> MemoryRecord | None:
        for r in self.list():
            if r.id == id:
                return r
        return None

    def recall(
        self,
        query: str,
        *,
        scope: dict[str, Any] | None = None,
        filter: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> list[RecallResult]:
        q_tokens = tokenize(query)
        q_set = set(q_tokens)
        results: list[RecallResult] = []
        for r in self.list():
            if filter and not self._passes_filter(r, filter):
                continue
            text = " ".join([r.title or "", r.text, " ".join(r.tags), json.dumps(r.metadata, sort_keys=True)])
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
            results.append(RecallResult(r, score, {"lexical": lexical, "scope_match": sm, "salience": sal}))
        results.sort(key=lambda x: x.score, reverse=True)
        return results[: max(0, min(limit, 50))]

    def _rewrite(self, records: list[MemoryRecord]) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
        tmp.replace(self.path)

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
