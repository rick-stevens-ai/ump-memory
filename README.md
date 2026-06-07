# UMP Memory

Reference implementation of a small **Universal Memory Protocol (UMP)** memory
store for local agents. It is designed for the Ollie/Kukla pattern: shared,
durable memory should be written to UMP **and** to the existing file-backed or
secure source of truth. UMP augments memory; it does not replace it.

## Goals

- Plain JSON memory records that can survive agent/runtime changes.
- Multiple bindings over the same store:
  - file: JSONL
  - CLI: `ump-memory`
  - HTTP: FastAPI endpoints
- Retrieval signals returned with recall results.
- Safe secret handling: store pointers/locations, not raw secrets.
- Test programs and prompt templates for agent integration.

## Non-goals

- Not a production vector database.
- Not a secret manager.
- Not the only durable store. Continue to use files, Keychain/env, and project
  docs for authoritative state.

## Quick start

```bash
cd ump-memory
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[test,server]'
pytest -q
```

Store a memory:

```bash
ump-memory --store ./data/memories.jsonl put \
  'Use UMP for durable shared memories, but never only there.' \
  --kind procedural \
  --title 'UMP memory policy' \
  --tag ump --tag policy \
  --scope '{"owner":"rick","agent":"ollie","visibility":"shared"}'
```

Recall:

```bash
ump-memory --store ./data/memories.jsonl recall 'UMP source of truth policy'
```

Run HTTP server:

```bash
UMP_STORE=./data/memories.jsonl ump-memory-server
curl http://127.0.0.1:8765/ump/capabilities
```

## HTTP API

- `GET /ump/capabilities`
- `POST /ump/put`
- `GET /ump/get/{id}`
- `POST /ump/recall`

## Record schema

See `docs/record-schema.md`.

## Prompts

See `prompts/` for agent-facing prompt templates:

- `agent-memory-policy.md`
- `write-memory.md`
- `recall-before-answer.md`
- `secret-pointer.md`
- `cross-agent-sync.md`

## License

MIT.
