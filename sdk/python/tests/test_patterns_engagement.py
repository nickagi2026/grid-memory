"""Tests for Pattern Promotion Engine and Engagement Graph + QBR."""

import os
import tempfile
import unittest
from grid_memory.local_grid import LocalGrid
from grid_memory.patterns import PatternEngine
from grid_memory.engagement import EngagementGraph


class TestPatternEngine(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.grid = LocalGrid(store_dir=self.tmpdir)
        self.engine = PatternEngine(self.grid)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_scan_empty(self):
        result = self.engine.scan()
        self.assertEqual(result["total"], 0)

    def test_scan_detects_tag_patterns(self):
        for i in range(5):
            self.grid.fact(f"Entry {i}", tags=["database", "architecture"])
        result = self.engine.scan(min_occurrences=3)
        self.assertGreaterEqual(result["total"], 1)

    def test_scan_detects_content_patterns(self):
        for i in range(4):
            self.grid.fact(f"Entry about compliance and security rules {i}",
                            tags=[f"project:alpha"])
        result = self.engine.scan(min_occurrences=3)
        self.assertGreaterEqual(result["total"], 1)

    def test_promote_to_playbook(self):
        r = self.grid.write(agent_id="test", type="pattern",
                             content="Test pattern", tags=["level:observation"])
        result = self.engine.promote(r["entry_id"], "playbook")
        self.assertTrue(result["success"])

    def test_promote_invalid(self):
        r = self.grid.write(agent_id="test", type="pattern",
                             content="Test", tags=["level:accelerator"])
        result = self.engine.promote(r["entry_id"], "observation")
        self.assertFalse(result["success"])

    def test_create_playbook(self):
        pb = self.engine.create_playbook(
            "Healthcare Prior Auth Playbook",
            "healthcare",
            ["Assess current process", "Map stakeholders", "Design automation"],
        )
        self.assertIn("id", pb)
        self.assertEqual(pb["domain"], "healthcare")

    def test_create_accelerator(self):
        acc = self.engine.create_accelerator(
            "HIPAA Compliance Scanner",
            "healthcare",
            "Automated scanning of infrastructure for HIPAA compliance gaps",
            "$50K per engagement",
        )
        self.assertIn("id", acc)
        self.assertEqual(acc["domain"], "healthcare")

    def test_moat_report(self):
        self.engine.create_playbook("Test PB", "fintech", ["Step 1"])
        self.engine.create_accelerator("Test Acc", "fintech", "Desc", "$10K")
        report = self.engine.get_moat_report()
        self.assertGreaterEqual(report["playbooks_count"], 1)
        self.assertGreaterEqual(report["accelerators_count"], 1)


class TestEngagementGraph(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.grid = LocalGrid(store_dir=self.tmpdir)
        self.eg = EngagementGraph(self.grid)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_track_activity(self):
        r = self.eg.track("acme-corp", "discovery",
                           "Initial discovery call completed",
                           "Discussed AI automation opportunities", agent="nick")
        self.assertEqual(r["client"], "acme-corp")
        self.assertEqual(r["phase"], "discovery")

    def test_get_engagement(self):
        self.eg.track("acme-corp", "discovery", "Discovery call", "Notes")
        self.eg.track("acme-corp", "assessment", "Architecture review", "Findings")
        eng = self.eg.get_engagement("acme-corp")
        self.assertEqual(eng["client"], "acme-corp")
        self.assertGreaterEqual(eng["total_activities"], 2)
        self.assertIn("discovery", eng["phases_involved"])
        self.assertIn("assessment", eng["phases_involved"])

    def test_get_all_clients(self):
        self.eg.track("client-a", "discovery", "Call", "")
        self.eg.track("client-b", "proposal", "Sent proposal", "")
        clients = self.eg.get_all_clients()
        self.assertGreaterEqual(clients["total"], 2)

    def test_qbr_generation(self):
        self.eg.track("acme-corp", "discovery", "Initial meeting", "Good fit")
        self.eg.track("acme-corp", "assessment", "Deep dive", "Architecture review")
        self.eg.track("acme-corp", "proposal", "Sent SOW", "$150K")

        qbr = self.eg.generate_qbr("acme-corp", "Q2 2026")
        self.assertEqual(qbr["client"], "acme-corp")
        self.assertGreaterEqual(qbr["summary"]["total_activities"], 3)
        self.assertIn("timeline", qbr)

    def test_qbr_with_lessons(self):
        self.eg.track("client-x", "build", "Building integration", "In progress")
        # Add a lesson manually
        self.grid.write(agent_id="test", type="lesson",
                         content="Lesson Learned [worked]\nContent: Good stuff",
                         tags=["lesson", "client:client-x"])
        qbr = self.eg.generate_qbr("client-x")
        self.assertIn("lessons", qbr)

    def test_qbr_format_report(self):
        self.eg.track("acme", "discovery", "Started", "Notes")
        qbr = self.eg.generate_qbr("acme", "Q1 2026")
        report = self.eg.format_qbr_report(qbr)
        self.assertIn("QUARTERLY BUSINESS REVIEW", report)
        self.assertIn("acme", report)
        self.assertIn("Q1 2026", report)

    def test_multiple_activities_same_phase(self):
        for i in range(3):
            self.eg.track("client-z", "discovery", f"Meeting {i}", f"Notes {i}")
        eng = self.eg.get_engagement("client-z")
        self.assertEqual(len(eng["by_phase"].get("discovery", [])), 3)

    def test_engagement_phases_ordered(self):
        phases = ["discovery", "assessment", "proposal", "build", "deploy", "operate", "expand"]
        for p in phases:
            self.eg.track("full-cycle", p, f"Phase: {p}", "")
        eng = self.eg.get_engagement("full-cycle")
        self.assertEqual(len(eng["phases_involved"]), 7)

    def test_qbr_stats(self):
        self.eg.track("stats-client", "discovery", "Call", "")
        self.eg.track("stats-client", "proposal", "SOW sent", "")
        qbr = self.eg.generate_qbr("stats-client", include_stats=True)
        self.assertIn("stats", qbr)


if __name__ == "__main__":
    unittest.main()
