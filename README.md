# Grid Memory

Grid Memory catches the things your AI agents forget.

Shared persistent memory for multi-agent teams. Any agent writes. Any agent reads.
The Grid remembers — and tells you when something has been forgotten, contradicted,
or lost.

## Quick Start

```bash
npm install grid-memory
node server.js
```

Or Python:
```bash
cd sdk/python
pip install -e .
```

---

## What's Free

| Feature | Community | Enterprise |
|---------|-----------|------------|
| Memory Engine (write, read, inject, TTL) | ✓ Free | ✓ |
| Conflict Detection | ✓ Free | ✓ |
| Amnesia Detection | ✓ Free | ✓ |
| Decision Graph | ✓ Free | ✓ |
| Developer ROI metrics | ✓ Free | ✓ |
| Governance (contracts, constitutions) | ✓ Free | ✓ |
| Federation | ✓ Free | ✓ |
| OpenAI-compatible proxy | ✓ Free | ✓ |
| **Executive Dashboard** | — (returns 402) | ✓ MIKE |
| **QBR Generator** | — (returns 402) | ✓ MIKE |
| **Portfolio Analytics** | — (returns 402) | ✓ MIKE |
| Semantic Search | — | ✓ Enterprise |
| Native Connectors | — | ✓ Enterprise |
| SSO / SAML | — | ✓ Enterprise |
| PostgreSQL Backend | — | ✓ Enterprise |

## What's Enterprise

Executive Dashboard, QBR Generator, Portfolio Analytics,
Opportunity Pipeline, Board Reporting — [gridmemory.io/enterprise](https://gridmemory.io/enterprise)

PostgreSQL backend, SSO/SAML, advanced audit retention,
SLA + support — [gridmemory.io/enterprise](https://gridmemory.io/enterprise)

---

## The Three Layers

### Layer 1: Memory Engine
The append-only, tamper-evident store. Every entry is timestamped, tagged, and never overwritten.

- Write decisions, facts, observations via API
- Query with relevance-weighted retrieval
- TTL-based expiry for stale data
- Context injection for subagents (max 4KB)

### Layer 2: Governance
Policies, contracts, federation, and security that control how memory is used.

- **Memory Contracts** — schema enforcement (type checking for memory)
- **Constitutions** — natural-language policy rules ("Never store API keys")
- **Federation** — sync Grid instances across teams or data centers
- **Audit Trail** — HMAC-SHA256 hash chaining for tamper evidence
- **PII Detection** — automatic SSN, credit card, email scanning

### Layer 3: Intelligence (MIKE)
Business intelligence derived from your organization's memory.

- **Opportunity Engine** — continuously surfaces revenue opportunities
- **Decision Graph** — maps every decision to its outcome
- **QBR Generator** — quarterly business reviews in seconds
- **Amnesia Detector** — finds knowledge gaps before they become crises
- **Executive Dashboard** — one screen showing everything that matters

---

## Documentation

| Document | Audience | What It Covers |
|----------|----------|---------------|
| [**Real Data Onboarding**](docs/REAL_DATA_ONBOARDING.md) | Everyone | Import your data, generate QBR, see ROI |
|----------|----------|---------------|
| [**Complete Guide**](docs/COMPREHENSIVE_GUIDE.md) | Everyone | Installation, every feature, API reference, architecture |
| [**Intelligence Layer Guide**](docs/MIKE_BUSINESS_GUIDE.md) | Executives, consultants | Business value, ROI, opportunity engine, decision intelligence |
| [**Installation**](docs/INSTALL.md) | DevOps | Quick install, Docker, Python pip |
| [**Security**](docs/SECURITY.md) | Security teams | Authentication, API keys, PII detection, audit |

---

## Quick Start

```bash

> **Package Status:**
> - **npm**: ✅ Published — `npm install grid-memory`
> - **PyPI**: ✅ Published — `pip install grid-memory`
> - **Docker**: ⏳ Pending
> - **Enterprise (MIKE + Connectors + Semantic Search)**: 🔒 Private — contact nick@criticalpathfoundry.com


# Start the server
cd grid-memory
node server.js

# Write your first entry
curl -X POST http://localhost:8080/write \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"my-agent","type":"decision","content":"Use PostgreSQL. Rationale: ACID compliance.","tags":["topic:database"]}'

# Read it back
curl "http://localhost:8080/query?tags=topic:database"

# See your business intelligence
curl http://localhost:8080/roi
curl http://localhost:8080/executive/dashboard
```

## API at a Glance

| What | Endpoint |
|------|----------|
| Write memory | `POST /write` |
| Query memory | `GET|POST /query` |
| Inject context | `GET|POST /inject` |
| Register contract | `POST /contracts` |
| Natural-language policy | `POST /constitution/from-text` |
| One-click federation | `POST /federation/quick-connect` |
| Executive dashboard | `GET /executive/dashboard` |
| Decision graph | `GET /decisions/graph` |
| QBR generation | `GET /qbr` |
| Amnesia detection | `GET /amnesia/detect` |
| Audit verification | `GET /gateway/audit/verify` |

## Requirements

- **Node.js 18+**
- **Python 3.8+** (optional, for SDK)
- Disk: 100MB minimum, 1GB recommended

---

*Grid Memory — the append-only, tamper-evident memory layer for multi-agent teams.*
