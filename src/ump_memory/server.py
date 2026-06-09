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


def make_app(store_path: str | Path | None = None):
    try:
        from fastapi import Body, FastAPI, HTTPException
        from pydantic import BaseModel, Field
    except Exception as e:  # pragma: no cover
        raise RuntimeError("Install server extras: pip install '.[server]'") from e

    store = _resolve_store(store_path)
    app = FastAPI(title="UMP Memory", version="0.1.0")

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

    @app.get("/ump/capabilities")
    def capabilities():
        return store.capabilities()

    @app.post("/ump/put")
    def put(req: PutRequest = Body(...)):
        rec = store.put(MemoryRecord(**req.model_dump()))
        return rec.to_dict()

    # NOTE: UMP record ids are URN-shaped (`urn:ump:<slug>`). FastAPI's path
    # parser splits on `/` and url-decodes `%2F`, but the embedded `:` plays
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
    def get_body(req: GetByIdRequest = Body(...)):
        rec = store.get(req.id)
        if rec is None:
            raise HTTPException(status_code=404, detail=f"not_found: {req.id}")
        return rec.to_dict()

    @app.post("/ump/recall")
    def recall(req: RecallRequest = Body(...)):
        return {
            "results": [
                r.to_dict()
                for r in store.recall(req.query, scope=req.scope, filter=req.filter, limit=req.limit)
            ]
        }

    return app


def main() -> None:  # pragma: no cover
    import uvicorn
    app = make_app()
    uvicorn.run(app, host=os.environ.get("UMP_HOST", "127.0.0.1"), port=int(os.environ.get("UMP_PORT", "8765")))
