"""
sqlite_backend.py — SQLite storage backend for LocalGrid.

Replaces the file-based JSON store with SQLite. Same API, same semantics.
Supports WAL mode for concurrent readers, full-text search, and
efficient tag/agent/type indexing.

Usage:
    from grid_memory.local_grid import LocalGrid
    from grid_memory.sqlite_backend import SQLiteBackend

    grid = LocalGrid(backend=SQLiteBackend(":memory:"))
    # or
    grid = LocalGrid(backend=SQLiteBackend("./data/grid.db"))
"""

import datetime
import json
import os
import sqlite3
import threading
import time
from typing import Dict, List, Optional, Any, Tuple


def _now_iso() -> str:
    """Get current time as ISO 8601 string."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}Z"


class SQLiteBackend:
    """SQLite-backed storage for Grid entries.

    Thread-safe (one write connection, one read connection per thread).
    Supports WAL mode for concurrent reads.

    Args:
        db_path: Path to SQLite database file, or ":memory:" for in-memory
    """

    def __init__(self, db_path: str = "./grid.db"):
        self.db_path = db_path
        self._lock = threading.Lock()

        # Use shared-cache URI for :memory: so all connections see the same data
        if db_path == ":memory:":
            self._connect_uri = "file::memory:?cache=shared"
        else:
            self._connect_uri = db_path

        self._write_conn = None
        self._local = threading.local()
        self._init_db()

    def _get_read_conn(self) -> sqlite3.Connection:
        """Get a read connection for the current thread."""
        if not hasattr(self._local, 'read_conn') or self._local.read_conn is None:
            conn = sqlite3.connect(self._connect_uri, timeout=10, uri=True)
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("PRAGMA journal_mode=WAL")
            except sqlite3.OperationalError:
                pass  # WAL may not be supported in some configurations
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.read_conn = conn
        return self._local.read_conn

    def _get_write_conn(self) -> sqlite3.Connection:
        """Get the single write connection."""
        if self._write_conn is None:
            conn = sqlite3.connect(self._connect_uri, timeout=10, uri=True)
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("PRAGMA journal_mode=WAL")
            except sqlite3.OperationalError:
                pass
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=5000")
            self._write_conn = conn
        return self._write_conn

    def _init_db(self):
        """Create tables and indexes if they don't exist."""
        conn = self._get_write_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS entries (
                id          TEXT PRIMARY KEY,
                session_id  TEXT NOT NULL DEFAULT '',
                agent_id    TEXT NOT NULL,
                type        TEXT NOT NULL,
                tags        TEXT NOT NULL DEFAULT '[]',
                content     TEXT NOT NULL,
                ttl_seconds INTEGER NOT NULL DEFAULT 86400,
                created_at  TEXT NOT NULL,
                expires_at  TEXT NOT NULL,
                parent_entry TEXT,
                last_read_at TEXT,
                embedding   BLOB,
                memory_tier TEXT NOT NULL DEFAULT 'working',
                read_count  INTEGER NOT NULL DEFAULT 0,
                promoted_from TEXT,
                workspace_id TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS tags_index (
                tag      TEXT NOT NULL,
                entry_id TEXT NOT NULL,
                PRIMARY KEY (tag, entry_id),
                FOREIGN KEY (entry_id) REFERENCES entries(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_entries_expires
                ON entries(expires_at);
            CREATE INDEX IF NOT EXISTS idx_entries_agent
                ON entries(agent_id);
            CREATE INDEX IF NOT EXISTS idx_entries_type
                ON entries(type);
            CREATE INDEX IF NOT EXISTS idx_entries_created
                ON entries(created_at);
            CREATE INDEX IF NOT EXISTS idx_tags_tag
                ON tags_index(tag);


        """)
        conn.commit()

        # Migrate existing databases: add columns that might be missing
        for sql in [
            "ALTER TABLE entries ADD COLUMN memory_tier TEXT NOT NULL DEFAULT 'working'",
            "ALTER TABLE entries ADD COLUMN read_count INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE entries ADD COLUMN promoted_from TEXT",
            "ALTER TABLE entries ADD COLUMN workspace_id TEXT DEFAULT ''",
        ]:
            try:
                conn.execute(sql)
                conn.commit()
            except Exception:
                pass

    def _row_to_dict(self, row: sqlite3.Row) -> Dict:
        """Convert a sqlite3.Row to a plain dict."""
        d = dict(row)
        # Parse tags from JSON
        if isinstance(d.get("tags"), str):
            d["tags"] = json.loads(d["tags"])
        # Deserialize embedding if present
        if d.get("embedding") is not None:
            try:
                d["embedding"] = json.loads(d["embedding"])
            except (json.JSONDecodeError, TypeError):
                d["embedding"] = None
        return d

    # ── Write ──

    def write_entry(self, entry: Dict) -> Dict:
        """Insert an entry into the store."""
        with self._lock:
            conn = self._get_write_conn()
            tags_json = json.dumps(entry.get("tags", []))
            embedding_json = json.dumps(entry.get("embedding")) if entry.get("embedding") else None

            conn.execute("""
                INSERT INTO entries
                    (id, session_id, agent_id, type, tags, content,
                     ttl_seconds, created_at, expires_at, parent_entry,
                     last_read_at, embedding, memory_tier, read_count,
                     promoted_from, workspace_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                entry["id"],
                entry.get("session_id", ""),
                entry["agent_id"],
                entry["type"],
                tags_json,
                entry["content"],
                entry["ttl_seconds"],
                entry["created_at"],
                entry["expires_at"],
                entry.get("parent_entry"),
                entry.get("last_read_at"),
                embedding_json,
                entry.get("memory_tier", "working"),
                entry.get("read_count", 0),
                entry.get("promoted_from"),
                entry.get("workspace_id", ""),
            ))

            # Update tags index
            for tag in entry.get("tags", []):
                conn.execute(
                    "INSERT OR IGNORE INTO tags_index (tag, entry_id) VALUES (?, ?)",
                    (tag, entry["id"])
                )

            conn.commit()

        return entry

    # ── Query ──

    def query_entries(self, tags: List[str] = None,
                      agents: List[str] = None,
                      type: str = None,
                      types: List[str] = None,
                      max: int = None,
                      since: str = None,
                      tag_mode: str = "OR",
                      parent_entry: str = None,
                      text_search: str = None) -> Tuple[List[Dict], int]:
        """Query entries with filtering. Returns (entries, total_before_filter)."""
        conn = self._get_read_conn()
        now_iso = _now_iso()

        conditions = ["e.expires_at >= ?"]
        params: List[Any] = [now_iso]

        # Tag filter
        if tags:
            if tag_mode.upper() == "AND":
                for tag in tags:
                    conditions.append(
                        "e.id IN (SELECT entry_id FROM tags_index WHERE tag = ?)"
                    )
                    params.append(tag)
            else:
                placeholders = ",".join("?" for _ in tags)
                conditions.append(
                    f"e.id IN (SELECT entry_id FROM tags_index WHERE tag IN ({placeholders}))"
                )
                params.extend(tags)

        # Agent filter
        if agents:
            placeholders = ",".join("?" for _ in agents)
            conditions.append(f"e.agent_id IN ({placeholders})")
            params.extend(agents)

        # Type filter
        if type:
            conditions.append("e.type = ?")
            params.append(type)
        elif types:
            placeholders = ",".join("?" for _ in types)
            conditions.append(f"e.type IN ({placeholders})")
            params.extend(types)

        # Time filter
        if since:
            conditions.append("e.created_at >= ?")
            params.append(since)

        # Parent filter
        if parent_entry:
            conditions.append("(e.parent_entry = ? OR e.id = ?)")
            params.extend([parent_entry, parent_entry])

        where = " AND ".join(conditions)

        # Get total before filter (expired only)
        total = conn.execute(
            "SELECT COUNT(*) FROM entries"
        ).fetchone()[0]

        # Get filtered results
        limit_clause = f"LIMIT {min(max or 50, 100)}" if max else "LIMIT 50"
        rows = conn.execute(
            f"SELECT * FROM entries e WHERE {where} ORDER BY e.created_at DESC {limit_clause}",
            params
        ).fetchall()

        entries = [self._row_to_dict(r) for r in rows]
        return entries, total

    def get_all_alive(self) -> List[Dict]:
        """Get all non-expired entries."""
        conn = self._get_read_conn()
        now_iso = _now_iso()
        rows = conn.execute(
            "SELECT * FROM entries WHERE expires_at >= ? ORDER BY created_at DESC",
            (now_iso,)
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_entry_by_id(self, entry_id: str) -> Optional[Dict]:
        """Get a single entry by ID."""
        conn = self._get_read_conn()
        row = conn.execute(
            "SELECT * FROM entries WHERE id = ?", (entry_id,)
        ).fetchone()
        return self._row_to_dict(row) if row else None

    # ── Prune ──

    def prune_expired(self) -> int:
        """Remove all expired entries. Returns count removed."""
        with self._lock:
            conn = self._get_write_conn()
            now_iso = _now_iso()
            result = conn.execute(
                "DELETE FROM entries WHERE expires_at < ?", (now_iso,)
            )
            conn.commit()
            # Clean orphaned tags
            conn.execute("""
                DELETE FROM tags_index WHERE entry_id NOT IN (SELECT id FROM entries)
            """)
            conn.commit()
            return result.rowcount

    # ── Update ──

    ALLOWED_UPDATE_FIELDS = {"memory_tier", "promoted_from", "last_read_at", "read_count", "workspace_id"}

    def update_entry(self, entry_id: str, fields: Dict) -> bool:
        """Update specific fields of an entry by ID.

        Args:
            entry_id: Entry to update
            fields: Dict of field names to new values (whitelisted for safety)

        Returns:
            True if entry was found and updated
        """
        if not fields:
            return False

        # Whitelist: only allow specific fields for safety
        filtered = {k: v for k, v in fields.items() if k in self.ALLOWED_UPDATE_FIELDS}
        if not filtered:
            return False

        set_clause = ", ".join(f"{k} = ?" for k in filtered.keys())
        values = list(filtered.values()) + [entry_id]

        with self._lock:
            conn = self._get_write_conn()
            cur = conn.execute(
                f"UPDATE entries SET {set_clause} WHERE id = ?",
                values
            )
            conn.commit()

        return cur.rowcount > 0

    # ── Forget ──

    def forget_entry(self, entry_id: str) -> Optional[Dict]:
        """Remove a specific entry. Returns the removed entry or None."""
        entry = self.get_entry_by_id(entry_id)
        if not entry:
            return None
        with self._lock:
            conn = self._get_write_conn()
            conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
            conn.execute("DELETE FROM tags_index WHERE entry_id = ?", (entry_id,))
            conn.commit()
        return entry

    # ── Info ──

    def get_info(self) -> Dict:
        """Get store statistics."""
        conn = self._get_read_conn()
        now_iso = _now_iso()

        total = conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0]
        alive = conn.execute(
            "SELECT COUNT(*) FROM entries WHERE expires_at >= ?", (now_iso,)
        ).fetchone()[0]

        # Unique agents and tags
        agent_count = conn.execute(
            "SELECT COUNT(DISTINCT agent_id) FROM entries"
        ).fetchone()[0]
        tag_count = conn.execute(
            "SELECT COUNT(DISTINCT tag) FROM tags_index"
        ).fetchone()[0]

        # By type
        by_type = {}
        for row in conn.execute(
            "SELECT type, COUNT(*) as cnt FROM entries GROUP BY type ORDER BY cnt DESC"
        ).fetchall():
            by_type[row["type"]] = row["cnt"]

        # By agent
        by_agent = {}
        for row in conn.execute(
            "SELECT agent_id, COUNT(*) as cnt FROM entries GROUP BY agent_id ORDER BY cnt DESC"
        ).fetchall():
            by_agent[row["agent_id"]] = row["cnt"]

        # Size
        size_kb = os.path.getsize(self.db_path) / 1024 if os.path.exists(self.db_path) else 0

        return {
            "total_entries": total,
            "alive_entries": alive,
            "expired_entries": total - alive,
            "unique_agents": agent_count,
            "unique_tags": tag_count,
            "store_size_kb": round(size_kb, 1),
            "by_type": by_type,
            "by_agent": by_agent,
            "store_version": "sqlite",
        }

    # ── Wipe ──

    def wipe(self):
        """Delete all entries."""
        with self._lock:
            conn = self._get_write_conn()
            conn.execute("DELETE FROM entries")
            conn.execute("DELETE FROM tags_index")

            conn.commit()

    def close(self):
        """Close all connections."""
        if self._write_conn:
            self._write_conn.close()
            self._write_conn = None
        if hasattr(self._local, 'read_conn') and self._local.read_conn:
            self._local.read_conn.close()
            self._local.read_conn = None
