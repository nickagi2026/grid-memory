"""
learning.py — Pattern Detection & Learning Layer for the Grid.

Analyzes entries across the store to surface:
- Recurring blockers and failure patterns
- Frequent decisions and standardization opportunities
- Workflow inefficiencies from handoff analysis
- Agent activity trends
- Knowledge gaps (missing information on frequently accessed topics)

Usage:
    from grid_memory.learning import LearningEngine

    engine = LearningEngine(grid)
    patterns = engine.analyze()
    print(patterns["recurring_blockers"])
    print(patterns["top_decisions"])
    print(patterns["agent_trends"])
"""

import datetime
import re
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Any, Tuple

from grid_memory.local_grid import LocalGrid


class LearningEngine:
    """Analyzes Grid entries for patterns, trends, and insights.

    Args:
        grid: LocalGrid instance
        min_samples: Minimum data points for pattern detection
        window_hours: Time window for trend analysis
    """

    def __init__(self, grid: LocalGrid,
                 min_samples: int = 3,
                 window_hours: int = 168):
        self.grid = grid
        self.min_samples = min_samples
        self.window_hours = window_hours

    def analyze(self) -> Dict:
        """Run all analyses and return comprehensive results.

        Returns:
            Dict with all pattern categories
        """
        entries = self._get_recent_entries()

        return {
            "analyzed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "total_entries_analyzed": len(entries),
            "recurring_blockers": self._find_recurring_blockers(entries),
            "frequent_decisions": self._find_frequent_decisions(entries),
            "workflow_patterns": self._find_workflow_patterns(entries),
            "agent_trends": self._find_agent_trends(entries),
            "contradictions": self._find_contradictions(entries),
            "knowledge_gaps": self._find_knowledge_gaps(entries),
            "top_tags": self._find_top_tags(entries),
        }

    def get_insights(self, min_confidence: float = 0.3) -> List[Dict]:
        """Get ranked insights with confidence scores."""
        results = self.analyze()
        insights = []

        # Recurring blockers → insights
        for blocker in results.get("recurring_blockers", []):
            score = min(blocker["count"] / max(blocker.get("agents_involved", 1), 1), 1.0)
            if score >= min_confidence:
                insights.append({
                    "type": "recurring_blocker",
                    "confidence": round(score, 2),
                    "summary": f"Blocker '{blocker['pattern']}' occurred {blocker['count']}x",
                    "detail": blocker,
                })

        # Frequent decisions → insights
        for decision in results.get("frequent_decisions", []):
            score = min(decision["count"] / 10, 1.0)
            if score >= min_confidence:
                insights.append({
                    "type": "frequent_decision",
                    "confidence": round(score, 2),
                    "summary": f"'{decision['topic']}' decided {decision['count']}x — consider standardizing",
                    "detail": decision,
                })

        # Workflow patterns → insights
        for wf in results.get("workflow_patterns", []):
            insights.append({
                "type": "workflow_pattern",
                "confidence": min(wf.get("handoff_count", 1) / 5, 1.0),
                "summary": f"Workflow: {wf.get('from_agent', '?')} → {wf.get('to_agent', '?')} ({wf.get('handoff_count', 0)} handoffs)",
                "detail": wf,
            })

        insights.sort(key=lambda x: -x["confidence"])
        return insights

    # ── Pattern Detectors ──

    def _get_recent_entries(self) -> List[Dict]:
        """Get entries within the analysis window."""
        result = self.grid.query(max=200)
        entries = result.get("entries", [])
        cutoff = (datetime.datetime.now(datetime.timezone.utc) -
                  datetime.timedelta(hours=self.window_hours)).isoformat()

        recent = []
        for e in entries:
            created = e.get("created_at", "")
            if created >= cutoff:
                recent.append(e)
        return recent

    def _find_recurring_blockers(self, entries: List[Dict]) -> List[Dict]:
        """Find patterns in blocker-type entries."""
        blockers = [e for e in entries if e.get("type") == "blocker"]
        if len(blockers) < self.min_samples:
            return []

        # Extract topics from blocker content
        topics = Counter()
        for b in blockers:
            content = b.get("content", "").lower()
            # Look for key phrases
            for phrase in self._extract_phrases(content):
                topics[phrase] += 1

        recurring = []
        for phrase, count in topics.most_common(10):
            if count >= self.min_samples:
                agents = set()
                for b in blockers:
                    if phrase in b.get("content", "").lower():
                        agents.add(b.get("agent_id", "?"))
                recurring.append({
                    "pattern": phrase,
                    "count": count,
                    "agents_involved": len(agents),
                    "agents": list(agents),
                })

        return recurring

    def _find_frequent_decisions(self, entries: List[Dict]) -> List[Dict]:
        """Find patterns in decision entries."""
        decisions = [e for e in entries if e.get("type") == "decision"]
        if len(decisions) < self.min_samples:
            return []

        # Group by topic using tags
        tag_groups: Dict[str, List[Dict]] = defaultdict(list)
        for d in decisions:
            for tag in d.get("tags", []):
                tag_groups[tag].append(d)

        frequent = []
        for tag, group in tag_groups.items():
            if len(group) >= self.min_samples and not tag.startswith("agent:"):
                agents = set(e.get("agent_id", "?") for e in group)
                frequent.append({
                    "topic": tag,
                    "count": len(group),
                    "agents_involved": len(agents),
                    "recent_content": group[-1].get("content", "")[:150],
                })

        frequent.sort(key=lambda x: -x["count"])
        return frequent[:10]

    def _find_workflow_patterns(self, entries: List[Dict]) -> List[Dict]:
        """Analyze handoff chains to find workflow patterns."""
        handoffs = [e for e in entries if e.get("type") == "handoff"]
        if len(handoffs) < self.min_samples:
            return []

        # Extract agent-to-agent handoff patterns
        pairs: Dict[Tuple[str, str], List[Dict]] = defaultdict(list)
        for h in handoffs:
            content = h.get("content", "")
            # Parse: [from_agent → to_agent] (status)
            match = re.match(r'\[(.+?)\s*→\s*(.+?)\]\s*\((.+?)\)', content)
            if match:
                from_agent = match.group(1).strip()
                to_agent = match.group(2).strip()
                status = match.group(3).strip()
                pairs[(from_agent, to_agent)].append(h)

        patterns = []
        for (from_agent, to_agent), handoff_list in pairs.items():
            if len(handoff_list) >= self.min_samples:
                statuses = [re.match(r'\[.+?\]\s*\((.+?)\)', h.get("content", ""))
                           for h in handoff_list]
                statuses = [m.group(1) if m else "unknown" for m in statuses]
                status_counts = Counter(statuses)
                patterns.append({
                    "from_agent": from_agent,
                    "to_agent": to_agent,
                    "handoff_count": len(handoff_list),
                    "most_common_status": status_counts.most_common(1)[0][0] if statuses else "ready",
                    "status_breakdown": dict(status_counts.most_common()),
                })

        patterns.sort(key=lambda x: -x["handoff_count"])
        return patterns

    def _find_agent_trends(self, entries: List[Dict]) -> List[Dict]:
        """Analyze per-agent activity trends."""
        agent_stats: Dict[str, Dict] = defaultdict(lambda: {
            "total": 0, "types": Counter(), "tags": Counter(), "last_active": "",
        })

        for e in entries:
            agent = e.get("agent_id", "unknown")
            agent_stats[agent]["total"] += 1
            agent_stats[agent]["types"][e.get("type", "observation")] += 1
            for tag in e.get("tags", []):
                agent_stats[agent]["tags"][tag] += 1
            created = e.get("created_at", "")
            if created > agent_stats[agent]["last_active"]:
                agent_stats[agent]["last_active"] = created

        trends = []
        for agent, stats in sorted(agent_stats.items(),
                                    key=lambda x: -x[1]["total"]):
            top_type = stats["types"].most_common(1)
            trends.append({
                "agent": agent,
                "total_entries": stats["total"],
                "most_common_type": top_type[0][0] if top_type else "observation",
                "last_active": stats["last_active"],
                "type_breakdown": dict(stats["types"].most_common(5)),
                "top_tags": [t for t, _ in stats["tags"].most_common(5)],
            })

        return trends

    def _find_contradictions(self, entries: List[Dict]) -> List[Dict]:
        """Find contradictory statements (conflicting numbers, statuses)."""
        contradictions = []

        # Group by tag and look for conflicting values
        by_tag: Dict[str, List[Dict]] = defaultdict(list)
        for e in entries:
            for tag in e.get("tags", []):
                by_tag[tag].append(e)

        for tag, group in by_tag.items():
            if len(group) < 2:
                continue

            # Extract numbers from entries sharing a tag
            numbers_by_entry = []
            for e in group:
                nums = self._extract_numbers(e.get("content", ""))
                if nums:
                    numbers_by_entry.append((e["id"], nums, e.get("content", "")[:100]))

            # Check for conflicting values within same context
            if len(numbers_by_entry) >= 2:
                for i in range(len(numbers_by_entry)):
                    for j in range(i + 1, len(numbers_by_entry)):
                        for key, val_i in numbers_by_entry[i][1].items():
                            for key2, val_j in numbers_by_entry[j][1].items():
                                if key == key2 and abs(val_i - val_j) > 1:
                                    contradictions.append({
                                        "tag": tag,
                                        "field": key,
                                        "value_a": val_i,
                                        "value_b": val_j,
                                        "entry_a": numbers_by_entry[i][0],
                                        "entry_b": numbers_by_entry[j][0],
                                        "snippet_a": numbers_by_entry[i][2],
                                        "snippet_b": numbers_by_entry[j][2],
                                    })

        return contradictions[:10]

    def _find_knowledge_gaps(self, entries: List[Dict]) -> List[Dict]:
        """Identify topics with questions but no clear answers."""
        questions = [e for e in entries if e.get("type") == "question"]
        if len(questions) < self.min_samples:
            return []

        # Check if questions have matching decisions
        decisions = [e for e in entries if e.get("type") == "decision"]
        decision_topics = set()
        for d in decisions:
            decision_topics.update(t for t in d.get("tags", []))

        gaps = []
        for q in questions:
            q_tags = set(q.get("tags", []))
            unanswered = q_tags - decision_topics
            if unanswered and q_tags:
                gaps.append({
                    "question": q.get("content", "")[:100],
                    "unanswered_tags": list(unanswered),
                    "asked_by": q.get("agent_id", "?"),
                })

        return gaps[:10]

    def _find_top_tags(self, entries: List[Dict]) -> List[Dict]:
        """Find most frequently used tags across entries."""
        tag_counts: Counter = Counter()
        tag_agents: Dict[str, set] = defaultdict(set)

        for e in entries:
            for tag in e.get("tags", []):
                tag_counts[tag] += 1
                tag_agents[tag].add(e.get("agent_id", "?"))

        top = []
        for tag, count in tag_counts.most_common(20):
            top.append({
                "tag": tag,
                "count": count,
                "unique_agents": len(tag_agents[tag]),
            })

        return top

    # ── Text Helpers ──

    def _extract_phrases(self, text: str) -> List[str]:
        """Extract meaningful phrases from text for pattern matching."""
        phrases = []
        # Single keywords
        keywords = [
            "timeout", "error", "failed", "crash", "outage", "bug",
            "permission denied", "not found", "connection refused",
            "timeout exceeded", "rate limit", "quota exceeded",
            "unhandled exception", "null pointer", "memory error",
        ]
        for kw in keywords:
            if kw in text:
                phrases.append(kw)

        # Extract quoted phrases
        quoted = re.findall(r'"([^"]+)"', text)
        phrases.extend(quoted[:3])

        return phrases

    def _extract_numbers(self, text: str) -> Dict[str, float]:
        """Extract key-value numeric pairs from text."""
        numbers: Dict[str, float] = {}

        # Pattern: key: value or "key is value"
        patterns = [
            r'([a-zA-Z_ ]+)\s*:\s*(\d+(?:\.\d+)?)',
            r'([a-zA-Z_ ]+)\s+is\s+(\d+(?:\.\d+)?)',
            r'([a-zA-Z_ ]+)\s+=\s+(\d+(?:\.\d+)?)',
            r'pool\s*:\s*(\d+)',  # pool: 25
            r'port\s*:\s*(\d+)',  # port: 3000
            r'timeout\s*:\s*(\d+)',
        ]

        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                groups = match.groups()
                if len(groups) == 2:
                    key = groups[0].strip().lower().replace(" ", "_")
                    try:
                        numbers[key] = float(groups[1])
                    except ValueError:
                        pass
                elif len(groups) == 1:
                    numbers["value"] = float(groups[0])

        return numbers
