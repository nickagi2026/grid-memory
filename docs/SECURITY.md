# Grid Memory — Security Guide

## Architecture

Every request flows through: Authentication → Authorization → Workspace Validation → PII Policy → Operation → Audit

## API Key Management

- Keys are stored as SHA-256 hashes (never plaintext)
- Permission levels (ascending): **viewer < analyst < architect < executive < admin**
- `viewer` — read-only queries and health checks
- `analyst` — viewer + write entries, access dashboards and reports
- `architect` — analyst + manage contracts and constitutions
- `executive` — architect + manage keys and audit logs (currently enforced on gateway management routes)
- `admin` — everything
- Keys are scoped to workspaces (`'*'` for all)
- Bootstrap key is one-time use, deleted after first admin creation
- Key rotation via `grid enterprise key-rotate <id>`

## Route Authorization

Starting in v68, routes are registered via a **Route Registry** that bakes in the required permission level at registration time. This means:
- Every route explicitly declares its minimum permission
- Authorization is applied structurally, not by per-endpoint human memory
- New endpoints automatically inherit the auth pattern

### MIKE Intelligence Routes (All require `analyst`+)
When `GRID_ENFORCE_AUTH=true`, these endpoints are protected:

| Endpoint | Required Permission |
|----------|-------------------|
| `GET /roi` | analyst |
| `GET /mike/dashboard` | analyst |
| `GET /executive/dashboard` | analyst |
| `GET /decisions/graph` | analyst |
| `GET /decisions/stats` | analyst |
| `GET /qbr` | analyst |
| `POST /qbr/generate` | analyst |
| `GET /amnesia/detect` | analyst |
| `POST /setup-wizard` | admin |

## PII/PHI Protection

Three modes:
- **detect**: Log PII findings without blocking (default)
- **redact**: Auto-redact PII before storing
- **block**: Reject writes containing PII

Detected patterns: SSN, Credit Cards, Email, Phone, IP Address, Addresses, Medical IDs

## Audit Trail

- Append-only with HMAC-SHA256 hash chaining
- Each entry includes `previous_hash` for tamper detection
- Encryption key auto-generated on first run (stored in `audit_key.secret`)
- Verify audit integrity: `GET /gateway/audit/verify`
- CLI verification: `grid audit verify`

## CORS

Configurable via `GRID_ALLOWED_ORIGINS`. Default: `'*'` for development.

## Rate Limiting

100 requests per minute per IP. Configurable via `GRID_RATE_LIMIT`.

## Threat Model

- **Data at rest**: JSON file store or SQLite. PostgreSQL for production.
- **Data in transit**: No TLS built-in. Use a reverse proxy (nginx, Caddy) in production.
- **Auth bypass**: `GRID_ENFORCE_AUTH` must be `true` in production. Server warns on startup if not set.
- **Workspace isolation**: `ws:*` tags + AND-mode queries. First-class workspace_id field available.
- **Concurrent writes**: In-process lock. Single server process required for JSON store. SQLite backend recommended for production.
- **Audit tampering**: HMAC-SHA256 hash chaining detects any modification to the audit log. Verify with `GET /gateway/audit/verify`.
