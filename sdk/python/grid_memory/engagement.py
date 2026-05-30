"""
engagement.py — Engagement Graph & QBR Generator.

Links every interaction across a client's journey:
  Discovery → Assessment → Proposal → Build → Deploy → Retain → Expansion

Generates Quarterly Business Reviews automatically from Grid data.
"""

import datetime
import json
import re
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Any

from grid_memory.local_grid import LocalGrid

# ─── Engagement Phases ─────────────────────────────────────────────────────────

PHASES = ["discovery", "assessment", "proposal", "build", "deploy", "operate", "expand"]
PHASE_LABELS = {
    "discovery": "Discovery", "assessment": "Assessment", "proposal": "Proposal",
    "build": "Build", "deploy": "Deploy", "operate": "Operate", "expand": "Expand",
}


class EngagementGraph:
    """Tracks client engagements across their lifecycle.

    Args:
        grid: LocalGrid instance
    """

    def __init__(self, grid: LocalGrid):
        self.grid = grid

    def track(self, client: str, phase: str,
              activity: str, detail: str = "",
              agent: str = "") -> Dict:
        """Record an activity in a client engagement.

        Args:
            client: Client identifier
            phase: Engagement phase
            activity: What happened
            detail: Details about the activity
            agent: Who performed it

        Returns:
            Dict with engagement record
        """
        content = (
            f"Engagement Activity [{client}]\n"
            f"Phase: {phase}\n"
            f"Activity: {activity}\n"
            f"Detail: {detail}\n"
            f"Date: {datetime.datetime.now(datetime.timezone.utc).isoformat()}\n"
        )

        result = self.grid.write(
            agent_id=agent or "engagement-graph",
            type="engagement",
            content=content,
            tags=["engagement", f"client:{client}", f"phase:{phase}"],
            memory_tier="organization",
        )

        return {"id": result["entry_id"], "client": client, "phase": phase}

    def get_engagement(self, client: str) -> Dict:
        """Get the full engagement timeline for a client."""
        result = self.grid.query(tags=["engagement", f"client:{client}"], max=500)
        entries = result.get("entries", [])

        by_phase: Dict[str, List] = defaultdict(list)
        all_activities = []

        for e in entries:
            content = e.get("content", "")
            phase = "unknown"
            activity = ""
            for line in content.split("\n"):
                if line.startswith("Phase: "):
                    phase = line.split(":", 1)[1].strip()
                elif line.startswith("Activity: "):
                    activity = line.split(":", 1)[1].strip()

            item = {
                "id": e.get("id"),
                "phase": phase,
                "activity": activity,
                "agent": e.get("agent_id"),
                "created_at": e.get("created_at"),
            }
            by_phase[phase].append(item)
            all_activities.append(item)

        return {
            "client": client,
            "total_activities": len(all_activities),
            "phases_involved": sorted(by_phase.keys()),
            "by_phase": dict(by_phase),
            "timeline": sorted(all_activities, key=lambda x: x.get("created_at", "")),
            "current_phase": sorted(by_phase.keys())[-1] if by_phase else "none",
        }

    def get_all_clients(self) -> Dict:
        """Get a summary of all tracked clients."""
        result = self.grid.query(tags=["engagement"], max=1000)
        entries = result.get("entries", [])

        client_phases: Dict[str, set] = defaultdict(set)
        client_activities: Dict[str, int] = Counter()
        client_last: Dict[str, str] = {}

        for e in entries:
            for t in e.get("tags", []):
                if t.startswith("client:"):
                    cid = t.split(":", 1)[1]
                    client_activities[cid] += 1
                    for pt in e.get("tags", []):
                        if pt.startswith("phase:"):
                            client_phases[cid].add(pt.split(":", 1)[1])
                    created = e.get("created_at", "")
                    if created > client_last.get(cid, ""):
                        client_last[cid] = created

        clients = []
        for cid in sorted(client_phases.keys()):
            phases = sorted(client_phases[cid])
            clients.append({
                "client": cid,
                "total_activities": client_activities[cid],
                "phases": phases,
                "current": phases[-1] if phases else "none",
                "last_activity": client_last.get(cid, ""),
            })

        return {"clients": clients, "total": len(clients)}

    def generate_qbr(self, client: str, quarter: str = "",
                     include_stats: bool = True) -> Dict:
        """Generate a Quarterly Business Review for a client.

        Args:
            client: Client identifier
            quarter: Quarter label (e.g. "Q2 2026")
            include_stats: Include engagement stats

        Returns:
            Dict with QBR content ready for rendering
        """
        engagement = self.get_engagement(client)
        lessons_engine = self.grid  # We'll query lessons directly

        # Get lessons for this client
        lessons_result = self.grid.query(
            tags=["lesson", f"client:{client}"], max=100
        )
        lessons = lessons_result.get("entries", [])

        # Get opportunities for this client
        opps_result = self.grid.query(
            tags=["opportunity", f"client:{client}"], max=100
        )
        opportunities = opps_result.get("entries", [])

        # Get decisions
        decisions_result = self.grid.query(
            tags=[f"client:{client}"], type="decision", max=50
        )
        decisions = decisions_result.get("entries", [])

        # Count by type for stats
        if include_stats:
            all_client = self.grid.query(tags=[f"client:{client}"], max=1000)
            all_entries = all_client.get("entries", [])
            type_counts = Counter(e.get("type", "unknown") for e in all_entries)
        else:
            type_counts = {}

        # Determine period
        if not quarter:
            quarter = f"Q{(datetime.datetime.now(datetime.timezone.utc).month - 1) // 3 + 1} {datetime.datetime.now(datetime.timezone.utc).year}"

        # Build QBR
        qbr = {
            "client": client,
            "quarter": quarter,
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "summary": {
                "total_activities": engagement["total_activities"],
                "phases_active": len(engagement["phases_involved"]),
                "current_phase": engagement["current_phase"],
                "lessons_learned": len(lessons),
                "opportunities_identified": len(opportunities),
                "key_decisions": len(decisions),
            },
            "timeline": [
                {"phase": item["phase"], "activity": item["activity"],
                 "date": item["created_at"][:10]}
                for item in engagement.get("timeline", [])[-20:]
            ],
            "lessons": [
                {"content": e.get("content", "")[:200], "date": e.get("created_at", "")[:10]}
                for e in lessons[-10:]
            ],
            "opportunities": [
                {"content": e.get("content", "")[:200], "stage": self._extract_stage(e)}
                for e in opportunities[-10:]
            ],
            "decisions": [
                {"content": e.get("content", "")[:200], "date": e.get("created_at", "")[:10]}
                for e in decisions[-10:]
            ],
            "stats": dict(type_counts.most_common(10)) if type_counts else {},
            "metrics": {
                "activities_per_phase": {
                    p: engagement["by_phase"].get(p, [])
                    for p in PHASES if engagement["by_phase"].get(p)
                }
            },
        }

        return qbr

    def format_qbr_report(self, qbr: Dict) -> str:
        """Format a QBR as human-readable text."""
        lines = [
            f"\n{'=' * 60}",
            f"  QUARTERLY BUSINESS REVIEW",
            f"  Client: {qbr['client']}",
            f"  Quarter: {qbr['quarter']}",
            f"  Generated: {qbr['generated_at'][:10]}",
            f"{'=' * 60}",
            "",
            f"  SUMMARY",
            f"  {'-' * 40}",
            f"  Activities:     {qbr['summary']['total_activities']}",
            f"  Phases Active:  {qbr['summary']['phases_active']}",
            f"  Current Phase:  {qbr['summary']['current_phase']}",
            f"  Lessons:        {qbr['summary']['lessons_learned']}",
            f"  Opportunities:  {qbr['summary']['opportunities_identified']}",
            f"  Key Decisions:  {qbr['summary']['key_decisions']}",
        ]

        if qbr.get("timeline"):
            lines.extend(["", "  TIMELINE", "  " + "-" * 40])
            for item in qbr["timeline"][-10:]:
                phase = item.get("phase", "?").capitalize()
                date = item.get("date", "?")
                activity = item.get("activity", "")[:60]
                lines.append(f"  [{phase}] {date} — {activity}")

        if qbr.get("lessons"):
            lines.extend(["", "  LESSONS LEARNED", "  " + "-" * 40])
            for l in qbr["lessons"][-5:]:
                lines.append(f"  \u2022 {l['content'][:80]}")

        if qbr.get("opportunities"):
            lines.extend(["", "  OPPORTUNITIES", "  " + "-" * 40])
            for o in qbr["opportunities"][-5:]:
                stage = o.get("stage", "detected")
                lines.append(f"  [{stage}] {o['content'][:80]}")

        if qbr.get("decisions"):
            lines.extend(["", "  KEY DECISIONS", "  " + "-" * 40])
            for d in qbr["decisions"][-5:]:
                lines.append(f"  \u2022 {d['content'][:80]}")

        if qbr.get("stats"):
            lines.extend(["", "  ACTIVITY BREAKDOWN", "  " + "-" * 40])
            for etype, count in sorted(qbr["stats"].items(), key=lambda x: -x[1])[:8]:
                lines.append(f"  {etype}: {count}")

        lines.append("")
        return "\n".join(lines)

    def _extract_stage(self, entry: Dict) -> str:
        for t in entry.get("tags", []):
            if t.startswith("stage:"):
                return t.split(":", 1)[1]
        return "detected"
