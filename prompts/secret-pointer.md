# Secret Pointer Prompt

For secrets, store only location and usage metadata in UMP.

Good:

```text
Semantic Scholar API key exists. Use env var S2_API_KEY. Keychain service:
semantic-scholar-api-key, account rick-stevens-ai. Header: x-api-key. Verified
HTTP 200 on 2026-06-07.
```

Bad:

```text
S2_API_KEY=<redacted>
```
