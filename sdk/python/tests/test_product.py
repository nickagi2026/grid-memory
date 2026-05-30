"""Tests for product-value features: expansion score, validation workflow, QBR 2.0."""

import os
import tempfile
import unittest
from grid_memory.local_grid import LocalGrid
from grid_memory.product.expansion import ExpansionScore
from grid_memory.product.validation import ValidationWorkflow
from grid_memory.product.qbr2 import QBRGenerator2
from grid_memory.engagement import EngagementGraph


class TestExpansionScore(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.grid = LocalGrid(store_dir=self.tmpdir)

    def tearDown(self):
        import shutil; shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_empty_score(self):
        es = ExpansionScore(self.grid, "test-client")
        r = es.calculate()
        self.assertIn("overall_score", r)
        self.assertIn("components", r)

    def test_score_with_data(self):
        self.grid.fact("Test", tags=["test"], agent_id="a")
        self.grid.fact("Test 2", tags=["test"], agent_id="a")
        es = ExpansionScore(self.grid, "test")
        r = es.calculate()
        self.assertGreater(r["overall_score"], 0)

    def test_recommendation(self):
        es = ExpansionScore(self.grid, "test")
        r = es.calculate()
        self.assertIn("recommendation", r)


class TestValidationWorkflow(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.grid = LocalGrid(store_dir=self.tmpdir)
        self.vw = ValidationWorkflow(self.grid)

    def tearDown(self):
        import shutil; shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_validate(self):
        from grid_memory.opportunity_lifecycle import OpportunityLifecycle
        ol = OpportunityLifecycle(self.grid)
        opp = ol.create(title="Test opp")
        r = self.vw.validate(opp["entry_id"], "triage", "reviewer", "Quick check")
        self.assertTrue(r["success"])
        self.assertEqual(r["gate"], "triage")

    def test_unknown_gate(self):
        r = self.vw.validate("test-id", "unknown_gate")
        self.assertFalse(r["success"])

    def test_pending(self):
        from grid_memory.opportunity_lifecycle import OpportunityLifecycle
        ol = OpportunityLifecycle(self.grid)
        ol.create(title="Pending opp")
        r = self.vw.get_pending()
        self.assertGreaterEqual(r["total"], 1)

    def test_pipeline(self):
        r = self.vw.get_pipeline()
        self.assertIn("by_gate", r)


class TestQBRGenerator2(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.grid = LocalGrid(store_dir=self.tmpdir)
        self.eg = EngagementGraph(self.grid)

    def tearDown(self):
        import shutil; shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_generate(self):
        self.eg.track("test-client", "discovery", "Started", "")
        qbr = QBRGenerator2(self.grid, "test-client")
        r = qbr.generate("Q2 2026")
        self.assertIn("executive_summary", r)
        self.assertIn("health", r)
        self.assertIn("expansion", r)

    def test_format_clients(self):
        self.eg.track("acme", "discovery", "Started", "")
        qbr = QBRGenerator2(self.grid, "acme")
        text = qbr.format_clients()
        self.assertIn("Quarterly Business Review", text)

    def test_health_score(self):
        qbr = QBRGenerator2(self.grid, "test").generate()
        self.assertIn("health", qbr)
        self.assertIn("score", qbr["health"])
        self.assertIn("level", qbr["health"])


if __name__ == "__main__":
    unittest.main()
