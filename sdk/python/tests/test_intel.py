"""Tests for Stage 3 Enterprise Intelligence features."""

import os
import tempfile
import unittest
from grid_memory.local_grid import LocalGrid
from grid_memory.intel.amnesia import AmnesiaDetector
from grid_memory.intel.decision_dna import DecisionDNA
from grid_memory.intel.radar2 import OpportunityRadar2
from grid_memory.intel.readiness import ReadinessEngine


class TestAmnesiaDetector(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.grid = LocalGrid(store_dir=self.tmpdir)
        self.detector = AmnesiaDetector(self.grid, min_recurrences=2)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_empty_scan(self):
        result = self.detector.scan()
        self.assertEqual(result["total_events"], 0)

    def test_detect_recurring_content(self):
        for i in range(3):
            self.grid.write(agent_id=f"agent{i}", type="blocker",
                             content=f"Connection timeout on service-{i}", tags=["database"])
        result = self.detector.scan()
        self.assertGreaterEqual(result["total_events"], 1)

    def test_detect_cross_project(self):
        self.grid.fact("Config issue", tags=["config", "project:alpha"])
        self.grid.fact("Config issue again", tags=["config", "project:beta"])
        result = self.detector.scan()
        self.assertGreaterEqual(result["total_events"], 1)

    def test_report_generates(self):
        self.grid.write(agent_id="a1", type="blocker", content="Timeout error")
        self.grid.write(agent_id="a2", type="blocker", content="Timeout error again")
        report = self.detector.report()
        self.assertIn("AMNESIA", report)
        self.assertIn("Total wasted", report)

    def test_wasted_hours_tracked(self):
        for i in range(5):
            self.grid.write(agent_id=f"a{i}", type="blocker",
                             content=f"Crash on server-{i}")
        result = self.detector.scan()
        self.assertGreater(result["total_wasted_hours"], 0)


class TestDecisionDNA(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.grid = LocalGrid(store_dir=self.tmpdir)
        self.dna = DecisionDNA(self.grid)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_empty_analyze(self):
        result = self.dna.analyze()
        self.assertEqual(result["total_decisions"], 0)

    def test_analyze_with_decisions(self):
        self.grid.decide("Use PostgreSQL", tags=["database"], agent_id="architect")
        self.grid.decide("Use React", tags=["frontend"], agent_id="architect")
        result = self.dna.analyze()
        self.assertGreaterEqual(result["total_decisions"], 2)

    def test_decision_maker_ranking(self):
        self.grid.decide("Decision 1", tags=["t1"], agent_id="alice")
        self.grid.decide("Decision 2", tags=["t2"], agent_id="bob")
        result = self.dna.analyze()
        makers = result.get("decision_makers", [])
        self.assertGreaterEqual(len(makers), 2)

    def test_track_outcome(self):
        r = self.grid.decide("Test decision", tags=["test"])
        result = self.dna.track_outcome(r["entry_id"], "success", 50000)
        self.assertTrue(result["success"])

    def test_maker_profile(self):
        self.grid.decide("Decision 1", tags=["db"], agent_id="carol")
        profile = self.dna.get_maker_profile("carol")
        self.assertGreaterEqual(profile["total_decisions"], 1)


class TestRadar2(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.grid = LocalGrid(store_dir=self.tmpdir)
        self.radar = OpportunityRadar2(self.grid)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_empty_scan(self):
        result = self.radar.scan()
        self.assertEqual(result["total"], 0)

    def test_detect_errors(self):
        for i in range(3):
            self.grid.write(agent_id=f"agent{i}", type="blocker",
                             content=f"Timeout on service-{i}")
        result = self.radar.scan()
        self.assertGreaterEqual(result["total"], 1)

    def test_confidence_scoring(self):
        for i in range(8):
            self.grid.write(agent_id=f"agent{i}", type="blocker",
                             content=f"Connection refused on server-{i}")
        result = self.radar.scan()
        if result["opportunities"]:
            self.assertGreaterEqual(result["opportunities"][0]["confidence"], 0.3)

    def test_handoff_detection(self):
        for i in range(5):
            self.grid.handoff(from_agent="dev", to_agent="ops",
                               content=f"Deploy {i}", status="ready")
        result = self.radar.scan()
        self.assertGreaterEqual(result["total"], 1)

    def test_radar_version(self):
        result = self.radar.scan()
        self.assertEqual(result["radar_version"], 2.0)


class TestReadinessEngine(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.grid = LocalGrid(store_dir=self.tmpdir)
        self.engine = ReadinessEngine(self.grid)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_empty_assessment(self):
        result = self.engine.assess()
        self.assertIn("overall_readiness", result)
        self.assertIn("dimensions", result)

    def test_assessment_with_data(self):
        self.grid.decide("Use PostgreSQL for database", tags=["database", "architecture"])
        self.grid.decide("Monitor with Prometheus", tags=["monitoring", "ops"])
        self.grid.fact("API endpoints documented", tags=["api", "tech"])
        result = self.engine.assess()
        self.assertGreater(result["overall_readiness"], 20)

    def test_all_dimensions_present(self):
        names = ["data", "process", "governance", "people", "technology"]
        result = self.engine.assess()
        for name in names:
            self.assertIn(name, result["dimensions"])
            self.assertIn("score", result["dimensions"][name])

    def test_roadmap_generated(self):
        self.grid.decide("Use AWS", tags=["cloud"])
        result = self.engine.assess()
        self.assertIn("roadmap", result)

    def test_strengths_and_gaps(self):
        result = self.engine.assess()
        self.assertIn("strengths", result)
        self.assertIn("gaps", result)

    def test_readiness_level(self):
        # High score scenario
        for i in range(10):
            self.grid.decide(f"Decision {i}", tags=["database", "api", "cloud", "monitoring"])
            self.grid.handoff(from_agent="dev", to_agent="ops", content=f"Handoff {i}", status="ready")
        result = self.engine.assess()
        self.assertIn("readiness_level", result)


if __name__ == "__main__":
    unittest.main()
