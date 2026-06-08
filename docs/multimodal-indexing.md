# Multi-Modal Indexing for UMP

> **Status:** **shipped (v1)** — `ump_memory.multimodal` module, 17 tests
> passing, 6 runnable examples under `examples/multimodal/`. Load-tested
> against a 36,026-card OSTI contact corpus.

## Problem

Native UMP `recall()` is single-axis: one `store.search()` hook per backend.
The reference Markdown-directory store uses Jaccard token overlap, which is
fine for fuzzy semantic recall but breaks down for:

- Exact-string lookup (`junlu@anl.gov` — `@.-` are tokenizer delimiters)
- Regex / pattern search (`cms-publication-.*@cern.ch`)
- Structured filter (`primary_lab=ORNL AND paper_count > 50`)
- Multi-axis ranking (find ORNL battery contacts who also publish on cathodes)

Swapping the backend (e.g. Postgres FTS or Qdrant) trades one axis for
another. We want **all axes simultaneously** without losing the native
semantic recall path.

## Architecture

A **sidecar** approach: a separate index DB + HTTP server reading the
same `memory.d/` source of truth, exposing 4 new axes alongside the
existing `/ump/recall` endpoint. Sidecar refreshes incrementally via mtime
tracking; cron at 10-minute intervals keeps drift bounded.

```
┌─────────────────────────┐
│  memory.d/*.json        │  ← UMP canonical store (unchanged)
└────────┬────────────────┘
         │ mtime-incremental scan
         ▼
┌─────────────────────────┐    ┌──────────────────────────┐
│  ump_index.db (SQLite)  │    │  UMP HTTP :4099          │
│  - ump_card (1 row/file)│    │  /ump/remember           │
│  - ump_fts (FTS5)       │    │  /ump/recall (semantic)  │
│  - ump_card_field       │    └──────────────────────────┘
│    (multi-value lookup) │                ▲
└────────┬────────────────┘                │ proxy
         │                                  │
         ▼                                  │
┌─────────────────────────────────────────────────────────┐
│  Multi-search HTTP :4100                                │
│  /search/exact      → FTS5 MATCH                         │
│  /search/regex      → Python re                          │
│  /search/structured → SQL + JOIN on field index          │
│  /search/semantic   → proxies UMP :4099                  │
│  /search/hybrid     → RRF fusion across axes             │
│  /health                                                  │
└─────────────────────────────────────────────────────────┘
```

## Five Axes

| Axis        | Backend         | Best for                                  | Typical latency |
| ----------- | --------------- | ----------------------------------------- | --------------- |
| exact       | SQLite FTS5     | Email, exact phrase, boolean AND/OR/NOT   | 50–500 ms       |
| regex       | Python `re`     | Pattern hunts (e.g. `cms-.*@cern.ch`)     | 100–500 ms      |
| structured  | SQL + JOIN      | `primary_lab=ORNL AND paper_count>50`     | 30–100 ms       |
| semantic    | UMP `/recall`   | "ORNL fusion contacts", concept queries   | 500–1000 ms     |
| hybrid      | RRF (k=60)      | Multi-axis ranking, surfaces co-occurring | 1000–2000 ms    |

## Pitfalls (already paid for)

1. **FTS5 default tokenizer splits on `@.-`** — emails become unsearchable
   as single tokens. Must use:
   ```python
   tokenize="unicode61 tokenchars '@.-_+'"
   ```
2. **`pkill -f ump_multisearch` matches its own pgrep cmdline** — causes
   self-kill loop. Use `pgrep -af ump_multisearch | grep -v grep` and
   `kill` by PID, not pattern.
3. **macOS `lsof` reports `(CLOSED)` for valid listening sockets** with
   no peer connections — don't trust it as a liveness signal. `curl
   /health` instead.
4. **UMP recall requires `scope.owner`** — scopeless queries return `[]`
   silently. Sidecar must forward owner from caller.
5. **JSON frontmatter, not YAML** — UMP cards are full JSON dicts;
   structured fields hoist from `body.structured.*` and `scope.*`.

## Worked Example: OSTI Contact Corpus

Production validation against 36,026 OSTI author-contact cards covering
10 DOE Office of Science labs:

- ORNL 5360, ANL 4049, LBNL 3205, PNNL 2284, SLAC 1711, BNL 1676,
  FNAL 1451, PPPL 568, TJNAF 117, AMES 51

Sample queries (subset, indexed=20,511 at smoke time):

| Query                                                              | Axis        | Result                          | Latency |
| ------------------------------------------------------------------ | ----------- | ------------------------------- | ------- |
| `"junlu@anl.gov"`                                                  | exact       | Jun Lu (160p)                   | 515 ms  |
| `ornl AND fusion AND tokamak`                                      | exact bool  | Kobayashi, Creely, Klepper      | 53 ms   |
| PPPL ∩ fusion ∩ paper_count>5                                      | structured  | J. Dominski (14p)               | 32 ms   |
| ANL ∩ name LIKE 'Lu' ∩ paper_count>50                              | structured  | Jun Lu (160p)                   | 57 ms   |
| "ORNL fusion contacts" (Jaccard)                                   | semantic    | 5 hits, noisy ~0.45 uniform     | 941 ms  |
| battery cathode ORNL + filter ORNL>20p                             | hybrid      | Belharouak (49p), 2-axis hit    | 1329 ms |

## API Sketch

### Exact
```http
POST /search/exact
{"query": "battery AND cathode AND ornl", "limit": 10}
```

### Regex
```http
POST /search/regex
{"pattern": "cms-.*@cern\\.ch", "limit": 50, "flags": "i"}
```

### Structured
```http
POST /search/structured
{
  "filter": {"primary_lab": "ORNL", "paper_count_min": 50},
  "field_filter": {"topics": ["fusion", "tokamak"]},
  "limit": 25
}
```

### Hybrid
```http
POST /search/hybrid
{
  "query": "neutrino oscillation",
  "filter": {"primary_lab": "FNAL", "paper_count_min": 10},
  "limit": 25
}
```
Returns each card with `axis_hits: ["exact", "structured"]` and a
fused RRF score (`1/(60+rank_exact) + 1/(60+rank_semantic) + ...`).

## Open Questions Before Final PR

- [ ] Should `multisearch` live in `ump_memory` or a separate package
      (`ump-memory-multisearch`) to avoid pulling SQLite into the
      lightweight core?
- [ ] Hybrid weights — equal RRF or expose per-axis weights in request?
- [ ] Pluggable semantic backend (Jaccard → Qdrant/Weaviate) — wire as
      an adapter, not hardcoded?
- [ ] CLI for ad-hoc queries (`ump-memory-search exact 'junlu@anl.gov'`)?

## Source

- Reference impl: `~/code/osti-replication-candidates/ump_index_builder.py`
  (~9 KB), `~/code/osti-replication-candidates/ump_multisearch.py` (~12 KB)
- Vault card: `~/Dropbox/XFER/memory-vault/infra/ump-multimodal-indexing.md`
- Bulk-load validation: 36,026 cards loaded, 0 errors, 20.7 min wall on
  12-worker parallel import (Jun 7 2026).
