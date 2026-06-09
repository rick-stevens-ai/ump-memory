from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .md_store import MarkdownDirectoryStore
from .models import MemoryRecord
from .store import UMPStore

StoreLike = UMPStore | MarkdownDirectoryStore


def _resolve_store(store_path: str | Path | None = None) -> StoreLike:
    """Pick a store backend based on env + filesystem hints.

    Selection order:
      1. ``UMP_STORE_KIND={json,markdown}`` if set explicitly.
      2. ``UMP_DIR`` set and existing → markdown directory store (matches the
         upstream JS reference layout).
      3. ``store_path`` argument or ``UMP_STORE`` env → JSONL store.
      4. Default ``~/.ump/memories.jsonl`` → JSONL store.
    """
    kind = (os.environ.get("UMP_STORE_KIND") or "").lower().strip()
    ump_dir = os.environ.get("UMP_DIR")

    if kind == "markdown":
        loc = store_path or ump_dir or "~/.ump"
        return MarkdownDirectoryStore(loc)
    if kind == "json":
        loc = store_path or os.environ.get("UMP_STORE") or "~/.ump/memories.jsonl"
        return UMPStore(loc)

    # No explicit kind — infer from environment.
    if ump_dir:
        return MarkdownDirectoryStore(ump_dir)

    loc = store_path or os.environ.get("UMP_STORE", "~/.ump/memories.jsonl")
    return UMPStore(loc)


def _default_owner() -> str | None:
    """Operator DID for default-scope injection.

    Read from ``UMP_OWNER`` env var. When set, server-side handlers will
    populate ``scope.owner`` for any recall request that doesn't specify one.
    This is the fix for the "recall returns empty by default" UX pitfall in
    the upstream JS reference server: production stores keyed to a single
    operator DID and visibility=private should still be discoverable from
    that operator's agent without it having to hand-thread the DID every call.

    Returns ``None`` when unset, in which case no default is injected and
    callers must supply ``scope.owner`` themselves (matching upstream).
    """
    v = os.environ.get("UMP_OWNER")
    return v.strip() if v and v.strip() else None


# Pydantic request models hoisted to module scope. Defining them inside
# make_app() works for /ump/put (Pydantic infers the body schema directly)
# but breaks under Pydantic 2.13 + FastAPI when combined with Body(...) — the
# closure-local ForwardRef never resolves. Module-scope models are also
# easier for OpenAPI schema introspection by downstream tooling.
try:
    from pydantic import BaseModel, Field

    class PutRequest(BaseModel):
        text: str
        kind: str = "semantic"
        scope: dict[str, Any] = Field(default_factory=lambda: {"owner": "rick", "visibility": "shared"})
        id: str | None = None
        title: str | None = None
        tags: list[str] = Field(default_factory=list)
        metadata: dict[str, Any] = Field(default_factory=dict)
        source: dict[str, Any] = Field(default_factory=lambda: {"binding": "http"})
        salience: float = 0.5

    class RecallRequest(BaseModel):
        query: str
        scope: dict[str, Any] | None = None
        filter: dict[str, Any] | None = None
        limit: int = 10

    class GetByIdRequest(BaseModel):
        id: str
except ImportError:  # pragma: no cover - pydantic is an extras dep
    PutRequest = RecallRequest = GetByIdRequest = None  # type: ignore[assignment]


def make_app(store_path: str | Path | None = None):
    try:
        from fastapi import FastAPI, HTTPException
    except Exception as e:  # pragma: no cover
        raise RuntimeError("Install server extras: pip install '.[server]'") from e

    store = _resolve_store(store_path)
    default_owner = _default_owner()
    app = FastAPI(title="UMP Memory", version="0.1.0")

    def _apply_default_scope(scope: dict[str, Any] | None) -> dict[str, Any] | None:
        """Inject the default operator DID into scope.owner if absent.

        - No default configured → return scope unchanged.
        - Caller supplied scope.owner → respect it (no override).
        - Caller supplied scope without owner → fill in owner.
        - Caller supplied no scope at all → return ``{"owner": <default>}``.
        """
        if not default_owner:
            return scope
        if scope is None:
            return {"owner": default_owner}
        if scope.get("owner"):
            return scope
        merged = dict(scope)
        merged["owner"] = default_owner
        return merged

    @app.get("/ump/capabilities")
    def capabilities():
        caps = store.capabilities() if hasattr(store, "capabilities") else {}
        # Self-document the default-scope behavior so MCP clients can discover
        # what owner DID this server falls back to. Agents reading capabilities
        # at startup learn the DID without needing a separate config channel.
        if default_owner:
            caps = {**caps, "default_scope": {"owner": default_owner}}
        return caps

    @app.post("/ump/put")
    def put(req: PutRequest):
        rec = store.put(MemoryRecord(**req.model_dump()))
        return rec.to_dict()

    # URN-in-URL is hostile to a lot of HTTP plumbing — ':' encodes
    # poorly with proxies/curl/MCP clients. We expose THREE ways to fetch a
    # record so callers can pick whichever is cleanest in their transport:
    #   - GET /ump/get/{record_id}   (path-encoded, original)
    #   - GET /ump/get?id=<urn>      (query-string)
    #   - POST /ump/get  {"id": ...} (body, escapes all encoding issues)
    @app.get("/ump/get/{record_id:path}")
    def get_path(record_id: str):
        rec = store.get(record_id)
        if rec is None:
            raise HTTPException(status_code=404, detail=f"not_found: {record_id}")
        return rec.to_dict()

    @app.get("/ump/get")
    def get_query(id: str):
        rec = store.get(id)
        if rec is None:
            raise HTTPException(status_code=404, detail=f"not_found: {id}")
        return rec.to_dict()

    @app.post("/ump/get")
    def get_body(req: GetByIdRequest):
        rec = store.get(req.id)
        if rec is None:
            raise HTTPException(status_code=404, detail=f"not_found: {req.id}")
        return rec.to_dict()

    @app.post("/ump/recall")
    def recall(req: RecallRequest):
        effective_scope = _apply_default_scope(req.scope)
        return {
            "results": [
                r.to_dict()
                for r in store.recall(req.query, scope=effective_scope, filter=req.filter, limit=req.limit)
            ]
        }

    return app


def main() -> None:  # pragma: no cover
    import uvicorn
    app = make_app()
    uvicorn.run(app, host=os.environ.get("UMP_HOST", "127.0.0.1"), port=int(os.environ.get("UMP_PORT", "8765")))
