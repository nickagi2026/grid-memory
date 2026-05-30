"""
dashboards.py — Business intelligence dashboards: executive, revenue, expansion, portfolio, proposals.

All derived from the Grid's existing data — no additional data sources required.
"""

import datetime
import json
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Any

from grid_memory.local_grid import LocalGrid
from grid_memory.workspace import WorkspaceManager


class ExecutiveDashboard:
    """C-suite view: revenue, opportunities, risks, trends."""

    def __init__(self, grid: LocalGrid, client: str = ""):
        self.grid = grid
        self.client = client

    def generate(self) -> Dict:
        entries = self.grid.query(max=500).get("entries", [])
        info = self.grid.info()

        by_type = Counter(e.get("type") for e in entries)
        by_agent = Counter(e.get("agent_id") for e in entries if e.get("agent_id"))
        stages = Counter()
        for e in entries:
            for t in e.get("tags", []):
                if t.startswith("stage:"): stages[t.split(":",1)[1]] += 1

        return {
            "period": "Last 90 days",
            "total_entries": info.get("total_entries", 0),
            "active_agents": info.get("unique_agents", 0),
            "activity_by_type": dict(by_type.most_common(8)),
            "top_agents": [{"agent": a, "count": c} for a, c in by_agent.most_common(5)],
            "pipeline_stages": dict(stages),
            "client": self.client,
        }


class RevenueDashboard:
    """Revenue view: won/lost, pipeline value, ROI accuracy."""

    def __init__(self, grid: LocalGrid):
        self.grid = grid

    def generate(self) -> Dict:
        from grid_memory.opportunity_engine import OpportunityEngine
        oe = OpportunityEngine(self.grid)
        analytics = oe.get_opportunity_analytics()
        summary = oe.summary()

        return {
            "total_revenue": analytics.get("total_revenue", 0),
            "avg_deal_size": analytics.get("avg_deal_size", 0),
            "win_rate": analytics.get("win_rate", 0),
            "avg_accuracy": analytics.get("avg_accuracy", 0),
            "pipeline_value": summary.get("pipeline", {}).get("total_pipeline_value", 0),
            "won_count": analytics.get("wins", 0),
            "loss_count": analytics.get("losses", 0),
        }


class ExpansionDashboard:
    """Expansion opportunities identified across clients."""

    def __init__(self, mgr: WorkspaceManager):
        self.mgr = mgr

    def generate(self) -> Dict:
        total_value = 0
        client_opps = []
        for ws in self.mgr.list():
            try:
                grid = self.mgr.get_grid(ws["id"])
                opps = grid.query(tags=["opportunity", "stage:won"], max=20)
                lessons = grid.query(tags=["lesson"], max=20)
                won = [e for e in opps.get("entries", []) if "stage:won" in e.get("tags", [])]
                client_opps.append({
                    "client": ws["id"],
                    "won_opportunities": len(won),
                    "lessons": len(lessons.get("entries", [])),
                    "last_activity": ws.get("last_activity", ""),
                })
            except: pass
        return {"clients": client_opps, "total": len(client_opps)}


class PortfolioDashboard:
    """Portfolio view: all clients, their health, and trends."""

    def __init__(self, mgr: WorkspaceManager):
        self.mgr = mgr

    def generate(self) -> Dict:
        clients = []
        for ws in self.mgr.list():
            try:
                grid = self.mgr.get_grid(ws["id"])
                info = grid.info()
                clients.append({
                    "id": ws["id"],
                    "entries": info.get("total_entries", 0),
                    "agents": info.get("unique_agents", 0),
                    "tags": info.get("unique_tags", 0),
                })
            except: pass
        return {"clients": clients, "total": len(clients)}


class ProposalDashboard:
    """Proposal pipeline view."""

    def __init__(self, grid: LocalGrid):
        self.grid = grid

    def generate(self) -> Dict:
        proposed = self.grid.query(tags=["stage:proposed"], max=50)
        assessing = self.grid.query(tags=["stage:assessment"], max=50)
        return {
            "in_proposal": len(proposed.get("entries", [])),
            "in_assessment": len(assessing.get("entries", [])),
        }
