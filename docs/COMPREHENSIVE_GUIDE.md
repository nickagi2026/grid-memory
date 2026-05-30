# Grid Memory — The Complete Guide

> **Everything you need to know to install, configure, use, and profit from the Grid.**
> Written for technical teams who want shared memory that actually works in production.

---


> **Publication Status:**
> - **npm**: `grid-memory` — pre-release, not yet published
> - **PyPI**: `grid-memory` — pre-release, not yet published
> - **GitHub**: Private repository — public launch planned
> - **Docker**: Build locally via `docker build -t grid-memory .`

## Table of Contents

<!-- TOC depth=4 -->

1. [Why This Exists](#1-why-this-exists)
2. [Core Concepts — Explained Simply](#2-core-concepts--explained-simply)
3. [Installation — Step by Step](#3-installation--step-by-step)
4. [Your First 5 Minutes](#4-your-first-5-minutes)
5. [Everyday Operations](#5-everyday-operations)
6. [Memory Contracts (Schema Enforcement)](#6-memory-contracts-schema-enforcement)
7. [Constitutions (Policy Rules)](#7-constitutions-policy-rules)
8. [Federation (Connecting Multiple Grids)](#8-federation-connecting-multiple-grids)
9. [Business Intelligence Dashboards](#9-business-intelligence-dashboards)
10. [Security & Enterprise Features](#10-security--enterprise-features)
11. [Complete API Reference](#11-complete-api-reference)
12. [Troubleshooting](#12-troubleshooting)
13. [Architecture Overview](#13-architecture-overview)

---

## 1. Why This Exists

### The Problem

Multi-agent systems fail because of **memory**, not reasoning. Research across 200+ execution traces shows:

- **40–80% failure rates** in multi-agent workflows
- **37% of failures** come from inter-agent misalignment — agents acting on incomplete, stale, or invisible state
- **Memory poisoning** is a verified injection vector with 95%+ success rates

When you spawn five subagents to work on a project, each one starts from zero. They don't know what the others decided. They can't see past results. They repeat mistakes and contradict each other. This is the **agent amnesia problem**, and it's the single biggest bottleneck in production multi-agent systems.

### What The Grid Does

The Grid is a **shared persistent memory layer** that sits between every agent in your system:

- **Agents write** structured entries (decisions, facts, observations, blockers)
- **Other agents read** them back with relevance-weighted retrieval
- **Everything is timestamped and append-only** — nothing is ever overwritten
- **TTLs expire stale data** automatically
- **Policies enforce rules** (no PII, no API keys, decisions must include rationale)
- **Audit trails are tamper-evident** with HMAC-SHA256 hash chaining
- **Federation syncs between Grid instances** across teams or data centers

### Who This Is For

- **Engineering teams** deploying multi-agent systems with LangGraph, CrewAI, AutoGen, or custom frameworks
- **Platform teams** building shared context layers for agent fleets
- **Consultants** delivering QBRs and decision intelligence to clients
- **Compliance teams** needing tamper-evident audit trails for AI-driven decisions

---

## 2. Core Concepts — Explained Simply

### What Is an Entry?

An **entry** is the atomic unit of memory. It's like a sticky note that an agent writes and other agents can read. Every entry has:

```
┌─────────────────────────────────────────────────────┐
│  Entry: grid_20260530_a1b2c3d4e5f6                   │
│  Agent:  arch-agent                                   │
│  Type:   decision                                     │
│  Tags:   [topic:database, project:alpha]              │
│  TTL:    86400 seconds (24 hours)                     │
│  Content: "Use PostgreSQL for primary storage.        │
│            Rationale: ACID compliance, team expertise"│
│  Created: 2026-05-30T07:00:00.000Z                    │
└─────────────────────────────────────────────────────┘
```

### Entry Types

| Type | When to Use | TTL Default |
|------|-------------|-------------|
| `decision` | An agent made a choice | 24h |
| `fact` | A verified piece of information | 24h |
| `observation` | Something noticed, not yet confirmed | 12h |
| `blocker` | Something blocking progress | 24h |
| `handoff` | Passing work between agents | 1h |
| `task_status` | Status update on ongoing work | 1h |
| `artifact_ref` | Reference to a created file/output | 7 days |
| `question` | An open question needing answer | 12h |
| `state_update` | System state change | 1h |
| `synthesis` | Aggregated insight from multiple entries | 24h |

### Tags

Tags are how agents find related entries. Think of them as labels:

```json
"tags": ["topic:database", "project:alpha", "env:production"]
```

**Best practices:**
- Use `topic:` prefix for subjects (e.g., `topic:database`, `topic:deployment`)
- Use `project:` prefix for projects (e.g., `project:alpha`, `project:beta`)
- Use `ws:` prefix for workspace isolation (auto-added by the server)
- Use `stage:` for pipeline stages (e.g., `stage:detected`, `stage:won`)
- Use `client:` for client names in multi-tenant setups

### What Is TTL?

**Time To Live** — how long an entry lives before it's automatically pruned.

- After TTL expires, the entry is invisible to queries and context injection
- The entry still exists on disk until a prune operation
- TTL is set per-entry, not globally
- Default TTLs are set per type (see table above)
- Set `ttl_seconds: 0` for permanent entries (never expire)

### Memory Tiers

Entries are assigned a tier that determines how long they're kept and how heavily they're weighted in relevance scoring:

| Tier | Retention | Typical Content |
|------|-----------|-----------------|
| ⚡ **Working** | Hours | Active agent context, high churn |
| 📦 **Project** | Weeks | Confirmed decisions, validated outcomes |
| 🏰 **Organization** | Years | Curated knowledge, audited decisions |

Tier promotion is automatic: entries referenced frequently get promoted to higher tiers.

### What Is a Workspace?

A **workspace** isolates data between different projects, clients, or teams. Every entry in a workspace gets an auto-applied `ws:<workspace>` tag. Queries scoped to a workspace only see entries with that tag.

```
GET /query?tags=ws:client-acme
```

### What Is Federation?

**Federation** connects two or more Grid instances so they can share entries:

```
Grid A (San Francisco) ←→ Grid B (New York)
```

- Entries synced from a peer get a `federated` tag
- Peers can be `verified` (shared secret), `unverified` (no secret), or `quarantine` (isolated)
- HMAC-SHA256 signatures ensure authenticity
- Conflict resolution: most recent entry wins

---

## 3. Installation — Step by Step

### Prerequisites

- **Node.js 18+** (required for the server)
- **Python 3.8+** (optional, for the Python SDK)
- **1 GB free disk** (recommended for active stores)
- **100 MB minimum** (for the server alone)

### Option A: Quick Install (curl — coming soon)

```bash
curl -sSL https://install.grid.sh | bash
grid start
```

This launches the server on port 8080 with demo mode enabled.

### Option B: Docker

```bash
# Pull and run
docker run -d \
  --name grid-memory \
  -p 8080:8080 \
  -v grid-data:/data \
  -e GRID_SEED_MODE=true \
  grid-memory:latest

# Verify it's running
curl http://localhost:8080/health
```

Expected response:
```json
{
  "status": "ok",
  "store": { "total_entries": 8, "alive_entries": 8, "store_size_kb": 4 },
  "version": "1.0.0"
}
```

### Option C: From Source (Node.js)

```bash
# Clone or copy the grid directory
cd grid-memory

# Install dependencies
npm install

# Start the server
node server.js
```

Output:
```
GRID_ENFORCE_AUTH is not set. Running in DEVELOPMENT MODE with NO authentication.
Grid Memory Server
Listening on http://0.0.0.0:8080
Seed mode (auto): 8 entries from 3 agents
```

### Option D: Python SDK

```bash
# Install from the SDK directory
cd grid-memory/sdk/python
pip install -e .

# Or directly
# pip install grid-memory (pre-release) 
```

### Verifying the Installation

```bash
# Health check
curl http://localhost:8080/health

# Quick info
curl http://localhost:8080/info
```

Both commands should return JSON. If they do, the Grid is running.

---

## 4. Your First 5 Minutes

### Step 1: Start the Server

```bash
cd grid-memory
node server.js
```

The server automatically:
1. Checks if the Grid is empty
2. Seeds 8 demo entries from 3 agents (arch-agent, ops-agent, sec-agent)
3. Makes them available immediately

### Step 2: Open the Dashboard

Open your browser to:

```
http://localhost:8080/dashboard
```

You'll see:
- Activity timeline of seeded entries
- Agent activity breakdown
- Store statistics

If the dashboard doesn't load, try:

```
http://localhost:8080/dashboard/index.html
```

### Step 3: Write Your First Entry

```bash
curl -X POST http://localhost:8080/write \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "my-agent",
    "type": "decision",
    "content": "Use PostgreSQL for primary storage. Rationale: ACID compliance, team expertise.",
    "tags": ["topic:database", "project:my-project"],
    "ttl_seconds": 86400
  }'
```

Expected response:
```json
{
  "entry_id": "grid_20260530_a1b2c3d4e5f6",
  "agent_id": "my-agent",
  "created_at": "2026-05-30T07:00:00.000Z",
  "ttl_expires_at": "2026-05-31T07:00:00.000Z"
}
```

### Step 4: Read It Back

```bash
curl "http://localhost:8080/query?tags=topic:database&max=5"
```

### Step 5: See Your Instant ROI

```bash
curl http://localhost:8080/roi
```

This tells you:
- How many duplicates were prevented
- How many contradictions were detected
- How many opportunities were found
- How much time you saved

---

## 5. Everyday Operations

### Writing Entries

**Via curl (HTTP API):**
```bash
curl -X POST http://localhost:8080/write \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "my-agent",
    "type": "decision",
    "content": "Use PostgreSQL for primary storage. Rationale: ACID compliance, team expertise.",
    "tags": ["topic:database", "project:my-project"],
    "ttl_seconds": 86400
  }'
```

**Via Node.js SDK:**
```javascript
const { Grid } = require('./reference/store.js');
const grid = new Grid();

await grid.write({
  agent_id: 'my-agent',
  type: 'decision',
  content: 'Use PostgreSQL for primary storage. Rationale: ACID compliance, team expertise.',
  tags: ['topic:database', 'project:my-project'],
  ttl_seconds: 86400,
});
```

**Via Python SDK:**
```python
from grid_memory import LocalGrid

grid = LocalGrid()
grid.write(
    agent_id='my-agent',
    type='decision',
    content='Use PostgreSQL for primary storage. Rationale: ACID compliance, team expertise.',
    tags=['topic:database', 'project:my-project'],
    ttl_seconds=86400,
)
```

### Reading Entries

**By tag:**
```bash
curl "http://localhost:8080/query?tags=topic:database"
```

**By agent:**
```bash
curl "http://localhost:8080/query?agents=arch-agent"
```

**By type:**
```bash
curl "http://localhost:8080/query?type=decision"
```

**Combined:**
```bash
curl "http://localhost:8080/query?tags=topic:database&agents=arch-agent&type=decision&max=10"
```

**Advanced query (POST with JSON body):**
```bash
curl -X POST http://localhost:8080/query \
  -H "Content-Type: application/json" \
  -d '{
    "tags": ["topic:database"],
    "agents": ["arch-agent"],
    "type": "decision",
    "max": 20,
    "since": "2026-05-01T00:00:00Z"
  }'
```

### Injecting Context

Before spawning a subagent, inject relevant context so it doesn't start from zero:

```bash
curl "http://localhost:8080/inject?context=I%27m%20building%20a%20database%20migration%20plan"
```

Returns a condensed block of relevant entries (max 4KB) that you can insert into the subagent's system prompt.

### Pruning Expired Data

```bash
# Manual prune
curl -X POST http://localhost:8080/prune

# Or let it happen automatically — the server prunes on a timer
```

### Forgetting an Entry

```bash
curl -X DELETE http://localhost:8080/forget/grid_20260530_a1b2c3d4e5f6
```

### Checking Server Status

```bash
curl http://localhost:8080/info
```

Returns total entries, alive entries, unique agents, unique tags, and store size.

---

## 6. Memory Contracts (Schema Enforcement)

Memory Contracts ensure that entries follow a predictable schema. Think of them as **type checking for memory**.

### Why Use Contracts?

Without contracts, agents can write anything in any format. This makes it hard to query, analyze, or trust the data. With contracts:

- Entries follow a defined schema
- Required fields must be present
- Values are type-checked (string, number, boolean, enum, semver)
- Violations can warn or reject the write

### Registering a Contract

```bash
curl -X POST http://localhost:8080/contracts \
  -H "Content-Type: application/json" \
  -d '{
    "scope": "topic:deployment",
    "schema": {
      "environment": "enum:production|staging|development",
      "version": "semver",
      "deployed_by": "string",
      "success": "boolean",
      "required": ["environment", "version", "success"]
    },
    "enforce": "reject"
  }'
```

### Enforce Modes

| Mode | Behavior |
|------|----------|
| `validate` (default) | Logs warnings but allows the write |
| `reject` | Blocks the write if validation fails |
| `warn` | Same as validate — logs warnings |

### What Happens on Violation

If `enforce: "reject"` and the entry doesn't match the schema:

```json
{
  "error": "Contract validation failed: Field 'environment': Expected one of: production, staging, development",
  "code": "CONTRACT_VIOLATION"
}
```

### Auto-Discovering Contracts

The Grid can scan your existing entries and suggest contract schemas automatically:

```bash
curl http://localhost:8080/auto-contracts
```

```json
{
  "suggestions": [
    {
      "scope": "topic:database",
      "suggested_schema": { "database": "string", "Rationale": "string" },
      "observed_entries": 3,
      "confidence": 100
    }
  ]
}
```

To approve a suggestion and make it a real contract:

```bash
curl -X POST http://localhost:8080/auto-contracts/approve \
  -H "Content-Type: application/json" \
  -d '{
    "scope": "topic:database",
    "suggested_schema": { "database": "string", "Rationale": "string" }
  }'
```

### Listing All Contracts

```bash
curl http://localhost:8080/contracts
```

### Removing a Contract

```bash
curl -X DELETE http://localhost:8080/contracts/topic:deployment
```

---

## 7. Constitutions (Policy Rules)

Constitutions are **behavioral rules** enforced at write time. While contracts check _format_, constitutions check _content_.

### Why Use Constitutions?

- Prevent agents from storing API keys or secrets
- Ensure decisions include rationale
- Block PII from being written to memory
- Enforce compliance rules (HIPAA, SOC2)
- Make agents accountable to team policies

### Writing Natural Language Policies

No need to learn a DSL. Write policies in plain English:

```bash
curl -X POST http://localhost:8080/constitution/from-text \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Never store API keys in content. All decisions must include rationale. Don'\''t include PII.",
    "enforceMode": "block"
  }'
```

The Grid parses the text into structured rules:

```json
{
  "generated": {
    "rules": [
      { "name": "Never store API keys in content", "blockedPatterns": ["api.?key"] },
      { "name": "All decisions must include rationale", "requiredWords": ["rationale"], "entryTypes": ["decision"] },
      { "name": "Don't include PII", "blockedPatterns": ["pii"] }
    ]
  }
}
```

### Registering a Constitution Programmatically

```bash
curl -X POST http://localhost:8080/constitution \
  -H "Content-Type: application/json" \
  -H "X-Grid-Workspace: default" \
  -d '{
    "rules": [
      "All decisions must include rationale",
      "Never store API keys in content",
      "Don'\''t include PII"
    ],
    "enforceMode": "block"
  }'
```

### Enforce Modes

| Mode | Behavior |
|------|----------|
| `validate` (default) | Returns warnings, allows the write |
| `block` | Rejects the write with CONSTITUTION_VIOLATION error |

### What Happens on Violation (block mode)

```json
{
  "error": "Constitution validation failed: Rule \"Never store API keys in content\": entry matches blocked pattern \"api.?key\"",
  "code": "CONSTITUTION_VIOLATION"
}
```

### Listing Constitutions

```bash
curl http://localhost:8080/constitution
```

### Removing a Constitution

```bash
curl -X DELETE http://localhost:8080/constitution \
  -H "X-Grid-Workspace: default"
```

### Example Policy Templates

**Decision integrity:**
```
All decisions must include rationale
All decisions must include alternatives considered
Never store API keys in content
```

**Security:**
```
Never include PII in content
Don't include credentials in content
All entries must include source attribution
```

**Compliance:**
```
Never include PHI in content
All decisions must include rationale
All entries must include compliance tags
```

---

## 8. Federation (Connecting Multiple Grids)

Federation lets you connect Grid instances across teams, data centers, or client environments.

### Quick Connect (One-Click)

The easiest way to connect two Grids:

```bash
curl -X POST http://localhost:8080/federation/quick-connect \
  -H "Content-Type: application/json" \
  -d '{
    "peerUrl": "http://other-grid.internal:8080"
  }'
```

This:
1. Checks if the peer is reachable (GET /health)
2. Gets peer info (GET /info)
3. Generates a shared secret
4. Registers the peer locally
5. Registers YOUR Grid on the remote (by calling POST /federation/peers on the remote)
6. Returns the connection details

### Manual Peer Registration

```bash
curl -X POST http://localhost:8080/federation/peers \
  -H "Content-Type: application/json" \
  -d '{
    "url": "http://sf-grid.internal:8080",
    "trustLevel": "verified",
    "sharedSecret": "my-shared-secret"
  }'
```

### Trust Levels

| Level | Description |
|-------|-------------|
| `verified` | Has shared secret — entries get full trust score (80) |
| `unverified` | No shared secret — entries get low trust score (40) |
| `quarantine` | Isolated — entries get minimal trust score (10) |

### Syncing from a Peer

```bash
# Trigger sync from a specific peer
curl -X POST http://localhost:8080/federation/sync/http%3A%2F%2Fsf-grid.internal%3A8080
```

### Listing Peers

```bash
curl http://localhost:8080/federation/peers
```

Returns peers without their shared secrets (security):

```json
{
  "peers": [
    {
      "url": "http://sf-grid.internal:8080",
      "trustLevel": "verified",
      "trustScore": 80,
      "has_secret": true,
      "last_synced_at": "2026-05-30T07:00:00.000Z"
    }
  ]
}
```

### Removing a Peer

```bash
curl -X DELETE "http://localhost:8080/federation/peers/http%3A%2F%2Fsf-grid.internal%3A8080"
```

### How Signatures Work

When a peer syncs with you:
1. They sign the request with HMAC-SHA256 using the shared secret
2. The payload is `timestamp.body`
3. You verify the signature against the stored shared secret
4. Reject if invalid, expired (>5 min), or missing

This prevents unauthorized syncs and replay attacks.

---

## 9. Business Intelligence Dashboards

The Grid generates real business value from existing data — no extra setup required.

### MIKE Dashboard

The operations dashboard combines everything into a single view:

```bash
curl http://localhost:8080/mike/dashboard
```

Returns:
```json
{
  "summary": {
    "total_entries": 47,
    "unique_agents": 5,
    "unique_workspaces": 2,
    "oldest_entry": "...",
    "newest_entry": "..."
  },
  "clients": [...],
  "opportunities": {
    "total": 12,
    "by_stage": { "detected": 5, "reviewed": 3, "won": 2, "lost": 2 },
    "pipeline_value": "$240,000",
    "win_rate": "50%"
  },
  "risks": [...],
  "revenue": {
    "won_deals": 2,
    "total_revenue": "$120,000",
    "pipeline": "$240,000",
    "avg_accuracy": "85%"
  }
}
```

### Executive Dashboard

C-suite view combining KPIs, decisions, opportunities, risks, amnesia, and quick actions:

```bash
curl http://localhost:8080/executive/dashboard
```

### Decision Graph

Visualize every decision, who made it, why, and what happened:

```bash
# Full graph
curl http://localhost:8080/decisions/graph

# Stats only
curl http://localhost:8080/decisions/stats
```

### QBR Reports

Generate Quarterly Business Review reports automatically:

```bash
# Current quarter
curl http://localhost:8080/qbr

# Specific quarter
curl "http://localhost:8080/qbr?period=Q1-2026"

# POST with custom parameters
curl -X POST http://localhost:8080/qbr/generate \
  -H "Content-Type: application/json" \
  -d '{"period": "Q1-2026", "include": ["decisions", "opportunities", "risks"]}'
```

### Amnesia Detection

Find knowledge gaps before they become problems:

```bash
curl http://localhost:8080/amnesia/detect
```

Detects:
- **Gaps** — topics not discussed in 30+ days
- **Orphans** — decisions made but never acted upon
- **Stale decisions** — no review in 60+ days
- **Single-points-of-failure** — knowledge held by only one agent

### Instant ROI

```bash
curl http://localhost:8080/roi
```

Shows: duplicates prevented, contradictions detected, opportunities found, time saved.

### Setup Wizard

If you're starting fresh, let the wizard guide you:

```bash
curl -X POST http://localhost:8080/setup-wizard
```

Returns steps to configure the Grid for your use case. Send answers to auto-configure:

```bash
curl -X POST http://localhost:8080/setup-wizard \
  -H "Content-Type: application/json" \
  -d '{
    "purpose": "Agent team coordination",
    "agents": "5–20",
    "compliance": "No"
  }'
```

---

## 10. Security & Enterprise Features

### Authentication

#### Development Mode (Default)

No authentication required. All endpoints are open. Good for local development.

```bash
# Start in dev mode (default)
node server.js
```

#### Production Mode

Set `GRID_ENFORCE_AUTH=true` to enable the full security pipeline.

```bash
GRID_ENFORCE_AUTH=true node server.js
```

Every request goes through:
```
Authentication → Authorization → Workspace Validation → Rate Limiting → Operation → Audit
```

#### Creating API Keys

```bash
# Create an admin key
curl -X POST http://localhost:8080/gateway/key/create \
  -H "Content-Type: application/json" \
  -d '{
    "label": "admin-key",
    "permission": "admin",
    "workspace": "*"
  }'

# Returns: { key_id, plaintext_key: "grid_..." }
# Save the plaintext key — it's shown only once!
```

#### Permission Levels

| Level | Can |
|-------|-----|
| `viewer` | Read queries, health checks |
| `analyst` | View + write entries |
| `architect` | Analyst + manage contracts, constitutions |
| `executive` | Architect + manage keys, audit logs |
| `admin` | Everything |

#### Using API Keys

```bash
curl http://localhost:8080/health \
  -H "Authorization: Bearer grid_a1b2c3d4e5f6..."
```

#### Key Rotation

```bash
# Rotate an API key (generates new key, revokes old)
curl -X POST http://localhost:8080/gateway/key/rotate/key_a1b2c3d4
```

#### Listing and Revoking Keys

```bash
# List all keys
curl http://localhost:8080/gateway/keys

# Revoke a key
curl -X DELETE http://localhost:8080/gateway/key/revoke/key_a1b2c3d4
```

### PII Detection

The Grid automatically scans entries for:
- **SSN** (`\b\d{3}-\d{2}-\d{4}\b`)
- **Credit Cards** (`\b(?:\d{4}[- ]?){3}\d{4}\b`)
- **Email** (`\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b`)
- **Phone** (`\b\d{3}[-.]?\d{3}[-.]?\d{4}\b`)
- **Medical IDs** (`MRN\d{4,10}`)

#### Scanning Content for PII

```bash
curl -X POST http://localhost:8080/gateway/pii/scan \
  -H "Content-Type: application/json" \
  -d '{
    "content": "My SSN is 123-45-6789 and email is user@example.com"
  }'
```

Returns:
```json
{
  "hasPII": true,
  "findings": [
    { "type": "SSN", "severity": "critical", "match": "123-45-6789" },
    { "type": "Email", "severity": "high", "match": "user@example.com" }
  ],
  "redacted": "My SSN is [REDACTED SSN] and email is [REDACTED Email]"
}
```

### Audit Trail (Tamper-Evident)

Every operation is logged with HMAC-SHA256 hash chaining. Each audit entry contains:

```json
{
  "id": 1,
  "timestamp": "2026-05-30T07:00:00.000Z",
  "action": "write",
  "result": "allowed",
  "method": "POST",
  "path": "/write",
  "workspace": "default",
  "actor": "arch-agent",
  "key_id": "key_a1b2c3d4",
  "ip": "192.168.1.100",
  "detail": "entry_id=grid_...",
  "previous_hash": "a1b2c3d4...",
  "_hash": "e5f6a7b8..."
}
```

#### Viewing the Audit Log

```bash
curl http://localhost:8080/gateway/audit
```

#### Verifying Audit Integrity

```bash
curl http://localhost:8080/gateway/audit/verify
```

If the chain is intact:
```json
{ "valid": true }
```

If tampered:
```json
{ "valid": false, "brokenAtIndex": 3, "reason": "chain break: prev hash mismatch at 3" }
```

### Rate Limiting

The Grid applies per-endpoint rate limits in memory:

| Endpoint | Rate Limit |
|----------|------------|
| General | 100/min |
| `/ask` | 30/min |
| `/subscribe` | 20/min |
| `/agents/reputation` | 30/min |
| `/contracts` | 30/min |
| `/export` | 10/min |
| `/federation` | 20/min |

---

## 11. Complete API Reference

### Core Endpoints

#### `POST /write`

Write a new entry.

```bash
curl -X POST http://localhost:8080/write \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "my-agent",
    "type": "decision",
    "content": "Use PostgreSQL for primary storage.",
    "tags": ["topic:database", "project:alpha"],
    "ttl_seconds": 86400,
    "session_id": "sess_123",
    "parent_entry": "grid_..."
  }'
```

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `agent_id` | Yes | string | Who wrote this |
| `type` | Yes | string | One of: decision, fact, observation, blocker, handoff, task_status, artifact_ref, question, state_update, synthesis |
| `content` | Yes | string | The actual content |
| `tags` | No | array | List of tag strings |
| `ttl_seconds` | No | number | Time to live in seconds (uses type default if omitted) |
| `session_id` | No | string | Session identifier for grouping |
| `parent_entry` | No | string | Link to a parent entry (for threading) |

#### `GET /query`

Query entries by tags, agents, type, etc.

```
GET /query?tags=topic:database,project:alpha&agents=arch-agent&type=decision&max=20&since=2026-01-01T00:00:00Z
```

#### `POST /query`

Same as GET/query but with JSON body for complex queries.

```bash
curl -X POST http://localhost:8080/query \
  -H "Content-Type: application/json" \
  -d '{
    "tags": ["topic:database"],
    "agents": ["arch-agent"],
    "types": ["decision", "fact"],
    "max": 50,
    "since": "2026-01-01T00:00:00Z",
    "before": "2026-12-31T23:59:59Z"
  }'
```

#### `GET|POST /inject`

Get condensed context block for subagent injection.

```
GET /inject?context=I%27m%20working%20on%20database%20migration
```

Returns max 4KB of relevant context.

#### `POST /prune`

Remove expired entries.

```bash
curl -X POST http://localhost:8080/prune
```

#### `DELETE /forget/:id`

Remove a specific entry.

```bash
curl -X DELETE http://localhost:8080/forget/grid_20260530_a1b2c3d4e5f6
```

#### `GET /info`

Store statistics.

```bash
curl http://localhost:8080/info
```

Returns: total_entries, alive_entries, unique_agents, unique_tags, store_size_kb, expired_entries.

#### `GET /health`

Health check.

```bash
curl http://localhost:8080/health
```

#### `GET /export`

Export all entries (for federation or backup).

```bash
curl http://localhost:8080/export
```

#### `POST /import`

Import entries from an export file.

```bash
curl -X POST http://localhost:8080/import \
  -H "Content-Type: application/json" \
  -d '{
    "entries": [...]
  }'
```

### Contract Endpoints

#### `POST /contracts`

Register a contract.

#### `GET /contracts`

List all contracts.

#### `DELETE /contracts/:scope`

Remove a contract.

#### `GET /auto-contracts`

Get auto-generated contract suggestions.

#### `POST /auto-contracts/approve`

Approve a suggestion and register as contract.

#### `POST /auto-contracts/reject`

Reject a suggestion (won't be suggested again).

#### `GET /auto-contracts/state`

View approval state (approved, rejected, pending scopes).

### Constitution Endpoints

#### `POST /constitution`

Register constitution rules.

#### `GET /constitution`

List constitutions for workspace.

#### `DELETE /constitution`

Remove constitution for workspace.

#### `POST /constitution/from-text`

Generate constitution rules from natural language text.

### Federation Endpoints

#### `POST /federation/peers`

Register a peer.

#### `GET /federation/peers`

List registered peers.

#### `DELETE /federation/peers/:url`

Remove a peer.

#### `POST /federation/sync/:url`

Trigger sync from a peer.

#### `POST /federation/peers (or /federation/quick-connect)`

One-click peer connection (auto-discovers, generates secret, registers both sides).

### Gateway Management Endpoints

#### `POST /gateway/key/create`

Create a new API key.

#### `GET /gateway/keys`

List all API keys.

#### `DELETE /gateway/key/revoke/:id`

Revoke an API key.

#### `POST /gateway/key/rotate/:id`

Rotate an API key (replace + revoke).

#### `GET /gateway/audit`

View audit log entries.

#### `GET /gateway/audit/verify`

Verify audit hash chain integrity.

#### `POST /gateway/pii/scan`

Scan content for PII.

### Business Intelligence Endpoints

#### `GET /roi`

Instant ROI report.

#### `GET /mike/dashboard`

Full operations dashboard.

#### `GET /executive/dashboard`

Executive overview (combines all dashboards).

#### `GET /decisions/graph`

Full decision graph.

#### `GET /decisions/stats`

Decision analytics and maker rankings.

#### `GET /qbr`

QBR report for current or specified period.

#### `POST /qbr/generate`

Generate QBR with custom parameters.

#### `GET /amnesia/detect`

Run amnesia detection.

#### `POST /setup-wizard`

Guided setup (GET steps or POST answers).

#### `POST /seed`

Seed demo data (requires admin).

### OpenAI-Compatible Endpoints

#### `GET /v1/models`

List available models (OpenAI-compatible).

#### `POST /v1/chat/completions`

Chat completions (OpenAI-compatible, proxies to upstream).

### Dashboard Endpoints

#### `GET /dashboard`

Serve the HTML dashboard.

---

## 12. Troubleshooting

### Server Won't Start

**Problem:** `Error: listen EADDRINUSE :::8080`

**Fix:** Port is already in use. Use a different port:
```bash
PORT=9090 node server.js
```

**Problem:** `Error: Cannot find module 'better-sqlite3'`

**Fix:** SQLite is optional. The Grid falls back to JSON file storage automatically. This warning is safe to ignore.

### Seed Mode Not Working

**Problem:** Server starts but no seed data appears.

**Fix:** Set the env var explicitly:
```bash
GRID_SEED_MODE=true node server.js
```
Or if you want to DISABLE auto-seed:
```bash
GRID_SEED_MODE=false node server.js
```

### Federation Sync Fails

**Problem:** `Invalid federation signature`

**Fix:** 
1. Verify both peers have the same shared secret configured
2. Check that clocks are synchronized (signatures expire after 5 minutes)
3. Ensure the peer URL is reachable from your server

### Auth Errors in Production

**Problem:** `Invalid API key`

**Fix:**
1. Create a new key: `POST /gateway/key/create`
2. Use it in the `Authorization: Bearer <key>` header
3. Verify the key hasn't expired

**Problem:** `Need admin` or `Need architect`

**Fix:** Your API key doesn't have sufficient permissions. Create a new key with the required permission level.

### Constitution Rules Not Blocking

**Problem:** Writes pass even though constitution is in `block` mode.

**Fix:**
1. Verify the constitution was registered for the correct workspace
2. Check that `X-Grid-Workspace` header is sent with write requests
3. Constitutions are workspace-scoped — rules in workspace A don't apply to workspace B

### Contracts Not Validating

**Problem:** Writes pass even though a contract exists.

**Fix:**
1. Contracts match by tag scope — verify your entry tags match the contract scope
2. Contract scopes support wildcards: `topic:*` matches any `topic:*` tag
3. Check enforce mode — `validate` mode warns but doesn't block

### Rate Limiting

**Problem:** `Rate limit exceeded`

**Fix:** Wait one minute and retry. Rate limits reset every 60 seconds. Reduce request frequency.

### Audit Hash Chain Broken

**Problem:** `/gateway/audit/verify` returns `valid: false`

**Fix:** The audit log has been tampered with. Investigate immediately:
1. Check which entry index is broken
2. Look for unexpected changes to the audit file
3. Restore from backup if available

---

## 13. Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                    Grid Memory Server (server.js)                     │
│                                                                       │
│  ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐           │
│  │ Router  │→│ Gateway  │→│ Workspace│→│ Features  │           │
│  │ (handle)│  │ (auth)   │  │ (isolation│  │           │           │
│  └─────────┘  └──────────┘  └──────────┘  └────────────┘           │
│                                                   ↓                   │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    Feature Modules                             │   │
│  │  ┌────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐        │   │
│  │  │Write/  │ │Contracts │ │Constit-  │ │Federation  │        │   │
│  │  │Query   │ │(schemas) │ │ution     │ │(peers)     │        │   │
│  │  └────────┘ │          │ │(policies)│ └────────────┘        │   │
│  │             └──────────┘ └──────────┘                        │   │
│  │  ┌────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐        │   │
│  │  │MIKE    │ │Decision  │ │QBR       │ │Amnesia     │        │   │
│  │  │Dashboard│ │Graph     │ │Generator │ │Detector    │        │   │
│  │  └────────┘ └──────────┘ └──────────┘ └────────────┘        │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                                                   ↓                   │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │                    Storage Layer                               │   │
│  │                       ↓                                        │   │
│  │            ┌────────────────────┐                              │   │
│  │            │  reference/store.js│                              │   │
│  │            │  (append-only JSON)│                              │   │
│  │            ├────────────────────┤                              │   │
│  │            │  governance-db.js  │                              │   │
│  │            │  (SQLite via       │                              │   │
│  │            │   better-sqlite3)  │                              │   │
│  │            └────────────────────┘                              │   │
│  │              ↓                  ↓                               │   │
│  │     store.json          governance.db                          │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────┐
│              Python SDK / Client                           │
│  grid_memory.LocalGrid → HTTP calls to server             │
│  grid_memory.GridFederation → federation management       │
└──────────────────────────────────────────────────────────┘
```

### Request Flow

Every request to the Grid server flows through this pipeline:

```
1. CORS check           → Handle OPTIONS preflight
2. Gateway endpoints?   → Handle key management, audit, PII scan
3. Auth check           → (if GRID_ENFORCE_AUTH=true) authenticate + authorize
4. Route matching       → Match method + URL to handler
5. Operation            → Execute the feature logic
6. Audit log            → Log the operation to tamper-evident audit trail
7. Response             → Return JSON result
```

### Data Flow: Write

```
Agent → POST /write
  → Gateway auth (if enabled)
  → Contract validation (schema check)
  → Constitution validation (policy check)
  → Dedup check (if enabled)
  → Conflict detection (if enabled)
  → Provenance tracking
  → Store.append(entry)
  → Audit.log("write", agent_id, entry_id)
  → Response: { entry_id, created_at, ttl_expires_at }
```

### Data Flow: Read

```
Agent → GET /query
  → Gateway auth (if enabled)
  → Workspace scoping (auto-add ws: tag)
  → Store.read(tags, agents, type, max, since, before)
  → Relevance weighting (tag match > type match > recency)
  → TTL filtering (skip expired entries)
  → Response: { entries: [...], query_meta: { ... } }
```

---

## Quick Reference Card

```bash
# ─── Server ───
node server.js                                    # Start server on :8080
PORT=9090 node server.js                          # Custom port
GRID_SEED_MODE=false node server.js               # Disable auto-seed
GRID_ENFORCE_AUTH=true node server.js             # Enable auth

# ─── Writing ───
curl -X POST /write -d '{"agent_id":"a","type":"decision","content":"c","tags":["t"]}'

# ─── Reading ───
curl /query?tags=topic:database
curl /query?agents=arch-agent&type=decision&max=10

# ─── Contracts ───
curl -X POST /contracts -d '{"scope":"t:db","schema":{"db":"string"}}'
curl /auto-contracts
curl -X POST /auto-contracts/approve -d '{"scope":"t:db","suggested_schema":{...}}'

# ─── Constitutions ───
curl -X POST /constitution/from-text -d '{"text":"Never store API keys"}'
curl -X POST /constitution -H "X-Grid-Workspace: default" -d '{"rules":[...]}'

# ─── Federation ───
curl -X POST /federation/peers (or /federation/quick-connect) -d '{"peerUrl":"http://other:8080"}'
curl -X POST /federation/peers -d '{"url":"http://other:8080","trustLevel":"verified","sharedSecret":"..."}'

# ─── Business ───
curl /roi
curl /mike/dashboard
curl /executive/dashboard
curl /decisions/graph
curl /qbr
curl /amnesia/detect

# ─── Security ───
curl -X POST /gateway/key/create -d '{"label":"admin","permission":"admin"}'
curl /gateway/audit
curl /gateway/audit/verify
```

---

## 14. Route Authorization

> All endpoints are registered with mandatory permission levels. Auth is structural, not per-endpoint.

### MIKE Intelligence Endpoints (require `analyst`+)

| Endpoint | Required Permission | Rate Limit |
|----------|-------------------|------------|
| `GET /roi` | analyst | 30/min |
| `GET /mike/dashboard` | analyst | 20/min |
| `GET /executive/dashboard` | analyst | 10/min |
| `GET /decisions/graph` | analyst | 20/min |
| `GET /decisions/stats` | analyst | 20/min |
| `GET /qbr` | analyst | 15/min |
| `POST /qbr/generate` | analyst | 15/min |
| `GET /amnesia/detect` | analyst | 15/min |
| `POST /setup-wizard` | admin | — |

### Management Endpoints

| Endpoint | Required Permission | Notes |
|----------|-------------------|-------|
| `POST /gateway/key/create` | admin | Requires GRID_ENFORCE_AUTH=true |
| `GET /gateway/keys` | admin | Lists all keys (masked) |
| `DELETE /gateway/key/revoke/:id` | admin | Revokes a key |
| `POST /gateway/key/rotate/:id` | admin | Replaces a key |
| `GET /gateway/audit` | admin | Audit log |
| `GET /gateway/audit/verify` | admin | Audit chain integrity |
| `POST /gateway/pii/scan` | admin | PII detection |

### Permission Levels

| Level | Access |
|-------|--------|
| `viewer` | Read-only queries, health checks |
| `analyst` | Viewer + write entries, dashboards, reports |
| `architect` | Analyst + manage contracts, constitutions |
| `executive` | Architect + manage keys, audit (gateway routes) |
| `admin` | Everything |

### Using Auth Headers

```bash
# With API key
curl http://localhost:8080/executive/dashboard \
  -H "Authorization: Bearer grid_a1b2c3d4e5f6..."
```

The executive dashboard HTML also supports API key auth via the key input field at the top of the page.

### Route Registry Architecture

Routes are registered via `route-registry.js`:

```javascript
const registry = new RouteRegistry();
registry.register('GET', '/roi', 'analyst', handler);
```

The `handle()` function checks the registry first. If a route matches, auth is enforced automatically before the handler runs. This means:
- New endpoints can't be added without declaring a permission level
- Dead code can't accumulate (old handlers are visible dead code)
- Auth is applied structurally, not by human memory
