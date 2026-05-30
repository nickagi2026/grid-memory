# Real Data Onboarding Guide

> **⚠️ Auth Note:** The examples below assume `GRID_ENFORCE_AUTH=false` (development mode).
> In production, add `-H "Authorization: Bearer YOUR_API_KEY"` to every curl command.
> See [How Authorization Works](HOW_AUTHORIZATION_WORKS.md) for details.

> You've explored the demo data and seen what Grid Memory can do.
> Now let's load your real data and generate real value.

---

## Step 1: Import Your First 50 Decisions

### Option A: API (for automated imports)

```bash
# Prepare a JSON file with your entries
cat > my-decisions.json << 'JSON'
{
  "entries": [
    {
      "agent_id": "cto",
      "type": "decision",
      "content": "Migrate to PostgreSQL. Rationale: ACID compliance, team expertise.",
      "tags": ["topic:database", "project:infra", "ws:my-company"]
    },
    {
      "agent_id": "pm",
      "type": "decision",
      "content": "Adopt Agile methodology. Rationale: faster iterations, team preference.",
      "tags": ["topic:process", "project:infra", "ws:my-company"]
    }
  ]
}
JSON

# Import via API
curl -X POST http://localhost:8080/import \
  -H "Content-Type: application/json" \
  -d @my-decisions.json
```

### Option B: Direct write (for individual entries)

```bash
curl -X POST http://localhost:8080/write \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "cto",
    "type": "decision",
    "content": "Use PostgreSQL for primary storage. Rationale: ACID compliance.",
    "tags": ["topic:database", "project:infra"]
  }'
```

---

## Step 2: Tag Your Data Properly

Tags are how Grid Memory organizes information. Follow these conventions:

| Tag Prefix | Purpose | Example |
|-----------|---------|---------|
| `topic:` | Subject area | `topic:database`, `topic:security` |
| `project:` | Project identifier | `project:alpha`, `project:infra-migration` |
| `ws:` | Workspace/client | `ws:client-acme`, `ws:my-company` |
| `stage:` | Pipeline stage | `stage:detected`, `stage:won` |
| `client:` | Client name | `client:acme-corp` |

**Best practice:** Every entry should have at least one `topic:` tag plus a `ws:` tag if you're using workspaces.

---

## Step 3: See Your Instant ROI

```bash
curl http://localhost:8080/roi
```

This shows:
- Duplicates prevented (entries you might have created twice)
- Contradictions detected (conflicting decisions made by different agents)
- Opportunities found (potential revenue signals)
- Decisions tracked
- Time saved estimate

---

## Step 4: Generate Your First QBR

```bash
curl http://localhost:8080/qbr
```

This generates a complete Quarterly Business Review:
- Executive summary
- KPIs and metrics
- Strategic decisions made
- Opportunity pipeline
- Risks and contradictions detected
- Recommendations for next quarter

A QBR that would take a consultant 20+ hours to prepare, delivered in under a second.

---

## Step 5: Check for Organizational Amnesia

```bash
curl http://localhost:8080/amnesia/detect
```

MIKE will tell you:
- Knowledge gaps (topics not discussed in 30+ days)
- Orphaned decisions (decisions made but never acted upon)
- Stale decisions (older than 60 days without review)
- Single points of failure (knowledge held by only one person/agent)

---

## Step 6: Explore Your Decision Graph

```bash
curl http://localhost:8080/decisions/graph
```

See every decision mapped with its rationale, outcomes, and linked entries.

```bash
curl http://localhost:8080/decisions/stats
```

See who the most effective decision-makers are and what patterns lead to success.

---

## Step 7: Open the Executive Dashboard

Open your browser to:

```
http://localhost:8080/dashboard
```

The dashboard shows:
- **KPIs**: Total entries, agents, revenue, pipeline value, win rate
- **Opportunities**: Every detected opportunity by stage
- **Risks**: Knowledge gaps, orphaned decisions, stale decisions, SPOFs
- **Recent Decisions**: What was decided and by whom
- **Quick Actions**: One-click access to all features

---

## Step 8: Replace the Demo Data

When you're ready to start fresh:

```bash
# Option A: Delete existing data and start fresh
rm -rf ~/.openclaw/grid/data
GRID_SEED_MODE=false node server.js

# Option B: Keep demo data as a reference layer
# Just add your real data alongside it — the dashboard shows everything
```

---

## What's Next?

| Feature | How |
|---------|-----|
| **Memory Contracts** | Enforce data schemas with `POST /contracts` |
| **Constitutions** | Set policies with `POST /constitution/from-text` |
| **Federation** | Connect Grid instances with `POST /federation/peers` |
| **Amnesia Monitoring** | Run `GET /amnesia/detect` weekly |
| **QBR Automation** | Run `GET /qbr` at the end of each quarter |
| **Executive Reviews** | Open `/dashboard` daily |

---

*You've gone from demo to real value in under 10 minutes.*
*The rest is depth. Explore the docs for advanced features.*
