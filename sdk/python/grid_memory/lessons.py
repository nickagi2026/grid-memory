"""
lessons.py — Lessons Learned Engine.

Every engagement automatically captures:
  ✅ What worked
  ❌ What failed
  😮 What surprised us
  ♻️ What should become reusable

Lessons feed back into discovery, assessment, architecture, and proposals.
Over time, MIKE becomes smarter than any competitor because every project
compounds knowledge.
"""

import datetime
import json
import os
import re
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Any

from grid_memory.local_grid import LocalGrid

# ─── Lesson Categories ─────────────────────────────────────────────────────────

CATEGORIES = {
    "worked": {"icon": "\u2705", "label": "What Worked", "color": "green"},
    "failed": {"icon": "\u274c", "label": "What Failed", "color": "red"},
    "surprised": {"icon": "\U0001f92f", "label": "What Surprised Us", "color": "yellow"},
    "reusable": {"icon": "\u267b\ufe0f", "label": "Reusable Asset", "color": "blue"},
}

SEVERITIES = {
    "insight": "\U0001f4a1",
    "warning": "\u26a0\ufe0f",
    "critical": "\U0001f6a8",
}


# ─── Lessons Engine ────────────────────────────────────────────────────────────


class LessonsEngine:
    """Manages lessons learned across engagements.

    Lessons are stored as Grid entries with type='lesson' and categorized
    tags. Every lesson can be linked back to the project/client it came from.

    Args:
        grid: LocalGrid instance
    """

    def __init__(self, grid: LocalGrid):
        self.grid = grid

    def add(self, content: str, category: str = "worked",
            severity: str = "insight",
            project: str = "",
            client: str = "",
            agent: str = "",
            tags: Optional[List[str]] = None) -> Dict:
        """Add a lesson learned.

        Args:
            content: The lesson content
            category: worked | failed | surprised | reusable
            severity: insight | warning | critical
            project: Project name this lesson came from
            client: Client name
            agent: Who learned this
            tags: Additional tags

        Returns:
            Dict with lesson info
        """
        category = category.lower()
        if category not in CATEGORIES:
            category = "worked"

        severity = severity.lower()
        if severity not in SEVERITIES:
            severity = "insight"

        all_tags = ["lesson", f"cat:{category}", f"sev:{severity}"]
        if project:
            all_tags.append(f"project:{project}")
        if client:
            all_tags.append(f"client:{client}")
        if tags:
            all_tags.extend(tags)

        structured = (
            f"Lesson Learned [{category}]\n"
            f"Severity: {severity}\n"
            f"Content: {content}\n"
        )
        if project:
            structured += f"Project: {project}\n"
        if client:
            structured += f"Client: {client}\n"
        if agent:
            structured += f"Agent: {agent}\n"
        structured += f"\nCaptured: {datetime.datetime.now(datetime.timezone.utc).isoformat()}"

        result = self.grid.write(
            agent_id=agent or "lessons-engine",
            type="lesson",
            content=structured,
            tags=all_tags,
            memory_tier="project",
        )

        return {
            "id": result["entry_id"],
            "category": category,
            "severity": severity,
            "content": content,
            "project": project,
            "client": client,
            "created_at": result["created_at"],
        }

    def auto_extract(self, project: str = "", client: str = "") -> Dict:
        """Auto-extract lessons from existing Grid entries.

        Scans recent entries for patterns that suggest lessons:
        - Blockers → "what failed"
        - Successful decisions → "what worked"
        - Questions with answers → "what surprised / what we learned"
        - Repeated patterns → "reusable"

        Args:
            project: Scope extraction to a project
            client: Scope extraction to a client

        Returns:
            Dict with extracted lessons
        """
        query_tags = []
        if project:
            query_tags.append(f"project:{project}")
        if client:
            query_tags.append(f"client:{client}")

        result = self.grid.query(tags=query_tags if query_tags else None, max=200)
        entries = result.get("entries", [])

        extracted = {
            "worked": [],
            "failed": [],
            "surprised": [],
            "reusable": [],
            "total": 0,
        }

        for entry in entries:
            etype = entry.get("type", "")
            content = entry.get("content", "")
            agent = entry.get("agent_id", "")
            tags = entry.get("tags", [])

            # Blockers → failed lessons
            if etype == "blocker":
                lesson = self.add(
                    content=f"Blocker encountered: {content[:200]}",
                    category="failed",
                    severity="critical" if self._is_critical(content) else "warning",
                    project=project,
                    client=client,
                    agent=agent,
                    tags=["auto-extracted"],
                )
                extracted["failed"].append(lesson)
                extracted["total"] += 1

            # Successful decisions → worked lessons
            elif etype == "decision" and "Rationale:" in content:
                lesson_text = content[:300].replace("Rationale:", "\nRationale: ")
                lesson = self.add(
                    content=f"Decision that worked: {lesson_text}",
                    category="worked",
                    severity="insight",
                    project=project,
                    client=client,
                    agent=agent,
                    tags=["auto-extracted"],
                )
                extracted["worked"].append(lesson)
                extracted["total"] += 1

            # Questions → surprised (knowledge gaps found)
            elif etype == "question":
                lesson = self.add(
                    content=f"Knowledge gap identified: {content[:200]}",
                    category="surprised",
                    severity="insight",
                    project=project,
                    client=client,
                    agent=agent,
                    tags=["auto-extracted", "knowledge-gap"],
                )
                extracted["surprised"].append(lesson)
                extracted["total"] += 1

            # Handoffs with "ready" status could indicate good workflow patterns
            elif etype == "handoff":
                if "ready" in content.lower():
                    match = re.match(r'\[(.+?)\s*\u2192\s*(.+?)\]\s*\((.+?)\)', content)
                    if match:
                        lesson = self.add(
                            content=f"Effective handoff pattern: {match.group(1).strip()} \u2192 {match.group(2).strip()}",
                            category="reusable",
                            severity="insight",
                            project=project,
                            client=client,
                            agent=agent,
                            tags=["auto-extracted", "workflow-pattern"],
                        )
                        extracted["reusable"].append(lesson)
                        extracted["total"] += 1

        return extracted

    def list(self, category: Optional[str] = None,
             project: Optional[str] = None,
             client: Optional[str] = None,
             severity: Optional[str] = None,
             max_results: int = 50) -> Dict:
        """Query lessons with filters.

        Args:
            category: Filter by category
            project: Filter by project
            client: Filter by client
            severity: Filter by severity
            max_results: Maximum results

        Returns:
            Dict with lessons and summary
        """
        query_tags = ["lesson"]
        if category:
            query_tags.append(f"cat:{category}")
        if project:
            query_tags.append(f"project:{project}")
        if client:
            query_tags.append(f"client:{client}")
        if severity:
            query_tags.append(f"sev:{severity}")

        result = self.grid.query(tags=query_tags, max=max_results)
        entries = result.get("entries", [])

        lessons = []
        for e in entries:
            lessons.append(self._format_lesson(e))

        # Summary
        by_cat = Counter()
        by_sev = Counter()
        for l in lessons:
            by_cat[l["category"]] += 1
            by_sev[l["severity"]] += 1

        return {
            "lessons": lessons,
            "total": len(lessons),
            "by_category": dict(by_cat),
            "by_severity": dict(by_sev),
        }

    def summary(self, project: Optional[str] = None,
                client: Optional[str] = None) -> Dict:
        """Get a summary of lessons learned.

        Args:
            project: Filter by project
            client: Filter by client

        Returns:
            Dict with summary stats
        """
        result = self.list(project=project, client=client, max_results=500)
        lessons = result.get("lessons", [])

        if not lessons:
            return {"total": 0, "message": "No lessons yet"}

        # Group by category
        by_cat: Dict[str, List] = defaultdict(list)
        for l in lessons:
            by_cat[l["category"]].append(l)

        top_insights = [l for l in lessons if l["severity"] == "insight"][:3]
        top_warnings = [l for l in lessons if l["severity"] == "warning"][:3]
        top_critical = [l for l in lessons if l["severity"] == "critical"][:3]

        return {
            "total": len(lessons),
            "by_category": dict(by_cat),
            "category_counts": result.get("by_category", {}),
            "severity_counts": result.get("by_severity", {}),
            "top_insights": top_insights[:3],
            "top_warnings": top_warnings[:3],
            "top_critical": top_critical[:3],
        }

    def generate_cross_project_report(self) -> Dict:
        """Generate a report of lessons across ALL projects.

        This is the "MIKE is getting smarter" proof point.
        """
        result = self.list(max_results=1000)
        lessons = result.get("lessons", [])

        if not lessons:
            return {"total": 0, "message": "No lessons yet across projects"}

        # Unique projects
        projects = set(l.get("project", "") for l in lessons if l.get("project"))
        clients = set(l.get("client", "") for l in lessons if l.get("client"))

        # Most common patterns
        content_words: Counter = Counter()
        for l in lessons:
            words = l.get("content", "").lower().split()
            for w in words:
                if len(w) > 4:
                    content_words[w] += 1

        top_keywords = [w for w, c in content_words.most_common(20)]

        return {
            "total_lessons": len(lessons),
            "projects_involved": len(projects),
            "projects": sorted(projects)[:20],
            "clients_involved": len(clients),
            "clients": sorted(clients)[:20],
            "by_category": result.get("by_category", {}),
            "by_severity": result.get("by_severity", {}),
            "top_keywords": top_keywords[:10],
            "trending_topics": top_keywords[:5],
        }

    # ── Internal ──

    def _format_lesson(self, entry: Dict) -> Dict:
        """Format a Grid entry as a lesson."""
        content = entry.get("content", "")
        tags = entry.get("tags", [])

        category = "worked"
        severity = "insight"
        lesson_content = content
        project = ""
        client = ""

        for t in tags:
            if t.startswith("cat:"):
                category = t.split(":", 1)[1]
            elif t.startswith("sev:"):
                severity = t.split(":", 1)[1]
            elif t.startswith("project:"):
                project = t.split(":", 1)[1]
            elif t.startswith("client:"):
                client = t.split(":", 1)[1]

        # Extract content from structured format
        for line in content.split("\n"):
            if line.startswith("Content: "):
                lesson_content = line[9:]

        return {
            "id": entry.get("id", ""),
            "category": category,
            "severity": severity,
            "content": lesson_content,
            "project": project,
            "client": client,
            "agent": entry.get("agent_id", ""),
            "created_at": entry.get("created_at", ""),
        }

    def _is_critical(self, content: str) -> bool:
        """Check if a blocker is critical."""
        critical_keywords = [
            "outage", "crash", "data loss", "security", "breach",
            "compliance", "legal", "fire", "customer impact",
        ]
        content_lower = content.lower()
        return any(kw in content_lower for kw in critical_keywords)
