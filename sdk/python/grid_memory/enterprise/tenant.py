"""
tenant.py — Tenant model and administration for enterprise multi-tenancy.

Hierarchy: Organization → Workspace → User → Role

Each tenant (organization) gets:
- Isolated workspace(s) with separate storage
- User accounts with role-based access
- Configurable retention policies
- Usage tracking and quotas
- Optional per-tenant encryption
"""

import datetime
import json
import os
import secrets
import sqlite3
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any

from grid_memory.enterprise.auth import KeyManager, PERMISSIONS, PERMISSION_HIERARCHY, has_permission


class TenantManager:
    """Manages organizations, workspaces, users, and tenant-level policies.

    Args:
        db_path: Path to the tenant database
        base_dir: Base directory for tenant data
    """

    def __init__(self, db_path: Optional[str] = None,
                 base_dir: Optional[str] = None):
        self.db_path = db_path or os.path.join(
            os.path.expanduser("~"), ".openclaw", "tenants", "tenants.db"
        )
        self.base_dir = base_dir or os.path.join(
            os.path.expanduser("~"), ".openclaw", "grid-workspaces"
        )
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self):
        Path(os.path.dirname(self.db_path)).mkdir(parents=True, exist_ok=True)
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tenants (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                domain      TEXT DEFAULT '',
                plan        TEXT DEFAULT 'starter',
                status      TEXT DEFAULT 'active',
                created_at  TEXT NOT NULL,
                updated_at  TEXT NOT NULL,
                settings    TEXT DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS workspaces (
                id          TEXT PRIMARY KEY,
                tenant_id   TEXT NOT NULL REFERENCES tenants(id),
                name        TEXT NOT NULL,
                label       TEXT DEFAULT '',
                backend     TEXT DEFAULT 'file',
                retention_days INTEGER DEFAULT 365,
                encryption_enabled INTEGER DEFAULT 0,
                created_at  TEXT NOT NULL,
                FOREIGN KEY (tenant_id) REFERENCES tenants(id)
            );
            CREATE TABLE IF NOT EXISTS users (
                id          TEXT PRIMARY KEY,
                tenant_id   TEXT NOT NULL REFERENCES tenants(id),
                email       TEXT NOT NULL,
                name        TEXT DEFAULT '',
                role        TEXT NOT NULL DEFAULT 'viewer',
                status      TEXT DEFAULT 'active',
                created_at  TEXT NOT NULL,
                last_login  TEXT,
                FOREIGN KEY (tenant_id) REFERENCES tenants(id)
            );
            CREATE TABLE IF NOT EXISTS usage_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id   TEXT NOT NULL,
                date        TEXT NOT NULL,
                api_calls   INTEGER DEFAULT 0,
                entries_written INTEGER DEFAULT 0,
                storage_bytes INTEGER DEFAULT 0,
                FOREIGN KEY (tenant_id) REFERENCES tenants(id)
            );
            CREATE INDEX IF NOT EXISTS idx_ws_tenant ON workspaces(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_user_tenant ON users(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_usage_tenant ON usage_log(tenant_id);
        """)
        conn.commit()
        conn.close()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    # ── Tenant CRUD ──

    def create_tenant(self, name: str, domain: str = "",
                      plan: str = "starter") -> Dict:
        """Create a new tenant organization."""
        tid = f"tenant_{secrets.token_hex(8)}"
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO tenants (id, name, domain, plan, status, created_at, updated_at) VALUES (?, ?, ?, ?, 'active', ?, ?)",
                (tid, name, domain, plan, now, now)
            )
            # Create default workspace
            ws_id = f"ws_{secrets.token_hex(6)}"
            conn.execute(
                "INSERT INTO workspaces (id, tenant_id, name, backend, created_at) VALUES (?, ?, ?, 'sqlite', ?)",
                (ws_id, tid, f"{name}-default", now)
            )
            conn.commit()
            conn.close()

        return {"tenant_id": tid, "workspace_id": ws_id, "name": name}

    def get_tenant(self, tenant_id: str) -> Optional[Dict]:
        """Get tenant details including workspaces and user count."""
        conn = self._get_conn()
        tenant = conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()
        if not tenant:
            conn.close()
            return None

        workspaces = conn.execute("SELECT id, name, label, backend, retention_days, encryption_enabled FROM workspaces WHERE tenant_id = ?", (tenant_id,)).fetchall()
        user_count = conn.execute("SELECT COUNT(*) FROM users WHERE tenant_id = ?", (tenant_id,)).fetchone()[0]
        usage = conn.execute("SELECT SUM(api_calls) as calls, SUM(entries_written) as writes FROM usage_log WHERE tenant_id = ?", (tenant_id,)).fetchone()
        conn.close()

        result = dict(tenant)
        result["workspaces"] = [dict(w) for w in workspaces]
        result["user_count"] = user_count
        result["total_api_calls"] = usage["calls"] or 0 if usage else 0
        result["total_entries_written"] = usage["writes"] or 0 if usage else 0
        return result

    def list_tenants(self) -> List[Dict]:
        """List all tenants with summary."""
        conn = self._get_conn()
        rows = conn.execute("SELECT t.*, (SELECT COUNT(*) FROM users u WHERE u.tenant_id = t.id) as user_count FROM tenants t ORDER BY t.created_at DESC").fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def update_tenant(self, tenant_id: str, **kwargs) -> Dict:
        """Update tenant properties."""
        allowed = {"name", "domain", "plan", "status"}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if not updates:
            return {"updated": False, "reason": "No valid fields"}

        updates["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        set_clause = ", ".join(f"{k} = ?" for k in updates)
        values = list(updates.values()) + [tenant_id]

        with self._lock:
            conn = self._get_conn()
            conn.execute(f"UPDATE tenants SET {set_clause} WHERE id = ?", values)
            conn.commit()
            conn.close()

        return {"updated": True, "tenant_id": tenant_id}

    # ── Workspace Management ──

    def create_workspace(self, tenant_id: str, name: str,
                         backend: str = "sqlite",
                         retention_days: int = 365,
                         encryption_enabled: bool = False) -> Dict:
        """Create a new workspace for a tenant."""
        ws_id = f"ws_{secrets.token_hex(6)}"
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO workspaces (id, tenant_id, name, backend, retention_days, encryption_enabled, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ws_id, tenant_id, name, backend, retention_days, 1 if encryption_enabled else 0, now)
            )
            conn.commit()
            conn.close()

        # Create the actual grid workspace
        from grid_memory.workspace import WorkspaceManager
        mgr = WorkspaceManager(base_dir=self.base_dir)
        mgr.create(ws_id, label=name, backend=backend)

        return {"workspace_id": ws_id, "tenant_id": tenant_id, "name": name}

    def get_workspace(self, workspace_id: str) -> Optional[Dict]:
        """Get workspace details."""
        conn = self._get_conn()
        ws = conn.execute(
            "SELECT w.*, t.name as tenant_name FROM workspaces w JOIN tenants t ON w.tenant_id = t.id WHERE w.id = ?",
            (workspace_id,)
        ).fetchone()
        conn.close()
        return dict(ws) if ws else None

    # ── User Management ──

    def create_user(self, tenant_id: str, email: str, name: str = "",
                    role: str = "viewer") -> Dict:
        """Create a user in a tenant."""
        uid = f"user_{secrets.token_hex(8)}"
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()

        if role not in PERMISSIONS:
            role = "viewer"

        with self._lock:
            conn = self._get_conn()
            conn.execute(
                "INSERT INTO users (id, tenant_id, email, name, role, status, created_at) VALUES (?, ?, ?, ?, ?, 'active', ?)",
                (uid, tenant_id, email, name, role, now)
            )
            conn.commit()
            conn.close()

        return {"user_id": uid, "tenant_id": tenant_id, "email": email, "role": role}

    def get_users(self, tenant_id: str) -> List[Dict]:
        """List users in a tenant."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT id, email, name, role, status, created_at, last_login FROM users WHERE tenant_id = ? ORDER BY created_at",
            (tenant_id,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def update_user_role(self, user_id: str, role: str) -> Dict:
        """Change a user's role."""
        if role not in PERMISSIONS:
            return {"updated": False, "reason": f"Invalid role: {role}"}

        with self._lock:
            conn = self._get_conn()
            conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
            conn.commit()
            conn.close()

        return {"updated": True, "user_id": user_id, "role": role}

    # ── Tenant-Level Policies ──

    def set_retention_policy(self, workspace_id: str, days: int) -> Dict:
        """Set retention policy for a workspace."""
        with self._lock:
            conn = self._get_conn()
            conn.execute("UPDATE workspaces SET retention_days = ? WHERE id = ?", (days, workspace_id))
            conn.commit()
            conn.close()
        return {"workspace_id": workspace_id, "retention_days": days}

    def set_encryption(self, workspace_id: str, enabled: bool) -> Dict:
        """Toggle per-tenant encryption for a workspace."""
        with self._lock:
            conn = self._get_conn()
            conn.execute("UPDATE workspaces SET encryption_enabled = ? WHERE id = ?", (1 if enabled else 0, workspace_id))
            conn.commit()
            conn.close()
        return {"workspace_id": workspace_id, "encryption_enabled": enabled}

    # ── Usage Tracking ──

    def log_usage(self, tenant_id: str, api_calls: int = 1,
                  entries_written: int = 0, storage_bytes: int = 0):
        """Record usage for a tenant."""
        today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
        try:
            conn = self._get_conn()
            existing = conn.execute(
                "SELECT id, api_calls, entries_written, storage_bytes FROM usage_log WHERE tenant_id = ? AND date = ?",
                (tenant_id, today)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE usage_log SET api_calls = api_calls + ?, entries_written = entries_written + ?, storage_bytes = ? WHERE id = ?",
                    (api_calls, entries_written, storage_bytes, existing["id"])
                )
            else:
                conn.execute(
                    "INSERT INTO usage_log (tenant_id, date, api_calls, entries_written, storage_bytes) VALUES (?, ?, ?, ?, ?)",
                    (tenant_id, today, api_calls, entries_written, storage_bytes)
                )
            conn.commit()
            conn.close()
        except Exception:
            pass

    def get_usage(self, tenant_id: str, days: int = 30) -> Dict:
        """Get usage statistics for a tenant."""
        conn = self._get_conn()
        cutoff = (datetime.datetime.utcnow() - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
        rows = conn.execute(
            "SELECT date, api_calls, entries_written, storage_bytes FROM usage_log WHERE tenant_id = ? AND date >= ? ORDER BY date",
            (tenant_id, cutoff)
        ).fetchall()
        conn.close()

        total_calls = sum(r["api_calls"] for r in rows)
        total_writes = sum(r["entries_written"] for r in rows)
        daily = [{"date": r["date"], "api_calls": r["api_calls"], "writes": r["entries_written"]} for r in rows]

        return {
            "tenant_id": tenant_id,
            "period_days": days,
            "total_api_calls": total_calls,
            "total_entries_written": total_writes,
            "daily_breakdown": daily[-30:],
        }

    # ── Admin Summary ──

    def admin_summary(self) -> Dict:
        """Get cross-tenant admin summary."""
        conn = self._get_conn()
        total_tenants = conn.execute("SELECT COUNT(*) FROM tenants").fetchone()[0]
        total_workspaces = conn.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0]
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_api = conn.execute("SELECT SUM(api_calls) FROM usage_log").fetchone()[0] or 0
        total_writes = conn.execute("SELECT SUM(entries_written) FROM usage_log").fetchone()[0] or 0
        conn.close()

        return {
            "total_tenants": total_tenants,
            "total_workspaces": total_workspaces,
            "total_users": total_users,
            "total_api_calls": total_api,
            "total_entries_written": total_writes,
        }
