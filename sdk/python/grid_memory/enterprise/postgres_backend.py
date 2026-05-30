"""
postgres_backend.py — PostgreSQL storage backend for production Grid deployments.

Drop-in replacement for SQLiteBackend with the same interface.
Requires: pip install psycopg2-binary

Usage:
    from grid_memory.enterprise.postgres_backend import PostgresBackend
    from grid_memory.local_grid import LocalGrid

    backend = PostgresBackend(
        host="db.example.com",
        port=5432,
        dbname="grid_memory",
        user="grid",
        password="***",
    )
    grid = LocalGrid(backend=backend)
"""

import datetime
import json
import os
from typing import Dict, List, Optional, Any, Tuple


class PostgresBackend:
    """PostgreSQL storage backend for Grid entries.

    Args:
        host: Database host
        port: Database port
        dbname: Database name
        user: Database user
        password: Database password
        min_connections: Minimum connection pool size
        max_connections: Maximum connection pool size
    """

    def __init__(self, host: str = "localhost", port: int = 5432,
                 dbname: str = "grid_memory", user: str = "grid",
                 password: str = "", min_connections: int = 1,
                 max_connections: int = 10):
        self._config = {
            "host": host,
            "port": port,
            "dbname": dbname,
            "user": user,
            "password": password,
            "min_connections": min_connections,
            "max_connections": max_connections,
        }
        self._pool = None
        self._init_pool()

    def _init_pool(self):
        """Initialize the connection pool."""
        try:
            from psycopg2 import pool
            self._pool = pool.ThreadedConnectionPool(
                self._config["min_connections"],
                self._config["max_connections"],
                host=self._config["host"],
                port=self._config["port"],
                dbname=self._config["dbname"],
                user=self._config["user"],
                password=self._config["password"],
            )
        except ImportError:
            raise ImportError(
                "PostgreSQL backend requires psycopg2. "
                "Install: pip install psycopg2-binary"
            )

        self._init_schema()

    def _init_schema(self):
        """Create tables if they don't exist."""
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            try:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            except Exception:
                pass

            cur.execute("""
                CREATE TABLE IF NOT EXISTS entries (
                    id          TEXT PRIMARY KEY,
                    session_id  TEXT NOT NULL DEFAULT '',
                    agent_id    TEXT NOT NULL,
                    type        TEXT NOT NULL,
                    tags        JSONB NOT NULL DEFAULT '[]',
                    content     TEXT NOT NULL,
                    ttl_seconds INTEGER NOT NULL DEFAULT 86400,
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    expires_at  TIMESTAMPTZ NOT NULL,
                    parent_entry TEXT,
                    last_read_at TIMESTAMPTZ,
                    embedding   TEXT,  -- JSON array or NULL; use vector extension for VECTOR(1536)
                    memory_tier TEXT NOT NULL DEFAULT 'working',
                    read_count  INTEGER NOT NULL DEFAULT 0,
                    promoted_from TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_entries_expires ON entries(expires_at);
                CREATE INDEX IF NOT EXISTS idx_entries_agent ON entries(agent_id);
                CREATE INDEX IF NOT EXISTS idx_entries_type ON entries(type);
                CREATE INDEX IF NOT EXISTS idx_entries_created ON entries(created_at);
                CREATE INDEX IF NOT EXISTS idx_entries_tier ON entries(memory_tier);

                CREATE TABLE IF NOT EXISTS tags_index (
                    tag      TEXT NOT NULL,
                    entry_id TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
                    PRIMARY KEY (tag, entry_id)
                );
                CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags_index(tag);

                -- Enable vector extension if available
                CREATE EXTENSION IF NOT EXISTS vector;
            """)
            conn.commit()
        finally:
            self._put_conn(conn)

    def _get_conn(self):
        """Get a connection from the pool."""
        return self._pool.getconn()

    def _put_conn(self, conn):
        """Return a connection to the pool."""
        self._pool.putconn(conn)

    def _row_to_dict(self, row) -> Dict:
        """Convert a DB row to a dict."""
        return dict(row)

    def write_entry(self, entry: Dict) -> Dict:
        """Insert an entry."""
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            tags_json = json.dumps(entry.get("tags", []))

            cur.execute("""
                INSERT INTO entries
                    (id, session_id, agent_id, type, tags, content,
                     ttl_seconds, created_at, expires_at, parent_entry,
                     last_read_at, memory_tier, read_count, promoted_from)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    last_read_at = EXCLUDED.last_read_at,
                    read_count = EXCLUDED.read_count
            """, (
                entry["id"], entry.get("session_id", ""), entry["agent_id"],
                entry["type"], tags_json, entry["content"],
                entry["ttl_seconds"], entry["created_at"], entry["expires_at"],
                entry.get("parent_entry"), entry.get("last_read_at"),
                entry.get("memory_tier", "working"), entry.get("read_count", 0),
                entry.get("promoted_from"),
            ))

            # Update tags index
            for tag in entry.get("tags", []):
                cur.execute(
                    "INSERT INTO tags_index (tag, entry_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (tag, entry["id"])
                )

            conn.commit()
        finally:
            self._put_conn(conn)
        return entry

    def query_entries(self, tags: List[str] = None,
                      agents: List[str] = None,
                      type: str = None,
                      types: List[str] = None,
                      max: int = None,
                      since: str = None,
                      tag_mode: str = "OR",
                      parent_entry: str = None,
                      text_search: str = None) -> Tuple[List[Dict], int]:
        """Query entries with filtering."""
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            conditions = ["e.expires_at >= NOW()"]
            params = []

            # Tag filter
            if tags:
                if tag_mode.upper() == "AND":
                    for tag in tags:
                        conditions.append(
                            "e.id IN (SELECT entry_id FROM tags_index WHERE tag = %s)"
                        )
                        params.append(tag)
                else:
                    placeholders = ",".join("%s" for _ in tags)
                    conditions.append(
                        f"e.id IN (SELECT entry_id FROM tags_index WHERE tag IN ({placeholders}))"
                    )
                    params.extend(tags)

            if agents:
                placeholders = ",".join("%s" for _ in agents)
                conditions.append(f"e.agent_id IN ({placeholders})")
                params.extend(agents)

            if type:
                conditions.append("e.type = %s")
                params.append(type)
            elif types:
                placeholders = ",".join("%s" for _ in types)
                conditions.append(f"e.type IN ({placeholders})")
                params.extend(types)

            if since:
                conditions.append("e.created_at >= %s")
                params.append(since)

            if parent_entry:
                conditions.append("(e.parent_entry = %s OR e.id = %s)")
                params.extend([parent_entry, parent_entry])

            where = " AND ".join(conditions)

            # Total
            cur.execute("SELECT COUNT(*) FROM entries")
            total = cur.fetchone()[0]

            # Results
            limit_clause = f"LIMIT {min(max or 50, 100)}" if max else "LIMIT 50"
            cur.execute(
                f"SELECT * FROM entries e WHERE {where} ORDER BY e.created_at DESC {limit_clause}",
                params
            )
            rows = cur.fetchall()
            entries = [self._row_to_dict(r) for r in rows]
        finally:
            self._put_conn(conn)

        return entries, total

    def get_all_alive(self) -> List[Dict]:
        """Get all non-expired entries."""
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM entries WHERE expires_at >= NOW() ORDER BY created_at DESC"
            )
            rows = cur.fetchall()
            return [self._row_to_dict(r) for r in rows]
        finally:
            self._put_conn(conn)

    def get_entry_by_id(self, entry_id: str) -> Optional[Dict]:
        """Get a single entry by ID."""
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT * FROM entries WHERE id = %s", (entry_id,))
            row = cur.fetchone()
            return self._row_to_dict(row) if row else None
        finally:
            self._put_conn(conn)

    def prune_expired(self) -> int:
        """Remove all expired entries."""
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM entries WHERE expires_at < NOW()")
            conn.commit()
            return cur.rowcount
        finally:
            self._put_conn(conn)

    ALLOWED_UPDATE_FIELDS = {"memory_tier", "promoted_from", "last_read_at", "read_count", "workspace_id"}

    def update_entry(self, entry_id: str, fields: Dict) -> bool:
        """Update specific fields of an entry by ID."""
        if not fields:
            return False
        filtered = {k: v for k, v in fields.items() if k in self.ALLOWED_UPDATE_FIELDS}
        if not filtered:
            return False
        set_clause = ", ".join(f"{k} = %s" for k in filtered.keys())
        values = list(filtered.values()) + [entry_id]
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                f"UPDATE entries SET {set_clause} WHERE id = %s",
                values
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            self._put_conn(conn)

    def forget_entry(self, entry_id: str) -> Optional[Dict]:
        """Remove a specific entry."""
        entry = self.get_entry_by_id(entry_id)
        if not entry:
            return None
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM entries WHERE id = %s", (entry_id,))
            cur.execute("DELETE FROM tags_index WHERE entry_id = %s", (entry_id,))
            conn.commit()
        finally:
            self._put_conn(conn)
        return entry

    def get_info(self) -> Dict:
        """Get store statistics."""
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM entries")
            total = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM entries WHERE expires_at >= NOW()")
            alive = cur.fetchone()[0]
            cur.execute("SELECT COUNT(DISTINCT agent_id) FROM entries")
            agents = cur.fetchone()[0]
            cur.execute("SELECT COUNT(DISTINCT tag) FROM tags_index")
            tags = cur.fetchone()[0]

            # By type
            cur.execute("SELECT type, COUNT(*) as cnt FROM entries GROUP BY type ORDER BY cnt DESC")
            by_type = {r[0]: r[1] for r in cur.fetchall()}
            # By agent
            cur.execute("SELECT agent_id, COUNT(*) as cnt FROM entries GROUP BY agent_id ORDER BY cnt DESC")
            by_agent = {r[0]: r[1] for r in cur.fetchall()}

            return {
                "total_entries": total,
                "alive_entries": alive,
                "expired_entries": total - alive,
                "unique_agents": agents,
                "unique_tags": tags,
                "store_size_kb": 0,
                "by_type": by_type,
                "by_agent": by_agent,
                "store_version": "postgresql",
            }
        finally:
            self._put_conn(conn)

    def wipe(self):
        """Delete all entries."""
        conn = self._get_conn()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM tags_index")
            cur.execute("DELETE FROM entries")
            conn.commit()
        finally:
            self._put_conn(conn)

    def close(self):
        """Close all connections."""
        if self._pool:
            self._pool.closeall()
            self._pool = None
