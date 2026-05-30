"""
knowledge_ops.py — Knowledge Operations: auditing, accelerator generation, cross-engagement learning.

Closes the remaining knowledge operations gaps.
"""

import datetime
import json
import re
from collections import Counter
from typing import Dict, List, Optional, Any
from grid_memory.local_grid import LocalGrid
from grid_memory.lessons import LessonsEngine
from grid_memory.patterns import PatternEngine


class KnowledgeOps:
    """Knowledge Operations: audit, accelerator generation, cross-engagement learning.

    Args:
        grid: LocalGrid instance
    """

    def __init__(self, grid: LocalGrid):
        self.grid = grid
        self.lessons = LessonsEngine(grid)
        self.patterns = PatternEngine(grid)

    def audit_knowledge(self) -> Dict:
        """Audit all knowledge assets for quality and coverage."""
        lessons = self.lessons.list(max_results=500).get("lessons", [])
        pattern_result = self.patterns.scan()
        report = self.lessons.generate_cross_project_report()

        categories = Counter(l.get("category", "unknown") for l in lessons)
        severities = Counter(l.get("severity", "unknown") for l in lessons)

        return {
            "total_lessons": len(lessons),
            "total_patterns": pattern_result.get("total", 0),
            "by_category": dict(categories),
            "by_severity": dict(severities),
            "projects_covered": report.get("projects_involved", 0),
            "clients_covered": report.get("clients_involved", 0),
        }

    def generate_accelerator_from_lessons(self, domain: str, min_lessons: int = 3) -> Dict:
        """Auto-generate an accelerator from lessons in a domain."""
        lessons = self.lessons.list(max_results=200).get("lessons", [])
        domain_lessons = [l for l in lessons if l.get("project", "").lower() == domain.lower()
                         or l.get("client", "").lower() == domain.lower()]

        if len(domain_lessons) < min_lessons:
            return {"generated": False, "reason": f"Need {min_lessons} lessons for domain '{domain}', have {len(domain_lessons)}"}

        worked = [l for l in domain_lessons if l["category"] == "worked"]
        reusable = [l for l in domain_lessons if l["category"] == "reusable"]

        title = f"{domain.title()} Accelerator"
        content = f"Domain: {domain}\nGenerated from {len(domain_lessons)} lessons\n\nWhat Works:\n"
        for l in worked[:3]:
            content += f"  - {l['content'][:100]}\n"
        content += "\nReusable Assets:\n"
        for l in reusable[:3]:
            content += f"  - {l['content'][:100]}\n"

        self.grid.write(agent_id="knowledge-ops", type="accelerator",
                        content=content,
                        tags=["accelerator", f"domain:{domain}", "auto-generated"],
                        memory_tier="organization")
        return {"generated": True, "title": title, "lessons_used": len(domain_lessons)}

    def cross_engagement_learning(self) -> Dict:
        """Find lessons that apply across multiple engagements."""
        report = self.lessons.generate_cross_project_report()
        all_lessons = self.lessons.list(max_results=500).get("lessons", [])

        # Find lessons whose content keywords appear in multiple projects
        keyword_projects: Dict[str, set] = {}
        for l in all_lessons:
            for word in l.get("content", "").lower().split():
                if len(word) > 5:
                    if word not in keyword_projects:
                        keyword_projects[word] = set()
                    if l.get("project"):
                        keyword_projects[word].add(l.get("project"))

        cross_cutting = [(kw, projs) for kw, projs in keyword_projects.items() if len(projs) >= 2]
        cross_cutting.sort(key=lambda x: -len(x[1]))

        return {
            "total_cross_cutting_topics": len(cross_cutting),
            "top_cross_cutting": [{"topic": kw, "projects": list(projs)[:5]} for kw, projs in cross_cutting[:10]],
            "projects_involved": report.get("projects_involved", 0),
        }
