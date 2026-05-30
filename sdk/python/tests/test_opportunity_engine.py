"""Tests for end-to-end opportunity engine."""

import os
import tempfile
import unittest
from grid_memory.local_grid import LocalGrid
from grid_memory.opportunity_engine import OpportunityEngine


class TestOpportunityEngine(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.grid = LocalGrid(store_dir=self.tmpdir)
        self.engine = OpportunityEngine(self.grid)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_link_proposal(self):
        opp = self.engine.lifecycle.create(title="Test opp")
        r = self.engine.link_proposal(opp["entry_id"], "prop_123")
        self.assertTrue(r["linked"])
        self.assertEqual(r["proposal_id"], "prop_123")

    def test_link_project(self):
        opp = self.engine.lifecycle.create(title="Test opp")
        r = self.engine.link_project(opp["entry_id"], "proj_456")
        self.assertTrue(r["linked"])

    def test_track_win(self):
        opp = self.engine.lifecycle.create(title="Won opp", estimated_value=50000)
        r = self.engine.track_win_loss(opp["entry_id"], "won",
                                        reason="Best technical solution", revenue=50000)
        self.assertEqual(r["result"], "won")
        self.assertEqual(r["revenue"], 50000)

    def test_track_loss(self):
        opp = self.engine.lifecycle.create(title="Lost opp")
        r = self.engine.track_win_loss(opp["entry_id"], "lost",
                                        reason="Budget constraints")
        self.assertEqual(r["result"], "lost")

    def test_track_roi(self):
        opp = self.engine.lifecycle.create(title="ROI opp", estimated_value=100000)
        oid = opp["entry_id"]
        self.engine.track_win_loss(oid, "won", "Good fit", 100000)
        r = self.engine.track_roi(oid, actual_value=85000, actual_hours=500)
        self.assertEqual(r["accuracy"], 85.0)

    def test_get_opportunity_graph(self):
        opp = self.engine.lifecycle.create(title="Graph test")
        oid = opp["entry_id"]
        self.engine.link_proposal(oid, "prop_1")
        self.engine.link_project(oid, "proj_2")
        self.engine.track_win_loss(oid, "won", "Great")
        graph = self.engine.get_opportunity_graph(oid)
        self.assertGreaterEqual(len(graph["links"]), 2)
        self.assertGreaterEqual(len(graph["outcomes"]), 1)

    def test_analytics(self):
        o1 = self.engine.lifecycle.create(title="Won $50K", estimated_value=50000)
        o2 = self.engine.lifecycle.create(title="Won $100K", estimated_value=100000)
        o3 = self.engine.lifecycle.create(title="Lost", estimated_value=30000)
        self.engine.track_win_loss(o1["entry_id"], "won", "Good", 50000)
        self.engine.track_win_loss(o2["entry_id"], "won", "Best", 100000)
        self.engine.track_win_loss(o3["entry_id"], "lost", "Price")
        analytics = self.engine.get_opportunity_analytics()
        self.assertGreaterEqual(analytics["wins"], 2)
        self.assertGreaterEqual(analytics["total_revenue"], 150000)

    def test_ranking(self):
        self.engine.lifecycle.create(title="Small", estimated_value=10000)
        self.engine.lifecycle.create(title="Big", estimated_value=500000)
        self.engine.lifecycle.create(title="Medium", estimated_value=75000)
        ranked = self.engine.rank_opportunities()
        self.assertGreaterEqual(len(ranked["ranked"]), 3)
        self.assertEqual(ranked["ranked"][0]["value"], 500000)

    def test_summary(self):
        self.engine.lifecycle.create(title="Test", estimated_value=50000)
        summary = self.engine.summary()
        self.assertIn("analytics", summary)
        self.assertIn("stage_counts", summary)

    def test_roi_accuracy_multiple(self):
        for i in range(3):
            opp = self.engine.lifecycle.create(title=f"Opp {i}", estimated_value=100000)
            oid = opp["entry_id"]
            self.engine.track_win_loss(oid, "won", "Good", 100000)
            self.engine.track_roi(oid, actual_value=80000)
        analytics = self.engine.get_opportunity_analytics()
        self.assertGreater(analytics["avg_accuracy"], 0)

    def test_rank_by_priority(self):
        self.engine.lifecycle.create(title="Low priority", estimated_value=5000)
        self.engine.lifecycle.create(title="High priority", estimated_value=500000,
                                     tags=["urgent"])
        ranked = self.engine.rank_opportunities()
        self.assertEqual(ranked["ranked"][0]["value"], 500000)


if __name__ == "__main__":
    unittest.main()
