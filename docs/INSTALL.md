# Grid Memory — Installation Guide

Grid Memory runs on **Node.js 18+**. Python 3.8+ is optional (for the SDK).


> **Publication Status:**
> - **npm**: `grid-memory` — pre-release, not yet published
> - **PyPI**: `grid-memory` — pre-release, not yet published
> - **GitHub**: Private repository — public launch planned
> - **Docker**: Build locally via `docker build -t grid-memory .`

## Quick Start (Node.js)

```bash
# Clone or copy the Grid directory
git clone <repo-url> grid-memory
cd grid-memory

# Install dependencies
npm install

# Start the server
node server.js
```

The server starts on port 8080 with demo mode enabled. You'll see:

```
Grid Memory Server
Listening on http://0.0.0.0:8080
Seed mode (auto): 8 entries from 3 agents
```

## Quick Start (Docker)

> Docker image coming soon. For now, build locally:

```bash
# Build from source
cd grid-memory
docker build -t grid-memory .
docker run -d -p 8080:8080 -v grid-data:/data grid-memory
curl http://localhost:8080/health
```

## Quick Start (Python SDK)

```bash
# From the SDK directory
cd sdk/python
pip install -e .

# # pip install grid-memory (pre-release) 
```

## Verifying the Installation

```bash
# Health check
curl http://localhost:8080/health

# Open the dashboard in your browser
open http://localhost:8080/dashboard
```

Both commands should return JSON. If they do, the Grid is running.

## Production Deployment

1. Set `GRID_ENFORCE_AUTH=true`
2. Create an admin API key:
   ```bash
   curl -X POST http://localhost:8080/gateway/key/create \
     -H "Content-Type: application/json" \
     -d '{"label":"admin","permission":"admin"}'
   ```
3. Create workspaces per client:
   ```bash
   curl -X POST http://localhost:8080/write \
     -H "Content-Type: application/json" \
     -H "X-Grid-Workspace: client-acme" \
     -d '{"agent_id":"setup","type":"fact","content":"Workspace initialized","tags":["ws:client-acme"]}'
   ```
4. Start with the built-in SQLite backend, upgrade to PostgreSQL when needed.

## System Requirements

- Node.js 18+
- Python 3.8+ (optional, for SDK)
- 100 MB disk for server, 1 GB+ recommended for active stores
- SQLite default, PostgreSQL 14+ for production deployments

## Configuration Reference

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `PORT` | 8080 | HTTP server port |
| `HOST` | 0.0.0.0 | HTTP server host |
| `GRID_STORE_DIR` | `~/.openclaw/grid` | Data directory |
| `GRID_SEED_MODE` | `true` | Auto-seed demo data on first launch |
| `GRID_ENFORCE_AUTH` | `false` | Enable API key authentication |
| `GRID_ENCRYPTION_KEY` | auto-generated | Key for audit hash chaining |
| `GRID_MAX_BODY_SIZE` | 1048576 | Max request body in bytes |
| `GRID_WORKSPACE` | `''` | Default workspace |
