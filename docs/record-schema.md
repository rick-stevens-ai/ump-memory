# UMP Record Schema

A UMP record is a JSON object:

```json
{
  "id": "mem_...",
  "kind": "semantic | episodic | procedural | working | identity",
  "title": "short optional title",
  "text": "memory text",
  "tags": ["ump", "policy"],
  "scope": {
    "owner": "rick",
    "agent": "ollie",
    "project": "optional-project",
    "visibility": "private | shared | public"
  },
  "metadata": {},
  "source": {
    "binding": "cli | http | file | mcp",
    "path": "optional file path",
    "line": 123
  },
  "created_at": "2026-06-07T20:00:00Z",
  "updated_at": "2026-06-07T20:00:00Z",
  "salience": 0.5
}
```

## Kinds

- `semantic`: durable fact or preference.
- `episodic`: event that happened.
- `procedural`: how to do something.
- `working`: temporary/current task state.
- `identity`: agent/person/project identity facts.

## Secret policy

Do **not** store raw API keys, passwords, private tokens, or bearer secrets in
UMP. Store a pointer such as:

```json
{
  "title": "Semantic Scholar API key location",
  "text": "Semantic Scholar API key exists; use env var S2_API_KEY. Stored in macOS Keychain service semantic-scholar-api-key, account rick-stevens-ai.",
  "tags": ["secret-pointer", "semantic-scholar"]
}
```
