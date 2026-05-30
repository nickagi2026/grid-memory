"""
# BETA MODULE - Heuristic pattern matching, not ML. Results are directional indicators, not definitive.
# Confidence caveat: Value estimates use simplified models. Human review required before action.

gps.py — Organizational GPS™

Maps how work ACTUALLY flows (not the org chart).
Reveals hidden influence networks, bottlenecks, and informal power structures.
"""

import datetime
import json
import re
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Any

from grid_memory.local_grid import LocalGrid


class OrganizationalGPS:
    """Maps real work flow vs org chart.

    Args:
        grid: LocalGrid instance
    """

    def __init__(self, grid: LocalGrid):
        self.grid = grid

    def analyze(self) -> Dict:
        """Build the organizational network map."""
        entries = self.grid.query(max=500).get("entries", [])
        handoffs = [e for e in entries if e.get("type") == "handoff"]

        # Build handoff graph
        edges: Dict[str, Counter] = defaultdict(Counter)
        node_activity: Counter = Counter()
        node_types: Dict[str, Counter] = defaultdict(Counter)

        for h in handoffs:
            content = h.get("content", "")
            match = re.match(r'\[(.+?)\s*\u2192\s*(.+?)\]\s*\((.+?)\)', content)
            if match:
                fr = match.group(1).strip()
                to = match.group(2).strip()
                edges[fr][to] += 1
                node_activity[fr] += 1
                node_activity[to] += 1

        # Also count activity from all entries
        for e in entries:
            agent = e.get("agent_id", "")
            if agent:
                node_activity[agent] += 1
                node_types[agent][e.get("type", "observation")] += 1

        # Calculate influence (agents who receive the most handoffs)
        influence: Counter = Counter()
        for fr, targets in edges.items():
            for to, count in targets.items():
                influence[to] += count

        top_influencers = [{"agent": a, "influence_score": s, "handoffs_received": s} for a, s in influence.most_common(10)]

        # Build weighted edges for visualization
        network_edges = []
        for fr, targets in edges.items():
            for to, count in targets.most_common(10):
                network_edges.append({"from": fr, "to": to, "weight": count})

        # Find bottlenecks (agents with high handoff volume + limited backlinks)
        bottlenecks = []
        for agent, total in node_activity.most_common(20):
            received = influence.get(agent, 0)
            sent = sum(edges.get(agent, {}).values())
            if sent > 3 and received > 3:
                bottlenecks.append({
                    "agent": agent,
                    "handoffs_in": received,
                    "handoffs_out": sent,
                    "total_activity": total,
                    "bottleneck_score": round((received + sent) / 2, 0),
                })

        bottlenecks.sort(key=lambda x: -x["bottleneck_score"])

        return {
            "agents_mapped": len(node_activity),
            "connections": len(network_edges),
            "top_influencers": top_influencers[:5],
            "bottlenecks": bottlenecks[:5],
            "network_edges": network_edges[:50],
            "activity_by_agent": sorted(
                [{"agent": a, "activity": c} for a, c in node_activity.most_common(20)],
                key=lambda x: -x["activity"],
            ),
        }

    def report(self) -> str:
        """Generate a human-readable organizational GPS report."""
        data = self.analyze()
        lines = [
            f"\n{'=' * 60}",
            f"  ORGANIZATIONAL GPS",
            f"  {data['agents_mapped']} agents, {data['connections']} connections",
            f"{'=' * 60}",
        ]

        if data.get("top_influencers"):
            lines.extend(["\n  TOP INFLUENCERS (most handoffs received)"])
            for i, inf in enumerate(data["top_influencers"][:5], 1):
                lines.append(f"  {i}. {inf['agent']} — influence score: {inf['influence_score']:.0f}")

        if data.get("bottlenecks"):
            lines.extend(["\n  BOTTLENECKS (congestion points)"])
            for b in data["bottlenecks"][:5]:
                lines.append(f"  {b['agent']} — {b['handoffs_in']} in/{b['handoffs_out']} out")

        return "\n".join(lines)
