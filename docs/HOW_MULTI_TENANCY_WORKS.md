# How Multi-Tenancy Works

Grid Memory supports multi-tenant deployments through workspace isolation.

## Workspace Tags

Every entry can be tagged with one or more workspace identifiers:

```json
{
  "agent_id": "arch-agent",
  "content": "Decision for client-acme",
  "tags": ["ws:client-acme", "topic:database"]
}
```

Workspace tags use the `ws:` prefix convention. They're treated as regular tags by the query engine, but application-level logic enforces isolation.

## How Isolation Works

### Write Isolation

When the server receives a write request with an `X-Grid-Workspace` header:

```
POST /write
X-Grid-Workspace: client-acme
```

The server automatically adds `ws:client-acme` to the entry's tags. No configuration needed.

### Query Isolation

When `X-Grid-Workspace` is set on a query, the server adds `ws:<workspace>` to the query tags and uses AND-mode to ensure only entries from that workspace are returned.

```
GET /query?tags=topic:database
X-Grid-Workspace: client-acme
```

This becomes: `tags=[topic:database, ws:client-acme]` with AND tag mode.

### Export Isolation

When `X-Grid-Workspace` is set on an export, only entries with that workspace tag are included:

```
GET /export
X-Grid-Workspace: client-acme
```

Admin requests (no workspace header) export everything.

### Import Isolation

When importing entries with a workspace header:

```
POST /import
X-Grid-Workspace: client-acme
```

The server:
1. **Strips** any existing `ws:` tags from imported entries
2. **Applies** the new workspace tag
3. Prevents cross-workspace contamination

### Delete Isolation

Before deleting an entry, the server verifies:

```
if entry has workspace tags → entry must include caller's workspace
if entry has no workspace tags → global entry, deletable by admin
```

This prevents workspace A from deleting workspace B's entries.

## Federation with Workspaces

Federation syncs entries between Grid instances. Synced entries retain their workspace tags:

```
Local Grid (client-acme workspace)
  → Syncs with Peer Grid
  → Receives entries with ws:peer-workspace tags
  → Entries remain isolated from local workspaces
```

## API Key Scoping

API keys can be scoped to specific workspaces:

```bash
curl -X POST /gateway/key/create \
  -d '{"label":"acme-key","permission":"analyst","workspace":"client-acme"}'
```

A key scoped to `client-acme` can only read and write entries with `ws:client-acme` tags.

## Testing Isolation

The workspace boundary test suite (`tests/test-workspace-boundaries.js`) verifies:

- Write isolation — entries created in separate workspaces don't leak
- Query isolation — workspace tags correctly scope results
- Export isolation — workspace tags survive export
- Delete isolation — only target entry is removed
- Cross-workspace isolation — entries from workspace A are invisible from workspace B
- Multi-workspace entries — entries visible from all assigned workspaces
