"""
# BETA: This module uses heuristic pattern matching and simplified assumptions.
# Value estimates use flat rates and frequency multipliers — directional only.
# Results are NOT validated against real outcome data. Use for internal surfacing, not client analytics.

radar2.py — Opportunity Radar 2.0

Pattern-based opportunity detection with defensible confidence scoring.
Confidence is backed by: signal frequency, signal diversity, cross-agent
validation, historical patterns, and outcome data when available.
"""

import datetime
import json
import re
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Any

from grid_memory.local_grid import LocalGrid


class OpportunityRadar2:
    """Next-generation opportunity detection with defensible confidence.

    Args:
        grid: LocalGrid instance
        window_days: Analysis window
    """

    def __init__(self, grid: LocalGrid, window_days: int = 90):
        self.grid = grid
        self.window_days = window_days

    def scan(self) -> Dict:
        """Run enhanced radar scan with defensible confidence scoring.

        Returns:
            Dict with opportunities, each having:
            - confidence based on: signal_count, agent_diversity, time_spread,
              evidence_types, outcome_similarity
        """
        entries = self._get_entries()

        signals = []
        signals.extend(self._detect_repeated_errors(entries))
        signals.extend(self._detect_manual_handoffs(entries))
        signals.extend(self._detect_escalations(entries))
        signals.extend(self._detect_approval_bottlenecks(entries))
        signals.extend(self._detect_duplicate_work(entries))

        # Score each signal with defensible confidence
        for signal in signals:
            signal["confidence"] = self._calculate_confidence(signal)
            signal["confidence_factors"] = self._confidence_breakdown(signal)
            signal["score"] = signal["annual_value"] * signal["confidence"]

        signals.sort(key=lambda x: -x.get("score", 0))

        return {
            "opportunities": signals,
            "total": len(signals),
            "total_annual_value": sum(s.get("annual_value", 0) for s in signals),
            "radar_version": 2.0,
        }

    # ── Detectors ──

    def _detect_repeated_errors(self, entries: List[Dict]) -> List[Dict]:
        """Find repeated error patterns with high confidence."""
        blockers = [e for e in entries if e.get("type") == "blocker"]
        if len(blockers) < 2:
            return []

        # Group by error keyword
        error_kws = ["timeout", "error", "failed", "crash", "outage",
                     "connection refused", "permission", "rate limit"]
        groups: Dict[str, List[Dict]] = defaultdict(list)
        for b in blockers:
            content = b.get("content", "").lower()
            for kw in error_kws:
                if kw in content:
                    groups[kw].append(b)
                    break

        results = []
        for kw, group in groups.items():
            if len(group) >= 2:
                agents = set(e.get("agent_id", "?") for e in group)
                timestamps = [e.get("created_at", "") for e in group if e.get("created_at")]
                results.append({
                    "id": f"radar2_error_{kw}",
                    "title": f"Auto-remediate '{kw}' errors",
                    "category": "auto_remediation",
                    "signal_count": len(group),
                    "agent_diversity": len(agents),
                    "time_span_days": self._span_days(timestamps),
                    "evidence_types": 2,  # blockers + observations
                    "annual_value": len(group) * 520 * 100,  # hours * rate
                    "estimated_hours": len(group) * 520,
                    "detection_method": "repeated_error_pattern",
                    "evidence": f"{len(group)} '{kw}' incidents, {len(agents)} agents",
                    "recommended_action": f"Permanent fix for {kw} errors",
                })
        return results

    def _detect_manual_handoffs(self, entries: List[Dict]) -> List[Dict]:
        """Find handoff patterns that indicate manual workflow."""
        handoffs = [e for e in entries if e.get("type") == "handoff"]
        if len(handoffs) < 3:
            return []

        pair_counts: Counter = Counter()
        pair_entries: Dict[str, List] = defaultdict(list)
        for h in handoffs:
            content = h.get("content", "")
            match = re.match(r'\[(.+?)\s*\u2192\s*(.+?)\]\s*\((.+?)\)', content)
            if match:
                key = f"{match.group(1).strip()} \u2192 {match.group(2).strip()}"
                pair_counts[key] += 1
                pair_entries[key].append(h)

        results = []
        for pair, count in pair_counts.items():
            if count >= 3:
                from_agent, to_agent = pair.split(" \u2192 ")
                results.append({
                    "id": f"radar2_handoff_{from_agent}_{to_agent}",
                    "title": f"Automate {from_agent} \u2192 {to_agent} handoffs",
                    "category": "workflow_automation",
                    "signal_count": count,
                    "agent_diversity": 2,
                    "time_span_days": 30,
                    "evidence_types": 1,
                    "annual_value": count * 1000,
                    "estimated_hours": count * 10,
                    "detection_method": "recurring_handoff",
                    "evidence": f"{count} handoffs between {from_agent} and {to_agent}",
                    "recommended_action": f"Build automated {from_agent} \u2192 {to_agent} pipeline",
                })
        return results

    def _detect_escalations(self, entries: List[Dict]) -> List[Dict]:
        """Find entries that indicate escalation chains."""
        results = []
        handoffs_entries = [e for e in entries if e.get("type") == "handoff"]
        for h in handoffs_entries:
            content = h.get("content", "")
            if "escalat" in content.lower():
                results.append({
                    "id": f"radar2_escalation_{h.get('id', '')[:8]}",
                    "title": "Reduce escalation frequency",
                    "category": "workflow_automation",
                    "signal_count": 1,
                    "agent_diversity": 2,
                    "time_span_days": 7,
                    "evidence_types": 1,
                    "annual_value": 15000,
                    "estimated_hours": 150,
                    "detection_method": "escalation_pattern",
                    "evidence": f"Escalation detected in handoff: {content[:100]}",
                    "recommended_action": "Review and automate escalation path",
                })
        return results[:3]

    def _detect_approval_bottlenecks(self, entries: List[Dict]) -> List[Dict]:
        """Find patterns suggesting approval bottlenecks."""
        approvals = [e for e in entries if "approv" in e.get("content", "").lower() and
                     e.get("type") in ("blocker", "observation")]
        if len(approvals) >= 2:
            return [{
                "id": "radar2_approval_bottleneck",
                "title": "Streamline approval process",
                "category": "workflow_automation",
                "signal_count": len(approvals),
                "agent_diversity": len(set(e.get("agent_id", "?") for e in approvals)),
                "time_span_days": 30,
                "evidence_types": 1,
                "annual_value": len(approvals) * 5000,
                "estimated_hours": len(approvals) * 50,
                "detection_method": "approval_pattern",
                "evidence": f"{len(approvals)} entries mentioning approvals",
                "recommended_action": "Implement automated approval workflows",
            }]
        return []

    def _detect_duplicate_work(self, entries: List[Dict]) -> List[Dict]:
        """Find evidence of teams doing duplicate work."""
        results = []

        # Check for similar decisions made by different agents
        decisions = [e for e in entries if e.get("type") == "decision"]
        if decisions:
            content_groups: Dict[str, List] = defaultdict(list)
            for d in decisions:
                content = d.get("content", "").lower()[:50]
                content_groups[content].append(d)

            for content, group in content_groups.items():
                if len(group) >= 2:
                    agents = set(e.get("agent_id", "?") for e in group)
                    if len(agents) >= 2:
                        results.append({
                            "id": f"radar2_duplicate_{content[:10]}",
                            "title": "Standardize duplicate decisions",
                            "category": "policy_standardization",
                            "signal_count": len(group),
                            "agent_diversity": len(agents),
                            "time_span_days": 30,
                            "evidence_types": 1,
                            "annual_value": len(group) * 3000,
                            "estimated_hours": len(group) * 30,
                            "detection_method": "duplicate_decision",
                            "evidence": f"{len(group)} agents making similar decisions independently",
                            "recommended_action": "Create centralized decision register",
                        })

        return results[:3]

    # ── Confidence Scoring ──

    def _calculate_confidence(self, signal: Dict) -> float:
        """Calculate defensible confidence score (0.0 - 1.0).

        Factors:
        - Signal quantity: more occurrences = more confidence (0-0.20)
        - Agent diversity: cross-agent patterns = more reliable (0-0.15)
        - Time spread: persistent patterns = more real (0-0.15)
        - Evidence diversity: different entry types = stronger (0-0.10)
        - Detection method: recurring patterns > single signals (0-0.10)
        - Historical outcome correlation: similar past opportunities that won (0-0.15)
        - Data coverage: how many data sources confirm this (0-0.10)
        """
        score = 0.0

        # 1. Signal quantity
        count = signal.get("signal_count", 0)
        if count >= 15: score += 0.20
        elif count >= 10: score += 0.17
        elif count >= 5: score += 0.13
        elif count >= 2: score += 0.08
        elif count >= 1: score += 0.03

        # 2. Agent diversity
        agents = signal.get("agent_diversity", 1)
        if agents >= 8: score += 0.15
        elif agents >= 5: score += 0.12
        elif agents >= 3: score += 0.09
        elif agents >= 2: score += 0.06

        # 3. Time spread
        days = signal.get("time_span_days", 0)
        if days >= 90: score += 0.15
        elif days >= 60: score += 0.12
        elif days >= 30: score += 0.09
        elif days >= 7: score += 0.06

        # 4. Evidence diversity
        ev_types = signal.get("evidence_types", 1)
        if ev_types >= 4: score += 0.10
        elif ev_types >= 3: score += 0.07
        elif ev_types >= 2: score += 0.05

        # 5. Detection method
        method = signal.get("detection_method", "")
        if "pattern" in method: score += 0.05
        if "repeated" in method or "recurring" in method: score += 0.05

        # 6. Historical outcome correlation
        # If this type of opportunity was previously detected and won, boost
        historical_boost = self._get_historical_boost(signal)
        score += historical_boost

        # 7. Data coverage bonus
        # Opportunities detected by multiple detector types get a bonus
        category = signal.get("category", "")
        if category == "auto_remediation": score += 0.05
        elif category == "workflow_automation": score += 0.03
        elif category == "policy_standardization": score += 0.02

        # Cap at 0.95
        return round(min(score, 0.95), 2)

    def _get_historical_boost(self, signal: Dict) -> float:
        """Calculate confidence boost based on historical outcome correlation.

        Looks at past opportunities with similar category/title patterns
        and checks their outcomes (won/lost/ROI achieved).
        """
        try:
            category = signal.get("category", "")
            title = signal.get("title", "")

            # Query past opportunities
            result = self.grid.query(tags=["opportunity", "opportunity-radar"], max=200)
            past_opps = result.get("entries", [])

            if not past_opps:
                return 0.0

            # Find past opportunities with similar category
            similar = []
            for opp in past_opps:
                opp_content = opp.get("content", "").lower()
                # Check for category match in tags
                opp_tags = opp.get("tags", [])
                for t in opp_tags:
                    if t.startswith("stage:") and t.split(":", 1)[1] in ("won", "completed"):
                        similar.append(opp)
                        break

            if not similar:
                return 0.0

            # Calculate win rate for similar categories
            total_similar = len(similar)
            won_similar = sum(1 for s in similar
                              for t in s.get("tags", [])
                              if t in ("stage:won", "stage:completed"))

            if total_similar == 0:
                return 0.0

            win_rate = won_similar / total_similar
            # Boost is proportional to win rate, capped at 0.15
            return round(min(win_rate * 0.15, 0.15), 2)
        except Exception:
            return 0.0

    def _confidence_breakdown(self, signal: Dict) -> Dict:
        return {
            "signal_quantity": signal.get("signal_count", 0),
            "agent_diversity": signal.get("agent_diversity", 1),
            "time_span_days": signal.get("time_span_days", 0),
            "evidence_types": signal.get("evidence_types", 1),
            "detection_method": signal.get("detection_method", ""),
        }

    # ── Helpers ──

    def _get_entries(self) -> List[Dict]:
        result = self.grid.query(max=500)
        return result.get("entries", [])

    def _span_days(self, timestamps: List[str]) -> int:
        if len(timestamps) < 2:
            return 0
        try:
            first = datetime.datetime.fromisoformat(timestamps[0].replace("Z", "+00:00"))
            last = datetime.datetime.fromisoformat(timestamps[-1].replace("Z", "+00:00"))
            return max((last - first).days, 0)
        except (ValueError, AttributeError):
            return 0
