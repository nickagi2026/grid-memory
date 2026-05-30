"""
# BETA MODULE - Heuristic pattern matching, not ML. Results are directional indicators, not definitive.
# Confidence caveat: Value estimates use simplified models. Human review required before action.

tribal.py — Tribal Knowledge Extractor™

Identifies people everyone depends on but nobody documented.
Warns about critical knowledge concentration and suggests extraction.
"""

import datetime
import json
import re
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Any

from grid_memory.local_grid import LocalGrid


class TribalKnowledgeExtractor:
    """Identifies and extracts undocumented knowledge from key individuals.

    Args:
        grid: LocalGrid instance
    """

    def __init__(self, grid: LocalGrid):
        self.grid = grid

    def scan(self) -> Dict:
        """Scan for knowledge concentration risks."""
        entries = self.grid.query(max=500).get("entries", [])

        # Build agent activity and dependency profiles
        agent_entries: Dict[str, List[Dict]] = defaultdict(list)
        agent_types: Dict[str, Counter] = defaultdict(Counter)
        agent_tags: Dict[str, set] = defaultdict(set)
        agent_mentions: Counter = Counter()  # how often an agent is referenced

        for e in entries:
            agent = e.get("agent_id", "")
            if agent:
                agent_entries[agent].append(e)
                agent_types[agent][e.get("type", "")] += 1
                for t in e.get("tags", []):
                    agent_tags[agent].add(t)

            # Check if content mentions another agent
            content = e.get("content", "")
            for mention in re.findall(r'agent:(\w+)', content):
                agent_mentions[mention] += 1

        risks = []
        for agent, entries_list in agent_entries.items():
            total = len(entries_list)
            decisions = agent_types[agent].get("decision", 0)
            blockers = agent_types[agent].get("blocker", 0)
            unique_tags = len(agent_tags[agent])
            mentions = agent_mentions.get(agent, 0)

            # Calculate knowledge concentration risk
            # High: unique decisions + few lessons + high mentions
            if decisions >= 3 and mentions >= 2:
                lesson_count = sum(1 for e in entries_list if "lesson" in e.get("tags", []))
                knowledge_share = round(decisions / max(total, 1) * 100, 0)

                risk_level = "HIGH" if (knowledge_share > 50 and lesson_count == 0) else "MODERATE"

                risks.append({
                    "agent": agent,
                    "risk_level": risk_level,
                    "knowledge_share": knowledge_share,
                    "decisions_made": decisions,
                    "times_referenced": mentions,
                    "blockers_handled": blockers,
                    "lessons_documented": lesson_count,
                    "unique_topics": unique_tags,
                })

        risks.sort(key=lambda x: -x.get("knowledge_share", 0))

        return {
            "agents_scanned": len(agent_entries),
            "critical_risks": [r for r in risks if r["risk_level"] == "HIGH"],
            "moderate_risks": [r for r in risks if r["risk_level"] == "MODERATE"],
            "total_at_risk": len([r for r in risks if r["risk_level"] == "HIGH"]),
            "recommendation": self._recommendation(risks),
        }

    def extract(self, agent: str) -> Dict:
        """Extract all knowledge from a specific agent's entries."""
        entries = self.grid.query(max=200).get("entries", [])
        agent_entries = [e for e in entries if e.get("agent_id") == agent]

        decisions = [e for e in agent_entries if e.get("type") == "decision"]
        blockers = [e for e in agent_entries if e.get("type") == "blocker"]
        facts = [e for e in agent_entries if e.get("type") == "fact"]

        all_tags = set()
        for e in agent_entries:
            all_tags.update(e.get("tags", []))

        return {
            "agent": agent,
            "total_entries": len(agent_entries),
            "decisions": [{"content": d.get("content", "")[:150], "date": d.get("created_at", "")[:10]} for d in decisions[:5]],
            "known_blockers": [{"content": b.get("content", "")[:100]} for b in blockers[:5]],
            "key_facts": [{"content": f.get("content", "")[:100]} for f in facts[:5]],
            "topics": sorted(all_tags)[:10],
            "extraction_quality": "high" if len(agent_entries) >= 5 else "needs_more_data",
        }

    def _recommendation(self, risks: List[Dict]) -> str:
        high = [r for r in risks if r["risk_level"] == "HIGH"]
        if not high:
            return "No critical knowledge concentration detected"
        names = [r["agent"] for r in high[:3]]
        return f"Knowledge extraction recommended for: {', '.join(names)}. These individuals hold disproportionate undocumented knowledge."
