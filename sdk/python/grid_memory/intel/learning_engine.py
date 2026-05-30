"""
# BETA: This module uses heuristic pattern matching and simplified assumptions.
# Value estimates use flat rates and frequency multipliers — directional only.
# Results are NOT validated against real outcome data. Use for internal surfacing, not client analytics.

learning_engine.py — Organizational Learning Engine.

Combines lessons, patterns, and promotion rules into a unified
organizational learning system with formal knowledge lifecycle.
"""

import datetime
import json
import re
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Any

from grid_memory.local_grid import LocalGrid
from grid_memory.lessons import LessonsEngine
from grid_memory.patterns import PatternEngine
from grid_memory.tiers import PromotionEngine

# Knowledge lifecycle stages
KNOWLEDGE_STAGES = ["tacit", "captured", "validated", "promoted", "retired"]

class OrganizationalLearningEngine:
    """Unified organizational learning with full knowledge lifecycle.

    Knowledge flows: tacit → captured → validated → promoted → retired
    """

    def __init__(self, grid: LocalGrid):
        self.grid = grid
        self.lessons = LessonsEngine(grid)
        self.patterns = PatternEngine(grid)
        self.promotion = PromotionEngine(grid)

    def scan_knowledge(self) -> Dict:
        """Scan all knowledge assets and their lifecycle stages."""
        # Get all lessons
        all_lessons = self.lessons.list(max_results=500)
        # Get all patterns
        pattern_scan = self.patterns.scan(min_occurrences=2)
        # Get tier distribution
        tier_dist = self.promotion.get_tier_distribution()

        lessons_list = all_lessons.get("lessons", [])
        patterns_list = pattern_scan.get("patterns", [])

        return {
            "total_lessons": len(lessons_list),
            "total_patterns": len(patterns_list),
            "tier_distribution": tier_dist,
            "by_category": all_lessons.get("by_category", {}),
            "ready_for_promotion": len([p for p in patterns_list if p.get("score", 0) >= 50]),
            "knowledge_age_days": self._avg_age_days(lessons_list),
        }

    def validate_knowledge(self, entry_id: str, validator: str = "",
                           notes: str = "") -> Dict:
        """Mark a knowledge entry as validated."""
        self.grid.write(
            agent_id=validator or "org-learning",
            type="observation",
            content=f"Knowledge validated\nEntry: {entry_id}\nValidator: {validator or 'system'}\nNotes: {notes}\nDate: {datetime.datetime.now(datetime.timezone.utc).isoformat()}",
            tags=["knowledge-lifecycle", "knowledge:validated", f"entry:{entry_id}"],
            parent_entry=entry_id,
        )
        return {"validated": True, "entry_id": entry_id}

    def retire_knowledge(self, entry_id: str, reason: str = "") -> Dict:
        """Mark knowledge as retired (outdated, superseded)."""
        self.grid.write(
            agent_id="org-learning",
            type="observation",
            content=f"Knowledge retired\nEntry: {entry_id}\nReason: {reason or 'Superseded'}\nDate: {datetime.datetime.now(datetime.timezone.utc).isoformat()}",
            tags=["knowledge-lifecycle", "knowledge:retired", f"entry:{entry_id}"],
            parent_entry=entry_id,
        )
        return {"retired": True, "entry_id": entry_id}

    def get_knowledge_report(self) -> Dict:
        """Generate organizational knowledge health report."""
        scan = self.scan_knowledge()
        lessons_list = self.lessons.list(max_results=500).get("lessons", [])
        pattern_result = self.patterns.scan(min_occurrences=2)

        return {
            "knowledge_base": {
                "lessons": scan["total_lessons"],
                "patterns": scan["total_patterns"],
                "playbooks": pattern_result.get("promotion_candidates", 0),
            },
            "tiers": scan["tier_distribution"],
            "health": self._calculate_health(scan),
            "recommendations": self._recommend_actions(scan),
        }

    def _avg_age_days(self, entries: List[Dict]) -> float:
        if not entries:
            return 0
        ages = []
        now = datetime.datetime.now(datetime.timezone.utc)
        for e in entries:
            try:
                created = datetime.datetime.fromisoformat(e.get("created_at", "").replace("Z", "+00:00"))
                ages.append((now - created).days)
            except (ValueError, AttributeError):
                pass
        return round(sum(ages) / len(ages), 1) if ages else 0

    def _calculate_health(self, scan: Dict) -> Dict:
        total = scan.get("total_lessons", 0) + scan.get("total_patterns", 0)
        score = min(total * 5, 100)
        level = "excellent" if score >= 80 else ("good" if score >= 50 else ("fair" if score >= 20 else "early"))
        return {"score": score, "level": level}

    def _recommend_actions(self, scan: Dict) -> List[str]:
        recs = []
        if scan.get("total_lessons", 0) < 5:
            recs.append("Add more lessons — aim for at least 5 per project")
        if scan.get("ready_for_promotion", 0) > 0:
            recs.append(f"Review {scan['ready_for_promotion']} patterns ready for promotion to playbooks")
        if scan.get("tier_distribution", {}).get("organization", 0) == 0 and scan.get("total_patterns", 0) > 3:
            recs.append("Promote your strongest patterns to organizational knowledge")
        if scan.get("total_patterns", 0) > 20:
            recs.append("Consider retiring outdated patterns — knowledge should be curated")
        return recs
