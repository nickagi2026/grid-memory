"""
# BETA: This module uses heuristic pattern matching and simplified assumptions.
# Value estimates use flat rates and frequency multipliers — directional only.
# Results are NOT validated against real outcome data. Use for internal surfacing, not client analytics.

time_machine.py — Institutional Memory Time Machine™

Ask natural language questions about past decisions, projects, and outcomes.
No searching. No meetings. Just answers.

"Why did we stop Project Falcon?"
→ March 2024, Reason: Vendor instability, Decision maker: CTO, Evidence: 5 outages
"""

import datetime
import json
import re
from typing import Dict, List, Optional, Any

from grid_memory.local_grid import LocalGrid


class TimeMachine:
    """Natural language query interface for institutional memory.

    Args:
        grid: LocalGrid instance
    """

    def __init__(self, grid: LocalGrid):
        self.grid = grid

    def ask(self, question: str) -> Dict:
        """Ask a question about the organization's history.

        Args:
            question: Natural language question

        Returns:
            Dict with answer, confidence, evidence
        """
        q = question.lower()

        # Route to the right handler based on question type
        if any(w in q for w in ["why did", "why was", "reason", "decision"]):
            return self._answer_decision(q)
        elif any(w in q for w in ["what happened", "when did", "timeline"]):
            return self._answer_timeline(q)
        elif any(w in q for w in ["who", "made the decision", "decided"]):
            return self._answer_who(q)
        elif any(w in q for w in ["how many", "count", "total"]):
            return self._answer_count(q)
        elif any(w in q for w in ["stop", "cancel", "kill", "abandon"]):
            return self._answer_why_stopped(q)
        elif any(w in q for w in ["fail", "problem", "issue", "blocker"]):
            return self._answer_failures(q)
        else:
            return self._answer_general(q)

    def _answer_decision(self, question: str) -> Dict:
        """Answer 'why' questions about decisions."""
        decisions = self.grid.query(type="decision", max=100).get("entries", [])

        # Find relevant decisions by keyword matching
        keywords = question.split()
        relevant = []
        for d in decisions:
            content = d.get("content", "").lower()
            score = sum(1 for kw in keywords if len(kw) > 3 and kw in content)
            if score > 0:
                relevant.append((score, d))

        relevant.sort(key=lambda x: -x[0])

        if not relevant:
            return {"answer": "I couldn't find a decision matching your question.", "confidence": 0, "sources": []}

        top = relevant[0][1]
        content = top.get("content", "")
        agent = top.get("agent_id", "unknown")
        date = top.get("created_at", "")[:10]

        # Extract rationale
        rationale = ""
        if "Rationale:" in content:
            rationale = content.split("Rationale:")[1].strip()[:200]

        return {
            "answer": f"Decision made by {agent} on {date}. Rationale: {rationale}",
            "confidence": round(min(relevant[0][0] / 5, 0.95), 2),
            "sources": [{"id": top.get("id"), "type": "decision", "date": date, "agent": agent}],
        }

    def _answer_timeline(self, question: str) -> Dict:
        """Answer 'what happened' questions."""
        entries = self.grid.query(max=50).get("entries", [])
        if not entries:
            return {"answer": "No timeline data available.", "confidence": 0, "sources": []}

        # Group by date
        timeline = defaultdict(list)
        for e in entries[:20]:
            date = e.get("created_at", "")[:10]
            content = e.get("content", "")[:100]
            timeline[date].append(f"[{e.get('type')}] {content}")

        dates = sorted(timeline.keys(), reverse=True)[:5]
        lines = ["Here's what I found:"]
        for d in dates:
            for item in timeline[d][:3]:
                lines.append(f"  {d}: {item}")

        return {"answer": "\n".join(lines), "confidence": 0.8, "sources": []}

    def _answer_who(self, question: str) -> Dict:
        """Answer 'who' questions."""
        result = self.grid.query(type="decision", max=200)
        decisions = result.get("entries", [])
        agents = Counter(d.get("agent_id", "unknown") for d in decisions)

        if not agents:
            return {"answer": "I couldn't find any decision makers.", "confidence": 0, "sources": []}

        top = agents.most_common(5)
        lines = ["Top decision makers:"]
        for agent, count in top:
            lines.append(f"  {agent}: {count} decisions")

        return {"answer": "\n".join(lines), "confidence": 0.9, "sources": []}

    def _answer_count(self, question: str) -> Dict:
        """Answer 'how many' questions."""
        info = self.grid.info()
        return {
            "answer": f"Total entries: {info.get('total_entries', 0)} ({info.get('alive_entries', 0)} active). Agents: {info.get('unique_agents', 0)}. Tags: {info.get('unique_tags', 0)}.",
            "confidence": 1.0,
            "sources": [],
        }

    def _answer_why_stopped(self, question: str) -> Dict:
        """Answer why a project/initiative was stopped."""
        blockers = self.grid.query(type="blocker", max=50).get("entries", [])
        decisions = self.grid.query(type="decision", max=50).get("entries", [])

        # Look for keywords about stopping/cancelling
        stop_keywords = ["stop", "cancel", "abandon", "deprioritize", "sunset"]
        evidence = []

        for d in decisions:
            content = d.get("content", "").lower()
            if any(kw in content for kw in stop_keywords):
                evidence.append(d)

        if not evidence:
            return {"answer": "No stopped projects found in the records.", "confidence": 0.3, "sources": []}

        e = evidence[0]
        content = e.get("content", "")
        date = e.get("created_at", "")[:10]
        agent = e.get("agent_id", "unknown")

        return {
            "answer": f"Found on {date} by {agent}: {content[:200]}",
            "confidence": 0.7,
            "sources": [{"id": e.get("id"), "type": "decision", "date": date}],
        }

    def _answer_failures(self, question: str) -> Dict:
        """Answer questions about failures and blockers."""
        blockers = self.grid.query(type="blocker", max=50).get("entries", [])
        if not blockers:
            return {"answer": "No blockers or failures recorded.", "confidence": 0, "sources": []}

        kw_groups = Counter()
        for b in blockers:
            content = b.get("content", "").lower()
            for kw in ["timeout", "error", "crash", "outage", "permission", "failed"]:
                if kw in content:
                    kw_groups[kw] += 1

        if not kw_groups:
            return {"answer": f"{len(blockers)} blockers found but no clear pattern.", "confidence": 0.5, "sources": []}

        top = kw_groups.most_common(3)
        lines = [f"Found {len(blockers)} blockers. Most common patterns:"]
        for kw, count in top:
            lines.append(f"  '{kw}': {count} occurrences")

        return {"answer": "\n".join(lines), "confidence": 0.7, "sources": []}

    def _answer_general(self, question: str) -> Dict:
        """General fallback — show recent activity."""
        entries = self.grid.query(max=10).get("entries", [])
        if not entries:
            return {"answer": "No data in the Grid yet.", "confidence": 0, "sources": []}

        lines = ["Recent Grid activity:"]
        for e in entries[:5]:
            content = e.get("content", "")[:80]
            date = e.get("created_at", "")[:10]
            lines.append(f"  [{date}] [{e.get('type')}] {content}")

        return {"answer": "\n".join(lines), "confidence": 0.5, "sources": []}
