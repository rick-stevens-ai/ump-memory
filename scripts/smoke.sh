#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STORE="${TMPDIR:-/tmp}/ump-smoke-$$.jsonl"
PYTHONPATH="$ROOT/src" python3 -m ump_memory.cli --store "$STORE" capabilities >/dev/null
PYTHONPATH="$ROOT/src" python3 -m ump_memory.cli --store "$STORE" put 'Use UMP but not only UMP.' --tag ump --id smoke_ump >/dev/null
PYTHONPATH="$ROOT/src" python3 -m ump_memory.cli --store "$STORE" recall 'UMP policy' --limit 1 | grep smoke_ump >/dev/null
echo "smoke ok: $STORE"
