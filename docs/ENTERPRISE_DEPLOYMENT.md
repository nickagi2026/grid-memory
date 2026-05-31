# Grid Memory — Enterprise Deployment Guide

## Architecture Overview

Production deployments should use the PostgreSQL backend behind a reverse proxy.

```
┌─────────────┐     ┌──────────┐     ┌──────────────┐
│  Clients    │────▶│  Reverse │────▶│  Grid Server  │
│  (agents,   │     │  Proxy   │     │  (Node.js)    │
│   SDKs,     │     │ (nginx,  │     │  port 8080    │
│   dashboards)│    │  Caddy)  │     └──────┬───────┘
└─────────────┘     └──────────┘            │
                                   ┌───────┴────────┐
                                   │  PostgreSQL     │
                                   │  14+            │
                                   └────────────────┘
```

## Prerequisites

- **Node.js 20+** (LTS recommended)
- **PostgreSQL 14+** with SSL
- **Reverse proxy** (nginx, Caddy, or Cloudflare)
- **1 GB RAM minimum**, 4 GB recommended
- **10 GB disk** for audit logs + metadata

## Step 1 — PostgreSQL Setup

```bash
# Create database and user
CREATE DATABASE grid_memory;
CREATE USER grid_admin WITH ENCRYPTED PASSWORD 'strong-password';
GRANT ALL PRIVILEGES ON DATABASE grid_memory TO grid_admin;

# Enable pgcrypto for encryption functions
CREATE EXTENSION IF NOT EXISTS pgcrypto;

# Recommended settings in postgresql.conf
# shared_buffers = '256MB'
# work_mem = '64MB'
# effective_cache_size = '1GB'
# wal_level = 'replica'              # for replication
# max_replication_slots = '2'        # if using read replicas
```

## Step 2 — Grid Server Configuration

```bash
# Core settings
export GRID_ENFORCE_AUTH=true
export GRID_BACKEND=postgres
export DATABASE_URL=postgresql://grid_admin:strong-password@localhost:5432/grid_memory
export GRID_POSTGRES_SSL=true

# Optional: connection pooling
export GRID_PG_POOL_MIN=5
export GRID_PG_POOL_MAX=20

# Audit key (auto-generated if not set, but set it explicitly for production)
export GRID_AUDIT_KEY=$(openssl rand -hex 32)

# Rate limiting
export GRID_RATE_LIMIT_MAX=200          # global rate limit per IP
export GRID_RATE_LIMIT_WRITE=50         # writes per minute
export GRID_RATE_LIMIT_AUTH_ATTEMPTS=10 # failed auth attempts per minute

# CORS (restrict for production)
export GRID_ALLOWED_ORIGINS=https://your-domain.com

# Start
node server.js
```

## Step 3 — Reverse Proxy (nginx)

```nginx
server {
    listen 443 ssl;
    server_name grid.example.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    # Security headers
    add_header Strict-Transport-Security "max-age=63072000" always;
    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options DENY;
    add_header X-XSS-Protection "1; mode=block";

    # Rate limiting
    limit_req_zone $binary_remote_addr zone=grid:10m rate=100r/s;
    limit_req zone=grid burst=200 nodelay;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket support (for SSE subscriptions)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

## Step 4 — API Key Management

```bash
# Create admin key
curl -X POST https://grid.example.com/gateway/key/create \
  -H "Authorization: Bearer <master-key>" \
  -d '{"label":"admin-key","permission":"admin","workspace":"*"}'

# Create workspace-scoped keys
curl -X POST https://grid.example.com/gateway/key/create \
  -H "Authorization: Bearer <admin-key>" \
  -d '{"label":"client-acme","permission":"analyst","workspace":"client-acme"}'

# Rotate keys regularly
curl -X POST https://grid.example.com/gateway/key/rotate/key_a1b2c3d4 \
  -H "Authorization: Bearer <admin-key>"
```

## Step 5 — Backup & Recovery

```bash
# PostgreSQL backup
pg_dump -U grid_admin grid_memory > grid_backup_$(date +%Y%m%d).sql

# Audit log backup (JSON file)
cp ~/.openclaw/audit/audit.json audit_backup_$(date +%Y%m%d).json

# Automated backup script
cat > /etc/cron.daily/grid-backup << 'SCRIPT'
#!/bin/bash
BACKUP_DIR=/backups/grid
mkdir -p $BACKUP_DIR
pg_dump -U grid_admin grid_memory | gzip > $BACKUP_DIR/grid_$(date +%Y%m%d).sql.gz
find $BACKUP_DIR -name "grid_*.sql.gz" -mtime +90 -delete
SCRIPT
chmod +x /etc/cron.daily/grid-backup
```

## Step 6 — Monitoring

```bash
# Health check endpoint
curl https://grid.example.com/health

# Audit trail verification
curl https://grid.example.com/gateway/audit/verify

# Store statistics
curl https://grid.example.com/info

# Prometheus metrics (if using OpenTelemetry)
curl https://grid.example.com/metrics
```

## Scaling

| Scale | Users | Recommendations |
|-------|-------|-----------------|
| Small | 1-10 | Single server, SQLite, cron backup |
| Medium | 10-100 | PostgreSQL, reverse proxy, daily backups |
| Large | 100-1000 | PostgreSQL cluster, read replicas, connection pooling |
| Enterprise | 1000+ | Horizontal sharding by workspace, CDN for dashboard assets |

## Security Checklist

- [ ] `GRID_ENFORCE_AUTH=true`
- [ ] TLS enabled via reverse proxy
- [ ] API keys rotated every 90 days
- [ ] Audit trail verification automated (weekly)
- [ ] PII scanning enabled on write endpoints
- [ ] Rate limiting configured per endpoint
- [ ] Workspace isolation verified with test suite
- [ ] PostgreSQL SSL enforced
- [ ] Backup tested with restore drill
- [ ] Failed auth attempt monitoring

## Troubleshooting

**Server won't start with PostgreSQL:**
```bash
# Check database connection
node -e "require('./enterprise/dbops.js').testConnection()"

# Verify DATABASE_URL format
echo $DATABASE_URL
# Should be: postgresql://user:password@host:5432/dbname
```

**Audit chain broken:**
```bash
curl https://grid.example.com/gateway/audit/verify
# Returns: { "valid": false, "brokenAtIndex": N }
# → Check who modified the audit.json file at that timestamp
```

**Rate limiting too aggressive:**
```bash
# Increase limit per endpoint
export GRID_RATE_LIMIT_DASHBOARD=50   # default 20
export GRID_RATE_LIMIT_QBR=30          # default 15
```
