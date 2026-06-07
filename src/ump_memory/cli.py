from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .models import MemoryRecord
from .store import UMPStore


def default_store_path() -> Path:
    return Path(os.environ.get("UMP_STORE", "~/.ump/memories.jsonl")).expanduser()


def parse_json_obj(s: str | None, default: dict[str, Any]) -> dict[str, Any]:
    if not s:
        return default
    return json.loads(s)


def cmd_capabilities(args) -> int:
    print(json.dumps(UMPStore(args.store).capabilities(), indent=2, ensure_ascii=False))
    return 0


def cmd_put(args) -> int:
    text = args.text if args.text != "-" else sys.stdin.read()
    rec = MemoryRecord(
        text=text,
        kind=args.kind,
        title=args.title,
        tags=args.tag or [],
        scope=parse_json_obj(args.scope, {"owner": "rick", "visibility": "shared", "agent": args.agent}),
        metadata=parse_json_obj(args.metadata, {}),
        source=parse_json_obj(args.source, {"binding": "cli"}),
        salience=args.salience,
        id=args.id,
    )
    out = UMPStore(args.store).put(rec)
    print(json.dumps(out.to_dict(), indent=2, ensure_ascii=False))
    return 0


def cmd_get(args) -> int:
    rec = UMPStore(args.store).get(args.id)
    if rec is None:
        print(json.dumps({"error": "not_found", "id": args.id}, indent=2), file=sys.stderr)
        return 1
    print(json.dumps(rec.to_dict(), indent=2, ensure_ascii=False))
    return 0


def cmd_recall(args) -> int:
    results = UMPStore(args.store).recall(
        args.query,
        scope=parse_json_obj(args.scope, None),
        filter=parse_json_obj(args.filter, None),
        limit=args.limit,
    )
    print(json.dumps({"results": [r.to_dict() for r in results]}, indent=2, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ump-memory")
    p.add_argument("--store", default=str(default_store_path()), help="JSONL store path (default: $UMP_STORE or ~/.ump/memories.jsonl)")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("capabilities")
    c.set_defaults(fn=cmd_capabilities)

    put = sub.add_parser("put", help="Store/upsert a memory record")
    put.add_argument("text", help="Memory text, or '-' for stdin")
    put.add_argument("--kind", default="semantic", choices=["semantic", "episodic", "procedural", "working", "identity"])
    put.add_argument("--title")
    put.add_argument("--tag", action="append")
    put.add_argument("--scope", help="JSON object")
    put.add_argument("--agent", default="ollie")
    put.add_argument("--metadata", help="JSON object")
    put.add_argument("--source", help="JSON object")
    put.add_argument("--salience", type=float, default=0.5)
    put.add_argument("--id")
    put.set_defaults(fn=cmd_put)

    get = sub.add_parser("get")
    get.add_argument("id")
    get.set_defaults(fn=cmd_get)

    rec = sub.add_parser("recall")
    rec.add_argument("query")
    rec.add_argument("--scope", help="JSON object")
    rec.add_argument("--filter", help="JSON object")
    rec.add_argument("--limit", type=int, default=10)
    rec.set_defaults(fn=cmd_recall)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.store = Path(args.store).expanduser()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
