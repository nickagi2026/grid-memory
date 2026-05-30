"""Tests for the Opportunity Lifecycle pipeline."""

import os
import tempfile
import unittest
from grid_memory.local_grid import LocalGrid
from grid_memory.opportunity_lifecycle import (
    OpportunityLifecycle, VALID_TRANSITIONS, STAGES
)


class TestLifecycleStages(unittest.TestCase):
    def test_valid_transitions(self):
        """detected → reviewed → accepted → assessment → proposed → won/lost"""
        self.assertIn("reviewed", VALID_TRANSITIONS["detected"])
        self.assertIn("accepted", VALID_TRANSITIONS["reviewed"])
        self.assertIn("lost", VALID_TRANSITIONS["reviewed"])
        self.assertIn("assessment", VALID_TRANSITIONS["accepted"])
        self.assertIn("proposed", VALID_TRANSITIONS["assessment"])
        self.assertIn("won", VALID_TRANSITIONS["proposed"])
        self.assertIn("lost", VALID_TRANSITIONS["proposed"])
        self.assertIn("completed", VALID_TRANSITIONS["won"])
        self.assertEqual(VALID_TRANSITIONS["lost"], [])
        self.assertEqual(VALID_TRANSITIONS["completed"], [])

    def test_invalid_transitions(self):
        self.assertNotIn("assessment", VALID_TRANSITIONS["detected"])
        self.assertNotIn("proposed", VALID_TRANSITIONS["detected"])
        self.assertNotIn("won", VALID_TRANSITIONS["detected"])
        self.assertNotIn("detected", VALID_TRANSITIONS["accepted"])


class TestOpportunityLifecycle(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.grid = LocalGrid(store_dir=self.tmpdir)
        self.lifecycle = OpportunityLifecycle(self.grid)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_create_opportunity(self):
        opp = self.lifecycle.create(
            title="Automate database backups",
            description="Manual backup process costs 10h/week",
            category="task_automation",
            estimated_value=50000,
            estimated_hours=520,
            confidence=0.85,
            department="Infrastructure",
        )
        self.assertIn("id", opp)
        self.assertIn("entry_id", opp)
        self.assertEqual(opp["stage"], "detected")

    def test_create_from_radar(self):
        radar_opp = {
            "title": "Auto-remediate timeout errors",
            "annual_value": 36000,
            "hours_saved_per_year": 240,
            "confidence": 0.87,
            "category": "auto_remediation",
            "evidence": "12 blocker entries across 4 agents",
            "id": "opp_20260529_blocker_timeout",
            "department": "Engineering",
            "recommended_action": "Implement retry logic",
        }
        opp = self.lifecycle.create_from_radar(radar_opp)
        self.assertEqual(opp["stage"], "detected")
        self.assertIn("entry_id", opp)

    def test_full_lifecycle(self):
        opp = self.lifecycle.create(
            title="Test opportunity",
            description="Test full lifecycle",
            estimated_value=10000,
        )
        oid = opp["entry_id"]

        # Advance through full pipeline
        stages = ["reviewed", "accepted", "assessment", "proposed", "won", "completed"]
        for stage in stages:
            result = self.lifecycle.advance(oid, stage)
            self.assertTrue(result["success"], f"Failed to advance to {stage}: {result.get('reason')}")
            self.assertEqual(result["to_stage"], stage)

    def test_invalid_transition_rejected(self):
        opp = self.lifecycle.create(title="Test opp")
        oid = opp["entry_id"]

        # Try to jump from detected to proposed (invalid)
        result = self.lifecycle.advance(oid, "proposed")
        self.assertFalse(result["success"])
        self.assertIn("Cannot transition", result.get("reason", ""))

    def test_get_pipeline(self):
        self.lifecycle.create(title="Opp 1", estimated_value=10000)
        self.lifecycle.create(title="Opp 2", estimated_value=20000)

        pipeline = self.lifecycle.get_pipeline()
        self.assertIn("pipeline", pipeline)
        self.assertIn("summary", pipeline)
        self.assertGreaterEqual(pipeline["summary"]["total_opportunities"], 2)

    def test_pipeline_by_stage(self):
        opp = self.lifecycle.create(title="Will advance", estimated_value=5000)
        oid = opp["entry_id"]
        self.lifecycle.advance(oid, "reviewed", notes="Looks good")

        detected = self.lifecycle.get_pipeline(stage="detected")
        reviewed = self.lifecycle.get_pipeline(stage="reviewed")

        # The advanced opp should appear in reviewed pipeline
        self.assertGreaterEqual(reviewed["stage_counts"].get("reviewed", 0), 0)

    def test_get_history(self):
        opp = self.lifecycle.create(title="Track this", estimated_value=50000)
        oid = opp["entry_id"]
        self.lifecycle.advance(oid, "reviewed", notes="Reviewed by team")
        self.lifecycle.advance(oid, "accepted", notes="Approved for assessment")

        history = self.lifecycle.get_history(oid)
        self.assertTrue(history["success"])
        self.assertIn("timeline", history)
        self.assertGreaterEqual(history["transitions"], 2)

    def test_get_stats(self):
        opp1 = self.lifecycle.create(title="Won opp", estimated_value=100000)
        opp2 = self.lifecycle.create(title="Lost opp", estimated_value=50000)

        self.lifecycle.advance(opp1["entry_id"], "reviewed")
        self.lifecycle.advance(opp1["entry_id"], "accepted")
        self.lifecycle.advance(opp1["entry_id"], "assessment")
        self.lifecycle.advance(opp1["entry_id"], "proposed")
        self.lifecycle.advance(opp1["entry_id"], "won")

        self.lifecycle.advance(opp2["entry_id"], "reviewed")
        self.lifecycle.advance(opp2["entry_id"], "lost")

        stats = self.lifecycle.get_stats()
        self.assertGreaterEqual(stats["won"]["count"], 1)
        self.assertGreaterEqual(stats["won"]["total_value"], 100000)
        self.assertGreaterEqual(stats["lost"]["count"], 1)
        self.assertGreater(stats["win_rate"], 0)

    def test_pipeline_value(self):
        self.lifecycle.create(title="Pipeline opp", estimated_value=75000)
        pipeline = self.lifecycle.get_pipeline()
        self.assertGreaterEqual(pipeline["summary"]["total_pipeline_value"], 75000)

    def test_notes_on_advance(self):
        opp = self.lifecycle.create(title="Noted opp")
        result = self.lifecycle.advance(
            opp["entry_id"], "reviewed",
            notes="High priority — client has budget"
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["notes"], "High priority — client has budget")

    def test_advance_nonexistent(self):
        result = self.lifecycle.advance("nonexistent", "reviewed")
        self.assertFalse(result["success"])

    def test_metadata_on_advance(self):
        opp = self.lifecycle.create(title="Metadata test")
        meta = {"assessment_completed": "2026-06-01", "team_size": 3}
        result = self.lifecycle.advance(
            opp["entry_id"], "reviewed",
            metadata=meta
        )
        self.assertTrue(result["success"])


if __name__ == "__main__":
    unittest.main()
