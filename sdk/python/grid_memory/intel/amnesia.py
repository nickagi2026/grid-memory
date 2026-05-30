"""
# BETA MODULE - Heuristic pattern matching, not ML. Results are directional indicators, not definitive.
# Confidence caveat: Value estimates use simplified models. Human review required before action.

amnesia.py — Organizational Amnesia Detector™

Detects when the same problem has been solved multiple times across
different teams, projects, or time periods — then surfaces the pattern
with estimated wasted effort.

"The Grid notices you've solved this problem 5 times already.
 Estimated wasted effort: 187 hours."
"""

import datetime
import json
import os
import re
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Any, Tuple

from grid_memory.local_grid import LocalGrid


class AmnesiaDetector:
    """Detects recurring problems that have been solved before but forgotten.

    Args:
        grid: LocalGrid instance
        window_days: How far back to search
        min_recurrences: Minimum times a problem must recur to flag
    """

    def __init__(self, grid: LocalGrid, window_days: int = 365,
                 min_recurrences: int = 2):
        self.grid = grid
        self.window_days = window_days
        self.min_recurrences = min_recurrences

    def scan(self) -> Dict:
        """Scan for organizational amnesia patterns.

        Returns:
            Dict with detected amnesia events
        """
        entries = self._get_recent_entries()

        amnesia_events = []

        # 1. Same content patterns across different entries
        content_matches = self._find_content_patterns(entries)
        amnesia_events.extend(content_matches)

        # 2. Same tag patterns across different projects
        tag_matches = self._find_cross_project_patterns(entries)
        amnesia_events.extend(tag_matches)

        # 3. Recurring blocker patterns
        blocker_matches = self._find_blocker_patterns(entries)
        amnesia_events.extend(blocker_matches)

        # Score and sort
        for event in amnesia_events:
            event["score"] = self._calculate_score(event)

        amnesia_events.sort(key=lambda x: -x.get("score", 0))

        total_wasted = sum(e.get("estimated_wasted_hours", 0) for e in amnesia_events)

        return {
            "amnesia_events": amnesia_events,
            "total_events": len(amnesia_events),
            "total_wasted_hours": total_wasted,
            "total_wasted_value": total_wasted * 100,  # blended hourly rate
            "top_issue": amnesia_events[0]["issue"] if amnesia_events else None,
        }

    def _get_recent_entries(self) -> List[Dict]:
        result = self.grid.query(max=500)
        return result.get("entries", [])

    def _find_content_patterns(self, entries: List[Dict]) -> List[Dict]:
        """Find the same problem described with similar language."""
        events = []

        # Extract key phrases from blocker/failed entries
        blocker_phrases: Dict[str, List[Dict]] = defaultdict(list)
        for e in entries:
            etype = e.get("type", "")
            content = e.get("content", "").lower()
            if etype in ("blocker", "observation", "task_status"):
                # Extract meaningful phrases
                phrases = self._extract_key_phrases(content)
                for phrase in phrases:
                    blocker_phrases[phrase].append(e)

        for phrase, group in blocker_phrases.items():
            if len(group) >= self.min_recurrences:
                agents = set(e.get("agent_id", "?") for e in group)
                projects = set()
                clients = set()
                for e in group:
                    for t in e.get("tags", []):
                        if t.startswith("project:"):
                            projects.add(t.split(":", 1)[1])
                        if t.startswith("client:"):
                            clients.add(t.split(":", 1)[1])

                timestamps = [e.get("created_at", "") for e in group if e.get("created_at")]
                timestamps.sort()
                span_days = self._date_span_days(timestamps) if timestamps else 0

                hours_per = 4  # avg hours wasted per recurrence
                total_hours = len(group) * hours_per

                events.append({
                    "type": "content_recurrence",
                    "issue": phrase.capitalize(),
                    "recurrences": len(group),
                    "unique_agents": len(agents),
                    "agents_involved": list(agents)[:5],
                    "projects_involved": list(projects),
                    "clients_involved": list(clients),
                    "first_seen": timestamps[0] if timestamps else "",
                    "last_seen": timestamps[-1] if timestamps else "",
                    "timespan_days": span_days,
                    "estimated_wasted_hours": total_hours,
                    "evidence": f"Occurred {len(group)} times across {len(agents)} agents",
                    "recommendation": f"Create standard runbook for '{phrase}'",
                })

        return events

    def _find_cross_project_patterns(self, entries: List[Dict]) -> List[Dict]:
        """Find the same tag/topic appearing across different projects."""
        tag_projects: Dict[str, set] = defaultdict(set)
        tag_entries: Dict[str, List[Dict]] = defaultdict(list)
        tag_types: Dict[str, Counter] = defaultdict(Counter)

        for e in entries:
            for t in e.get("tags", []):
                if t.startswith("project:"):
                    tag_projects[t.split(":", 1)[1]].add(t)
                elif t.startswith("client:"):
                    tag_projects[t.split(":", 1)[1]].add(t)
                else:
                    tag_entries[t].append(e)
                    tag_types[t][e.get("type", "")] += 1

        events = []
        # Find tags that appear across multiple projects
        for tag, e_list in tag_entries.items():
            if len(e_list) < self.min_recurrences:
                continue

            projects = set()
            clients = set()
            agents = set()
            for e in e_list:
                for t in e.get("tags", []):
                    if t.startswith("project:"):
                        projects.add(t.split(":", 1)[1])
                    elif t.startswith("client:"):
                        clients.add(t.split(":", 1)[1])
                agents.add(e.get("agent_id", "?"))

            if len(projects) >= 2 or len(clients) >= 2:
                event_type = tag_types[tag].most_common(1)[0][0] if tag_types[tag] else "unknown"
                events.append({
                    "type": "cross_project",
                    "issue": f"'{tag}' issue appearing across engagements",
                    "recurrences": len(e_list),
                    "unique_agents": len(agents),
                    "agents_involved": list(agents)[:5],
                    "projects_involved": list(projects),
                    "clients_involved": list(clients),
                    "estimated_wasted_hours": len(e_list) * 3,
                    "evidence": f"'{tag}' appeared across {len(projects) + len(clients)} engagements",
                    "recommendation": f"Create cross-engagement standard for '{tag}'",
                })

        return events

    def _find_blocker_patterns(self, entries: List[Dict]) -> List[Dict]:
        """Find recurring blockers with same root cause."""
        blockers = [e for e in entries if e.get("type") == "blocker"]
        if len(blockers) < self.min_recurrences:
            return []

        # Group by keyword patterns
        kw_groups: Dict[str, List[Dict]] = defaultdict(list)
        for b in blockers:
            content = b.get("content", "").lower()
            # Check for known patterns
            for kw in ["timeout", "connection refused", "permission denied",
                        "rate limit", "crash", "outage", "disk full",
                        "memory error", "null pointer", "deadlock"]:
                if kw in content:
                    kw_groups[kw].append(b)
                    break
            else:
                # Generic blocker
                kw_groups["other_blocker"].append(b)

        events = []
        for kw, group in kw_groups.items():
            if len(group) >= self.min_recurrences:
                agents = set(e.get("agent_id", "?") for e in group)
                timestamps = [e.get("created_at", "") for e in group if e.get("created_at")]
                timestamps.sort()

                hours_per = 2
                total_hours = len(group) * hours_per

                events.append({
                    "type": "recurring_blocker",
                    "issue": f"Recurring '{kw}' blocker",
                    "recurrences": len(group),
                    "unique_agents": len(agents),
                    "agents_involved": list(agents)[:5],
                    "first_seen": timestamps[0] if timestamps else "",
                    "last_seen": timestamps[-1] if timestamps else "",
                    "estimated_wasted_hours": total_hours,
                    "evidence": f"{len(group)} '{kw}' incidents across {len(agents)} agents",
                    "recommendation": f"Implement permanent fix for {kw} rather than repeated remediation",
                })

        return events

    def report(self) -> str:
        """Generate a human-readable amnesia report."""
        data = self.scan()
        events = data.get("amnesia_events", [])

        if not events:
            return "\n  No organizational amnesia detected. Your teams may have excellent memory.\n"

        lines = [
            f"\n{'=' * 60}",
            f"  ORGANIZATIONAL AMNESIA DETECTOR",
            f"  Total wasted: ${data['total_wasted_value']:,.0f} "
            f"({data['total_wasted_hours']} hours)",
            f"  Problems that keep being re-solved: {data['total_events']}",
            f"{'=' * 60}",
        ]

        for i, event in enumerate(events[:10], 1):
            lines.extend([
                f"\n  {i}. {event['issue']}",
                f"     Occurred: {event['recurrences']}x  "
                f"Wasted: {event['estimated_wasted_hours']} hours  "
                f"Agents: {event['unique_agents']}",
            ])
            if event.get("projects_involved"):
                lines.append(f"     Projects: {', '.join(event['projects_involved'][:3])}")
            if event.get("clients_involved"):
                lines.append(f"     Clients: {', '.join(event['clients_involved'][:3])}")
            if event.get("first_seen"):
                lines.append(f"     First: {event['first_seen'][:10]}  "
                            f"Last: {event['last_seen'][:10]}")
            lines.append(f"     \u2192 {event['recommendation']}")

        lines.append("")
        return "\n".join(lines)

    # ── Helpers ──

    def _extract_key_phrases(self, text: str) -> List[str]:
        """Extract key phrases from text."""
        phrases = []
        # Look for patterns like "cannot X", "failed to X", "X error"
        patterns = [
            r'(?:cannot|unable to|could not)\s+([\w\s]+)',
            r'failed to\s+([\w\s]+)',
            r'(timeout|error|crash|outage)\s+(?:error|issue|problem)?',
            r'([\w\-\_]+)\s+(?:timeout|error|failed)',
        ]
        for pat in patterns:
            for match in re.finditer(pat, text, re.IGNORECASE):
                phrase = match.group(1).strip()[:40] if match.lastindex else match.group(0)[:40]
                if phrase and len(phrase) > 5:
                    phrases.append(phrase)

        if not phrases and len(text) > 10:
            # Fallback: use first meaningful segment
            phrases.append(text[:40].strip())

        return phrases[:3]

    def _date_span_days(self, timestamps: List[str]) -> int:
        if len(timestamps) < 2:
            return 0
        try:
            first = datetime.datetime.fromisoformat(timestamps[0].replace("Z", "+00:00"))
            last = datetime.datetime.fromisoformat(timestamps[-1].replace("Z", "+00:00"))
            return max((last - first).days, 0)
        except (ValueError, AttributeError):
            return 0

    def _calculate_score(self, event: Dict) -> float:
        """Calculate severity score for ranking."""
        recurrences = event.get("recurrences", 0)
        agents = event.get("unique_agents", 1)
        hours = event.get("estimated_wasted_hours", 0)
        projects = len(event.get("projects_involved", []))
        return (recurrences * 5) + (agents * 3) + (hours * 0.5) + (projects * 10)
