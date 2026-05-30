# Workspace Isolation

> Current limitations and planned improvements for multi-tenant deployments.

## Current Architecture

Workspace isolation uses two mechanisms:

1. **workspace_id field** — stored on every entry at write time
2. **ws:* tags** — applied via the `X-Grid-Workspace` header

## What's Authoritative

Currently, **ws:* tags** are the primary isolation mechanism. The `workspace_id` field exists on all entries but most enforcement paths check tags rather than the field.

## Why This Matters

In true enterprise multi-tenant deployments, security should not depend on metadata (tags) that could be manipulated. The `workspace_id` field is set at write time and cannot be changed — it's a more reliable isolation boundary.

## Migration Path

| Version | Status | Isolation Mechanism |
|---------|--------|-------------------|
| Current (v84) | ✅ | ws:* tags (primary), workspace_id (secondary) |
| Planned | 🔄 | workspace_id (primary), ws:* tags (metadata only) |

## What's Already Isolated

- **Write**: workspace_id set on every entry
- **Query**: ws:* tags filtered by workspace header
- **Export**: filtered by ws:* tags when header present
- **Import**: old ws:* tags stripped, new ones applied, workspace_id set
- **Delete**: workspace membership verified before deletion
- **Federation**: sync preserves workspace boundaries

## What's Still Tag-Dependent

- Dashboard scoping
- Subscription feeds
- Amnesia detection per workspace
