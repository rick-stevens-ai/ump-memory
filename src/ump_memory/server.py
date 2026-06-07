from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .models import MemoryRecord
from .store import UMPStore


def make_app(store_path: str | Path | None = None):
    try:
        from fastapi import FastAPI, HTTPException
        from pydantic import BaseModel, Field
    except Exception as e:  # pragma: no cover
        raise RuntimeError("Install server extras: pip install '.[server]'") from e

    store = UMPStore(store_path or os.environ.get("UMP_STORE", "~/.ump/memories.jsonl"))
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

    @app.get("/ump/capabilities")
    def capabilities():
        return store.capabilities()

    @app.post("/ump/put")
    def put(req: PutRequest):
        rec = store.put(MemoryRecord(**req.model_dump()))
        return rec.to_dict()

    @app.get("/ump/get/{record_id}")
    def get(record_id: str):
        rec = store.get(record_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="not_found")
        return rec.to_dict()

    @app.post("/ump/recall")
    def recall(req: RecallRequest):
        return {"results": [r.to_dict() for r in store.recall(req.query, scope=req.scope, filter=req.filter, limit=req.limit)]}

    return app


def main() -> None:  # pragma: no cover
    import uvicorn
    app = make_app()
    uvicorn.run(app, host=os.environ.get("UMP_HOST", "127.0.0.1"), port=int(os.environ.get("UMP_PORT", "8765")))
