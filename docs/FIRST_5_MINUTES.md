# Grid Memory — First 5 Minutes

> **From zero to "holy shit, this found something valuable" in under 5 minutes.**

---

## Minute 1: Install

```bash
# Start the server (already in grid-memory/)
node server.js
```

You'll see:
```
Seed mode (auto): 8 entries from 3 agents
```

That means demo data is loaded automatically. You're already running.

## Minute 2: Open the Dashboard

Open your browser to:

```
http://localhost:8080/dashboard
```

This is the **Executive Dashboard**. It shows:
- How many entries and agents are in your Grid
- Revenue and pipeline value
- Win rate and amnesia score
- Active opportunities by stage
- Risks and alerts
- Recent decisions

No configuration needed. The demo data makes it work immediately.

## Minute 3: See What MIKE Found

The demo data includes a **deliberate contradiction** — two agents made opposing decisions about the database:

- **arch-agent** says: "Primary database should be MongoDB for schema flexibility"
- **ops-agent** says: "Primary database must use PostgreSQL"

MIKE detected this as a contradiction. You can see it in the dashboard under risks.

**This is the core value proposition:** Without anyone noticing, two agents made opposite decisions. MIKE caught it immediately.

## Minute 4: See Your ROI

```bash
curl http://localhost:8080/roi
```

MIKE tells you:
- Duplicates prevented
- Contradictions detected
- Opportunities found
- Time saved estimate

This is not a demo number. This is calculated from your actual data.

## Minute 5: Generate a QBR

```bash
curl http://localhost:8080/qbr
```

You just generated a Quarterly Business Review that would take a consultant 20+ hours to build manually.

## What to Do Next

### Replace the Demo Data

The demo data is just for exploration. To use your real data:

```bash
# Write your first real entry
curl -X POST http://localhost:8080/write \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"my-agent","type":"decision","content":"PostgreSQL for production. Rationale: ACID compliance, team expertise.","tags":["topic:database","project:my-project"]}'

# Read it back
curl "http://localhost:8080/query?tags=topic:database"

# See updated ROI
curl http://localhost:8080/roi
```

### Explore Advanced Features

| Feature | How |
|---------|-----|
| Memory Contracts | `POST /contracts` — enforce schemas |
| Constitutions | `POST /constitution/from-text` — natural language policies |
| Federation | `POST /federation/quick-connect` — connect Grids |
| Amnesia Detection | `GET /amnesia/detect` — find knowledge gaps |
| Executive Dashboard | Open `http://localhost:8080/dashboard` |
| Decision Graph | `GET /decisions/graph` — see every decision mapped |
| QBR Generation | `GET /qbr` — instant quarterly reports |

### Connect Your Agents

If you're using an agent framework (LangGraph, CrewAI, AutoGen):

```javascript
// Before spawning a subagent, inject context:
const context = await fetch('http://localhost:8080/inject?context=working%20on%20database%20migration');
// Insert the response into your subagent's system prompt

// When the subagent finishes, write its output:
await fetch('http://localhost:8080/write', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    agent_id: 'subagent-name',
    type: 'decision',
    content: 'Selected PostgreSQL. Rationale: ACID compliance.',
    tags: ['topic:database', 'project:my-project']
  })
});
```

### Set Up Authentication (Production)

```bash
GRID_ENFORCE_AUTH=true node server.js
curl -X POST http://localhost:8080/gateway/key/create \
  -H "Content-Type: application/json" \
  -d '{"label":"admin","permission":"admin"}'
# Save the returned key — it's shown only once
```

Then use it in every request:

```bash
curl http://localhost:8080/executive/dashboard \
  -H "Authorization: Bearer grid_a1b2c3d4e5f6..."
```

---

*You've now experienced the full Grid Memory flow: install → explore → create value — in under 5 minutes.*
*Everything else is depth.*
