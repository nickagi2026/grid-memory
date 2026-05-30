"""
migrations.py — Database migration manager for PostgreSQL and SQLite.

Supports versioned schema migrations with rollback support.
Tracks applied migrations in a `_migrations` table.
"""

import datetime
import json
import os
import re
from typing import Dict, List, Optional, Any


# ─── Migration Definitions ─────────────────────────────────────────────────────

MIGRATIONS = [
    {
        "version": 1,
        "name": "initial_schema",
        "description": "Create entries, tags_index, and audit tables",
        "sqlite": """
            CREATE TABLE IF NOT EXISTS entries (
                id TEXT PRIMARY KEY, session_id TEXT DEFAULT '', agent_id TEXT NOT NULL,
                type TEXT NOT NULL, tags TEXT DEFAULT '[]', content TEXT NOT NULL,
                ttl_seconds INTEGER DEFAULT 86400, created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL, parent_entry TEXT, last_read_at TEXT,
                embedding TEXT, memory_tier TEXT DEFAULT 'working',
                read_count INTEGER DEFAULT 0, promoted_from TEXT
            );
            CREATE TABLE IF NOT EXISTS tags_index (tag TEXT, entry_id TEXT, PRIMARY KEY(tag, entry_id));
            CREATE INDEX IF NOT EXISTS idx_expires ON entries(expires_at);
            CREATE INDEX IF NOT EXISTS idx_agent ON entries(agent_id);
            CREATE INDEX IF NOT EXISTS idx_type ON entries(type);
            CREATE INDEX IF NOT EXISTS idx_tier ON entries(memory_tier);
        """,
        "postgresql": """
            CREATE TABLE IF NOT EXISTS entries (
                id TEXT PRIMARY KEY, session_id TEXT DEFAULT '', agent_id TEXT NOT NULL,
                type TEXT NOT NULL, tags JSONB DEFAULT '[]', content TEXT NOT NULL,
                ttl_seconds INTEGER DEFAULT 86400,
                created_at TIMESTAMPTZ DEFAULT NOW(), expires_at TIMESTAMPTZ NOT NULL,
                parent_entry TEXT, last_read_at TIMESTAMPTZ,
                embedding TEXT, memory_tier TEXT DEFAULT 'working',
                read_count INTEGER DEFAULT 0, promoted_from TEXT
            );
            CREATE TABLE IF NOT EXISTS tags_index (tag TEXT, entry_id TEXT REFERENCES entries(id) ON DELETE CASCADE, PRIMARY KEY(tag, entry_id));
            CREATE INDEX IF NOT EXISTS idx_expires ON entries(expires_at);
            CREATE INDEX IF NOT EXISTS idx_agent ON entries(agent_id);
            CREATE INDEX IF NOT EXISTS idx_type ON entries(type);
            CREATE INDEX IF NOT EXISTS idx_tier ON entries(memory_tier);
        """,
    },
    {
        "version": 2,
        "name": "audit_and_keys",
        "description": "Create audit_log and api_keys tables",
        "sqlite": """
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
                action TEXT NOT NULL, result TEXT DEFAULT 'allowed',
                method TEXT DEFAULT '', path TEXT DEFAULT '', workspace TEXT DEFAULT '',
                actor TEXT DEFAULT 'anonymous', key_id TEXT DEFAULT '',
                ip TEXT DEFAULT '', detail TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS api_keys (
                key_id TEXT PRIMARY KEY, key_hash TEXT NOT NULL,
                label TEXT DEFAULT '', workspace TEXT DEFAULT '*',
                permission TEXT DEFAULT 'read', created_at TEXT NOT NULL,
                expires_at TEXT, last_used TEXT, enabled INTEGER DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(timestamp);
            CREATE INDEX IF NOT EXISTS idx_audit_ws ON audit_log(workspace);
        """,
        "postgresql": """
            CREATE TABLE IF NOT EXISTS audit_log (
                id SERIAL PRIMARY KEY, timestamp TIMESTAMPTZ DEFAULT NOW(),
                action TEXT NOT NULL, result TEXT DEFAULT 'allowed',
                method TEXT DEFAULT '', path TEXT DEFAULT '', workspace TEXT DEFAULT '',
                actor TEXT DEFAULT 'anonymous', key_id TEXT DEFAULT '',
                ip TEXT DEFAULT '', detail TEXT DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS api_keys (
                key_id TEXT PRIMARY KEY, key_hash TEXT NOT NULL,
                label TEXT DEFAULT '', workspace TEXT DEFAULT '*',
                permission TEXT DEFAULT 'read', created_at TIMESTAMPTZ DEFAULT NOW(),
                expires_at TIMESTAMPTZ, last_used TIMESTAMPTZ, enabled INTEGER DEFAULT 1
            );
            CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(timestamp);
        """,
    },
    {
        "version": 3,
        "name": "enterprise_indexes",
        "description": "Additional indexes for enterprise queries",
        "sqlite": """
            CREATE INDEX IF NOT EXISTS idx_entries_created ON entries(created_at);
            CREATE INDEX IF NOT EXISTS idx_entries_parent ON entries(parent_entry);
            CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags_index(tag);
            CREATE INDEX IF NOT EXISTS idx_api_ws ON api_keys(workspace);
        """,
        "postgresql": """
            CREATE INDEX IF NOT EXISTS idx_entries_created ON entries(created_at);
            CREATE INDEX IF NOT EXISTS idx_entries_parent ON entries(parent_entry);
            CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags_index(tag);
            CREATE INDEX IF NOT EXISTS idx_api_ws ON api_keys(workspace);
        """,
    },
]


class MigrationManager:
    """Manages database schema migrations.

    Args:
        db_type: 'sqlite' or 'postgresql'
        db_path: Path for SQLite, or connection string for PostgreSQL
    """

    def __init__(self, db_type: str = "sqlite", db_path: str = "./grid.db"):
        self.db_type = db_type
        self.db_path = db_path

    def get_current_version(self) -> int:
        """Get the current schema version from the database."""
        try:
            if self.db_type == "sqlite":
                import sqlite3
                conn = sqlite3.connect(self.db_path)
                try:
                    row = conn.execute("SELECT version FROM _migrations ORDER BY version DESC LIMIT 1").fetchone()
                    return row[0] if row else 0
                except Exception:
                    return 0
                finally:
                    conn.close()
            else:
                import psycopg2
                conn = psycopg2.connect(self.db_path)
                try:
                    cur = conn.cursor()
                    cur.execute("SELECT version FROM _migrations ORDER BY version DESC LIMIT 1")
                    row = cur.fetchone()
                    return row[0] if row else 0
                except Exception:
                    return 0
                finally:
                    conn.close()
        except ImportError:
            return 0

    def migrate(self, target_version: Optional[int] = None) -> Dict:
        """Run migrations up to target_version (or latest).

        Returns:
            Dict with migration results
        """
        current = self.get_current_version()
        applied = []
        errors = []

        for m in MIGRATIONS:
            if m["version"] <= current:
                continue
            if target_version and m["version"] > target_version:
                break

            try:
                self._run_migration(m)
                applied.append(m["version"])
            except Exception as e:
                errors.append({"version": m["version"], "error": str(e)})
                break

        return {
            "from_version": current,
            "to_version": max(applied) if applied else current,
            "applied": applied,
            "errors": errors,
            "success": len(errors) == 0,
        }

    def _run_migration(self, migration: Dict):
        """Run a single migration."""
        sql_key = "sqlite" if self.db_type == "sqlite" else "postgresql"
        sql = migration.get(sql_key, migration.get("sqlite", ""))

        if not sql:
            return

        if self.db_type == "sqlite":
            import sqlite3
            conn = sqlite3.connect(self.db_path)
            try:
                conn.executescript(sql)
                # Create migrations tracking table if needed
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS _migrations (
                        version INTEGER PRIMARY KEY,
                        name TEXT NOT NULL,
                        applied_at TEXT NOT NULL
                    )
                """)
                conn.execute(
                    "INSERT OR IGNORE INTO _migrations (version, name, applied_at) VALUES (?, ?, ?)",
                    (migration["version"], migration["name"],
                     datetime.datetime.now(datetime.timezone.utc).isoformat())
                )
                conn.commit()
            finally:
                conn.close()
        else:
            import psycopg2
            conn = psycopg2.connect(self.db_path)
            try:
                cur = conn.cursor()
                cur.execute(sql)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS _migrations (
                        version INTEGER PRIMARY KEY,
                        name TEXT NOT NULL,
                        applied_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                cur.execute(
                    "INSERT INTO _migrations (version, name) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (migration["version"], migration["name"])
                )
                conn.commit()
            finally:
                conn.close()

    def status(self) -> Dict:
        """Get migration status."""
        current = self.get_current_version()
        return {
            "current_version": current,
            "latest_version": max(m["version"] for m in MIGRATIONS) if MIGRATIONS else 0,
            "pending": [m for m in MIGRATIONS if m["version"] > current],
            "total_migrations": len(MIGRATIONS),
        }

    def export_schema(self, output_path: str = "") -> str:
        """Export the full schema for a given db_type."""
        lines = [f"-- Grid Memory Schema ({self.db_type})", f"-- Generated: {datetime.datetime.now(datetime.timezone.utc).isoformat()}", ""]
        for m in sorted(MIGRATIONS, key=lambda x: x["version"]):
            sql_key = "sqlite" if self.db_type == "sqlite" else "postgresql"
            sql = m.get(sql_key, "")
            if sql:
                lines.append(f"-- Migration {m['version']}: {m['name']}")
                lines.append(sql)
                lines.append("")

        result = "\n".join(lines)
        if output_path:
            with open(output_path, "w") as f:
                f.write(result)
            return output_path
        return result


# ─── CLI Integration ───────────────────────────────────────────────────────────


def cmd_migrate(args):
    """Run database migrations."""
    db_type = args.db_type or "sqlite"
    db_path = args.db_path or "./grid.db"
    mgr = MigrationManager(db_type=db_type, db_path=db_path)

    action = args.m_action or "run"

    if action == "run":
        result = mgr.migrate()
        print(f"\n  Migration: {result['from_version']} → {result['to_version']}")
        print(f"  Applied: {result['applied']}")
        if result["errors"]:
            for e in result["errors"]:
                print(f"  Error on v{e['version']}: {e['error']}")
        print()

    elif action == "status":
        status = mgr.status()
        print(f"\n  Migration Status")
        print(f"  Current: {status['current_version']}")
        print(f"  Latest:  {status['latest_version']}")
        if status["pending"]:
            print(f"  Pending: {len(status['pending'])}")
            for m in status["pending"]:
                print(f"    v{m['version']}: {m['name']} — {m['description']}")
        else:
            print(f"  Up to date")
        print()

    elif action == "export":
        path = mgr.export_schema(output_path=args.output or "")
        print(f"\n  Schema exported to {path}\n")

    elif action == "apply":
        mgr = MigrationManager(db_type=db_type, db_path=db_path)
        result = mgr.migrate()
        print(f"  {result['to_version']}")
