"""Tests for business intelligence, governance, and knowledge ops."""

import os
import tempfile
import unittest
from grid_memory.local_grid import LocalGrid
from grid_memory.business.dashboards import ExecutiveDashboard, RevenueDashboard
from grid_memory.enterprise.governance import GovernanceEngine
from grid_memory.knowledge_ops import KnowledgeOps


class TestDashboards(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.grid = LocalGrid(store_dir=self.tmpdir)

    def tearDown(self):
        import shutil; shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_executive_dashboard(self):
        self.grid.fact("Test", tags=["t"], agent_id="a")
        ed = ExecutiveDashboard(self.grid, "test")
        r = ed.generate()
        self.assertIn("total_entries", r)
        self.assertIn("active_agents", r)

    def test_revenue_dashboard(self):
        rd = RevenueDashboard(self.grid)
        r = rd.generate()
        self.assertIn("total_revenue", r)


class TestGovernance(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.grid = LocalGrid(store_dir=self.tmpdir)
        self.gov = GovernanceEngine(self.grid)

    def tearDown(self):
        import shutil; shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_classify_public(self):
        r = self.gov.classify_content("Clean text about databases")
        self.assertEqual(r["classification"], "public")

    def test_classify_restricted(self):
        r = self.gov.classify_content("SSN: 123-45-6789")
        self.assertEqual(r["classification"], "restricted")

    def test_compliance_check(self):
        r = self.gov.compliance_check("hipaa")
        self.assertIn("compliance_score", r)
        self.assertIn("checks", r)

    def test_legal_hold(self):
        r = self.gov.legal_hold("ws-1", "case-123")
        self.assertTrue(r["hold_placed"])


class TestKnowledgeOps(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.grid = LocalGrid(store_dir=self.tmpdir)
        self.ko = KnowledgeOps(self.grid)

    def tearDown(self):
        import shutil; shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_audit_empty(self):
        r = self.ko.audit_knowledge()
        self.assertEqual(r["total_lessons"], 0)

    def test_audit_with_data(self):
        self.grid.write(agent_id="test", type="lesson",
                         content="Lesson: test", tags=["cat:worked", "lesson"])
        r = self.ko.audit_knowledge()
        self.assertGreaterEqual(r["total_lessons"], 1)

    def test_accelerator_not_enough_lessons(self):
        r = self.ko.generate_accelerator_from_lessons("healthcare", 10)
        self.assertFalse(r["generated"])

    def test_cross_engagement_learning(self):
        r = self.ko.cross_engagement_learning()
        self.assertIn("total_cross_cutting_topics", r)
