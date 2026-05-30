"""
# BETA: This module uses heuristic pattern matching and simplified assumptions.
# Value estimates use flat rates and frequency multipliers — directional only.
# Results are NOT validated against real outcome data. Use for internal surfacing, not client analytics.

readiness.py — Transformation Readiness Engine™

Scores an organization's readiness for AI/automation transformation across
five dimensions: Data, Process, Governance, People, Technology.

Generates a quantified readiness score and a prioritized roadmap.
Supports Playbooks 1-2 (Transformation Readiness, Target State Definition).
"""

import datetime
import json
import re
from typing import Dict, List, Optional, Any

from grid_memory.local_grid import LocalGrid


class ReadinessEngine:
    """Scores organizational readiness for AI-driven transformation.

    Args:
        grid: LocalGrid instance scoped to a workspace
    """

    def __init__(self, grid: LocalGrid):
        self.grid = grid

    def assess(self, client: str = "") -> Dict:
        """Run a full readiness assessment.

        Args:
            client: Client identifier to scope the assessment

        Returns:
            Dict with readiness scores, findings, and roadmap
        """
        entries = self._get_entries(client)

        dimensions = {
            "data": self._assess_data(entries),
            "process": self._assess_process(entries),
            "governance": self._assess_governance(entries),
            "people": self._assess_people(entries),
            "technology": self._assess_technology(entries),
        }

        overall = round(sum(d["score"] for d in dimensions.values()) / len(dimensions), 1)

        return {
            "client": client or "unknown",
            "overall_readiness": overall,
            "readiness_level": self._level(overall),
            "dimensions": dimensions,
            "strengths": self._find_strengths(dimensions),
            "gaps": self._find_gaps(dimensions),
            "roadmap": self._generate_roadmap(dimensions),
            "assessed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

    # ── Dimension Assessments ──

    def _assess_data(self, entries: List[Dict]) -> Dict:
        """Score data readiness (0-100)."""
        score = 30  # baseline
        findings = []
        recommendations = []

        # Check for data-related decisions
        has_db_decision = any(
            "database" in e.get("content", "").lower() and e.get("type") == "decision"
            for e in entries
        )
        if has_db_decision:
            score += 15
            findings.append("Database architecture decisions documented")

        # Check for structured data patterns
        has_tags = any(e.get("tags") for e in entries)
        if has_tags:
            score += 10
            findings.append("Structured tagging in use")

        # Check for metrics/monitoring
        has_monitoring = any(
            kw in e.get("content", "").lower()
            for e in entries for kw in ["metric", "monitoring", "dashboard", "kpi"]
        )
        if has_monitoring:
            score += 15
            findings.append("Monitoring/metrics infrastructure present")

        # Check for data quality issues reported
        has_data_issues = any(
            kw in e.get("content", "").lower()
            for e in entries for kw in ["data quality", "incomplete data", "missing data"]
        )
        if has_data_issues:
            score -= 10
            findings.append("Data quality issues reported (corrective action needed)")

        recommendations = self._data_recommendations(score)
        return {
            "score": min(max(score, 0), 100),
            "findings": findings[:5],
            "recommendations": recommendations,
        }

    def _assess_process(self, entries: List[Dict]) -> Dict:
        """Score process readiness (0-100)."""
        score = 30
        findings = []
        recommendations = []

        handoffs = [e for e in entries if e.get("type") == "handoff"]
        if handoffs:
            score += 10
            findings.append(f"{len(handoffs)} handoffs documented — process visibility exists")

        if len(handoffs) >= 10:
            score += 10
            findings.append("Mature handoff patterns — automation candidates identified")

        blockers = [e for e in entries if e.get("type") == "blocker"]
        if blockers:
            score += 5
            findings.append(f"{len(blockers)} blockers tracked — process friction visible")

        has_approval_mentions = any(
            "approv" in e.get("content", "").lower()
            for e in entries
        )
        if has_approval_mentions:
            score += 5
            findings.append("Approval steps identified — process formalization evident")

        # Check for automation mentions
        has_automation = any(
            "automation" in e.get("content", "").lower() or "automate" in e.get("content", "").lower()
            for e in entries
        )
        if has_automation:
            score += 10
            findings.append("Automation already being discussed — cultural readiness")

        recommendations = self._process_recommendations(score)
        return {
            "score": min(max(score, 0), 100),
            "findings": findings[:5],
            "recommendations": recommendations,
        }

    def _assess_governance(self, entries: List[Dict]) -> Dict:
        """Score governance readiness (0-100)."""
        score = 25
        findings = []
        recommendations = []

        decisions = [e for e in entries if e.get("type") == "decision"]
        if decisions:
            score += 15
            findings.append(f"{len(decisions)} decisions documented — governance trail exists")

        has_rationale = any(
            "Rationale:" in e.get("content", "")
            for e in entries
        )
        if has_rationale:
            score += 10
            findings.append("Decisions include rationale — audit-ready")

        # Check for compliance/security mentions
        has_compliance = any(
            kw in e.get("content", "").lower()
            for e in entries for kw in ["compliance", "audit", "regulation", "policy"]
        )
        if has_compliance:
            score += 10
            findings.append("Compliance considerations present in records")

        recommendations = self._governance_recommendations(score)
        return {
            "score": min(max(score, 0), 100),
            "findings": findings[:5],
            "recommendations": recommendations,
        }

    def _assess_people(self, entries: List[Dict]) -> Dict:
        """Score people readiness (0-100)."""
        score = 30
        findings = []
        recommendations = []

        agents = set(e.get("agent_id", "?") for e in entries if e.get("agent_id"))
        if len(agents) >= 3:
            score += 10
            findings.append(f"{len(agents)} contributors active — cross-functional engagement")

        questions = [e for e in entries if e.get("type") == "question"]
        if questions:
            score += 5
            findings.append(f"{len(questions)} questions asked — learning culture present")

        lessons = [e for e in entries
                   if any(t.startswith("cat:") for t in e.get("tags", []))]
        if lessons:
            score += 10
            findings.append("Lessons being documented — learning culture strong")

        has_training = any(
            kw in e.get("content", "").lower()
            for e in entries for kw in ["training", "workshop", "learning"]
        )
        if has_training:
            score += 10
            findings.append("Training/learning activities detected")

        recommendations = self._people_recommendations(score)
        return {
            "score": min(max(score, 0), 100),
            "findings": findings[:5],
            "recommendations": recommendations,
        }

    def _assess_technology(self, entries: List[Dict]) -> Dict:
        """Score technology readiness (0-100)."""
        score = 30
        findings = []
        recommendations = []

        has_api = any(
            kw in e.get("content", "").lower()
            for e in entries for kw in ["api", "rest", "endpoint"]
        )
        if has_api:
            score += 15
            findings.append("API infrastructure present")

        has_cloud = any(
            kw in e.get("content", "").lower()
            for e in entries for kw in ["cloud", "aws", "azure", "gcp"]
        )
        if has_cloud:
            score += 10
            findings.append("Cloud infrastructure in use")

        has_automation_tools = any(
            kw in e.get("content", "").lower()
            for e in entries for kw in ["ci/cd", "pipeline", "automated", "terraform"]
        )
        if has_automation_tools:
            score += 15
            findings.append("Automation tools already in place")

        recommendations = self._tech_recommendations(score)
        return {
            "score": min(max(score, 0), 100),
            "findings": findings[:5],
            "recommendations": recommendations,
        }

    # ── Recommendations ──

    def _data_recommendations(self, score: int) -> List[str]:
        if score < 40:
            return ["Establish data governance framework", "Document data sources and owners"]
        elif score < 60:
            return ["Improve data quality monitoring", "Create data catalog"]
        else:
            return ["Explore advanced analytics opportunities", "Build data products"]

    def _process_recommendations(self, score: int) -> List[str]:
        if score < 40:
            return ["Document current-state processes", "Identify top 3 automation candidates"]
        elif score < 60:
            return ["Implement process monitoring", "Automate high-volume manual steps"]
        else:
            return ["End-to-end process automation", "Build digital twins of key processes"]

    def _governance_recommendations(self, score: int) -> List[str]:
        if score < 40:
            return ["Create AI governance policy", "Establish decision documentation standards"]
        elif score < 60:
            return ["Implement automated compliance checks", "Build audit trail for AI decisions"]
        else:
            return ["Scale governance across all departments", "Industry-leading AI ethics framework"]

    def _people_recommendations(self, score: int) -> List[str]:
        if score < 40:
            return ["Conduct AI literacy training", "Identify transformation champions"]
        elif score < 60:
            return ["Build internal AI community of practice", "Establish innovation time policy"]
        else:
            return ["Scale AI expertise across organization", "Build internal AI academy"]

    def _tech_recommendations(self, score: int) -> List[str]:
        if score < 40:
            return ["Assess current tech stack for AI readiness", "Implement API-first strategy"]
        elif score < 60:
            return ["Build data pipeline infrastructure", "Implement MLOps foundation"]
        else:
            return ["Enterprise AI platform", "Edge AI / real-time intelligence"]

    def _find_strengths(self, dimensions: Dict) -> List[str]:
        strengths = []
        for name, dim in dimensions.items():
            if dim["score"] >= 70:
                for f in dim.get("findings", [])[:2]:
                    strengths.append(f"{name.title()}: {f}")
        return strengths[:5]

    def _find_gaps(self, dimensions: Dict) -> List[str]:
        gaps = []
        for name, dim in sorted(dimensions.items(), key=lambda x: x[1]["score"]):
            if dim["score"] < 50:
                for r in dim.get("recommendations", [])[:2]:
                    gaps.append(f"{name.title()}: {r}")
        return gaps[:5]

    def _generate_roadmap(self, dimensions: Dict) -> List[Dict]:
        """Generate a prioritized transformation roadmap."""
        sorted_dims = sorted(dimensions.items(), key=lambda x: x[1]["score"])

        roadmap = []
        phase = 1
        for name, dim in sorted_dims:
            if dim["score"] < 50:
                for rec in dim.get("recommendations", [])[:2]:
                    roadmap.append({
                        "phase": phase,
                        "dimension": name,
                        "action": rec,
                        "priority": "high" if phase <= 2 else "medium",
                    })
                    phase += 1

        return roadmap[:10]

    def _level(self, score: float) -> str:
        if score >= 80:
            return "AI-Native Ready"
        elif score >= 60:
            return "Transformation Ready"
        elif score >= 40:
            return "Foundation Building"
        else:
            return "Early Stage"

    def _get_entries(self, client: str = "") -> List[Dict]:
        tags = []
        if client:
            tags.append(f"client:{client}")
        result = self.grid.query(tags=tags if tags else None, max=500)
        return result.get("entries", [])
