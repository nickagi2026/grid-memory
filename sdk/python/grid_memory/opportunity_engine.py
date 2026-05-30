"""
opportunity_engine.py — End-to-end opportunity lifecycle with accuracy tracking.

Connects: Opportunity → Proposal → Project → Outcome → ROI
Tracks: win/loss reasons, accuracy, ranking, prioritization
"""

import datetime
import json
import re
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Any

from grid_memory.local_grid import LocalGrid
from grid_memory.opportunity_lifecycle import OpportunityLifecycle


class OpportunityEngine:
    """End-to-end opportunity management with tracking and analytics.

    Args:
        grid: LocalGrid instance
    """

    def __init__(self, grid: LocalGrid):
        self.grid = grid
        self.lifecycle = OpportunityLifecycle(grid)

    def link_proposal(self, opportunity_id: str, proposal_id: str) -> Dict:
        """Link an opportunity to its proposal."""
        entry = {"opportunity_id": opportunity_id, "proposal_id": proposal_id}
        content = f"Proposal linked\nOpportunity: {opportunity_id}\nProposal: {proposal_id}\nDate: {datetime.datetime.now(datetime.timezone.utc).isoformat()}"
        self.grid.write(agent_id="opp-engine", type="opportunity", content=content,
                        tags=["opportunity-link", "link:proposal", f"opportunity:{opportunity_id}"],
                        parent_entry=opportunity_id)
        return {"linked": True, "opportunity_id": opportunity_id, "proposal_id": proposal_id}

    def link_project(self, opportunity_id: str, project_id: str) -> Dict:
        """Link an opportunity to its project."""
        content = f"Project linked\nOpportunity: {opportunity_id}\nProject: {project_id}"
        self.grid.write(agent_id="opp-engine", type="opportunity", content=content,
                        tags=["opportunity-link", "link:project", f"opportunity:{opportunity_id}"],
                        parent_entry=opportunity_id)
        return {"linked": True, "opportunity_id": opportunity_id, "project_id": project_id}

    def track_win_loss(self, opportunity_id: str, result: str,
                       reason: str = "", revenue: float = 0) -> Dict:
        """Track win/loss with reason and revenue.

        Args:
            opportunity_id: The opportunity ID
            result: 'won' or 'lost'
            reason: Why it was won or lost
            revenue: Revenue if won, expected value if lost
        """
        if result == "won":
            self.lifecycle.advance(opportunity_id, "won", notes=f"Revenue: ${revenue:,.0f}. Reason: {reason}")
        elif result == "lost":
            self.lifecycle.advance(opportunity_id, "lost", notes=f"Lost value: ${revenue:,.0f}. Reason: {reason}")

        # Store win/loss detail
        entry_content = (
            f"Win/Loss Result\n"
            f"Opportunity: {opportunity_id}\n"
            f"Result: {result}\n"
            f"Reason: {reason}\n"
            f"Revenue: {revenue}\n"
            f"Date: {datetime.datetime.now(datetime.timezone.utc).isoformat()}\n"
        )
        self.grid.write(agent_id="opp-engine", type="observation", content=entry_content,
                        tags=["win-loss", f"result:{result}", f"opportunity:{opportunity_id}"],
                        parent_entry=opportunity_id)

        return {"recorded": True, "opportunity_id": opportunity_id, "result": result, "revenue": revenue}

    def track_roi(self, opportunity_id: str, actual_value: float,
                  actual_hours: int = 0, notes: str = "") -> Dict:
        """Track actual ROI achieved from a won opportunity."""
        # Get the original opportunity
        q = self.grid.query(parent_entry=opportunity_id, max=50)
        entries = q.get("entries", [])
        estimated_value = 0
        for e in entries:
            content = e.get("content", "")
            match = re.search(r'Estimated Annual Value:\s*\$?([\d,]+)', content)
            if match:
                estimated_value = float(match.group(1).replace(",", ""))

        accuracy = round(actual_value / estimated_value * 100, 1) if estimated_value > 0 else 0

        content = (
            f"ROI Achievement\n"
            f"Opportunity: {opportunity_id}\n"
            f"Estimated Value: ${estimated_value:,.0f}\n"
            f"Actual Value: ${actual_value:,.0f}\n"
            f"Accuracy: {accuracy}%\n"
            f"Actual Hours: {actual_hours}\n"
            f"Notes: {notes}\n"
            f"Date: {datetime.datetime.now(datetime.timezone.utc).isoformat()}\n"
        )
        self.grid.write(agent_id="opp-engine", type="observation", content=content,
                        tags=["roi", f"opportunity:{opportunity_id}", f"accuracy:{accuracy}"],
                        parent_entry=opportunity_id)

        self.lifecycle.advance(opportunity_id, "completed", notes=f"ROI: ${actual_value:,.0f} ({accuracy}% accuracy)")

        return {"recorded": True, "estimated": estimated_value, "actual": actual_value, "accuracy": accuracy}

    def get_opportunity_graph(self, opportunity_id: str) -> Dict:
        """Get the full graph for an opportunity: links, outcomes, ROI."""
        result = self.grid.query(parent_entry=opportunity_id, max=100)
        children = result.get("entries", [])

        links = []
        outcomes = []
        roi = None

        for c in children:
            content = c.get("content", "")
            tags = c.get("tags", [])
            if "Proposal linked" in content:
                links.append({"type": "proposal", "id": content.split("Proposal: ")[1].split("\n")[0] if "Proposal: " in content else ""})
            elif "Project linked" in content:
                links.append({"type": "project", "id": content.split("Project: ")[1].split("\n")[0] if "Project: " in content else ""})
            elif "Win/Loss Result" in content:
                res = "won" if "Result: won" in content else "lost"
                reason = ""
                for line in content.split("\n"):
                    if line.startswith("Reason: "): reason = line.split(":", 1)[1].strip()
                outcomes.append({"result": res, "reason": reason})
            elif "ROI Achievement" in content:
                acc_match = re.search(r'Accuracy: ([\d.]+)%', content)
                roi = {"accuracy": float(acc_match.group(1)) if acc_match else 0}

        return {"opportunity_id": opportunity_id, "links": links, "outcomes": outcomes, "roi": roi}

    def get_opportunity_analytics(self) -> Dict:
        """Get cross-opportunity analytics: win rate, accuracy, ranking."""
        result = self.grid.query(tags=["win-loss"], max=500)
        entries = result.get("entries", [])

        wins = 0
        losses = 0
        revenues = []
        reasons = Counter()
        total_revenue = 0

        for e in entries:
            content = e.get("content", "")
            if "Result: won" in content:
                wins += 1
                rev_match = re.search(r'Revenue: ([\d.]+)', content)
                if rev_match: revenues.append(float(rev_match.group(1)))
            elif "Result: lost" in content:
                losses += 1
            for line in content.split("\n"):
                if line.startswith("Reason: "):
                    reasons[line.split(":", 1)[1].strip()] += 1

        total_revenue = sum(revenues)

        # Get accuracy data
        roi_result = self.grid.query(tags=["roi"], max=500)
        roi_entries = roi_result.get("entries", [])
        accuracies = []
        for e in roi_entries:
            content = e.get("content", "")
            match = re.search(r'Accuracy: ([\d.]+)%', content)
            if match:
                accuracies.append(float(match.group(1)))

        avg_accuracy = round(sum(accuracies) / len(accuracies), 1) if accuracies else 0

        return {
            "total_outcomes": wins + losses,
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / (wins + losses) * 100, 1) if (wins + losses) > 0 else 0,
            "total_revenue": total_revenue,
            "avg_deal_size": round(total_revenue / wins, 2) if wins > 0 else 0,
            "avg_accuracy": avg_accuracy,
            "top_win_reasons": [r for r, _ in reasons.most_common(5)],
            "top_loss_reasons": [r for r, _ in reasons.most_common(5)],
        }

    def rank_opportunities(self, max_results: int = 20) -> Dict:
        """Rank open opportunities by priority score.

        Score factors: estimated value, confidence, stage, recency
        """
        result = self.grid.query(tags=["opportunity"], max=200)
        entries = result.get("entries", [])

        ranked = []
        for e in entries:
            content = e.get("content", "")
            stage = "detected"
            for t in e.get("tags", []):
                if t.startswith("stage:"):
                    stage = t.split(":", 1)[1]
            if stage in ("won", "lost", "completed"):
                continue

            value = 0
            conf = 0
            value_match = re.search(r'Estimated Annual Value:\s*\$?([\d,]+)', content)
            if value_match:
                value = float(value_match.group(1).replace(",", ""))

            stage_weights = {"detected": 0.3, "reviewed": 0.5, "accepted": 0.7, "assessment": 0.8, "proposed": 0.9}
            stage_weight = stage_weights.get(stage, 0.3)

            priority_score = value * stage_weight

            ranked.append({
                "id": e.get("id", ""),
                "content": content[:100],
                "stage": stage,
                "priority_score": round(priority_score, 0),
                "value": value,
            })

        ranked.sort(key=lambda x: -x["priority_score"])
        return {"ranked": ranked[:max_results], "total": len(ranked)}

    def summary(self) -> Dict:
        """Get full opportunity engine summary."""
        analytics = self.get_opportunity_analytics()
        pipeline = self.lifecycle.get_pipeline()

        return {
            "analytics": analytics,
            "pipeline": pipeline.get("summary", {}),
            "stage_counts": pipeline.get("stage_counts", {}),
            "by_stage": {
                s: pipeline.get("stage_counts", {}).get(s, 0)
                for s in ["detected", "reviewed", "accepted", "assessment", "proposed", "won", "lost", "completed"]
            },
        }
