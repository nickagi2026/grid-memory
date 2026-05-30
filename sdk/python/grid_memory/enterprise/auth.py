"""
auth.py — API key authentication and permission model for the Grid.

Provides:
- API key generation and validation
- Key scoping to specific workspaces
- Read/write/admin permission levels
- Key rotation and revocation
- Built-in key hashing (keys are stored hashed, never in plaintext)
"""

import datetime
import hashlib
import json
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Any

# ─── Permission Levels ─────────────────────────────────────────────────────────

PERMISSIONS = ["viewer", "analyst", "architect", "executive", "admin"]
PERMISSION_HIERARCHY = {"viewer": 0, "analyst": 1, "architect": 2, "executive": 3, "admin": 4}


def has_permission(required: str, granted: str) -> bool:
    """Check if a granted permission level satisfies a requirement."""
    return PERMISSION_HIERARCHY.get(granted, 0) >= PERMISSION_HIERARCHY.get(required, 0)


# ─── Key Manager ───────────────────────────────────────────────────────────────


class KeyManager:
    """Manages API keys for Grid access.

    Keys are stored hashed (SHA-256). The plaintext key is only shown once
    on creation.

    Args:
        db_path: Path to the auth database
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or os.path.join(
            os.path.expanduser("~"), ".openclaw", "auth", "keys.db"
        )
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        Path(os.path.dirname(self.db_path)).mkdir(parents=True, exist_ok=True)
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS api_keys (
                key_id      TEXT PRIMARY KEY,
                key_hash    TEXT NOT NULL,
                label       TEXT NOT NULL DEFAULT '',
                workspace   TEXT NOT NULL DEFAULT '*',
                permission  TEXT NOT NULL DEFAULT 'read',
                created_at  TEXT NOT NULL,
                expires_at  TEXT,
                last_used   TEXT,
                enabled     INTEGER NOT NULL DEFAULT 1,
                created_by  TEXT NOT NULL DEFAULT 'system'
            );
            CREATE INDEX IF NOT EXISTS idx_keys_workspace ON api_keys(workspace);
            CREATE INDEX IF NOT EXISTS idx_keys_enabled ON api_keys(enabled);
        """)
        conn.commit()
        conn.close()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def create_key(self, label: str = "", workspace: str = "*",
                   permission: str = "read",
                   expires_in_days: Optional[int] = None,
                   created_by: str = "system") -> Dict:
        """Create a new API key.

        Args:
            label: Human-readable label for this key
            workspace: Workspace this key is scoped to ('*' for all)
            permission: Access level (viewer, analyst, architect, executive, admin)
            expires_in_days: Key expiry in days (None = no expiry)
            created_by: Who created this key

        Returns:
            Dict with key_id and plaintext_key (show once, not stored)
        """
        if permission not in PERMISSIONS:
            permission = "read"

        key_id = f"key_{secrets.token_hex(8)}"
        plaintext = f"grid_{secrets.token_hex(32)}"
        key_hash = self._hash_key(plaintext)

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        expires_at = ""
        if expires_in_days:
            expires_dt = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=expires_in_days)
            expires_at = expires_dt.isoformat()

        with self._lock:
            conn = self._get_conn()
            conn.execute(
                """INSERT INTO api_keys
                   (key_id, key_hash, label, workspace, permission,
                    created_at, expires_at, enabled, created_by)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)""",
                (key_id, key_hash, label, workspace, permission, now, expires_at, created_by)
            )
            conn.commit()
            conn.close()

        self._log_audit("key_created", f"Key {key_id} ({permission}, workspace: {workspace})", created_by)

        return {
            "key_id": key_id,
            "plaintext_key": plaintext,
            "label": label,
            "workspace": workspace,
            "permission": permission,
            "expires_at": expires_at or None,
        }

    def validate_key(self, plaintext_key: str, required_permission: str = "read",
                     workspace: str = "") -> Dict:
        """Validate an API key and return its info.

        Args:
            plaintext_key: The key to validate
            required_permission: Minimum required permission
            workspace: Required workspace scope

        Returns:
            Dict with valid flag and key info
        """
        key_hash = self._hash_key(plaintext_key)
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM api_keys WHERE key_hash = ? AND enabled = 1",
            (key_hash,)
        ).fetchone()
        conn.close()

        if not row:
            return {"valid": False, "reason": "Invalid key"}

        # Check expiry
        if row["expires_at"] and row["expires_at"] < now:
            return {"valid": False, "reason": "Key expired"}

        # Check permission
        if not has_permission(required_permission, row["permission"]):
            return {"valid": False, "reason": f"Insufficient permissions (need {required_permission}, have {row['permission']})"}

        # Check workspace scope
        if workspace and row["workspace"] != "*" and row["workspace"] != workspace:
            return {"valid": False, "reason": f"Key not scoped to workspace '{workspace}'"}

        # Update last_used
        conn = self._get_conn()
        conn.execute("UPDATE api_keys SET last_used = ? WHERE key_hash = ?", (now, key_hash))
        conn.commit()
        conn.close()

        return {
            "valid": True,
            "key_id": row["key_id"],
            "label": row["label"],
            "workspace": row["workspace"],
            "permission": row["permission"],
        }

    def revoke_key(self, key_id: str, by: str = "system") -> Dict:
        """Revoke an API key."""
        with self._lock:
            conn = self._get_conn()
            conn.execute("UPDATE api_keys SET enabled = 0 WHERE key_id = ?", (key_id,))
            conn.commit()
            conn.close()
        self._log_audit("key_revoked", f"Key {key_id} revoked by {by}", by)
        return {"revoked": True, "key_id": key_id}

    def list_keys(self, workspace: str = "") -> List[Dict]:
        """List all active API keys."""
        conn = self._get_conn()
        if workspace:
            rows = conn.execute(
                "SELECT key_id, label, workspace, permission, created_at, expires_at, last_used, enabled "
                "FROM api_keys WHERE workspace = ? OR workspace = '*' ORDER BY created_at DESC",
                (workspace,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT key_id, label, workspace, permission, created_at, expires_at, last_used, enabled "
                "FROM api_keys ORDER BY created_at DESC"
            ).fetchall()
        conn.close()

        return [dict(r) for r in rows]

    # ── Internal ──

    def _hash_key(self, key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest()

    def _log_audit(self, action: str, detail: str, by: str = "system"):
        """Write to audit log."""
        import sqlite3
        try:
            audit_path = os.path.join(os.path.dirname(self.db_path), "audit.db")
            conn = sqlite3.connect(audit_path)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    action TEXT NOT NULL,
                    detail TEXT,
                    actor TEXT NOT NULL
                )
            """)
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            conn.execute(
                "INSERT INTO audit_log (timestamp, action, detail, actor) VALUES (?, ?, ?, ?)",
                (now, action, detail, by)
            )
            conn.commit()
            conn.close()
        except Exception:
            pass
