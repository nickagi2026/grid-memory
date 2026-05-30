"""
pii.py — PII/PHI detection and redaction for enterprise compliance.

Detects and optionally redacts sensitive data before it reaches the Grid.
Patterns cover: SSN, credit cards, email, phone, addresses, medical IDs.
"""

import re
from typing import Dict, List, Optional, Tuple


# ─── PII Patterns ──────────────────────────────────────────────────────────────

# Each pattern: (name, regex, category, severity, replacement)

PII_PATTERNS = [
    # US Social Security Number
    (r'\b\d{3}-\d{2}-\d{4}\b', "SSN", "pii", "critical", "[REDACTED SSN]"),
    # Credit Card (basic Luhn-checkable patterns)
    (r'\b(?:\d{4}[-\s]?){3}\d{4}\b', "Credit Card", "pii", "critical", "[REDACTED CC]"),
    # Email
    (r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', "Email", "pii", "high", "[REDACTED EMAIL]"),
    # US Phone
    (r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', "Phone", "pii", "high", "[REDACTED PHONE]"),
    # IP Address
    (r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', "IP Address", "pii", "medium", "[REDACTED IP]"),
    # US Street Address (basic)
    (r'\b\d{1,5}\s+[A-Za-z]+\s+(Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|Court|Ct)\b',
     "Address", "pii", "high", "[REDACTED ADDRESS]"),
    # Date of Birth
    (r'\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b', "Date", "pii", "medium", "[REDACTED DATE]"),
]

PHI_PATTERNS = [
    # Medical Record Number (common formats)
    (r'\b(?:MRN|MR|HSN|PID)[-:]?\d{4,10}\b', "Medical ID", "phi", "critical", "[REDACTED MEDICAL ID]"),
    # HIPAA-related codes
    (r'\b(?:ICD|CPT|HCPCS)[-:]?\d{2,5}\b', "Medical Code", "phi", "high", "[REDACTED MED CODE]"),
    # Health Plan ID
    (r'\b(?:HPID|HP|Plan)[-:]?\d{5,15}\b', "Health Plan ID", "phi", "critical", "[REDACTED PLAN ID]"),
]

ALL_PATTERNS = PII_PATTERNS + PHI_PATTERNS


# ─── Detector ──────────────────────────────────────────────────────────────────


class PIIDetector:
    """Detects and optionally redacts PII/PHI from content.

    Args:
        mode: "detect" (log only), "redact" (replace), "block" (reject writes)
        enabled_categories: Which categories to check (pii, phi)
    """

    def __init__(self, mode: str = "detect",
                 enabled_categories: Optional[List[str]] = None):
        self.mode = mode
        self.enabled_categories = enabled_categories or ["pii", "phi"]

    def scan(self, content: str) -> Dict:
        """Scan content for PII/PHI.

        Args:
            content: Text to scan

        Returns:
            Dict with scan results
        """
        findings = []

        for pattern_str, name, category, severity, replacement in ALL_PATTERNS:
            if category not in self.enabled_categories:
                continue

            for match in re.finditer(pattern_str, content, re.IGNORECASE):
                findings.append({
                    "type": name,
                    "category": category,
                    "severity": severity,
                    "match": match.group(0),
                    "position": match.start(),
                })

        return {
            "has_pii": len(findings) > 0,
            "findings": findings,
            "total": len(findings),
            "critical": len([f for f in findings if f["severity"] == "critical"]),
            "high": len([f for f in findings if f["severity"] == "high"]),
        }

    def redact(self, content: str) -> Tuple[str, Dict]:
        """Redact PII/PHI from content.

        Args:
            content: Text to redact

        Returns:
            Tuple of (redacted_content, scan_results)
        """
        scan_result = self.scan(content)
        redacted = content

        for pattern_str, name, category, severity, replacement in ALL_PATTERNS:
            if category not in self.enabled_categories:
                continue
            redacted = re.sub(pattern_str, replacement, redacted, flags=re.IGNORECASE)

        return redacted, scan_result

    def check_write(self, content: str) -> Dict:
        """Check if content can be written based on mode.

        Args:
            content: Content to check

        Returns:
            Dict with allowed flag, redacted_content, and findings
        """
        scan_result = self.scan(content)

        if self.mode == "block" and scan_result["has_pii"]:
            return {
                "allowed": False,
                "reason": f"Content contains {scan_result['total']} PII/PHI items "
                         f"({scan_result['critical']} critical)",
                "findings": scan_result["findings"],
            }

        if self.mode == "redact" and scan_result["has_pii"]:
            redacted, _ = self.redact(content)
            return {
                "allowed": True,
                "redacted": True,
                "content": redacted,
                "findings": scan_result["findings"],
            }

        return {
            "allowed": True,
            "redacted": False,
            "content": content,
            "findings": [],
        }

    def summary(self, scan_result: Dict) -> str:
        """Get a human-readable summary of scan results."""
        if not scan_result.get("has_pii"):
            return "No PII/PHI detected"
        parts = []
        for f in scan_result.get("findings", []):
            parts.append(f"{f['severity'].upper()}: {f['type']} at position {f['position']}")
        return "\n".join(parts)
