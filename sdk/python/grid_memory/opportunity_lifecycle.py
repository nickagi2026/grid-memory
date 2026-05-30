"""
opportunity_lifecycle.py — Opportunity Lifecycle Pipeline.

Turns raw detected opportunities into revenue through a structured pipeline:

  Detected → Reviewed → Accepted → Assessment → Proposal → Won/Lost → ROI

Every stage links back to its parent via parent_entry, creating a traceable
chain from signal to outcome.
"""

import datetime
import json
import os
import re
import time
from typing import Dict, List, Optional, Any

from grid_memory.local_grid import LocalGrid

# ─── Lifecycle Stages ──────────────────────────────────────────────────────────

STAGES = [
    "detected",
    "reviewed",
    "accepted",
    "assessment",
    "proposed",
    "won",
    "lost",
    "completed",
]

STAGE_DISPLAY = {
    "detected": "\U0001f4e1 Detected",
    "reviewed": "\U0001f50d Reviewed",
    "accepted": "\u2705 Accepted",
    "assessment": "\U0001f4ca Assessment",
    "proposed": "\U0001f4dd Proposed",
    "won": "\U0001f3c6 Won",
    "lost": "\U0001f614 Lost",
    "completed": "\U0001f331 Completed",
}

STAGE_ICONS = {
    "detected": "\U0001f4e1",
    "reviewed": "\U0001f50d",
    "accepted": "\u2705",
    "assessment": "\U0001f4ca",
    "proposed": "\U0001f4dd",
    "won": "\U0001f3c6",
    "lost": "\U0001f614",
    "completed": "\U0001f331",
}

# Valid transitions
VALID_TRANSITIONS = {
    "detected": ["reviewed"],
    "reviewed": ["accepted", "lost"],
    "accepted": ["assessment", "lost"],
    "assessment": ["proposed", "lost"],
    "proposed": ["won", "lost"],
    "won": ["completed"],
    "lost": [],  # terminal
    "completed": [],  # terminal
}


# ─── Opportunity Lifecycle ────────────────────────────────────────────────────


class OpportunityLifecycle:
    """Manages the full lifecycle of an opportunity from detection to outcome.

    Args:
        grid: LocalGrid instance
    """

    def __init__(self, grid: LocalGrid):
        self.grid = grid

    def create_from_radar(self, radar_opportunity: Dict) -> Dict:
        """Create a lifecycle opportunity from a Radar detection.

        Args:
            radar_opportunity: Output dict from OpportunityRadar.scan()

        Returns:
            The created lifecycle opportunity dict
        """
        return self.create(
            title=radar_opportunity.get("title", "Unnamed opportunity"),
            description=radar_opportunity.get("evidence", ""),
            category=radar_opportunity.get("category", "unknown"),
            estimated_value=radar_opportunity.get("annual_value", 0),
            estimated_hours=radar_opportunity.get("hours_saved_per_year", 0),
            confidence=radar_opportunity.get("confidence", 0),
            source_id=radar_opportunity.get("id", ""),
            source="radar",
            department=radar_opportunity.get("department", "Engineering"),
            recommended_action=radar_opportunity.get("recommended_action", ""),
        )

    def create(self, title: str, description: str = "",
               category: str = "unknown",
               estimated_value: float = 0,
               estimated_hours: int = 0,
               confidence: float = 0,
               source_id: str = "",
               source: str = "manual",
               department: str = "Engineering",
               recommended_action: str = "",
               client: str = "",
               tags: Optional[List[str]] = None) -> Dict:
        """Create a new opportunity in the 'detected' stage."""
        all_tags = (tags or []) + [
            "opportunity",
            f"stage:detected",
            f"source:{source}",
            f"dept:{department}",
        ]
        if client:
            all_tags.append(f"client:{client}")

        content = self._build_content(
            title=title,
            description=description,
            category=category,
            estimated_value=estimated_value,
            estimated_hours=estimated_hours,
            confidence=confidence,
            source_id=source_id,
            source=source,
            department=department,
            recommended_action=recommended_action,
            client=client,
            stage="detected",
        )

        result = self.grid.write(
            agent_id="opportunity-lifecycle",
            type="opportunity",
            content=content,
            tags=all_tags,
            memory_tier="project",
        )

        return {
            "id": result["entry_id"],
            "title": title,
            "stage": "detected",
            "created_at": result["created_at"],
            "entry_id": result["entry_id"],
        }

    def advance(self, opportunity_id: str, to_stage: str,
                notes: str = "",
                metadata: Optional[Dict] = None) -> Dict:
        """Advance an opportunity to the next stage.

        Args:
            opportunity_id: The entry ID of the opportunity
            to_stage: Target stage
            notes: Notes about this transition
            metadata: Additional metadata (e.g. assessment_id, proposal_id)

        Returns:
            Dict with success status, new stage, previous stage
        """
        # Get the current opportunity entry
        entry = self._get_entry(opportunity_id)
        if not entry:
            return {"success": False, "reason": "Opportunity not found"}

        current_stage = self._extract_stage(entry)

        if to_stage not in VALID_TRANSITIONS.get(current_stage, []):
            return {
                "success": False,
                "reason": f"Cannot transition from '{current_stage}' to '{to_stage}'",
                "current_stage": current_stage,
                "allowed": VALID_TRANSITIONS.get(current_stage, []),
            }

        # Update the original entry's content to reflect new stage
        updated_content = entry.get("content", "")
        if notes:
            updated_content += f"\n\n---\nTransition: {current_stage} → {to_stage}\nDate: {datetime.datetime.now(datetime.timezone.utc).isoformat()}\nNotes: {notes}"

        # Write a transition event (links to parent via parent_entry)
        transition_content = (
            f"[Opportunity] {current_stage} → {to_stage}\n"
            f"Opportunity ID: {opportunity_id}\n"
            f"Date: {datetime.datetime.now(datetime.timezone.utc).isoformat()}\n"
        )
        if notes:
            transition_content += f"Notes: {notes}\n"
        if metadata:
            transition_content += json.dumps(metadata, indent=2)

        self.grid.write(
            agent_id="opportunity-lifecycle",
            type="opportunity",
            content=transition_content,
            tags=[
                "opportunity",
                f"stage:{to_stage}",
                f"transition:{current_stage}_{to_stage}",
            ],
            parent_entry=opportunity_id,
            memory_tier="project",
        )

        # Update the original entry's stage tag in-place (direct store modification)
        old_tags = list(entry.get("tags", []))
        new_tags = []
        for t in old_tags:
            if t.startswith("stage:"):
                if t != f"stage:{to_stage}":
                    new_tags.append(f"stage:{to_stage}")
                else:
                    new_tags.append(t)
            else:
                new_tags.append(t)
        if not any(t.startswith("stage:") for t in new_tags):
            new_tags.append(f"stage:{to_stage}")

        # Write a new version entry with the updated stage (original remains immutable)
        # The current stage is always derived from the latest child entry -> original fallback
        self.grid.write(
            agent_id="opportunity-lifecycle",
            type="opportunity",
            content=updated_content,
            tags=new_tags,
            parent_entry=opportunity_id,
            memory_tier="project",
        )

        return {
            "success": True,
            "opportunity_id": opportunity_id,
            "from_stage": current_stage,
            "to_stage": to_stage,
            "notes": notes,
        }

    def get_pipeline(self, stage: Optional[str] = None,
                     client: Optional[str] = None,
                     department: Optional[str] = None) -> Dict:
        """Get the current opportunity pipeline.

        Args:
            stage: Filter by stage
            client: Filter by client
            department: Filter by department

        Returns:
            Dict with pipeline summary and opportunities by stage
        """
        query_tags = ["opportunity"]
        if stage:
            query_tags.append(f"stage:{stage}")
        if client:
            query_tags.append(f"client:{client}")
        if department:
            query_tags.append(f"dept:{department}")

        result = self.grid.query(tags=query_tags, max=200)
        entries = result.get("entries", [])

        # Group by stage
        by_stage: Dict[str, List[Dict]] = {s: [] for s in STAGES}
        for entry in entries:
            s = self._extract_stage(entry)
            if s in by_stage:
                by_stage[s].append(self._format_entry(entry))

        # Calculate totals
        total_value = 0
        for s, items in by_stage.items():
            for item in items:
                val = item.get("estimated_value", 0) or 0
                total_value += val

        pipeline = {}
        for s in STAGES:
            items = by_stage.get(s, [])
            if items:
                pipeline[s] = {
                    "count": len(items),
                    "total_value": sum(
                        i.get("estimated_value", 0) or 0 for i in items
                    ),
                    "items": items[:10],
                }

        return {
            "pipeline": pipeline,
            "summary": {
                "total_opportunities": len(entries),
                "total_pipeline_value": total_value,
                "by_stage": {
                    s: len(by_stage.get(s, [])) for s in STAGES
                },
            },
            "stage_counts": {s: len(by_stage.get(s, [])) for s in STAGES},
        }

    def get_history(self, opportunity_id: str) -> Dict:
        """Get the full transition history for an opportunity."""
        # Get the original entry
        original = self._get_entry(opportunity_id)
        if not original:
            return {"success": False, "reason": "Opportunity not found"}

        # Query all child entries
        result = self.grid.query(parent_entry=opportunity_id, max=50)
        children = result.get("entries", [])

        # Build timeline
        timeline = [self._format_entry(original)]
        timeline.extend(self._format_entry(c) for c in children)
        timeline.sort(key=lambda x: x.get("created_at", ""))

        return {
            "success": True,
            "opportunity_id": opportunity_id,
            "title": self._extract_title(original),
            "stage": self._extract_stage(original),
            "timeline": timeline,
            "transitions": len(children),
        }

    def get_stats(self) -> Dict:
        """Get lifecycle statistics."""
        result = self.grid.query(tags=["opportunity"], max=500)
        entries = result.get("entries", [])

        won_value = 0
        lost_value = 0
        won_count = 0
        lost_count = 0

        for entry in entries:
            stage = self._extract_stage(entry)
            value = self._extract_value(entry)
            if stage == "won":
                won_value += value
                won_count += 1
            elif stage == "lost":
                lost_value += value
                lost_count += 1

        return {
            "total_opportunities": len(entries),
            "won": {"count": won_count, "total_value": won_value},
            "lost": {"count": lost_count, "total_value": lost_value},
            "win_rate": won_count / (won_count + lost_count) * 100 if (won_count + lost_count) > 0 else 0,
            "pipeline_value": self._get_pipeline_value(entries),
        }

    # ── Internal Helpers ──

    def _build_content(self, **kwargs) -> str:
        """Build structured content for an opportunity entry."""
        parts = [
            f"Title: {kwargs.get('title', '')}",
            f"Category: {kwargs.get('category', '')}",
            f"Department: {kwargs.get('department', '')}",
            f"Stage: {kwargs.get('stage', 'detected')}",
            f"Estimated Annual Value: ${kwargs.get('estimated_value', 0):,.0f}",
            f"Estimated Hours Saved: {kwargs.get('estimated_hours', 0)}/yr",
            f"Confidence: {kwargs.get('confidence', 0):.0%}",
            f"Source: {kwargs.get('source', 'manual')}",
        ]
        if kwargs.get("source_id"):
            parts.append(f"Source ID: {kwargs.get('source_id', '')}")
        if kwargs.get("client"):
            parts.append(f"Client: {kwargs.get('client', '')}")
        if kwargs.get("description"):
            parts.append(f"\nDescription:\n{kwargs.get('description', '')}")
        if kwargs.get("recommended_action"):
            parts.append(f"\nRecommended Action:\n{kwargs.get('recommended_action', '')}")
        return "\n".join(parts)

    def _get_entry(self, entry_id: str) -> Optional[Dict]:
        """Get a single entry from the store.
        Uses the public query API to avoid direct _store access.
        """
        # Use the public query API
        try:
            result = self.grid.query(max=200)
            for e in result.get("entries", []):
                if e["id"] == entry_id:
                    return e
        except Exception:
            pass
        return None

    def _extract_stage(self, entry: Dict) -> str:
        """Extract the lifecycle stage from entry tags.

        First checks children (transitions) for the latest stage,
        then falls back to the entry's own tags.
        Uses the public query API to avoid direct _store access.
        """
        # Check children for the latest stage (immutable approach)
        eid = entry.get("id", "")
        if eid:
            try:
                children = self.grid.query(parent_entry=eid, max=50)
                children_entries = children.get("entries", [])
                if children_entries:
                    children_entries.sort(key=lambda x: x.get("created_at", ""), reverse=True)
                    for child in children_entries:
                        for t in child.get("tags", []):
                            if t.startswith("stage:"):
                                return t.split(":", 1)[1]
            except Exception:
                pass

        # Fallback: check the entry's own tags
        tags = entry.get("tags", [])
        for t in tags:
            if t.startswith("stage:"):
                return t.split(":", 1)[1]

        return "detected"

    def _extract_title(self, entry: Dict) -> str:
        """Extract the title from entry content."""
        content = entry.get("content", "")
        for line in content.split("\n"):
            if line.startswith("Title:"):
                return line.split(":", 1)[1].strip()
        return "Untitled"

    def _extract_value(self, entry: Dict) -> float:
        """Extract estimated value from entry content."""
        content = entry.get("content", "")
        match = re.search(r'Estimated Annual Value:\s*\$?([\d,]+)', content)
        if match:
            return float(match.group(1).replace(",", ""))
        return 0

    def _format_entry(self, entry: Dict) -> Dict:
        """Format an entry for API/display."""
        return {
            "id": entry.get("id", ""),
            "agent_id": entry.get("agent_id", ""),
            "type": entry.get("type", ""),
            "tags": entry.get("tags", []),
            "content": entry.get("content", ""),
            "created_at": entry.get("created_at", ""),
            "parent_entry": entry.get("parent_entry"),
            "stage": self._extract_stage(entry),
            "title": self._extract_title(entry),
            "estimated_value": self._extract_value(entry),
        }

    def _get_pipeline_value(self, entries: List[Dict]) -> float:
        """Calculate total pipeline value."""
        total = 0
        for entry in entries:
            stage = self._extract_stage(entry)
            if stage not in ("won", "lost", "completed"):
                total += self._extract_value(entry)
        return total


# ─── CLI Integration ───────────────────────────────────────────────────────────


def cmd_opportunity(args):
    """Manage opportunity lifecycle."""
    from grid_memory.opportunity_lifecycle import OpportunityLifecycle
    grid = _get_grid(args)
    lifecycle = OpportunityLifecycle(grid)

    action = args.opp_action

    if action == "list":
        stage = args.stage
        result = lifecycle.get_pipeline(stage=stage)
        pipeline = result.get("pipeline", {})
        summary = result.get("summary", {})

        print(f"\n  {_c('bold', 'Opportunity Pipeline')}")
        print(f"  {'─' * 50}")
        print(f"  Total: {summary.get('total_opportunities', 0)} opportunities"
              f"  |  Pipeline Value: ${summary.get('total_pipeline_value', 0):,.0f}")
