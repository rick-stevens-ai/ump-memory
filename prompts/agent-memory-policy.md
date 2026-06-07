# Agent Memory Policy Prompt

Use UMP for appropriate durable/shared memory, but never only UMP.

When you learn something durable:

1. Decide whether it belongs in UMP:
   - shared preference, project convention, endpoint location, cross-agent fact,
     reusable procedure, or notable event.
2. Also update the authoritative local source:
   - `MEMORY.md`, `TOOLS.md`, daily memory, project docs, Keychain/env, or the
     relevant mailbox/Sibline log.
3. If the item involves a secret, put only a pointer/location in UMP.
4. Include provenance in `source` so another agent can verify it.
5. Use scoped visibility; default to `{owner:"rick", visibility:"shared"}` for
   Ollie/Kukla shared memories.
