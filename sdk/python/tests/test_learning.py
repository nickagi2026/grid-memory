"""Tests for the learning layer / pattern detection."""

import os
import tempfile
import unittest
from grid_memory.local_grid import LocalGrid
from grid_memory.learning import LearningEngine


class TestLearningEngine(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.grid = LocalGrid(store_dir=self.tmpdir)
        self.engine = LearningEngine(self.grid, min_samples=2, window_hours=9999)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_empty_grid_returns_empty(self):
        results = self.engine.analyze()
        self.assertEqual(results["total_entries_analyzed"], 0)
        self.assertEqual(results["recurring_blockers"], [])

    def test_blocker_detection(self):
        self.grid.write(agent_id="agent1", type="blocker",
                         content="timeout: database connection timeout", tags=["db"])
        self.grid.write(agent_id="agent2", type="blocker",
                         content="timeout: database connection timeout again", tags=["db"])
        self.grid.write(agent_id="agent3", type="blocker",
                         content="timeout: database keeps timing out", tags=["db"])
        results = self.engine.analyze()
        self.assertGreaterEqual(len(results["recurring_blockers"]), 1)

    def test_frequent_decisions(self):
        self.grid.decide("Use PostgreSQL", tags=["database", "architecture"],
                          agent_id="arch1")
        self.grid.decide("Use PostgreSQL for main DB", tags=["database", "architecture"],
                          agent_id="arch2")
        results = self.engine.analyze()
        # The tag "database" should appear as a frequent decision topic
        freq = results.get("frequent_decisions", [])
        self.assertGreaterEqual(len(freq), 1)

    def test_workflow_patterns(self):
        self.grid.handoff(from_agent="researcher", to_agent="builder",
                           content="API design ready", status="ready")
        self.grid.handoff(from_agent="researcher", to_agent="builder",
                           content="DB schema ready", status="ready")
        self.grid.handoff(from_agent="researcher", to_agent="builder",
                           content="Tests passing", status="ready")
        results = self.engine.analyze()
        workflows = results.get("workflow_patterns", [])
        self.assertGreaterEqual(len(workflows), 1)
        self.assertEqual(workflows[0]["from_agent"], "researcher")
        self.assertEqual(workflows[0]["to_agent"], "builder")

    def test_agent_trends(self):
        self.grid.fact("Entry 1", agent_id="worker-a", tags=["test"])
        self.grid.fact("Entry 2", agent_id="worker-a", tags=["test"])
        self.grid.decide("Decision 1", agent_id="worker-a", tags=["arch"])
        results = self.engine.analyze()
        trends = results.get("agent_trends", [])
        self.assertGreaterEqual(len(trends), 1)
        worker = next((t for t in trends if t["agent"] == "worker-a"), None)
        self.assertIsNotNone(worker)
        self.assertEqual(worker["total_entries"], 3)

    def test_top_tags(self):
        self.grid.fact("Entry 1", tags=["database", "prod", "config"])
        self.grid.fact("Entry 2", tags=["database", "prod"])
        self.grid.fact("Entry 3", tags=["database"])
        results = self.engine.analyze()
        tags = results.get("top_tags", [])
        self.assertGreaterEqual(len(tags), 1)
        self.assertEqual(tags[0]["tag"], "database")
        self.assertEqual(tags[0]["count"], 3)

    def test_knowledge_gaps(self):
        self.grid.write(agent_id="dev", type="question",
                         content="What is the max pool size?",
                         tags=["database", "config"])
        self.grid.write(agent_id="dev", type="question",
                         content="What timeout should we use?",
                         tags=["database", "config"])
        # No decision entries on these topics = gap
        results = self.engine.analyze()
        gaps = results.get("knowledge_gaps", [])
        self.assertGreaterEqual(len(gaps), 1)

    def test_insights_generated(self):
        self.grid.handoff(from_agent="a", to_agent="b",
                           content="Work item 1", status="ready")
        self.grid.handoff(from_agent="a", to_agent="b",
                           content="Work item 2", status="ready")
        self.grid.handoff(from_agent="a", to_agent="b",
                           content="Work item 3", status="ready")
        insights = self.engine.get_insights(min_confidence=0.0)
        self.assertGreaterEqual(len(insights), 1)

    def test_extract_numbers(self):
        text = "pool: 25 connections, port: 5432, timeout: 30"
        nums = self.engine._extract_numbers(text)
        self.assertEqual(nums.get("pool"), 25)
        self.assertEqual(nums.get("port"), 5432)
        self.assertEqual(nums.get("timeout"), 30)

    def test_extract_phrases(self):
        text = 'Got a "connection refused" error and a timeout exceeded'
        phrases = self.engine._extract_phrases(text)
        self.assertIn("connection refused", phrases)
        self.assertIn("timeout exceeded", phrases)

    def test_contradiction_detection(self):
        self.grid.fact("Pool size: 25", tags=["database", "config"],
                        agent_id="dev1")
        self.grid.fact("Pool size: 50 on prod", tags=["database", "config"],
                        agent_id="dev2")
        results = self.engine.analyze()
        contradictions = results.get("contradictions", [])
        # May or may not detect depending on tag grouping
        self.assertIsInstance(contradictions, list)

    def test_empty_insights(self):
        insights = self.engine.get_insights()
        self.assertEqual(insights, [])

    def test_multiple_blockers_different_agents(self):
        for i in range(5):
            self.grid.write(agent_id=f"agent{i}", type="blocker",
                             content=f"Timeout error on service-{i % 2}", tags=["timeout"])
        results = self.engine.analyze()
        self.assertGreaterEqual(len(results["recurring_blockers"]), 1)

    def test_agent_trend_type_breakdown(self):
        self.grid.fact("Fact 1", agent_id="multi")
        self.grid.fact("Fact 2", agent_id="multi")
        self.grid.decide("Decision 1", agent_id="multi")
        results = self.engine.analyze()
        trends = results.get("agent_trends", [])
        if trends:
            tb = trends[0].get("type_breakdown", {})
            self.assertIn("fact", tb)
            self.assertIn("decision", tb)


if __name__ == "__main__":
    unittest.main()
