"""Example 6: stand up the HTTP server and curl it.

Runs ``MultiSearchServer`` on 127.0.0.1:4100 against the demo corpus,
prints a few sample curl commands, then blocks. Ctrl-C to stop.

In production, pair this with a running ``ump-memory-server`` (the
classic UMP HTTP server) and pass its ``/ump/recall`` URL as
``semantic_proxy_url`` to wire up the semantic axis automatically.
"""
from __future__ import annotations

from _demo_corpus import build_demo_corpus
from ump_memory.multimodal import MultiSearchServer

PORT = 4100


def main() -> None:
    _, db = build_demo_corpus()
    print(f"Index DB: {db}")
    print(f"Demo corpus has 5 cards across ORNL, ANL, PPPL, FNAL, LBNL.")
    print()
    print("Try these in another terminal:")
    print()
    print(f"  curl http://127.0.0.1:{PORT}/health")
    print()
    print(f"  curl -X POST http://127.0.0.1:{PORT}/search/exact \\")
    print(f"    -H 'content-type: application/json' \\")
    print(f"    -d '{{\"query\": \"\\\"alice@ornl.gov\\\"\", \"limit\": 5}}'")
    print()
    print(f"  curl -X POST http://127.0.0.1:{PORT}/search/regex \\")
    print(f"    -H 'content-type: application/json' \\")
    print(f"    -d '{{\"pattern\": \"cms-.*@cern\\\\.ch\", \"limit\": 5}}'")
    print()
    print(f"  curl -X POST http://127.0.0.1:{PORT}/search/structured \\")
    print(f"    -H 'content-type: application/json' \\")
    print(f"    -d '{{\"filters\": {{\"primary_lab\": \"ORNL\", \"paper_count_min\": 50}}}}'")
    print()
    print(f"  curl -X POST http://127.0.0.1:{PORT}/search/hybrid \\")
    print(f"    -H 'content-type: application/json' \\")
    print(f"    -d '{{\"query\": \"battery cathode\", \"filters\": {{\"primary_lab\": \"ORNL\"}}}}'")
    print()

    srv = MultiSearchServer(db_path=db, port=PORT)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")


if __name__ == "__main__":
    main()
