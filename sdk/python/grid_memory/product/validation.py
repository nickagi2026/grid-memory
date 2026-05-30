import datetime
"""
validation.py — Opportunity Validation Workflow.

Turns raw detected opportunities into validated, priced proposals.
Each opportunity passes through validation gates before advancing.

Gates:
  Detected → Triage → Validated → Scoped → Priced → Proposed → Won/Lost
"""

from typing import Dict, List, Optional, Any
from grid_memory.local_grid import LocalGrid
from grid_memory.opportunity_lifecycle import OpportunityLifecycle

GATES = ["triage", "validated", "scoped", "priced", "proposed"]
GATE_LABELS = {
    "triage": "Initial triage — quick viability check",
    "validated": "Validated with client need",
    "scoped": "Scope defined and resources estimated",
    "priced": "Priced with business case",
    "proposed": "Proposal delivered to client",
}


class ValidationWorkflow:
    """Validates opportunities through structured gates before they become proposals.

    Args:
        grid: LocalGrid instance
    """

    def __init__(self, grid: LocalGrid):
        self.grid = grid
        self.lifecycle = OpportunityLifecycle(grid)

    def validate(self, opportunity_id: str, gate: str,
                 validator: str = "", notes: str = "") -> Dict:
        """Pass an opportunity through a validation gate.

        Args:
            opportunity_id: Opportunity entry ID
            gate: Validation gate (triage, validated, scoped, priced, proposed)
            validator: Who validated it
            notes: Validation notes

        Returns:
            Dict with validation result
        """
        if gate not in GATES:
            return {"success": False, "reason": f"Unknown gate: {gate}. Valid: {', '.join(GATES)}"}

        content = (
            f"Validation Gate: {gate}\n"
            f"Opportunity: {opportunity_id}\n"
            f"Validator: {validator or 'system'}\n"
            f"Notes: {notes}\n"
            f"Date: {datetime.datetime.now(datetime.timezone.utc).isoformat()}\n"
        )

        self.grid.write(
            agent_id=validator or "validation-workflow",
            type="observation",
            content=content,
            tags=["validation", f"gate:{gate}", f"opportunity:{opportunity_id}"],
            parent_entry=opportunity_id,
            memory_tier="project",
        )

        # Auto-advance lifecycle when validated
        if gate in ("triage", "validated"):
            self.lifecycle.advance(opportunity_id, "accepted", notes=f"Gate: {gate}")
        elif gate == "scoped":
            self.lifecycle.advance(opportunity_id, "assessment", notes=f"Gate: {gate}")
        elif gate in ("priced", "proposed"):
            self.lifecycle.advance(opportunity_id, "proposed", notes=f"Gate: {gate}")

        return {"success": True, "gate": gate, "opportunity_id": opportunity_id}

    def get_pending(self) -> Dict:
        """Get all opportunities pending validation."""
        result = self.grid.query(tags=["opportunity"], max=200)
        entries = result.get("entries", [])

        pending = []
        for e in entries:
            tags = e.get("tags", [])
            stage = "detected"
            for t in tags:
                if t.startswith("stage:"):
                    stage = t.split(":", 1)[1]

            if stage in ("detected", "reviewed"):
                pending.append({
                    "id": e.get("id", ""),
                    "content": e.get("content", "")[:100],
                    "stage": stage,
                    "next_gate": "triage" if stage == "detected" else "validated",
                })

        return {"pending": pending, "total": len(pending)}

    def get_pipeline(self) -> Dict:
        """Get the full validation pipeline summary."""
        result = self.grid.query(tags=["validation"], max=200)
        entries = result.get("entries", [])

        by_gate: Dict[str, int] = {}
        for e in entries:
            for t in e.get("tags", []):
                if t.startswith("gate:"):
                    gate = t.split(":", 1)[1]
                    by_gate[gate] = by_gate.get(gate, 0) + 1

        return {"by_gate": by_gate, "total_validations": len(entries)}


