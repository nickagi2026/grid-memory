# How Authorization Works

Grid Memory uses a structured authorization pipeline enforced by the Route Registry.

## Overview

```
Request → Route Registry Match
  → Rate Limit Check (built into registry)
  → Gateway Authentication (API key validation)
  → Permission Level Check (viewer < analyst < architect < executive < admin)
  → Workspace Scope Validation
  → Handler Execution
  → Audit Logging
```

## Components

### Gateway (`gateway.js`)

The Gateway handles authentication and API key management:

- **API keys** are stored as SHA-256 hashes (never plaintext)
- **Bootstrap mode** creates a one-time key on first run (deleted after use)
- **Key rotation** generates new keys and revokes old ones atomically

### Route Registry (`route-registry.js`)

The Route Registry is the central authorization layer:

```javascript
registry.register('GET', '/roi', 'analyst', handler, { rateLimit: 30 });
```

Every route MUST declare:
- **HTTP method** (GET, POST, DELETE, etc.)
- **URL path** (supports `:param` and `*` patterns)
- **Permission level** (viewer, analyst, architect, executive, admin)
- **Handler function**
- **Optional rate limit** (requests per 60-second window)

### Permission Levels

| Level | Can Do | Example Routes |
|-------|--------|---------------|
| `viewer` | Read-only queries, health checks | `GET /health`, `GET /query` |
| `analyst` | Viewer + write, dashboards, reports | `POST /write`, `GET /roi`, `GET /qbr` |
| `architect` | Analyst + manage schemas and policies | `POST /contracts`, `POST /constitution` |
| `executive` | Architect + key management and audit | `GET /gateway/keys`, `GET /gateway/audit` |
| `admin` | Everything | `DELETE /forget/:id`, `POST /prune` |

### How a Request is Authorized

1. **Route Matching**: The `handle()` function calls `registry.match(method, url)`
2. **Rate Limiting**: If the route has a rate limit, the registry checks the in-memory rate counter (by IP)
3. **Authentication**: If `GRID_ENFORCE_AUTH=true`, the Gateway validates the `Authorization: Bearer <key>` header
4. **Permission Check**: The Gateway compares the key's permission level against the route's required level
5. **Workspace Scoping**: If the key is scoped to a workspace, it's enforced on the request
6. **Handler Execution**: The route handler receives the authorized request
7. **Audit Logging**: Every operation is logged to the tamper-evident audit trail

### API Key Headers

```bash
# Bearer token
curl http://localhost:8080/health \
  -H "Authorization: Bearer grid_a1b2c3d4e5f6..."

# API Key header
curl http://localhost:8080/health \
  -H "Authorization: ApiKey grid_a1b2c3d4e5f6..."
```

### Workspace Scoping

API keys can be scoped to specific workspaces:

```bash
# Create a key scoped to client-acme
curl -X POST /gateway/key/create \
  -d '{"label":"acme-key","permission":"analyst","workspace":"client-acme"}'

# Requests with this key automatically get ws:client-acme isolation
```

### Security Notes

- `GRID_ENFORCE_AUTH` must be `true` in production — the server warns on startup otherwise
- Rate limiting is in-memory and resets on server restart
- Audit hash chaining uses an auto-generated key persisted to `audit_key.secret`
- Verify audit integrity: `GET /gateway/audit/verify` or `grid enterprise audit-verify`
