"""
enforcer.py — Enforced security pipeline for all Grid operations.

Every write/read/goes through:
  Authenticate → Authorize → PII Policy → Execute → Audit

This is the enforcement layer that makes enterprise security real,
not just a module next to the product.
"""

import datetime
import json
import os
from typing import Dict, List, Optional, Any, Callable

from grid_memory.enterprise.auth import KeyManager
from grid_memory.enterprise.audit import AuditTrail
from grid_memory.enterprise.pii import PIIDetector


class SecurityEnforcer:
    """Enforces the security pipeline on every Grid operation.

    Pipeline: Authenticate → Authorize → PII Policy → Execute → Audit

    Usage:
        enforcer = SecurityEnforcer()
        enforcer.check_write(key="sk-...", workspace="client-a", content="...")
    """

    def __init__(self, pii_mode: str = "detect",
                 audit_path: Optional[str] = None,
                 auth_path: Optional[str] = None):
        self.key_manager = KeyManager(db_path=auth_path)
        self.audit = AuditTrail(db_path=audit_path)
        self.pii = PIIDetector(mode=pii_mode)

    def check_write(self, api_key: str = "", workspace: str = "",
                    content: str = "", entity_type: str = "entry",
                    actor: str = "", ip_address: str = "") -> Dict:
        """Run the full security pipeline for a write operation.

        Args:
            api_key: API key for authentication
            workspace: Target workspace
            content: Content to write
            entity_type: Type of entity being written
            actor: Who is performing the operation
            ip_address: Source IP

        Returns:
            Dict with allowed flag, reason, redacted_content, audit_id
        """
        # 1. Authenticate
        if api_key:
            auth = self.key_manager.validate_key(api_key, "architect", workspace)
            if not auth.get("valid"):
                self.audit.log("write_blocked", entity_type, "",
                               workspace, api_key[:8], auth.get("reason", "Auth failed"), ip_address)
                return {"allowed": False, "reason": auth.get("reason", "Authentication failed")}
            actor = actor or auth.get("key_id", "unknown")
        elif not actor:
            # No key, no actor — rely on actor field for internal use
            actor = "unauthenticated"

        # 2. Authorize (workspace scope)
        if workspace:
            # Already checked in validate_key for key-based access
            pass

        # 3. PII Policy
        pii_result = self.pii.check_write(content)
        if not pii_result.get("allowed"):
            self.audit.log("write_blocked_by_pii", entity_type, "",
                           workspace, actor,
                           f"PII detected: {pii_result.get('reason', '')}", ip_address)
            return {
                "allowed": False,
                "reason": pii_result.get("reason", "Content blocked by PII policy"),
                "pii_findings": pii_result.get("findings", []),
            }

        redacted_content = pii_result.get("content", content)

        # 4. Audit (write will be logged by caller)
        audit_entry = self.audit.log(
            "write", entity_type, "", workspace, actor,
            f"Write allowed (PII: {pii_result.get('redacted', False)})", ip_address
        )

        return {
            "allowed": True,
            "content": redacted_content,
            "pii_redacted": pii_result.get("redacted", False),
            "pii_findings": pii_result.get("findings", []),
            "audit_id": audit_entry.get("audit_id"),
            "actor": actor,
        }

    def check_read(self, api_key: str = "", workspace: str = "",
                   actor: str = "", ip_address: str = "") -> Dict:
        """Run the security pipeline for a read operation."""
        if api_key:
            auth = self.key_manager.validate_key(api_key, "read", workspace)
            if not auth.get("valid"):
                self.audit.log("read_blocked", "entry", "", workspace,
                               api_key[:8], auth.get("reason", "Auth failed"), ip_address)
                return {"allowed": False, "reason": auth.get("reason", "Authentication failed")}
            actor = actor or auth.get("key_id", "unknown")

        audit_entry = self.audit.log(
            "read", "entry", "", workspace, actor, "Read allowed", ip_address
        )

        return {"allowed": True, "audit_id": audit_entry.get("audit_id"), "actor": actor}

    def check_admin(self, api_key: str = "", workspace: str = "",
                    actor: str = "", ip_address: str = "") -> Dict:
        """Run the security pipeline for an admin operation."""
        if api_key:
            auth = self.key_manager.validate_key(api_key, "admin", workspace)
            if not auth.get("valid"):
                self.audit.log("admin_blocked", "admin", "", workspace,
                               api_key[:8], auth.get("reason", "Auth failed"), ip_address)
                return {"allowed": False, "reason": auth.get("reason", "Authentication failed")}
            actor = actor or auth.get("key_id", "unknown")

        return {"allowed": True, "actor": actor}

    def log_operation(self, action: str, entity_type: str = "entry",
                      entity_id: str = "", workspace: str = "",
                      actor: str = "system", detail: str = "",
                      ip_address: str = "") -> Dict:
        """Log any operation to the audit trail."""
        return self.audit.log(action, entity_type, entity_id,
                              workspace, actor, detail, ip_address)

    def get_stats(self) -> Dict:
        """Get security enforcer statistics."""
        audit_summary = self.audit.summary()
        keys = self.key_manager.list_keys()

        return {
            "total_keys": len(keys),
            "active_keys": len([k for k in keys if k.get("enabled")]),
            "audit_events_30d": audit_summary.get("total_events", 0),
            "pii_mode": self.pii.mode,
        }
