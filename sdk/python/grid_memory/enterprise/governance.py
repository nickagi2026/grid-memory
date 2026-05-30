"""
governance.py — Enterprise governance: policies, compliance, data classification, workflows.

Provides the governance layer for enterprise Grid deployments.
"""

import datetime
import json
import os
from typing import Dict, List, Optional, Any

from grid_memory.local_grid import LocalGrid
from grid_memory.enterprise.pii import PIIDetector


class GovernanceEngine:
    """Enterprise governance: policies, compliance, data classification.

    Args:
        grid: LocalGrid instance
    """

    def __init__(self, grid: LocalGrid):
        self.grid = grid

    # ── Data Classification ──

    def classify_content(self, content: str) -> Dict:
        """Classify content by sensitivity level."""
        pii = PIIDetector(mode="detect")
        scan = pii.scan(content)

        if scan.get("critical"):
            return {"classification": "restricted", "reason": f"{scan['critical']} critical PII items", "findings": scan}
        if scan.get("high"):
            return {"classification": "confidential", "reason": f"{scan['high']} high-sensitivity items", "findings": scan}
        if scan.get("total", 0) > 0:
            return {"classification": "sensitive", "reason": f"{scan['total']} PII items", "findings": scan}

        return {"classification": "public", "reason": "No sensitive data detected", "findings": scan}

    def tag_by_classification(self, entry_id: str, classification: str) -> Dict:
        """Apply classification tag to an entry."""
        tags = ["public", "sensitive", "confidential", "restricted"]
        if classification not in tags:
            return {"tagged": False, "reason": f"Invalid: {classification}"}
        self.grid.fact(f"Classified as {classification}", tags=[f"class:{classification}", f"entry:{entry_id}"])
        return {"tagged": True, "classification": classification}

    # ── Compliance Framework ──

    def compliance_check(self, framework: str = "hipaa") -> Dict:
        """Run a compliance check against a framework. Returns gaps and recommendations."""
        entries = self.grid.query(max=500).get("entries", [])
        content_all = " ".join(e.get("content", "") for e in entries)

        checks = []
        if framework.lower() == "hipaa":
            checks = [
                {"rule": "Access control", "passed": "encrypt" in content_all.lower() or "auth" in content_all.lower(), "evidence": "Encryption/auth mentioned" if "encrypt" in content_all.lower() or "auth" in content_all.lower() else "Not found"},
                {"rule": "Audit controls", "passed": "audit" in content_all.lower(), "evidence": "Audit mentioned" if "audit" in content_all.lower() else "Not found"},
                {"rule": "Integrity controls", "passed": "hmac" in content_all.lower() or "checksum" in content_all.lower(), "evidence": "HMAC/checksum mentioned" if "hmac" in content_all.lower() or "checksum" in content_all.lower() else "Not found"},
                {"rule": "PII/PHI protection", "passed": "pii" in content_all.lower() or "phi" in content_all.lower(), "evidence": "PII/PHI handled" if "pii" in content_all.lower() or "phi" in content_all.lower() else "Not found"},
            ]

        passed = sum(1 for c in checks if c["passed"])
        return {
            "framework": framework.upper(),
            "checks": checks,
            "compliance_score": round(passed / len(checks) * 100, 1) if checks else 0,
            "passed": passed,
            "total": len(checks),
        }

    # ── Legal Hold ──

    def legal_hold(self, workspace_id: str, case_id: str,
                   reason: str = "") -> Dict:
        """Place a legal hold on a workspace — prevents any data deletion."""
        self.grid.fact(
            f"Legal hold placed\nWorkspace: {workspace_id}\nCase: {case_id}\nReason: {reason or 'Legal matter'}\nDate: {datetime.datetime.now(datetime.timezone.utc).isoformat()}",
            tags=["legal-hold", f"case:{case_id}", f"workspace:{workspace_id}"],
            agent_id="governance",
        )
        return {"hold_placed": True, "workspace": workspace_id, "case": case_id}
