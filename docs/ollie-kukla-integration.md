# Ollie/Kukla Integration Notes

## Standing policy

Rick wants durable/shared memory items placed in UMP, but not only there.
For every durable UMP write, keep or update a file-backed/source-of-truth record:

- `MEMORY.md` for curated long-term memory.
- `TOOLS.md` for environment-specific operational pointers.
- `memory/YYYY-MM-DD.md` for daily/event logs.
- Keychain/env files for secrets.
- Sibline/mailbox for cross-agent transport and acknowledgements.

## Current recommended flow

1. Agent learns a durable shared fact.
2. Agent writes/updates file-backed source.
3. Agent writes a UMP record with provenance pointing to that source.
4. Agent sends a concise cross-agent sync over Sibline if the other agent needs it.
5. Agent verifies by recalling the item from UMP and reading the source file when precision matters.

## Secret example

Do not write raw keys to UMP.

Store:

- secret name
- expected env var
- Keychain/service/account pointer
- verification date/status
- source file path

Do not store:

- API key value
- bearer token
- password
