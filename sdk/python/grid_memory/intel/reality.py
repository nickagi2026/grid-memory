"""
# BETA MODULE - Heuristic pattern matching, not ML. Results are directional indicators, not definitive.
# Confidence caveat: Value estimates use simplified models. Human review required before action.

reality.py — Enterprise Reality Engine™

Discovers hidden truths with evidence, not opinions.
"Leadership believes Problem = Ticket Volume. Reality: Problem = Approval Latency."
"""

from collections import Counter, defaultdict
from typing import Dict, List, Optional, Any
from grid_memory.local_grid import LocalGrid
from grid_memory.intel.gps import OrganizationalGPS
from grid_memory.learning import LearningEngine


class RealityEngine:
    """Discovers counterintuitive truths about how the organization really operates.

    Args:
        grid: LocalGrid instance
    """

    def __init__(self, grid: LocalGrid):
        self.grid = grid
        self.gps = OrganizationalGPS(grid)
        self.learner = LearningEngine(grid)

    def discover(self) -> Dict:
        """Run full reality discovery scan."""
        gps_data = self.gps.analyze()
        patterns = self.learner.analyze()

        truths = []

        # Truth 1: Org chart vs reality
        influencers = gps_data.get("top_influencers", [])
        if influencers:
            truths.append({
                "category": "org_chart_vs_reality",
                "finding": f"Top influencers are {', '.join(i['agent'] for i in influencers[:3])} — likely not on the official org chart",
                "evidence": f"Each receives {influencers[0]['influence_score']:.0f}+ handoffs",
                "confidence": 0.85,
            })

        # Truth 2: Perceived problem vs actual problem
        blockers = patterns.get("recurring_blockers", [])
        workflows = patterns.get("workflow_patterns", [])
        if blockers and workflows:
            blocker_count = sum(b.get("count", 0) for b in blockers[:3])
            truths.append({
                "category": "perception_vs_reality",
                "finding": f"Most frequent issue: '{blockers[0]['pattern']}' ({blocker_count}x). Root cause may be workflow friction, not the issue itself.",
                "evidence": f"{len(workflows)} workflow patterns detected — process issues may be misdiagnosed as technical",
                "confidence": 0.7,
            })

        # Truth 3: Knowledge concentration risks
        more_blockers_than_decisions = any(
            b.get("count", 0) > d.get("count", 0) * 2
            for b in blockers for d in patterns.get("frequent_decisions", [])
        ) if blockers and patterns.get("frequent_decisions") else False
        if more_blockers_than_decisions:
            truths.append({
                "category": "reactive_vs_proactive",
                "finding": "Organization reacts to problems more than making decisions. More blockers recorded than decisions.",
                "evidence": f"{blockers[0]['count']} blockers vs {len(patterns.get('frequent_decisions', []))} decision topics",
                "confidence": 0.75,
            })

        # Truth 4: Hidden bottlenecks
        bottlenecks = gps_data.get("bottlenecks", [])
        if bottlenecks:
            truths.append({
                "category": "hidden_bottlenecks",
                "finding": f"Workflow congestion at {bottlenecks[0]['agent']} — this person handles {bottlenecks[0]['handoffs_in']:.0f} incoming handoffs",
                "evidence": "Single point of congestion creates delays that aren't visible to leadership",
                "confidence": 0.8,
            })

        return {
            "truths": truths,
            "total_truths": len(truths),
            "reality_score": round(85 - (len(truths) * 5), 1),  # More truths = more misalignment
            "recommendation": "Run targeted discovery at the identified misalignment points",
        }
