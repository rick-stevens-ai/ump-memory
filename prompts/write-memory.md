# Write Memory Prompt

Convert the following fact/event/procedure into a UMP record.

Requirements:

- Pick one kind: semantic, episodic, procedural, working, identity.
- Use concise title and precise text.
- Include tags.
- Include scope: owner, agent, project if known, visibility.
- Include source/provenance.
- Do not include raw secrets.
- State which file-backed source of truth must also be updated.

Input:

```text
{{MEMORY_ITEM}}
```

Return JSON only.
