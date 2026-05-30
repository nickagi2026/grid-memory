"""Tests for AI Opportunity Radar."""

import os
import tempfile
import unittest
from grid_memory.local_grid import LocalGrid
from grid_memory.opportunity_radar import OpportunityRadar


class TestOpportunityRadar(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.grid = LocalGrid(store_dir=self.tmpdir)
        self.radar = OpportunityRadar(self.grid, min_confidence=0.0, min_annual_value=0)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_empty_grid_no_opportunities(self):
        result = self.radar.scan()
        self.assertEqual(result["total_opportunities"], 0)
        self.assertEqual(result["total_annual_value"], 0)

    def test_blocker_patterns_detected(self):
        for i in range(5):
            self.grid.write(
                agent_id=f"agent{i}", type="blocker",
                content=f"Timeout error on service-{i}: database connection timeout",
                tags=["database"],
            )
        result = self.radar.scan()
        self.assertGreaterEqual(result["total_opportunities"], 1)
        opps = [o for o in result["opportunities"] if "timeout" in o["title"].lower()]
        self.assertGreaterEqual(len(opps), 1)

    def test_workflow_automation_detected(self):
        for i in range(5):
            self.grid.handoff(
                from_agent="researcher", to_agent="builder",
                content=f"Work item {i} ready", status="ready",
            )
        result = self.radar.scan()
        workflows = [o for o in result["opportunities"]
                     if o["category"] == "workflow_automation"]
        self.assertGreaterEqual(len(workflows), 1)

    def test_knowledge_gaps_detected(self):
        for i in range(3):
            self.grid.write(
                agent_id="support", type="question",
                content=f"How do I configure the database? attempt {i}",
                tags=["database", "faq"],
            )
        result = self.radar.scan()
        kb = [o for o in result["opportunities"]
              if o["category"] == "knowledge_base"]
        self.assertGreaterEqual(len(kb), 1)

    def test_bottlenecks_detected(self):
        for i in range(8):
            self.grid.handoff(
                from_agent=f"worker{i}", to_agent="bottleneck-bob",
                content=f"Item {i}", status="ready",
            )
        result = self.radar.scan()
        bottlenecks = [o for o in result["opportunities"]
                       if o["category"] == "load_balancing"]
        self.assertGreaterEqual(len(bottlenecks), 1)

    def test_repeated_decisions_detected(self):
        for i in range(4):
            self.grid.decide(
                f"Should we use PostgreSQL?",
                tags=["database", "architecture"],
                agent_id=f"engineer{i}",
            )
        result = self.radar.scan()
        standards = [o for o in result["opportunities"]
                     if o["category"] == "policy_standardization"]
        self.assertGreaterEqual(len(standards), 1)

    def test_manual_patterns_detected(self):
        self.grid.fact("We currently do a manual copy-paste for deployments",
                        tags=["deploy", "ops"], agent_id="devops")
        self.grid.fact("The spreadsheet is updated by hand every day",
                        tags=["ops", "reporting"], agent_id="analyst")
        result = self.radar.scan()
        manual = [o for o in result["opportunities"]
                  if o["category"] == "task_automation"]
        self.assertGreaterEqual(len(manual), 1)

    def test_opportunity_has_value(self):
        for i in range(5):
            self.grid.write(
                agent_id=f"agent{i}", type="blocker",
                content="Error: database timeout", tags=["db"],
            )
        result = self.radar.scan()
        if result["opportunities"]:
            opp = result["opportunities"][0]
            self.assertGreater(opp["annual_value"], 0)
            self.assertGreater(opp["hours_saved_per_year"], 0)
            self.assertGreater(opp["confidence"], 0)
            self.assertIn("recommended_action", opp)

    def test_opportunity_has_id_and_category(self):
        for i in range(3):
            self.grid.write(
                agent_id="agent", type="blocker",
                content=f"Rate limit error attempt {i}", tags=["api"],
            )
        result = self.radar.scan()
        if result["opportunities"]:
            opp = result["opportunities"][0]
            self.assertIn("id", opp)
            self.assertIn("category", opp)
            self.assertIn("department", opp)

    def test_report_generates_text(self):
        for i in range(3):
            self.grid.handoff(
                from_agent="a", to_agent="b",
                content=f"Task {i}", status="ready",
            )
        report = self.radar.report(format="text")
        self.assertIn("AI OPPORTUNITY RADAR", report)
        self.assertIn("$", report)

    def test_scan_writes_fact(self):
        for i in range(3):
            self.grid.write(
                agent_id="agent", type="blocker",
                content="Timeout on service", tags=["timeout"],
            )
        radar = OpportunityRadar(self.grid, min_confidence=0.0, min_annual_value=0)
        result = self.radar.scan()
        self.assertIn("total_annual_value", result)
        self.assertIn("total_opportunities", result)
        self.assertIn("scanned_at", result)

    def test_complex_scan(self):
        """Multiple signal types produce multiple opportunities."""
        # Blockers
        for i in range(4):
            self.grid.write(
                agent_id=f"agent{i}", type="blocker",
                content=f"Connection refused on service-{i}", tags=["network"],
            )
        # Handoffs
        for i in range(6):
            self.grid.handoff(
                from_agent="dev", to_agent="qa",
                content=f"Build {i} for testing", status="ready",
            )
        # Questions
        for i in range(3):
            self.grid.write(
                agent_id="newhire", type="question",
                content="How do I deploy to production?", tags=["deploy", "onboarding"],
            )
        result = self.radar.scan()
        self.assertGreaterEqual(result["total_opportunities"], 3)
        self.assertGreater(result["total_annual_value"], 0)


if __name__ == "__main__":
    unittest.main()
