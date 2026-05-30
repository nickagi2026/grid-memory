# Happy Path — Multi-Agent Coding Session

## Scenario
Main agent spawns a research subagent, then a builder subagent. Both use The Grid to share context.

## Step 1: Researcher Writes Findings

```json
{
  "operation": "write",
  "payload": {
    "agent_id": "researcher-1",
    "type": "fact",
    "tags": ["project:alpha", "database", "postgresql"],
    "content": "PostgreSQL connection pool max should be 25. Connection pooling via pg-pool is recommended over raw pg.Client. Walks through the 3-tier architecture: API → PgBouncer → PostgreSQL cluster.",
    "ttl_seconds": 86400
  }
}
```

**Grid response:**
```json
{
  "entry_id": "grid_20260526_a1b2c3d4e5f6",
  "agent_id": "researcher-1",
  "type": "fact",
  "tags": ["project:alpha", "database", "postgresql"],
  "created_at": "2026-05-26T18:15:00Z",
  "ttl_seconds": 86400,
  "expires_at": "2026-05-27T18:15:00Z",
  "store_entries_count": 1
}
```

## Step 2: Main Agent Makes a Decision

```json
{
  "operation": "write",
  "payload": {
    "agent_id": "main",
    "type": "decision",
    "tags": ["project:alpha", "architecture"],
    "content": "Chose Express over Fastify for the API layer. Rationale: middleware ecosystem maturity, team familiarity, and better documentation for the auth patterns we need.",
    "ttl_seconds": 604800,
    "parent_entry": "grid_20260526_a1b2c3d4e5f6"
  }
}
```

**Grid response:**
```json
{
  "entry_id": "grid_20260526_f6e5d4c3b2a1",
  "agent_id": "main",
  "type": "decision",
  "created_at": "2026-05-26T18:20:00Z",
  "expires_at": "2026-06-02T18:20:00Z",
  "store_entries_count": 2
}
```

## Step 3: Builder Subagent Spawns — Reads Grid

**Injection context (auto-generated from message "implement the API routes"):**

```
─── SHARED MEMORY GRID ───

Recent shared context for "builder-1" (filtered: api, database):

[fact] 2026-05-26 18:15 · researcher-1 · project:alpha, database, postgresql
  PostgreSQL connection pool max should be 25. Connection pooling via pg-pool…

[decision] 2026-05-26 18:20 · main · project:alpha, architecture
  Chose Express over Fastify for the API layer. Rationale: middleware ecosystem…

─── END GRID ───
```

## Step 4: Builder Writes Completion

```json
{
  "operation": "write",
  "payload": {
    "agent_id": "builder-1",
    "type": "handoff",
    "tags": ["project:alpha", "handoff"],
    "content": "API routes implemented. PR #42 filed. Awaiting review. Two concerns noted in code comments: rate limiting thresholds and error format consistency.",
    "ttl_seconds": 3600,
    "parent_entry": "grid_20260526_f6e5d4c3b2a1"
  }
}
```

**Grid response:** entry written. Next subagent will see the full chain.
