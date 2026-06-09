# LUCID100 shared UMP memory pack

This repository includes a small shared-memory pack for the LUCID100 low-dose
radiation biology replication effort:

- `data/lucid100_shared_memories.jsonl`

The records are **pointers and coordination facts only**. They do not replace
the file-backed source of truth.

Authoritative project source:

- Repo: `rick-stevens-ai/replication-project`
- Branch: `main`
- LUCID100 campaign commit: `f9c20b5`
- Curated master: `LUCID-replications/_LUCID100_ADMIN/LUCID100_SOLID_MASTER_QA.tsv`
- QA report: `LUCID-replications/_LUCID100_ADMIN/LUCID100_QA_REPORT.md`
- Wave 1 launch package: `LUCID-replications/_LUCID100_WAVE1_LAUNCH_QA/`

## Agent usage

Ollie and Kukla should:

1. Recall UMP for LUCID100 state and pointers.
2. Inspect the replication-project repo files for authoritative details.
3. Treat `LUCID100_SOLID_MASTER_QA.tsv` as the current source of truth.
4. Keep future durable updates in both UMP and the repo/file-backed project docs.

UMP augments durable memory; it is not the only source of truth.
