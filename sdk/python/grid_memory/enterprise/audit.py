"""
audit.py — Immutable audit trail for all Grid operations.

Every write, read, promotion, deletion, and opportunity creation
is logged with timestamp, actor, action, and detail.
"""

import datetime
import json
import os
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Any




class AuditTrail:
    """Immutable append-only audit log for Grid operations.

    Args:
        db_path: Path to the audit database
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.path.join(
            os.path.expanduser("~"), ".openclaw", "audit", "audit.db"
        )
        self._init_db()

    def _init_db(self):
        Path(os.path.dirname(self.db_path)).mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT NOT NULL,
                action      TEXT NOT NULL,
                entity_type TEXT,
                entity_id   TEXT,
                workspace   TEXT DEFAULT '',
                actor       TEXT NOT NULL DEFAULT 'system',
                detail      TEXT DEFAULT '',
                ip_address  TEXT DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
            CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);
            CREATE INDEX IF NOT EXISTS idx_audit_workspace ON audit_log(workspace);
            CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity_id);
        """)
        conn.commit()
        conn.close()

    def log(self, action: str, entity_type: str = "",
            entity_id: str = "", workspace: str = "",
            actor: str = "system", detail: str = "",
            ip_address: str = "") -> Dict:
        """Record an audit event.

        Args:
            action: What happened (write, read, promote, delete, opportunity_create, etc.)
            entity_type: Type of entity (entry, key, workspace, etc.)
            entity_id: ID of the affected entity
            workspace: Workspace context
            actor: Who performed the action
            detail: Human-readable detail
            ip_address: Source IP

        Returns:
            Dict with audit entry info
        """
        conn = sqlite3.connect(self.db_path)
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        conn.execute(
            """INSERT INTO audit_log
               (timestamp, action, entity_type, entity_id, workspace, actor, detail, ip_address)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (now, action, entity_type, entity_id, workspace, actor, detail[:500], ip_address)
        )
        conn.commit()
        entry_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.close()
        return {"audit_id": entry_id, "timestamp": now, "action": action}

    def query(self, workspace: str = "", action: str = "",
              entity_id: str = "", limit: int = 100) -> List[Dict]:
        """Query the audit log.

        Args:
            workspace: Filter by workspace
            action: Filter by action type
            entity_id: Filter by entity ID
            limit: Max results

        Returns:
            List of audit entries
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        conditions = []
        params = []

        if workspace:
            conditions.append("workspace = ?")
            params.append(workspace)
        if action:
            conditions.append("action = ?")
            params.append(action)
        if entity_id:
            conditions.append("entity_id = ?")
            params.append(entity_id)

        where = " AND ".join(conditions) if conditions else "1=1"
        rows = conn.execute(
            f"SELECT * FROM audit_log WHERE {where} ORDER BY id DESC LIMIT ?",
            params + [limit]
        ).fetchall()
        conn.close()

        return [dict(r) for r in rows]

    def summary(self, workspace: str = "", days: int = 30) -> Dict:
        """Get a summary of audit activity.

        Args:
            workspace: Filter by workspace
            days: Look back period

        Returns:
            Dict with activity summary
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row

        cutoff = (datetime.datetime.now(datetime.timezone.utc) -
                  datetime.timedelta(days=days)).isoformat()

        ws_filter = "WHERE timestamp >= ?" if not workspace else "WHERE timestamp >= ? AND workspace = ?"
        params = [cutoff]
        if workspace:
            params.append(workspace)

        total = conn.execute(f"SELECT COUNT(*) FROM audit_log {ws_filter}", params).fetchone()[0]

        rows = conn.execute(
            f"SELECT action, COUNT(*) as cnt FROM audit_log {ws_filter} GROUP BY action ORDER BY cnt DESC",
            params
        ).fetchall()

        actions = {r["action"]: r["cnt"] for r in rows}

        conn.close()

        return {
            "total_events": total,
            "period_days": days,
            "by_action": actions,
            "workspace": workspace or "all",
        }

    def export(self, workspace: str = "", days: int = 90,
               output_path: str = "") -> str:
        """Export audit log to JSON."""
        entries = self.query(workspace=workspace, limit=10000)

        # Filter by date
        cutoff = (datetime.datetime.now(datetime.timezone.utc) -
                  datetime.timedelta(days=days)).isoformat()
        entries = [e for e in entries if e.get("timestamp", "") >= cutoff]

        output = {
            "exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "workspace": workspace,
            "days": days,
            "entries": entries,
        }

        if output_path:
            with open(output_path, "w") as f:
                json.dump(output, f, indent=2)
            return output_path
        return json.dumps(output, indent=2)
