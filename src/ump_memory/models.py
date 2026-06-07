from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Literal
import hashlib
import json
import uuid

MemoryKind = Literal["semantic", "episodic", "procedural", "working", "identity"]


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stable_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


@dataclass
class MemoryScope:
    """Audience/ownership scope for a memory record.

    Suggested fields:
    - owner: human or org owner, e.g. "rick"
    - agent: creator/subject agent, e.g. "ollie" or "kukla"
    - project: optional project namespace
    - visibility: "private", "shared", or "public"
    """

    owner: str = "rick"
    agent: str | None = None
    project: str | None = None
    visibility: str = "shared"

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class MemoryRecord:
    """UMP memory record.

    Records are intentionally plain JSON so they can be stored in JSONL,
    served over HTTP, or exposed as MCP tool payloads.
    """

    text: str
    kind: MemoryKind = "semantic"
    scope: dict[str, Any] = field(default_factory=lambda: MemoryScope().to_dict())
    id: str | None = None
    title: str | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    source: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    salience: float = 0.5

    def __post_init__(self) -> None:
        self.text = self.text.strip()
        if not self.text:
            raise ValueError("MemoryRecord.text must be non-empty")
        if self.id is None:
            digest = hashlib.sha256(stable_json({
                "text": self.text,
                "kind": self.kind,
                "scope": self.scope,
                "title": self.title,
                "source": self.source,
            }).encode("utf-8")).hexdigest()[:16]
            self.id = f"mem_{digest}_{uuid.uuid4().hex[:8]}"
        if not 0.0 <= float(self.salience) <= 1.0:
            raise ValueError("salience must be between 0 and 1")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryRecord":
        return cls(**data)
