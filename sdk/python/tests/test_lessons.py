"""Tests for the Lessons Learned Engine."""

import os
import tempfile
import unittest
from grid_memory.local_grid import LocalGrid
from grid_memory.lessons import LessonsEngine, CATEGORIES, SEVERITIES


class TestLessonsEngine(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.grid = LocalGrid(store_dir=self.tmpdir)
        self.engine = LessonsEngine(self.grid)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_add_lesson(self):
        lesson = self.engine.add(
            "Using PostgreSQL with connection pooling reduced latency by 60%",
            category="worked",
            project="mercury",
            client="acme-corp",
        )
        self.assertIn("id", lesson)
        self.assertEqual(lesson["category"], "worked")
        self.assertEqual(lesson["project"], "mercury")

    def test_add_all_categories(self):
        for cat in CATEGORIES:
            l = self.engine.add(f"Test {cat}", category=cat)
            self.assertEqual(l["category"], cat)

    def test_add_all_severities(self):
        for sev in SEVERITIES:
            l = self.engine.add(f"Test {sev}", severity=sev)
            self.assertEqual(l["severity"], sev)

    def test_list_lessons(self):
        self.engine.add("Lesson one", category="worked")
        self.engine.add("Lesson two", category="failed")
        self.engine.add("Lesson three", category="surprised")

        result = self.engine.list()
        self.assertGreaterEqual(result["total"], 3)

    def test_list_by_category(self):
        self.engine.add("Worked great", category="worked")
        self.engine.add("Failed badly", category="failed")

        worked = self.engine.list(category="worked")
        self.assertGreaterEqual(worked["total"], 1)
        self.assertEqual(worked["by_category"].get("worked", 0), 1)

    def test_list_by_project(self):
        self.engine.add("Mercury lesson", category="worked", project="mercury")
        self.engine.add("Venus lesson", category="failed", project="venus")

        mercury = self.engine.list(project="mercury")
        self.assertGreaterEqual(mercury["total"], 1)

    def test_list_by_client(self):
        self.engine.add("Acme insight", category="worked", client="acme-corp")
        result = self.engine.list(client="acme-corp")
        self.assertGreaterEqual(result["total"], 1)

    def test_summary(self):
        self.engine.add("Insight 1", category="worked", severity="insight")
        self.engine.add("Insight 2", category="worked", severity="insight")
        self.engine.add("Warning 1", category="failed", severity="warning")

        summary = self.engine.summary()
        self.assertGreaterEqual(summary["total"], 3)
        self.assertIn("by_category", summary)

    def test_summary_empty(self):
        summary = self.engine.summary()
        self.assertEqual(summary["total"], 0)

    def test_auto_extract_from_blockers(self):
        self.grid.write(agent_id="ops", type="blocker",
                         content="Database connection timeout in production",
                         tags=["database"])
        result = self.engine.auto_extract()
        self.assertGreaterEqual(result["total"], 1)
        self.assertGreaterEqual(len(result["failed"]), 1)

    def test_auto_extract_from_decisions(self):
        self.grid.decide("Use PostgreSQL with connection pooling",
                          rationale="Better performance at scale",
                          agent_id="arch")
        result = self.engine.auto_extract()
        self.assertGreaterEqual(len(result["worked"]), 1)

    def test_auto_extract_from_questions(self):
        self.grid.write(agent_id="dev", type="question",
                         content="How do we configure the connection pool?",
                         tags=["database"])
        result = self.engine.auto_extract()
        self.assertGreaterEqual(len(result["surprised"]), 1)

    def test_auto_extract_from_handoffs(self):
        self.grid.handoff(from_agent="dev", to_agent="qa",
                           content="Build ready for testing", status="ready")
        result = self.engine.auto_extract()
        self.assertGreaterEqual(len(result["reusable"]), 1)

    def test_cross_project_report(self):
        self.engine.add("Lesson A", category="worked", project="project-alpha")
        self.engine.add("Lesson B", category="failed", project="project-beta")
        self.engine.add("Lesson C", category="worked", project="project-alpha")

        report = self.engine.generate_cross_project_report()
        self.assertGreaterEqual(report["total_lessons"], 3)
        self.assertGreaterEqual(report["projects_involved"], 2)

    def test_cross_project_report_empty(self):
        report = self.engine.generate_cross_project_report()
        self.assertEqual(report["total"], 0)

    def test_invalid_category_defaults_to_worked(self):
        l = self.engine.add("Test", category="invalid_category")
        self.assertEqual(l["category"], "worked")

    def test_invalid_severity_defaults_to_insight(self):
        l = self.engine.add("Test", severity="invalid")
        self.assertEqual(l["severity"], "insight")

    def test_lesson_has_structured_content(self):
        l = self.engine.add("My insight", category="worked", project="proj-x", client="client-y")
        # Verify the raw Grid entry has structured content
        if hasattr(self.grid, '_load_store'):
            self.grid._load_store()
            for e in self.grid._store["entries"]:
                if e["id"] == l["id"]:
                    content = e["content"]
                    self.assertIn("Lesson Learned", content)
                    self.assertIn("Content: My insight", content)
                    break

    def test_summary_with_top_insights(self):
        self.engine.add("Critical: database outage", severity="critical")
        self.engine.add("Warning: slow queries", severity="warning")
        self.engine.add("Insight: connection pooling", severity="insight")

        summary = self.engine.summary()
        self.assertGreaterEqual(len(summary["top_critical"]), 1)
        self.assertGreaterEqual(len(summary["top_warnings"]), 1)
        self.assertGreaterEqual(len(summary["top_insights"]), 1)


if __name__ == "__main__":
    unittest.main()
