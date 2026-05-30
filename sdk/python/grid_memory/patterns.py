"""
patterns.py — Pattern Promotion Engine.

Turns raw memory into institutional knowledge through a promotion pipeline:

  Memory → Pattern → Playbook → Accelerator

After N projects in a domain, the Grid identifies recurring patterns
and distills them into reusable assets that become MIKE's competitive moat.
"""

import datetime
import json
import os
import re
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Any

from grid_memory.local_grid import LocalGrid

# ─── Pattern Levels ────────────────────────────────────────────────────────────

LEVELS = ["observation", "pattern", "playbook", "accelerator"]
LEVEL_ICONS = {"observation": "\U0001f50d", "pattern": "\U0001f4ca", "playbook": "\U0001f4d6", "accelerator": "\U0001f680"}
LEVEL_LABELS = {"observation": "Observation", "pattern": "Pattern", "playbook": "Playbook", "accelerator": "Accelerator"}


class PatternEngine:
    """Detects, promotes, and manages patterns across engagements.

    Args:
        grid: LocalGrid instance
    """

    def __init__(self, grid: LocalGrid):
        self.grid = grid

    def scan(self, domain: str = "", min_occurrences: int = 3) -> Dict:
        """Scan all entries for recurring patterns.

        Args:
            domain: Focus on a specific domain (healthcare, fintech, etc.)
            min_occurrences: Minimum times a pattern must appear

        Returns:
            Dict with detected patterns and promotion candidates
        """
        entries = self._get_entries(domain)
        patterns = []

        # 1. Tag-based pattern detection
        tag_patterns = self._find_tag_patterns(entries, min_occurrences)
        patterns.extend(tag_patterns)

        # 2. Content-based pattern detection
        content_patterns = self._find_content_patterns(entries, min_occurrences)
        patterns.extend(content_patterns)

        # 3. Handoff/workflow patterns
        workflow_patterns = self._find_workflow_patterns(entries, min_occurrences)
        patterns.extend(workflow_patterns)

        # 4. Blocker/recurring issue patterns
        issue_patterns = self._find_issue_patterns(entries, min_occurrences)
        patterns.extend(issue_patterns)

        # Score and sort
        for p in patterns:
            p["score"] = self._calculate_pattern_score(p)

        patterns.sort(key=lambda x: -x.get("score", 0))

        return {
            "patterns": patterns,
            "total": len(patterns),
            "promotion_candidates": [p for p in patterns if p.get("score", 0) >= 50],
            "domain": domain,
        }

    def promote(self, pattern_id: str, to_level: str) -> Dict:
        """Promote a detected pattern to a higher level.

        Args:
            pattern_id: The pattern entry ID
            to_level: Target level (pattern, playbook, accelerator)

        Returns:
            Dict with promotion result
        """
        # Get the pattern entry
        entry = self._get_entry(pattern_id)
        if not entry:
            return {"success": False, "reason": "Pattern not found"}

        current_level = self._extract_level(entry)
        if not self._can_promote(current_level, to_level):
            return {"success": False, "reason": f"Cannot promote from {current_level} to {to_level}"}

        # Create the promoted version
        result = self.grid.write(
            agent_id="pattern-engine",
            type="pattern",
            content=entry.get("content", ""),
            tags=["pattern", f"level:{to_level}", f"promoted_from:{pattern_id}"],
            memory_tier="project",
            parent_entry=pattern_id,
        )

        # Update original
        if hasattr(self.grid, '_load_store') and hasattr(self.grid, '_save_store'):
            self.grid._load_store()
            for se in self.grid._store["entries"]:
                if se["id"] == pattern_id:
                    tags = se.get("tags", [])
                    new_tags = [t for t in tags if not t.startswith("level:")]
                    new_tags.append(f"level:{to_level}")
                    se["tags"] = new_tags
                    break
            self.grid._save_store()

        return {
            "success": True,
            "pattern_id": pattern_id,
            "from_level": current_level,
            "to_level": to_level,
            "promoted_id": result["entry_id"],
        }

    def create_playbook(self, title: str, domain: str,
                        steps: List[str], tags: Optional[List[str]] = None) -> Dict:
        """Create a playbook from promoted patterns.

        Args:
            title: Playbook title
            domain: Domain (healthcare, fintech, etc.)
            steps: List of playbook steps
            tags: Additional tags

        Returns:
            Dict with created playbook info
        """
        content = f"Playbook: {title}\nDomain: {domain}\n\n"
        for i, step in enumerate(steps, 1):
            content += f"{i}. {step}\n"

        result = self.grid.write(
            agent_id="pattern-engine",
            type="playbook",
            content=content,
            tags=(tags or []) + ["pattern", "playbook", f"domain:{domain}", f"level:playbook"],
            memory_tier="organization",
        )

        return {
            "id": result["entry_id"],
            "title": title,
            "domain": domain,
            "steps": len(steps),
        }

    def create_accelerator(self, title: str, domain: str,
                           description: str, value_estimate: str = "",
                           tags: Optional[List[str]] = None) -> Dict:
        """Create an accelerator asset from promoted playbooks.

        Accelerators are the highest value output — reusable assets
        that can be sold or used to speed up delivery.

        Args:
            title: Accelerator title
            domain: Domain
            description: What this accelerator does
            value_estimate: Estimated value (hours saved, revenue, etc.)
            tags: Additional tags

        Returns:
            Dict with created accelerator info
        """
        content = (
            f"Accelerator: {title}\n"
            f"Domain: {domain}\n"
            f"Description: {description}\n"
            f"Value: {value_estimate}\n"
            f"Created: {datetime.datetime.now(datetime.timezone.utc).isoformat()}\n"
        )

        result = self.grid.write(
            agent_id="pattern-engine",
            type="accelerator",
            content=content,
            tags=(tags or []) + ["pattern", "accelerator", f"domain:{domain}", f"level:accelerator"],
            memory_tier="organization",
        )

        return {
            "id": result["entry_id"],
            "title": title,
            "domain": domain,
            "value_estimate": value_estimate,
        }

    def get_moat_report(self) -> Dict:
        """Generate a 'moat report' — summary of all patterns, playbooks, accelerators.

        This is the proof that MIKE compounds knowledge across engagements.
        """
        patterns = self._query_level("pattern")
        playbooks = self._query_level("playbook")
        accelerators = self._query_level("accelerator")

        domains = set()
        for items in [patterns, playbooks, accelerators]:
            for item in items:
                for t in item.get("tags", []):
                    if t.startswith("domain:"):
                        domains.add(t.split(":", 1)[1])

        return {
            "patterns_count": len(patterns),
            "playbooks_count": len(playbooks),
            "accelerators_count": len(accelerators),
            "domains_covered": sorted(domains),
            "patterns": patterns,
            "playbooks": playbooks,
            "accelerators": accelerators,
        }

    # ── Internal ──

    def _get_entries(self, domain: str = "") -> List[Dict]:
        tags = []
        if domain:
            tags.append(f"domain:{domain}")
        result = self.grid.query(tags=tags if tags else None, max=500)
        return result.get("entries", [])

    def _get_entry(self, eid: str) -> Optional[Dict]:
        if hasattr(self.grid, '_load_store'):
            self.grid._load_store()
            for e in self.grid._store.get("entries", []):
                if e["id"] == eid:
                    return e
        return None

    def _find_tag_patterns(self, entries: List[Dict], min_occ: int) -> List[Dict]:
        tag_counts: Counter = Counter()
        tag_agents: Dict[str, set] = defaultdict(set)
        tag_projects: Dict[str, set] = defaultdict(set)

        for e in entries:
            for t in e.get("tags", []):
                if not t.startswith("agent:") and not t.startswith("stage:") and not t.startswith("client:"):
                    tag_counts[t] += 1
                    tag_agents[t].add(e.get("agent_id", "?"))
                    for et in e.get("tags", []):
                        if et.startswith("project:"):
                            tag_projects[t].add(et.split(":", 1)[1])

        patterns = []
        for tag, count in tag_counts.most_common(30):
            if count >= min_occ:
                level = "observation" if count < 5 else ("pattern" if count < 10 else "playbook")
                patterns.append({
                    "id": f"pattern_tag_{tag}",
                    "type": "tag_pattern",
                    "pattern": tag,
                    "evidence": f"Appeared {count} times across {len(tag_agents[tag])} agents",
                    "occurrences": count,
                    "unique_agents": len(tag_agents[tag]),
                    "projects": list(tag_projects.get(tag, [])),
                    "current_level": level,
                    "suggested_level": "playbook" if count >= 5 else "pattern",
                    "confidence": min(count / 10, 0.95),
                })

        return patterns

    def _find_content_patterns(self, entries: List[Dict], min_occ: int) -> List[Dict]:
        keyword_patterns: Counter = Counter()
        keyword_agents: Dict[str, set] = defaultdict(set)

        important_keywords = [
            "compliance", "regulation", "audit", "security", "integration",
            "migration", "automation", "optimization", "monitoring", "scaling",
            "deployment", "testing", "validation", "approval", "governance",
        ]

        for e in entries:
            content = e.get("content", "").lower()
            for kw in important_keywords:
                if kw in content:
                    keyword_patterns[kw] += 1
                    keyword_agents[kw].add(e.get("agent_id", "?"))

        patterns = []
        for kw, count in keyword_patterns.most_common(20):
            if count >= min_occ:
                level = "observation" if count < 5 else ("pattern" if count < 10 else "playbook")
                patterns.append({
                    "id": f"pattern_kw_{kw}",
                    "type": "content_pattern",
                    "pattern": f"'{kw}' appears across engagements",
                    "evidence": f"Mentioned {count} times by {len(keyword_agents[kw])} agents",
                    "occurrences": count,
                    "unique_agents": len(keyword_agents[kw]),
                    "current_level": level,
                    "suggested_level": "playbook" if count >= 5 else "pattern",
                    "confidence": min(count / 10, 0.95),
                })

        return patterns

    def _find_workflow_patterns(self, entries: List[Dict], min_occ: int) -> List[Dict]:
        handoffs = [e for e in entries if e.get("type") == "handoff"]
        if len(handoffs) < min_occ:
            return []

        pair_counts: Counter = Counter()
        for h in handoffs:
            content = h.get("content", "")
            match = re.match(r'\[(.+?)\s*\u2192\s*(.+?)\]\s*\((.+?)\)', content)
            if match:
                pair_counts[f"{match.group(1).strip()} \u2192 {match.group(2).strip()}"] += 1

        patterns = []
        for pair, count in pair_counts.most_common(10):
            if count >= min_occ:
                patterns.append({
                    "id": f"pattern_wf_{pair.replace(' ', '_')[:30]}",
                    "type": "workflow_pattern",
                    "pattern": f"Recurring handoff: {pair}",
                    "evidence": f"{count} handoffs observed",
                    "occurrences": count,
                    "unique_agents": 2,
                    "current_level": "observation",
                    "suggested_level": "pattern",
                    "confidence": min(count / 5, 0.9),
                })

        return patterns

    def _find_issue_patterns(self, entries: List[Dict], min_occ: int) -> List[Dict]:
        blockers = [e for e in entries if e.get("type") == "blocker"]
        if len(blockers) < min_occ:
            return []

        issue_kws = ["timeout", "error", "failed", "crash", "outage", "permission"]
        issue_counts: Counter = Counter()
        for b in blockers:
            content = b.get("content", "").lower()
            for kw in issue_kws:
                if kw in content:
                    issue_counts[kw] += 1

        patterns = []
        for kw, count in issue_counts.most_common(10):
            if count >= min_occ:
                patterns.append({
                    "id": f"pattern_issue_{kw}",
                    "type": "issue_pattern",
                    "pattern": f"Recurring blocker: '{kw}'",
                    "evidence": f"{count} blocker entries",
                    "occurrences": count,
                    "unique_agents": 1,
                    "current_level": "observation",
                    "suggested_level": "pattern",
                    "confidence": min(count / 5, 0.85),
                })

        return patterns

    def _calculate_pattern_score(self, pattern: Dict) -> float:
        occ = pattern.get("occurrences", 0)
        agents = pattern.get("unique_agents", 1)
        confidence = pattern.get("confidence", 0.5)
        # Cross-agent patterns are more valuable
        cross_agent_bonus = min(agents * 5, 25)
        return (occ * 5) + cross_agent_bonus + (confidence * 20)

    def _extract_level(self, entry: Dict) -> str:
        for t in entry.get("tags", []):
            if t.startswith("level:"):
                return t.split(":", 1)[1]
        return "observation"

    def _can_promote(self, current: str, target: str) -> bool:
        order = {"observation": 0, "pattern": 1, "playbook": 2, "accelerator": 3}
        return order.get(target, 0) > order.get(current, 0)

    def _query_level(self, level: str) -> List[Dict]:
        result = self.grid.query(tags=[f"level:{level}"], max=200)
        entries = result.get("entries", [])
        formatted = []
        for e in entries:
            domain = ""
            for t in e.get("tags", []):
                if t.startswith("domain:"):
                    domain = t.split(":", 1)[1]
            formatted.append({
                "id": e.get("id", ""),
                "content": e.get("content", "")[:200],
                "domain": domain,
                "created_at": e.get("created_at", ""),
                "tags": e.get("tags", []),
            })
        return formatted
