"""
expansion.py — Expansion Score engine.

Calculates a scored expansion opportunity for each client based on:
- Recent activity (engagement level)
- Number of lessons learned (knowledge depth)
- Won opportunities (proven value delivery)
- Open opportunities (active pipeline)
- Patterns detected (repeatable value)
"""

import datetime
from typing import Dict, List, Optional, Any
from grid_memory.local_grid import LocalGrid


class ExpansionScore:
    """Calculates expansion opportunity scores for clients.

    Args:
        grid: LocalGrid instance for a specific client workspace
        client_id: Client identifier
    """

    def __init__(self, grid: LocalGrid, client_id: str = ""):
        self.grid = grid
        self.client_id = client_id

    def calculate(self) -> Dict:
        """Calculate expansion score for this client."""
        entries = self.grid.query(max=500).get("entries", [])
        info = self.grid.info()

        # Factors
        total_entries = info.get("total_entries", 0)
        unique_agents = info.get("unique_agents", 0)

        # Count won opportunities
        won = [e for e in entries if "stage:won" in e.get("tags", [])]
        open_opps = [e for e in entries if any(t.startswith("stage:") for t in e.get("tags", []))
                     and not any(t in ("stage:won", "stage:lost", "stage:completed") for t in e.get("tags", []))]
        lessons = [e for e in entries if "lesson" in e.get("tags", [])]

        # Recency
        recent = sum(1 for e in entries if e.get("created_at", "") >=
                     (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30)).isoformat())

        # Score components (0-100 each)
        engagement_score = min(recent * 10, 100)
        depth_score = min(total_entries * 2, 100)
        delivery_score = min(len(won) * 25, 100)
        pipeline_score = min(len(open_opps) * 20, 100)
        learning_score = min(len(lessons) * 15, 100)

        overall = round((engagement_score + depth_score + delivery_score + pipeline_score + learning_score) / 5, 1)

        return {
            "client": self.client_id,
            "overall_score": overall,
            "level": "high" if overall >= 70 else ("medium" if overall >= 40 else "low"),
            "components": {
                "engagement": {"score": engagement_score, "detail": f"{recent} activities in last 30 days"},
                "knowledge_depth": {"score": depth_score, "detail": f"{total_entries} total entries"},
                "proven_delivery": {"score": delivery_score, "detail": f"{len(won)} won opportunities"},
                "active_pipeline": {"score": pipeline_score, "detail": f"{len(open_opps)} open opportunities"},
                "organizational_learning": {"score": learning_score, "detail": f"{len(lessons)} lessons captured"},
            },
            "recommendation": self._recommend(overall, won, lessons),
        }

    def _recommend(self, score: float, won: List, lessons: List) -> str:
        if score >= 70:
            return "Strong expansion candidate. Schedule executive QBR and present next-phase opportunities."
        elif score >= 40:
            return "Moderate engagement. Deepen relationship through lessons review and targeted opportunity surfacing."
        return "Early stage. Focus on delivering initial value and capturing lessons."
