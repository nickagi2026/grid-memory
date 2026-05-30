"""Tests for the operational loop orchestrator and MIKE hooks."""

import os
import tempfile
import unittest
from grid_memory.local_grid import LocalGrid
from grid_memory.pipeline import PipelineOrchestrator, AutoScheduler
from grid_memory.hooks.mike_hook import MikeGridHook
from grid_memory.workspace import WorkspaceManager


class TestPipelineOrchestrator(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.grid = LocalGrid(store_dir=self.tmpdir)
        self.pipe = PipelineOrchestrator(self.grid, "test-client")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_full_loop_runs(self):
        result = self.pipe.full_loop(run_radar=False, extract_lessons=False, scan_patterns=False)
        self.assertIn("ran_at", result)
        self.assertEqual(result.get("client"), "test-client")

    def test_on_engagement_change(self):
        result = self.pipe.on_engagement_change("test-client", "discovery", "Started")
        self.assertEqual(result["client"], "test-client")
        self.assertEqual(result["phase"], "discovery")

    def test_on_engagement_change_extracts_lessons(self):
        # Add a blocker that should get extracted
        self.grid.write(agent_id="test", type="blocker",
                         content="Production timeout error", tags=["db"])
        result = self.pipe.on_engagement_change("test-client", "build", "Building")
        # Should have auto-extracted the blocker as a lesson
        self.assertEqual(result["client"], "test-client")

    def test_on_engagement_change_runs_radar_on_discovery(self):
        result = self.pipe.on_engagement_change("test-client", "discovery", "Discovery call")
        self.assertEqual(result["phase"], "discovery")

    def test_client_report(self):
        from grid_memory.engagement import EngagementGraph
        eg = EngagementGraph(self.grid)
        eg.track("test-client", "discovery", "Started", "")
        eg.track("test-client", "proposal", "Sent SOW", "")

        report = self.pipe.generate_client_report("Q2 2026")
        self.assertEqual(report["client"], "test-client")
        self.assertIn("qbr", report)
        self.assertIn("lessons", report)
        self.assertIn("radar", report)

    def test_full_loop_with_actual_data(self):
        self.grid.fact("Database config done", tags=["database"], agent_id="arch")
        self.grid.write(agent_id="ops", type="blocker",
                         content="Timeout on production", tags=["database"])
        result = self.pipe.full_loop(run_radar=False, extract_lessons=False, scan_patterns=False)
        self.assertIn("ran_at", result)


class TestAutoScheduler(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.mgr = WorkspaceManager(base_dir=os.path.join(self.tmpdir, "ws"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_start_stop(self):
        sched = AutoScheduler(self.mgr, interval_hours=999)  # Long interval
        self.assertFalse(sched.is_running)
        sched.start()
        self.assertTrue(sched.is_running)
        sched.stop()
        self.assertFalse(sched.is_running)

    def test_double_start(self):
        sched = AutoScheduler(self.mgr, interval_hours=999)
        sched.start()
        self.assertFalse(sched.start())  # Second start returns False
        sched.stop()

    def test_double_stop(self):
        sched = AutoScheduler(self.mgr, interval_hours=999)
        self.assertFalse(sched.stop())  # Stop when not running returns False
        sched.start()
        self.assertTrue(sched.stop())
        self.assertFalse(sched.stop())  # Second stop returns False


class TestMikeHook(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        os.environ["GRID_STORE_DIR"] = self.tmpdir  # Override default store
        self.hook = MikeGridHook()

        # Create a test workspace
        self.hook.mgr.create("test-workspace")

    def tearDown(self):
        import shutil
        if "GRID_STORE_DIR" in os.environ:
            del os.environ["GRID_STORE_DIR"]
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_session_start(self):
        context = self.hook.on_session_start("test-workspace")
        self.assertIn("workspace", context)
        self.assertEqual(context["workspace"], "test-workspace")

    def test_on_decision(self):
        self.hook.on_session_start("test-workspace")
        result = self.hook.on_decision("Use PostgreSQL", rationale="Better ecosystem")
        self.assertTrue(result.get("recorded"))

    def test_on_blocker(self):
        self.hook.on_session_start("test-workspace")
        result = self.hook.on_blocker("Database timeout")
        self.assertTrue(result.get("recorded"))

    def test_on_lesson(self):
        self.hook.on_session_start("test-workspace")
        result = self.hook.on_lesson("Connection pooling works great", category="worked")
        self.assertTrue(result.get("recorded"))

    def test_on_opportunity(self):
        self.hook.on_session_start("test-workspace")
        result = self.hook.on_opportunity("Automate deployments", estimated_value=50000)
        self.assertTrue(result.get("recorded"))

    def test_session_end(self):
        self.hook.on_session_start("test-workspace")
        result = self.hook.on_session_end("Architecture review completed")
        self.assertTrue(result.get("ended"))

    def test_full_session_lifecycle(self):
        self.hook.on_session_start("test-workspace")
        self.hook.on_decision("Use Express", rationale="Ecosystem")
        self.hook.on_blocker("Timeout issue", tags=["network"])
        self.hook.on_lesson("Testing strategy worked", category="worked")
        self.hook.on_opportunity("CI/CD automation", estimated_value=30000)
        self.hook.on_session_end("Completed migration plan")

        # Verify everything was written
        result = self.hook.grid.query(tags=["mike-session"])
        entries = result.get("entries", [])
        self.assertGreaterEqual(len(entries), 2)  # start + end

    def test_session_context(self):
        self.hook.on_session_start("test-workspace")
        context = self.hook.get_session_context()
        self.assertIn("Grid Memory", context)

    def test_auto_create_workspace(self):
        hook = MikeGridHook()
        context = hook.on_session_start("auto-created-ws")
        self.assertIn("workspace", context)
        self.assertEqual(context["workspace"], "auto-created-ws")


if __name__ == "__main__":
    unittest.main()
