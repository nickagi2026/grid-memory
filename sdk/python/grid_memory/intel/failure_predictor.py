"""
# BETA MODULE - Heuristic pattern matching, not ML. Results are directional indicators, not definitive.
# Confidence caveat: Value estimates use simplified models. Human review required before action.

failure_predictor.py — Future Failure Predictor™

Analyzes past failed projects to predict failure probability of current projects.
"Similar to Projects Atlas, Mercury, and Delta. Failure probability: 72%."
"""

import datetime
import json
import re
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Any

from grid_memory.local_grid import LocalGrid


class FailurePredictor:
    """Predicts project failure probability based on historical patterns.

    Args:
        grid: LocalGrid instance
    """

    def __init__(self, grid: LocalGrid):
        self.grid = grid

    def predict(self, project_tags: List[str] = None) -> Dict:
        """Predict failure probability for a project based on tags.

        Args:
            project_tags: Tags describing the current project

        Returns:
            Dict with prediction, similar past projects, and risk factors
        """
        entries = self.grid.query(max=500).get("entries", [])

        # Find past failures (blockers, lost opportunities, failed tasks)
        past_failures = [e for e in entries if e.get("type") in ("blocker", "task_status")
                        and any(w in e.get("content", "").lower() for w in ["fail", "error", "crash", "outage"])]

        # Find successful patterns
        past_successes = [e for e in entries if e.get("type") == "decision"
                         and "Rationale:" in e.get("content", "")]

        # Calculate risk factors based on signal ratios
        risk_factors = self._calculate_risk_factors(past_failures, past_successes, project_tags or [])

        # Calculate overall failure probability
        base_probability = 30  # baseline
        for factor in risk_factors:
            base_probability += factor.get("risk_contribution", 0)

        probability = min(max(base_probability, 5), 95)

        # Find similar past projects
        similar = self._find_similar(past_failures, project_tags or [])

        return {
            "failure_probability": probability,
            "similar_failed_projects": similar[:3],
            "risk_factors": risk_factors[:5],
            "confidence": round(min(len(past_failures) * 2, 85), 0),
        }

    def _calculate_risk_factors(self, failures: List[Dict],
                                 successes: List[Dict],
                                 tags: List[str]) -> List[Dict]:
        factors = []

        # Check blocker-to-decision ratio
        if len(failures) > len(successes) * 2 and len(successes) > 0:
            factors.append({
                "factor": "High blocker-to-decision ratio",
                "risk_contribution": 15,
                "evidence": f"{len(failures)} blockers vs {len(successes)} decisions",
            })

        # Check for shared tags with past failures
        if tags:
            failure_tags: Counter = Counter()
            for b in failures:
                for t in b.get("tags", []):
                    failure_tags[t] += 1
            shared = [t for t in tags if t in failure_tags]
            if shared:
                factors.append({
                    "factor": f"Similar tags to past failures: {', '.join(shared[:3])}",
                    "risk_contribution": 10,
                    "evidence": f"Tags {shared} appear in {sum(failure_tags[t] for t in shared)} prior incidents",
                })

        # Time-based risk: more recent failures = higher risk
        recent = [f for f in failures if f.get("created_at", "") >= (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30)).isoformat()]
        if len(recent) >= 3:
            factors.append({
                "factor": f"{len(recent)} recent failures in last 30 days",
                "risk_contribution": 10,
                "evidence": "Recency indicates systemic issues may persist",
            })

        return factors

    def _find_similar(self, failures: List[Dict], tags: List[str]) -> List[Dict]:
        if not tags or not failures:
            return []
        similar = []
        for b in failures:
            shared = [t for t in tags if t in b.get("tags", [])]
            if shared:
                similar.append({
                    "content": b.get("content", "")[:100],
                    "date": b.get("created_at", "")[:10],
                    "shared_tags": shared,
                    "agent": b.get("agent_id", ""),
                })
        return similar[:3]
