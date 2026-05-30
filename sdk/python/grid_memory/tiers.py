"""
tiers.py — Memory Tier Promotion Engine for the Grid.

Three-tier memory architecture:
  ⚡ Working   (hours)   — Active agent context, high churn
  📦 Project   (weeks)   — Confirmed decisions, validated outcomes
  🏰 Organization (years) — Curated knowledge, audited, permanent

Promotion rules automate the flow: working → project → organization.
"""

import datetime
import json
import os
import re
import time
from typing import Dict, List, Optional, Any, Tuple

from grid_memory.local_grid import LocalGrid

# ─── Tier Constants ─────────────────────────────────────────────────────────────

TIERS = ["working", "project", "organization"]
TIER_ORDER = {"working": 0, "project": 1, "organization": 2}


def tier_rank(tier: str) -> int:
    return TIER_ORDER.get(tier, 0)


def is_promotable(current: str, target: str) -> bool:
    """Check if promotion from current to target is valid."""
    return tier_rank(target) > tier_rank(current)


# ─── Promotion Engine ───────────────────────────────────────────────────────────


class PromotionEngine:
    """Scans entries and promotes them based on rules.

    Args:
        grid: LocalGrid instance
        read_threshold: Min read count for promotion consideration
        relevance_threshold: Min avg relevance score for promotion
        handoff_reference_threshold: Min references from other entries
    """

    def __init__(self, grid: LocalGrid,
                 read_threshold: int = 5,
                 relevance_threshold: float = 7.0,
                 handoff_reference_threshold: int = 3):
        self.grid = grid
        self.read_threshold = read_threshold
        self.relevance_threshold = relevance_threshold
        self.handoff_reference_threshold = handoff_reference_threshold

    def promote(self, entry_id: str, target_tier: str) -> Dict:
        """Manually promote a single entry to a target tier.

        Args:
            entry_id: Entry to promote
            target_tier: Target memory tier

        Returns:
            Dict with success status
        """
        entry = self._get_entry(entry_id)
        if not entry:
            return {"success": False, "reason": "Entry not found"}

        current_tier = entry.get("memory_tier", "working")
        if not is_promotable(current_tier, target_tier):
            return {"success": False, "reason": f"Cannot promote from {current_tier} to {target_tier}"}

        self._set_tier(entry_id, target_tier, promoted_from=current_tier)

        # Write a promotion event as an observation
        self.grid.fact(
            f"Promoted entry {entry_id[:20]}... from {current_tier} to {target_tier}",
            tags=["promotion", f"tier:{target_tier}"],
            agent_id="promotion-engine",
        )

        return {
            "success": True,
            "entry_id": entry_id,
            "from_tier": current_tier,
            "to_tier": target_tier,
        }

    def scan_and_promote(self, dry_run: bool = False) -> Dict:
        """Scan all entries and auto-promote eligible ones.

        Args:
            dry_run: If True, report what would be promoted without acting

        Returns:
            Dict with promotion results
        """
        # Get all alive entries
        all_entries = self.grid.query(max=100)
        entries = all_entries.get("entries", [])

        # Build reference index (which entries reference which)
        references = self._build_reference_index()

        promotions = {
            "working_to_project": [],
            "project_to_organization": [],
            "total_candidates": len(entries),
            "dry_run": dry_run,
        }

        for entry in entries:
            current_tier = entry.get("memory_tier", "working")
            read_count = entry.get("read_count", 0)
            entry_id = entry.get("id", "")

            # Check references from other entries
            ref_count = len(references.get(entry_id, []))

            if current_tier == "working" and self._should_promote_to_project(entry, ref_count):
                promotions["working_to_project"].append({
                    "id": entry_id,
                    "agent": entry.get("agent_id"),
                    "type": entry.get("type"),
                    "content_preview": entry.get("content", "")[:80],
                    "read_count": read_count,
                    "relevance_score": entry.get("relevance_score", 0),
                    "ref_count": ref_count,
                    "reasons": self._promotion_reasons(entry, ref_count),
                })
                if not dry_run:
                    self._set_tier(entry_id, "project", promoted_from="working")

            elif current_tier == "project" and self._should_promote_to_organization(entry, ref_count):
                promotions["project_to_organization"].append({
                    "id": entry_id,
                    "agent": entry.get("agent_id"),
                    "type": entry.get("type"),
                    "content_preview": entry.get("content", "")[:80],
                    "read_count": read_count,
                    "ref_count": ref_count,
                    "reasons": self._promotion_reasons(entry, ref_count),
                })
                if not dry_run:
                    self._set_tier(entry_id, "organization", promoted_from="project")

        if not dry_run:
            # Write promotion summary
            total = len(promotions["working_to_project"]) + len(promotions["project_to_organization"])
            if total > 0:
                self.grid.fact(
                    f"Auto-promoted {total} entries: "
                    f"{len(promotions['working_to_project'])} to project, "
                    f"{len(promotions['project_to_organization'])} to organization",
                    tags=["promotion", "summary"],
                    agent_id="promotion-engine",
                )

        return promotions

    def get_tier_distribution(self) -> Dict:
        """Get count of entries per tier."""
        all_entries = self.grid.query(max=100)
        entries = all_entries.get("entries", [])
        dist: Dict[str, int] = {"working": 0, "project": 0, "organization": 0}
        for e in entries:
            tier = e.get("memory_tier", "working")
            dist[tier] = dist.get(tier, 0) + 1
        return dist

    def promote_by_tag(self, tag: str, target_tier: str) -> Dict:
        """Promote all entries with a specific tag to a target tier."""
        result = self.grid.query(tags=[tag], max=100)
        entries = result.get("entries", [])
        promoted = []
        for entry in entries:
            r = self.promote(entry["id"], target_tier)
            promoted.append(r)
        return {"tag": tag, "target_tier": target_tier, "promoted": len(promoted), "results": promoted}

    # ── Internal ──

    def _get_entry(self, entry_id: str) -> Optional[Dict]:
        """Get a single entry from the store by ID.
        Supports both JSON file backend and SQLite/PostgreSQL backends.
        """
        # If using a custom backend (SQLite, Postgres), use its get_entry_by_id
        if self.grid._backend and hasattr(self.grid._backend, 'get_entry_by_id'):
            return self.grid._backend.get_entry_by_id(entry_id)

        # Fallback: search directly in the JSON file store
        if hasattr(self.grid, '_load_store'):
            self.grid._load_store()
            for e in self.grid._store.get("entries", []):
                if e["id"] == entry_id:
                    return e
        return None

    def _set_tier(self, entry_id: str, tier: str, promoted_from: Optional[str] = None):
        """Set the memory_tier on an entry in the store.
        Supports all backends: JSON file, SQLite, PostgreSQL.
        """
        # Use backend update_entry when available (SQLite, Postgres)
        if self.grid._backend and hasattr(self.grid._backend, 'update_entry'):
            fields = {"memory_tier": tier}
            if promoted_from:
                fields["promoted_from"] = promoted_from
            self.grid._backend.update_entry(entry_id, fields)
            return
        # Fallback to file store direct access
        if not hasattr(self.grid, '_load_store'):
            return
        self.grid._load_store()
        for entry in self.grid._store["entries"]:
            if entry["id"] == entry_id:
                entry["memory_tier"] = tier
                if promoted_from:
                    entry["promoted_from"] = promoted_from
                break
        self.grid._save_store()

    def _build_reference_index(self) -> Dict[str, List[str]]:
        """Build a map of which entries reference which."""
        refs: Dict[str, List[str]] = {}
        result = self.grid.query(max=200)
        for entry in result.get("entries", []):
            content = entry.get("content", "")
            eid = entry.get("id", "")
            # Check if content references other entry IDs
            for match in re.finditer(r'grid_\d{8}_[a-f0-9]+', content):
                ref_id = match.group(0)
                if ref_id not in refs:
                    refs[ref_id] = []
                refs[ref_id].append(eid)
        return refs

    def _should_promote_to_project(self, entry: Dict, ref_count: int) -> bool:
        """Check if a working entry qualifies for project promotion."""
        read_count = entry.get("read_count", 0)
        if read_count < self.read_threshold and ref_count < self.handoff_reference_threshold:
            return False
        # Decisions and handoffs with reads get priority
        if entry.get("type") in ("decision", "handoff") and read_count >= 3:
            return True
        return read_count >= self.read_threshold or ref_count >= self.handoff_reference_threshold

    def _should_promote_to_organization(self, entry: Dict, ref_count: int) -> bool:
        """Check if a project entry qualifies for organization promotion."""
        read_count = entry.get("read_count", 0)
        # Organization requires significant engagement
        if read_count < 10 and ref_count < 5:
            return False
        return True

    def _promotion_reasons(self, entry: Dict, ref_count: int) -> List[str]:
        """Get human-readable reasons for promotion."""
        reasons = []
        read_count = entry.get("read_count", 0)
        if read_count >= self.read_threshold:
            reasons.append(f"{read_count} reads")
        if ref_count >= self.handoff_reference_threshold:
            reasons.append(f"referenced by {ref_count} entries")
        if entry.get("type") == "decision":
            reasons.append("architectural decision")
        if entry.get("type") == "handoff":
            reasons.append("workflow handoff")
        return reasons


# ─── CLI Integration ────────────────────────────────────────────────────────────


def add_tier_commands(subparsers):
    """Add tier-related CLI subcommands."""
    p_tier = subparsers.add_parser("tier", help="Memory tier operations")
    p_tier_sub = p_tier.add_subparsers(dest="tier_command")

    # tier list
    p_list = p_tier_sub.add_parser("list", help="Show tier distribution")
    p_list.add_argument("--dir", help="Store directory")

    # tier promote
    p_promote = p_tier_sub.add_parser("promote", help="Promote an entry")
    p_promote.add_argument("entry_id", help="Entry ID to promote")
    p_promote.add_argument("tier", choices=["project", "organization"],
                          help="Target tier")

    # tier scan
    p_scan = p_tier_sub.add_parser("scan", help="Scan and auto-promote eligible entries")
    p_scan.add_argument("--dry-run", action="store_true",
                       help="Preview without promoting")
    p_scan.add_argument("--dir", help="Store directory")

    return p_tier
