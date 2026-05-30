"""
opportunity_radar.py — AI Opportunity Radar™

Continuously scans the Grid for automation opportunities surfaced from
real agent activity patterns. Every opportunity includes an estimated
annual dollar value.

Detection methods:
  - Repeated blockers → auto-remediation opportunities
  - Frequent handoffs → workflow automation opportunities
  - Repeated decisions → policy/standardization opportunities
  - Knowledge gaps → documentation/knowledge base opportunities
  - Bottleneck agents → load balancing opportunities
  - Manual patterns in content → task automation opportunities

Output:
  {
    "opportunities": [
      {
        "id": "opp_20260529_abc123",
        "title": "Automate database pool restart on timeout",
        "department": "Infrastructure",
        "category": "auto_remediation",
        "pattern": "timeout errors recurring every 3 days",
        "evidence": "12 blocker entries across 4 agents",
        "hours_saved_per_year": 240,
        "hourly_rate": 150,
        "annual_value": 36000,
        "confidence": 0.87,
        "difficulty": "medium",
        "recommended_action": "Implement automated retry + health check",
      }
    ],
    "total_annual_value": 36000,
    "top_opportunity": "..."
  }
"""

import datetime
import math
import os
import re
import time
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Any, Tuple

from grid_memory.local_grid import LocalGrid

# ─── Configuration ──────────────────────────────────────────────────────────────

# Default hourly rates by department/role
DEFAULT_RATES = {
    "engineering": 150,
    "infrastructure": 150,
    "support": 60,
    "operations": 75,
    "security": 175,
    "data": 140,
    "management": 200,
    "default": 100,
}

# Opportunity categories
CATEGORIES = {
    "auto_remediation": "Auto-Remediation",
    "workflow_automation": "Workflow Automation",
    "policy_standardization": "Policy Standardization",
    "knowledge_base": "Knowledge Base",
    "task_automation": "Task Automation",
    "load_balancing": "Load Balancing",
    "monitoring": "Monitoring & Alerting",
    "self_service": "Self-Service Portal",
}

PATTERN_RATES = {
    "timeout": {"category": "auto_remediation", "hours_per_event": 2.5, "difficulty": "easy"},
    "error": {"category": "auto_remediation", "hours_per_event": 2.0, "difficulty": "easy"},
    "failed": {"category": "task_automation", "hours_per_event": 3.0, "difficulty": "medium"},
    "manual": {"category": "task_automation", "hours_per_event": 4.0, "difficulty": "medium"},
    "permission denied": {"category": "auto_remediation", "hours_per_event": 1.5, "difficulty": "easy"},
    "connection refused": {"category": "auto_remediation", "hours_per_event": 1.0, "difficulty": "easy"},
    "rate limit": {"category": "auto_remediation", "hours_per_event": 0.5, "difficulty": "easy"},
    "timeout exceeded": {"category": "auto_remediation", "hours_per_event": 2.0, "difficulty": "easy"},
}


# ─── Opportunity Detector ───────────────────────────────────────────────────────


class OpportunityRadar:
    """Scans the Grid for automation opportunities with financial estimates.

    Args:
        grid: LocalGrid instance
        window_days: How far back to scan (default: 90)
        min_confidence: Minimum confidence to report (0-1)
        min_annual_value: Minimum $ value to report
    """

    def __init__(self, grid: LocalGrid,
                 window_days: int = 90,
                 min_confidence: float = 0.3,
                 min_annual_value: float = 500):
        self.grid = grid
        self.window_days = window_days
        self.min_confidence = min_confidence
        self.min_annual_value = min_annual_value
        self._scan_id = f"opp_{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d')}_{os.urandom(4).hex()}"

    def scan(self) -> Dict:
        """Run a full scan and return all detected opportunities.

        Returns:
            Dict with opportunities list, total value, metadata
        """
        entries = self._get_entries()

        opportunities = []

        # Run all detectors
        opportunities.extend(self._detect_blocker_patterns(entries))
        opportunities.extend(self._detect_workflow_automation(entries))
        opportunities.extend(self._detect_knowledge_base_gaps(entries))
        opportunities.extend(self._detect_bottlenecks(entries))
        opportunities.extend(self._detect_repeated_decisions(entries))
        opportunities.extend(self._detect_manual_patterns(entries))

        # Score and sort
        for opp in opportunities:
            opp["score"] = self._calculate_score(opp)

        opportunities.sort(key=lambda x: -x.get("score", 0))

        # Filter
        opportunities = [
            o for o in opportunities
            if o.get("confidence", 0) >= self.min_confidence
            and o.get("annual_value", 0) >= self.min_annual_value
        ]

        total_value = sum(o.get("annual_value", 0) for o in opportunities)

        return {
            "scan_id": self._scan_id,
            "scanned_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "window_days": self.window_days,
            "entries_analyzed": len(entries),
            "opportunities": opportunities,
            "total_opportunities": len(opportunities),
            "total_annual_value": round(total_value, 2),
            "top_opportunity": opportunities[0]["title"] if opportunities else None,
            "by_category": self._summarize_by_category(opportunities),
        }

    def report(self, format: str = "text") -> str:
        """Get a human-readable report.

        Args:
            format: "text" for CLI, "json" for structured
        """
        data = self.scan()
        if format == "json":
            import json
            return json.dumps(data, indent=2)

        lines = [
            f"\n{'=' * 60}",
            f"  AI OPPORTUNITY RADAR SCAN",
            f"  {data['scanned_at'][:19]}",  # type: ignore
            f"  Entries analyzed: {data['entries_analyzed']}",  # type: ignore
            f"  Window: {data['window_days']} days",  # type: ignore
            f"{'=' * 60}",
        ]

        total_value = data.get("total_annual_value", 0)  # type: ignore
        lines.append(f"\n  Total Annual Opportunity: ${total_value:,.0f}")
        lines.append(f"  Opportunities Found: {data.get('total_opportunities', 0)}\n")  # type: ignore

        # By category
        by_cat = data.get("by_category", {})  # type: ignore
        if by_cat:
            lines.append("  ── By Category ──")
            for cat, info in sorted(by_cat.items(), key=lambda x: -x[1]["value"]):
                cat_name = CATEGORIES.get(cat, cat)
                lines.append(f"    {cat_name}: {info['count']} opps, ${info['value']:,.0f}/yr")

        # Top opportunities
        opportunities = data.get("opportunities", [])[:10]  # type: ignore
        if opportunities:
            lines.append(f"\n  ── Top Opportunities ──")
            for i, opp in enumerate(opportunities, 1):
                confidence_bar = "\u2588" * int(opp["confidence"] * 10) + "\u2591" * (10 - int(opp["confidence"] * 10))
                lines.append(f"\n  {i}. {opp['title']}")
                lines.append(f"     Category: {CATEGORIES.get(opp['category'], opp['category'])}")
                lines.append(f"     Value: ${opp['annual_value']:,.0f}/yr  ({opp['hours_saved_per_year']} hrs)")
                lines.append(f"     Confidence: {confidence_bar} {opp['confidence']:.0%}")
                lines.append(f"     {opp['evidence']}")
                lines.append(f"     \u2192 {opp['recommended_action']}")

        return "\n".join(lines)

    # ── Entry Access ──

    def _get_entries(self) -> List[Dict]:
        """Get entries within the analysis window."""
        result = self.grid.query(max=200)
        return result.get("entries", [])

    # ── Detectors ──

    def _detect_blocker_patterns(self, entries: List[Dict]) -> List[Dict]:
        """Find recurring blocker patterns that indicate auto-remediation opps."""
        blockers = [e for e in entries if e.get("type") == "blocker"]
        if len(blockers) < 2:
            return []

        # Group blocker content by recurring keywords
        pattern_groups: Dict[str, List[Dict]] = defaultdict(list)

        for b in blockers:
            content = b.get("content", "").lower()
            for keyword, config in PATTERN_RATES.items():
                if keyword in content:
                    pattern_groups[keyword].append(b)
                    break

        opportunities = []
        for pattern, group in pattern_groups.items():
            if len(group) >= 2:
                config = PATTERN_RATES.get(pattern, {})
                unique_agents = set(e.get("agent_id", "?") for e in group)
                hours_per = config.get("hours_per_event", 2)
                freq_per_week = self._estimate_frequency(group)
                hours_yearly = int(freq_per_week * 52 * hours_per)
                annual_value = hours_yearly * self._rate_for_agents(unique_agents)
                confidence = min(0.5 + (len(group) * 0.05), 0.95)

                opp = {
                    "id": f"{self._scan_id}_blocker_{pattern}",
                    "title": f"Auto-remediate {pattern} errors",
                    "department": "Engineering",
                    "category": config.get("category", "auto_remediation"),
                    "pattern": f"'{pattern}' errors recurring",
                    "evidence": f"{len(group)} blocker entries across {len(unique_agents)} agents",
                    "hours_saved_per_year": hours_yearly,
                    "hourly_rate": self._rate_for_agents(unique_agents),
                    "annual_value": annual_value,
                    "confidence": round(confidence, 2),
                    "difficulty": config.get("difficulty", "medium"),
                    "recommended_action": self._recommendation_for(pattern),
                    "source": "blocker_pattern",
                }
                opportunities.append(opp)

        return opportunities

    def _detect_workflow_automation(self, entries: List[Dict]) -> List[Dict]:
        """Find handoff patterns that suggest workflow automation."""
        handoffs = [e for e in entries if e.get("type") == "handoff"]
        if len(handoffs) < 3:
            return []

        # Count handoff pairs
        pair_counts: Dict[str, int] = defaultdict(int)
        pair_entries: Dict[str, List[Dict]] = defaultdict(list)

        for h in handoffs:
            content = h.get("content", "")
            match = re.match(r'\[(.+?)\s*→\s*(.+?)\]\s*\((.+?)\)', content)
            if match:
                key = f"{match.group(1).strip()} → {match.group(2).strip()}"
                pair_counts[key] += 1
                pair_entries[key].append(h)

        opportunities = []
        for pair, count in pair_counts.items():
            if count >= 3:
                from_agent, to_agent = pair.split(" → ")
                hours_per_handoff = 1.5  # avg time per manual handoff
                freq_per_week = self._estimate_frequency(pair_entries[pair])
                hours_yearly = int(freq_per_week * 52 * hours_per_handoff)
                annual_value = int(hours_yearly * 100)  # blended rate
                confidence = min(0.5 + (count * 0.05), 0.9)

                opportunities.append({
                    "id": f"{self._scan_id}_workflow_{from_agent}_{to_agent}",
                    "title": f"Automate handoffs from {from_agent} to {to_agent}",
                    "department": "Operations",
                    "category": "workflow_automation",
                    "pattern": f"Recurring {from_agent} → {to_agent} transfers",
                    "evidence": f"{count} handoffs in last {self.window_days} days",
                    "hours_saved_per_year": hours_yearly,
                    "hourly_rate": 100,
                    "annual_value": annual_value,
                    "confidence": round(confidence, 2),
                    "difficulty": "medium" if count < 10 else "easy",
                    "recommended_action": f"Build automation for {from_agent} → {to_agent} workflow",
                    "source": "handoff_pattern",
                })

        return opportunities

    def _detect_knowledge_base_gaps(self, entries: List[Dict]) -> List[Dict]:
        """Find frequently asked questions without documented answers."""
        questions = [e for e in entries if e.get("type") == "question"]
        if len(questions) < 3:
            return []

        decisions = [e for e in entries if e.get("type") == "decision"]
        decision_tags = set()
        for d in decisions:
            decision_tags.update(d.get("tags", []))

        # Find questions on topics with no decisions
        topic_questions: Dict[str, List[Dict]] = defaultdict(list)
        for q in questions:
            for tag in q.get("tags", []):
                if tag not in decision_tags:
                    topic_questions[tag].append(q)

        opportunities = []
        for tag, qs in topic_questions.items():
            if len(qs) >= 2:
                unique_agents = set(q.get("agent_id", "?") for q in qs)
                hours_per_inquiry = 1.0  # time to research/re-answer
                freq_per_week = self._estimate_frequency(qs)
                hours_yearly = int(freq_per_week * 52 * hours_per_inquiry)
                annual_value = int(hours_yearly * 60)  # support rates

                opportunities.append({
                    "id": f"{self._scan_id}_knowledge_{tag}",
                    "title": f"Create knowledge base for '{tag}' questions",
                    "department": "Support",
                    "category": "knowledge_base",
                    "pattern": f"Unanswered questions about '{tag}'",
                    "evidence": f"{len(qs)} questions from {len(unique_agents)} agents",
                    "hours_saved_per_year": hours_yearly,
                    "hourly_rate": 60,
                    "annual_value": annual_value,
                    "confidence": round(min(0.5 + (len(qs) * 0.08), 0.9), 2),
                    "difficulty": "easy",
                    "recommended_action": f"Create KB article for '{tag}' FAQ",
                    "source": "knowledge_gap",
                })

        return opportunities

    def _detect_bottlenecks(self, entries: List[Dict]) -> List[Dict]:
        """Find agents with high handoff volume suggesting load balancing."""
        handoffs = [e for e in entries if e.get("type") == "handoff"]
        if len(handoffs) < 5:
            return []

        # Count handoffs per target agent
        to_counts: Counter = Counter()
        for h in handoffs:
            content = h.get("content", "")
            match = re.match(r'\[(.+?)\s*→\s*(.+?)\]\s*\((.+?)\)', content)
            if match:
                to_counts[match.group(2).strip()] += 1

        opportunities = []
        for agent, count in to_counts.most_common(3):
            if count >= 5:
                hours_yearly = int(count * (52 / max(self._estimate_frequency(handoffs), 1)) * 0.5)
                opportunities.append({
                    "id": f"{self._scan_id}_bottleneck_{agent}",
                    "title": f"Load balance handoffs for {agent}",
                    "department": "Operations",
                    "category": "load_balancing",
                    "pattern": f"Single point of handoff congestion",
                    "evidence": f"{count} handoffs routed through {agent}",
                    "hours_saved_per_year": hours_yearly,
                    "hourly_rate": 100,
                    "annual_value": int(hours_yearly * 100),
                    "confidence": round(min(0.5 + (count * 0.03), 0.85), 2),
                    "difficulty": "medium",
                    "recommended_action": f"Distribute {agent}'s workload or automate triage",
                    "source": "bottleneck",
                })

        return opportunities

    def _detect_repeated_decisions(self, entries: List[Dict]) -> List[Dict]:
        """Find decisions made repeatedly on the same topic."""
        decisions = [e for e in entries if e.get("type") == "decision"]
        if len(decisions) < 3:
            return []

        tag_groups: Dict[str, List[Dict]] = defaultdict(list)
        for d in decisions:
            for tag in d.get("tags", []):
                tag_groups[tag].append(d)

        opportunities = []
        for tag, group in tag_groups.items():
            if len(group) >= 3 and not tag.startswith("agent:"):
                unique_agents = set(e.get("agent_id", "?") for e in group)
                hours_per_decision = 4.0  # avg time per decision process
                hours_yearly = int(len(group) * 4)
                annual_value = int(hours_yearly * 150)

                opportunities.append({
                    "id": f"{self._scan_id}_decision_{tag}",
                    "title": f"Standardize decisions on '{tag}'",
                    "department": "Engineering",
                    "category": "policy_standardization",
                    "pattern": f"Repeated {tag} decisions across {len(unique_agents)} agents",
                    "evidence": f"{len(group)} decisions from {len(unique_agents)} agents",
                    "hours_saved_per_year": hours_yearly,
                    "hourly_rate": 150,
                    "annual_value": annual_value,
                    "confidence": round(min(0.5 + (len(group) * 0.05), 0.85), 2),
                    "difficulty": "easy",
                    "recommended_action": f"Create policy/runbook for '{tag}' decisions",
                    "source": "repeated_decision",
                })

        return opportunities

    def _detect_manual_patterns(self, entries: List[Dict]) -> List[Dict]:
        """Find entries describing manual processes that could be automated."""
        manual_keywords = [
            "manual", "hand-typed", "copy paste", "by hand", "human review",
            "eyeball", "manual check", "spreadsheet", "email chain",
            "back and forth", "phone tag", "paper form",
        ]

        opportunities = []
        for entry in entries:
            content = entry.get("content", "").lower()
            for keyword in manual_keywords:
                if keyword in content:
                    opportunities.append({
                        "id": f"{self._scan_id}_manual_{entry['id'][:8]}",
                        "title": f"Automate manual process: '{keyword}'",
                        "department": "Operations",
                        "category": "task_automation",
                        "pattern": f"Manual '{keyword}' process detected",
                        "evidence": f"Entry from {entry.get('agent_id', '?')}: {content[:80]}...",
                        "hours_saved_per_year": 100,  # rough estimate
                        "hourly_rate": 75,
                        "annual_value": 7500,
                        "confidence": 0.4,
                        "difficulty": "medium",
                        "recommended_action": "Review and automate this manual step",
                        "source": "manual_pattern",
                    })
                    break  # one opp per entry

        return opportunities[:5]  # limit manual detections

    # ── Helpers ──

    def _estimate_frequency(self, entries: List[Dict]) -> float:
        """Estimate weekly frequency from a list of entries."""
        if not entries:
            return 0

        timestamps = []
        for e in entries:
            created = e.get("created_at", "")
            if created:
                try:
                    ts = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
                    timestamps.append(ts)
                except (ValueError, AttributeError):
                    pass

        if len(timestamps) < 2:
            return max(len(entries), 1)

        # Calculate date range in days
        min_ts = min(timestamps)
        max_ts = max(timestamps)
        days = (max_ts - min_ts).days + 1

        if days < 1:
            return len(timestamps)

        return len(timestamps) / max(days / 7, 0.1)

    def _rate_for_agents(self, agents: set) -> int:
        """Get blended hourly rate for a group of agents."""
        return 100  # simplified blended rate

    def _calculate_score(self, opp: Dict) -> float:
        """Calculate a composite score for ranking opportunities."""
        value_score = min(opp.get("annual_value", 0) / 50000, 1.0)
        confidence_score = opp.get("confidence", 0)
        ease_score = {"easy": 1.0, "medium": 0.5, "hard": 0.2}.get(
            opp.get("difficulty", "medium"), 0.5
        )
        return (value_score * 0.4) + (confidence_score * 0.35) + (ease_score * 0.25)

    def _recommendation_for(self, pattern: str) -> str:
        """Get a recommended action for a pattern."""
        recs = {
            "timeout": "Implement automated retry with exponential backoff",
            "error": "Build automated error handling and alerting",
            "failed": "Create automated retry + notification pipeline",
            "manual": "Evaluate for robotic process automation (RPA)",
            "permission denied": "Implement just-in-time access provisioning",
            "connection refused": "Add health check + auto-restart",
            "rate limit": "Implement rate limiting with queuing",
            "timeout exceeded": "Add circuit breaker + fallback",
        }
        return recs.get(pattern, f"Investigate and automate '{pattern}' handling")

    def _summarize_by_category(self, opportunities: List[Dict]) -> Dict:
        """Summarize opportunities by category."""
        summary: Dict = {}
        for opp in opportunities:
            cat = opp.get("category", "other")
            if cat not in summary:
                summary[cat] = {"count": 0, "value": 0.0}
            summary[cat]["count"] += 1
            summary[cat]["value"] += opp.get("annual_value", 0)
        return summary



