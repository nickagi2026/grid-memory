# Tool Contract — Shared Memory Grid

## Tools Available

### `Grid.read(query)`
- **Purpose:** Retrieve entries from shared memory
- **Parameters:** `{ tags, agents, types, type, since, tagMode, max, parent_entry }`
- **Returns:** `{ entries[], query_meta }`
- **Risk:** L2 (Read only)
- **Can decide autonomously:** Yes

### `Grid.write(payload)`
- **Purpose:** Write a new entry to shared memory
- **Parameters:** `{ agent_id, content, type, tags, ttl_seconds, session_id, parent_entry }`
- **Returns:** `{ entry_id, agent_id, type, tags, created_at, ttl_seconds, expires_at, store_entries_count }`
- **Risk:** L3 (Write draft)
- **Can decide autonomously:** Yes — appends only, never modifies existing data

### `Grid.prune()`
- **Purpose:** Remove expired entries, compress large stores
- **Returns:** `{ removed, remaining, total_before, store_size_mb, compressed }`
- **Risk:** L4 (Execute with caution)
- **Can decide autonomously:** Yes — only removes timed-out entries, never touches alive data

### `Grid.forget(entryId)`
- **Purpose:** Remove a specific entry by ID
- **Returns:** `{ found, entry_id, type, agent_id }`
- **Risk:** L4 (Execute with caution)
- **Can decide autonomously:** No — requires user confirmation

### `Grid.inject(contextHint)`
- **Purpose:** Generate context injection block for agent activation
- **Parameters:** `contextHint` (the user's message string)
- **Returns:** `{ block, entry_count, bytes }`
- **Risk:** L2 (Read only)
- **Can decide autonomously:** Yes

### `Grid.info()`
- **Purpose:** Get store statistics
- **Returns:** `{ total_entries, alive_entries, expired_entries, unique_agents, unique_tags, store_size_kb, by_type, by_agent }`
- **Risk:** L1 (Think only)
- **Can decide autonomously:** Yes

## Schema Enforcement

Every `write` must pass schema validation before reaching the store:
- `agent_id`: string, non-empty
- `content`: string, non-empty
- `type`: one of [decision, fact, task_status, artifact_ref, handoff, question, observation, blocker, state_update]
- `tags`: array of strings (optional)
- `ttl_seconds`: positive integer (optional, type-based default)

## Error Contract

All errors return structured JSON:
```json
{
  "error": "<human-readable message>",
  "code": "INVALID_PARAMETER | STORE_ERROR | SECURITY_REJECTION | NOT_FOUND"
}
```

Errors are never silent. If a write fails, the calling agent knows why.
