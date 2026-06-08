# Multimodal Search Examples

Five self-contained, runnable scripts demonstrating each retrieval axis of
the `ump_memory.multimodal` layer. All examples build a tiny synthetic
corpus in a temp directory, index it, and run real queries — no external
dependencies beyond `ump_memory`.

## Run them

```bash
# From repo root, with the package installed (e.g. `pip install -e .`):
python examples/multimodal/01_build_index.py
python examples/multimodal/02_exact_search.py
python examples/multimodal/03_regex_search.py
python examples/multimodal/04_structured_search.py
python examples/multimodal/05_hybrid_rrf.py
python examples/multimodal/06_http_server.py    # blocks; ^C to stop
```

## What each shows

| # | File                          | Axis        | Demonstrates                                            |
|---|-------------------------------|-------------|---------------------------------------------------------|
| 1 | `01_build_index.py`           | (setup)     | Incremental SQLite/FTS5 index over a UMP store dir       |
| 2 | `02_exact_search.py`          | exact       | Email-as-single-token, boolean AND, prefix              |
| 3 | `03_regex_search.py`          | regex       | Pattern hunts (collaboration mailers, domain patterns)  |
| 4 | `04_structured_search.py`     | structured  | SQL filters + multi-value JOINs (lab × topic × papers)  |
| 5 | `05_hybrid_rrf.py`            | hybrid      | RRF fusion of exact + structured + custom semantic      |
| 6 | `06_http_server.py`           | (transport) | Stand up the HTTP server and curl the endpoints         |

## Worked example: OSTI author-contact corpus

The examples use a 5-card synthetic corpus, but the layer is validated
against a production 36,026-card OSTI author-contact corpus across 10 DOE
Office of Science labs (ORNL, ANL, LBNL, PNNL, SLAC, BNL, FNAL, PPPL,
TJNAF, AMES). Real-world latency numbers:

| Query                                       | Axis        | Result                          | Latency |
|---------------------------------------------|-------------|---------------------------------|---------|
| `"junlu@anl.gov"` (exact phrase)            | exact       | Jun Lu (160 papers)             | 515 ms  |
| `ornl AND fusion AND tokamak`               | exact bool  | Kobayashi, Creely, Klepper      | 53 ms   |
| `cms-.*@cern\.ch`                           | regex       | 989-paper CMS mailer            | 380 ms  |
| PPPL ∩ Fusion ∩ paper_count>5               | structured  | J. Dominski                     | 32 ms   |
| ORNL ∩ name LIKE 'Lu' ∩ paper_count>50      | structured  | Jun Lu                          | 57 ms   |
| battery cathode + ORNL filter               | hybrid RRF  | Belharouak (2-axis hit)         | 1.3 s   |

See `docs/multimodal-indexing.md` for the full architecture.
