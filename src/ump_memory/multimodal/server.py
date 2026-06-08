"""HTTP server exposing the 5 multi-modal search axes.

Stdlib-only (``http.server.ThreadingHTTPServer``) so it works in the
zero-dep core. For a fastapi/uvicorn variant, install the ``server`` extra
and wire ``ump_memory.multimodal.search.MultiSearch`` directly.

Endpoints
---------
GET  /health                  → ``{ok, cards_indexed}``
POST /search/exact            → ``{query, limit?}``
POST /search/regex            → ``{pattern, limit?, flags?}``
POST /search/structured       → ``{filters: {...}, limit?}``
POST /search/semantic         → ``{query, limit?, owner?, project?}`` (proxied)
POST /search/hybrid           → ``{query, filters?, limit?}``

All POST responses: ``{results: [...], took_ms, count}``.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .search import (
    MultiSearch,
    SearchResult,
    search_exact,
    search_hybrid,
    search_regex,
    search_structured,
)


@dataclass
class ServerConfig:
    db_path: Path
    semantic_proxy_url: str | None = None  # e.g. "http://localhost:8080/ump/recall"
    default_owner: str | None = None
    default_project: str | None = None


def _semantic_proxy(cfg: ServerConfig, query: str, limit: int = 10,
                    owner: str | None = None, project: str | None = None,
                    visibility: str = "private") -> list[dict[str, Any]]:
    """Proxy /search/semantic to a running UMP HTTP server."""
    if not cfg.semantic_proxy_url:
        return [{"error": "no semantic_proxy_url configured"}]
    body = {
        "query": query,
        "limit": limit,
        "scope": {
            "owner": owner or cfg.default_owner,
            "project": project or cfg.default_project,
            "visibility": visibility,
        },
    }
    req = urllib.request.Request(
        cfg.semantic_proxy_url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        return data.get("results", [])
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        return [{"error": f"{type(e).__name__}: {e}"}]


def _serialize(results: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in results:
        if isinstance(r, SearchResult):
            out.append(r.to_dict())
        elif isinstance(r, dict):
            out.append(r)
    return out


class _Handler(BaseHTTPRequestHandler):
    server_version = "UmpMultiSearch/0.1"

    # injected by run_server
    cfg: ServerConfig

    def _send(self, status: int, body: dict[str, Any]) -> None:
        payload = json.dumps(body, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        # Quiet by default — wire to logging if needed
        pass

    def do_GET(self) -> None:
        if self.path == "/health":
            try:
                db = sqlite3.connect(str(self.cfg.db_path))
                n = db.execute("select count(*) from ump_card").fetchone()[0]
                db.close()
                self._send(200, {"ok": True, "cards_indexed": n})
            except sqlite3.Error as e:
                self._send(500, {"ok": False, "error": str(e)})
        else:
            self._send(404, {"error": "not_found"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            req = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._send(400, {"error": "bad_json"})
            return

        cfg = self.cfg
        db = sqlite3.connect(str(cfg.db_path))
        db.row_factory = sqlite3.Row
        t0 = time.time()
        try:
            if self.path == "/search/exact":
                out = _serialize(search_exact(db, req["query"], limit=int(req.get("limit", 10))))
            elif self.path == "/search/regex":
                out = _serialize(search_regex(db, req["pattern"], limit=int(req.get("limit", 10))))
            elif self.path == "/search/structured":
                out = _serialize(search_structured(db, req.get("filters", {}), limit=int(req.get("limit", 10))))
            elif self.path == "/search/semantic":
                out = _semantic_proxy(
                    cfg, req["query"], limit=int(req.get("limit", 10)),
                    owner=req.get("owner"), project=req.get("project"),
                    visibility=req.get("visibility", "private"),
                )
            elif self.path == "/search/hybrid":
                def semantic_fn(q: str, lim: int) -> list[dict[str, Any]]:
                    return _semantic_proxy(cfg, q, limit=lim,
                                           owner=req.get("owner"),
                                           project=req.get("project"))
                out = _serialize(search_hybrid(
                    db, req["query"],
                    filters=req.get("filters"),
                    semantic=semantic_fn if cfg.semantic_proxy_url else None,
                    limit=int(req.get("limit", 10)),
                ))
            else:
                self._send(404, {"error": "unknown endpoint"})
                return
        except KeyError as e:
            self._send(400, {"error": f"missing field: {e}"})
            return
        except ValueError as e:
            self._send(400, {"error": str(e)})
            return
        except Exception as e:  # noqa: BLE001
            self._send(500, {"error": str(e), "type": type(e).__name__})
            return
        finally:
            db.close()

        elapsed = (time.time() - t0) * 1000
        self._send(200, {"results": out, "took_ms": round(elapsed, 1), "count": len(out)})


class MultiSearchServer:
    """Thin wrapper around ThreadingHTTPServer.

    Examples
    --------
    >>> from pathlib import Path
    >>> from ump_memory.multimodal import MultiSearchServer
    >>> srv = MultiSearchServer(
    ...     db_path=Path("/var/ump/index.db"),
    ...     port=4100,
    ...     semantic_proxy_url="http://localhost:8080/ump/recall",
    ... )
    >>> srv.serve_forever()
    """

    def __init__(
        self,
        db_path: Path | str,
        *,
        host: str = "127.0.0.1",
        port: int = 4100,
        semantic_proxy_url: str | None = None,
        default_owner: str | None = None,
        default_project: str | None = None,
    ) -> None:
        self.cfg = ServerConfig(
            db_path=Path(db_path),
            semantic_proxy_url=semantic_proxy_url,
            default_owner=default_owner,
            default_project=default_project,
        )
        # Inject cfg into the handler class
        handler_cls = type("BoundHandler", (_Handler,), {"cfg": self.cfg})
        self.httpd = ThreadingHTTPServer((host, port), handler_cls)
        self.host = host
        self.port = port

    def serve_forever(self) -> None:
        print(f"UMP multi-search listening on http://{self.host}:{self.port}", flush=True)
        print(f"  DB: {self.cfg.db_path}", flush=True)
        if self.cfg.semantic_proxy_url:
            print(f"  Semantic proxy: {self.cfg.semantic_proxy_url}", flush=True)
        print("  Endpoints: /health, /search/{exact,regex,structured,semantic,hybrid}", flush=True)
        try:
            self.httpd.serve_forever()
        finally:
            self.httpd.server_close()

    def shutdown(self) -> None:
        self.httpd.shutdown()


def run_server(
    db_path: Path | str,
    *,
    host: str = "127.0.0.1",
    port: int = 4100,
    semantic_proxy_url: str | None = None,
    default_owner: str | None = None,
    default_project: str | None = None,
) -> None:
    """One-shot convenience: build a server and block on serve_forever()."""
    MultiSearchServer(
        db_path=db_path,
        host=host,
        port=port,
        semantic_proxy_url=semantic_proxy_url,
        default_owner=default_owner,
        default_project=default_project,
    ).serve_forever()


def _cli() -> None:
    ap = argparse.ArgumentParser(
        prog="ump-memory-search-server",
        description="Run the UMP multi-modal search HTTP server.",
    )
    ap.add_argument("--db", required=True, type=Path, help="SQLite index database path")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=4100)
    ap.add_argument("--semantic-proxy-url", default=None,
                    help="URL of a running ump-memory-server /ump/recall endpoint")
    ap.add_argument("--default-owner", default=None)
    ap.add_argument("--default-project", default=None)
    args = ap.parse_args()
    run_server(
        args.db,
        host=args.host,
        port=args.port,
        semantic_proxy_url=args.semantic_proxy_url,
        default_owner=args.default_owner,
        default_project=args.default_project,
    )


if __name__ == "__main__":
    _cli()
