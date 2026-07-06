
## 2026-06-15 — UMP CLI module import failed without PYTHONPATH
- **What failed:** `python3 -m ump_memory.cli ...` from `ump-memory/` returned `ModuleNotFoundError: No module named 'ump_memory'`.
- **Root cause:** The repo package is not installed into the active Python environment; source layout requires either editable install or `PYTHONPATH=src`.
- **Fix:** Re-ran with `PYTHONPATH=src python3 -m ump_memory.cli ...`, which succeeded.
- **Prevention:** For repo-local UMP CLI smoke tests, use installed `ump-memory` if present, or prefix `PYTHONPATH=src` from the repo root.

## 2026-06-15 — UMP CLI recall does not accept --json
- **What failed:** `python3 -m ump_memory.cli ... recall ... --json` returned `unrecognized arguments: --json`.
- **Root cause:** The current UMP CLI emits JSON for `put`, but `recall` has no `--json` flag in this implementation.
- **Fix:** Re-ran recall without `--json`.
- **Prevention:** Check `PYTHONPATH=src python3 -m ump_memory.cli <subcommand> --help` before assuming CLI flags.
