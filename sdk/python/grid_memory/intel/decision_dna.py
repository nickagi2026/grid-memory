"""
# BETA: This module uses heuristic pattern matching and simplified assumptions.
# Value estimates use flat rates and frequency multipliers — directional only.
# Results are NOT validated against real outcome data. Use for internal surfacing, not client analytics.

decision_dna.py — Decision DNA™

Tracks every decision: who made it, why, what evidence they had, what the
outcome was. Over time, learns:
- Who the best decision-makers are (by success rate)
- What patterns lead to failure
- What decisions should be standardized
"""

import datetime
import json
import re
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Any

from grid_memory.local_grid import LocalGrid


class DecisionDNA:
    """Tracks and analyzes decision patterns across the organization.

    Args:
        grid: LocalGrid instance
    """

    def __init__(self, grid: LocalGrid):
        self.grid = grid

    def analyze(self) -> Dict:
        """Run full decision DNA analysis.

        Returns:
            Dict with decision-maker rankings, patterns, and insights
        """
        decisions = self._get_decisions()

        if not decisions:
            return {"total_decisions": 0, "message": "No decisions tracked yet"}

        return {
            "total_decisions": len(decisions),
            "decision_makers": self._rank_decision_makers(decisions),
            "topics": self._analyze_topics(decisions),
            "common_patterns": self._find_patterns(decisions),
            "success_rate": self._calculate_success_rate(decisions),
            "recommendations": self._generate_recommendations(decisions),
        }

    def track_outcome(self, decision_id: str, outcome: str,
                      outcome_value: float = 0) -> Dict:
        """Record the outcome of a past decision.

        Args:
            decision_id: The entry ID of the decision
            outcome: 'success', 'failure', 'neutral', or description
            outcome_value: Quantitative outcome measure ($ or hours)

        Returns:
            Dict with tracking result
        """
        entry = None
        if hasattr(self.grid, '_load_store'):
            self.grid._load_store()
            for e in self.grid._store.get("entries", []):
                if e["id"] == decision_id:
                    entry = e
                    break

        if not entry:
            return {"success": False, "reason": "Decision not found"}

        # Write outcome as a child entry
        content = (
            f"Decision Outcome\n"
            f"Decision ID: {decision_id}\n"
            f"Outcome: {outcome}\n"
            f"Value: {outcome_value}\n"
            f"Date: {datetime.datetime.now(datetime.timezone.utc).isoformat()}\n"
        )

        self.grid.write(
            agent_id="decision-dna",
            type="observation",
            content=content,
            tags=["decision-outcome", f"outcome:{outcome}"],
            parent_entry=decision_id,
            memory_tier="project",
        )

        return {"success": True, "decision_id": decision_id, "outcome": outcome}

    def get_maker_profile(self, agent_id: str) -> Dict:
        """Get a decision-making profile for a specific agent."""
        all_decisions = self._get_decisions()
        maker_decisions = [d for d in all_decisions
                           if d.get("agent_id") == agent_id]

        if not maker_decisions:
            return {"agent": agent_id, "total_decisions": 0}

        outcomes = self._get_outcomes([d["id"] for d in maker_decisions])
        success_count = sum(1 for o in outcomes.values() if o.get("outcome") == "success")
        total_outcomes = len(outcomes)

        top_tags = Counter()
        for d in maker_decisions:
            for t in d.get("tags", []):
                top_tags[t] += 1

        return {
            "agent": agent_id,
            "total_decisions": len(maker_decisions),
            "decisions_with_outcomes": total_outcomes,
            "success_count": success_count,
            "success_rate": success_count / total_outcomes * 100 if total_outcomes > 0 else 0,
            "top_topics": [t for t, _ in top_tags.most_common(5)],
            "recent_decisions": [
                {"content": d.get("content", "")[:100], "date": d.get("created_at", "")[:10]}
                for d in maker_decisions[-5:]
            ],
        }

    # ── Internal ──

    def _get_decisions(self) -> List[Dict]:
        result = self.grid.query(type="decision", max=500)
        return result.get("entries", [])

    def _get_outcomes(self, decision_ids: List[str]) -> Dict[str, Dict]:
        """Get outcomes for a set of decisions."""
        outcomes = {}
        for did in decision_ids:
            result = self.grid.query(parent_entry=did, max=10)
            for e in result.get("entries", []):
                content = e.get("content", "")
                for line in content.split("\n"):
                    if line.startswith("Outcome: "):
                        outcome = line.split(":", 1)[1].strip()
                        outcomes[did] = {"outcome": outcome, "entry": e}
        return outcomes

    def _rank_decision_makers(self, decisions: List[Dict]) -> List[Dict]:
        """Rank agents by decision-making success rate."""
        agent_decisions: Dict[str, List[Dict]] = defaultdict(list)
        for d in decisions:
            agent_decisions[d.get("agent_id", "unknown")].append(d)

        rankings = []
        for agent, d_list in agent_decisions.items():
            outcomes = self._get_outcomes([d["id"] for d in d_list])
            success_count = sum(1 for o in outcomes.values() if o.get("outcome") == "success")
            fail_count = sum(1 for o in outcomes.values() if o.get("outcome") == "failure")
            total = len(outcomes)

            rankings.append({
                "agent": agent,
                "total_decisions": len(d_list),
                "tracked_outcomes": total,
                "successes": success_count,
                "failures": fail_count,
                "success_rate": round(success_count / total * 100, 1) if total > 0 else 0,
                "outcome_coverage": round(total / len(d_list) * 100, 1) if d_list else 0,
            })

        rankings.sort(key=lambda x: -x["success_rate"])
        return rankings

    def _analyze_topics(self, decisions: List[Dict]) -> List[Dict]:
        """Analyze decision topics and their outcomes."""
        tag_outcomes: Dict[str, Dict] = defaultdict(lambda: {"total": 0, "success": 0, "failure": 0})

        for d in decisions:
            for t in d.get("tags", []):
                if t.startswith("agent:") or t.startswith("stage:"):
                    continue
                tag_outcomes[t]["total"] += 1

        topics = []
        for tag, stats in sorted(tag_outcomes.items(), key=lambda x: -x[1]["total"])[:20]:
            topics.append({
                "topic": tag,
                "total_decisions": stats["total"],
            })

        return topics

    def _find_patterns(self, decisions: List[Dict]) -> List[Dict]:
        """Find patterns in decision-making."""
        patterns = []

        # Look for decisions without rationale
        no_rationale = [d for d in decisions if "Rationale:" not in d.get("content", "")]
        if no_rationale:
            patterns.append({
                "pattern": "Decisions without documented rationale",
                "count": len(no_rationale),
                "percentage": round(len(no_rationale) / len(decisions) * 100, 1),
                "insight": f"{len(no_rationale)} decisions ({round(len(no_rationale) / len(decisions) * 100, 1)}%) lack rationale documentation",
                "recommendation": "Encourage documenting rationale for all decisions",
            })

        return patterns

    def _calculate_success_rate(self, decisions: List[Dict]) -> Dict:
        all_outcomes = self._get_outcomes([d["id"] for d in decisions])
        success = sum(1 for o in all_outcomes.values() if o.get("outcome") == "success")
        failure = sum(1 for o in all_outcomes.values() if o.get("outcome") == "failure")
        total = len(all_outcomes)

        return {
            "decisions_with_outcomes": total,
            "outcome_coverage": round(total / len(decisions) * 100, 1) if decisions else 0,
            "successes": success,
            "failures": failure,
            "success_rate": round(success / total * 100, 1) if total > 0 else 0,
        }

    def _generate_recommendations(self, decisions: List[Dict]) -> List[Dict]:
        recs = []
        # Check outcome coverage
        outcomes = self._get_outcomes([d["id"] for d in decisions])
        coverage = len(outcomes) / len(decisions) * 100 if decisions else 0
        if coverage < 50:
            recs.append({
                "priority": "high",
                "recommendation": f"Track outcomes for more decisions (currently {coverage:.0f}% coverage)",
                "expected_impact": "Better decision-maker rankings and pattern detection",
            })
        return recs
