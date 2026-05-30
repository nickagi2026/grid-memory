# Thin Input — Minimal Input, Graceful Inference

## Scenario
A newly spawned subagent doesn't know what tags to use. It writes a bare observation with no metadata, and reads without specifying any query.

## Write: Thin Input

### Agent sends:
```json
{
  "operation": "write",
  "payload": {
    "agent_id": "scout-db-1",
    "content": "Found a race condition in the booking system when two users try to book the last slot simultaneously."
  }
}
```

### Grid infers:
- No type provided → defaults to `observation`
- No tags provided → empty tags array
- No TTL provided → defaults to 24 hours (`observation` default)

### Grid response:
```json
{
  "entry_id": "grid_20260526_x1y2z3",
  "agent_id": "scout-db-1",
  "type": "observation",
  "tags": [],
  "created_at": "2026-05-26T19:00:00Z",
  "ttl_seconds": 86400,
  "expires_at": "2026-05-27T19:00:00Z"
}
```

## Read: Thin Input

### Agent sends:
```json
{
  "operation": "read",
  "payload": {}
}
```

### Grid response:
```json
{
  "entries": [
    {
      "id": "grid_20260526_a1b2c3d4e5f6",
      "agent_id": "researcher-1",
      "type": "fact",
      "content": "PostgreSQL connection pool...",
      "created_at": "2026-05-26T18:15:00Z"
    },
    {
      "id": "grid_20260526_f6e5d4c3b2a1",
      "agent_id": "main",
      "type": "decision",
      "content": "Chose Express over Fastify...",
      "created_at": "2026-05-26T18:20:00Z"
    }
  ],
  "query_meta": {
    "total_before_filter": 3,
    "returned": 2,
    "expired_filtered": 0
  }
}
```

### Graceful handling:
- Empty read returns most recent entries sorted by recency
- Empty write still requires agent_id and content (non-negotiable)
- Missing type defaults to `observation` (least committal)
- No tags means the entry won't be found by tag queries, but stays accessible via wildcard reads
