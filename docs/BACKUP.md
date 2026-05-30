# Grid Memory — Backup & Restore Guide

## Automated Backups

```bash
# Start auto-backup (every 24h)
grid db auto-backup --interval 24

# Stop auto-backup
grid db auto-backup --stop
```

## Manual Backup

```bash
# Create backup with label
grid db backup --label "weekly-2026-05-29"

# List all backups
grid db backup-list

# Restore from backup (dry run first)
grid db restore <backup_name> --dry-run
grid db restore <backup_name>
```

## Archive Old Data

```bash
# Archive entries older than 365 days
grid db archive --days 365

# Archive and remove from active store
grid db archive --days 365 --delete
```

## Export/Import

```bash
# API export (requires auth when enabled)
GET /export

# API import (requires admin auth when enabled)
POST /import
Content-Type: application/json
{
  "entries": [...]
}

# CLI export/import
grid export --output backup.json
grid import --file backup.json
```

## Disaster Recovery

1. Stop the Grid server
2. Restore the store file from backup
3. Restart the server
4. Verify integrity: `grid db status`
