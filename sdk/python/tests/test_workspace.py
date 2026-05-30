"""Tests for client workspace isolation."""

import json
import os
import tempfile
import unittest
from grid_memory.local_grid import LocalGrid
from grid_memory.workspace import WorkspaceManager


class TestWorkspaceManager(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.mgr = WorkspaceManager(base_dir=os.path.join(self.tmpdir, "workspaces"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_create_workspace(self):
        result = self.mgr.create("client-acme-corp", label="Acme Corp")
        self.assertTrue(result["success"])
        self.assertEqual(result["workspace_id"], "client-acme-corp")
        self.assertTrue(os.path.exists(result["path"]))

    def test_create_duplicate_fails(self):
        self.mgr.create("client-dup")
        result = self.mgr.create("client-dup")
        self.assertFalse(result["success"])
        self.assertIn("already exists", result.get("reason", ""))

    def test_list_workspaces(self):
        self.mgr.create("client-alpha", label="Alpha Inc")
        self.mgr.create("client-beta", label="Beta LLC")
        workspaces = self.mgr.list()
        self.assertEqual(len(workspaces), 2)
        ids = [w["id"] for w in workspaces]
        self.assertIn("client-alpha", ids)
        self.assertIn("client-beta", ids)

    def test_get_grid_isolated(self):
        """Two workspaces have independent stores."""
        self.mgr.create("ws-a")
        self.mgr.create("ws-b")

        grid_a = self.mgr.get_grid("ws-a")
        grid_b = self.mgr.get_grid("ws-b")

        grid_a.fact("Secret A data", tags=["confidential"], agent_id="agent-a")
        grid_b.fact("Secret B data", tags=["confidential"], agent_id="agent-b")

        info_a = grid_a.info()
        info_b = grid_b.info()

        self.assertEqual(info_a["total_entries"], 1)
        self.assertEqual(info_b["total_entries"], 1)

        # Query each — should only find their own data
        q_a = grid_a.query(tags=["confidential"])
        self.assertEqual(len(q_a["entries"]), 1)
        self.assertIn("Secret A", q_a["entries"][0]["content"])

        q_b = grid_b.query(tags=["confidential"])
        self.assertEqual(len(q_b["entries"]), 1)
        self.assertIn("Secret B", q_b["entries"][0]["content"])

    def test_no_cross_contamination(self):
        """Data from one workspace NEVER appears in another."""
        self.mgr.create("client-x")
        self.mgr.create("client-y")

        grid_x = self.mgr.get_grid("client-x")
        grid_y = self.mgr.get_grid("client-y")

        grid_x.fact("X: database password rotated", tags=["security", "db"])
        grid_y.fact("Y: API key rotated", tags=["security", "api"])

        # Query X should never see Y's data
        q_x = grid_x.query(tags=["security"])
        for e in q_x["entries"]:
            self.assertNotIn("Y:", e["content"])

        # Query Y should never see X's data
        q_y = grid_y.query(tags=["security"])
        for e in q_y["entries"]:
            self.assertNotIn("X:", e["content"])

    def test_active_workspace(self):
        self.mgr.set_active("client-alpha")
        self.assertEqual(self.mgr.get_active(), "client-alpha")
        self.mgr.set_active(None)
        self.assertIsNone(self.mgr.get_active())

    def test_delete_workspace(self):
        self.mgr.create("client-temp")
        result = self.mgr.delete("client-temp")
        self.assertFalse(result["success"])  # needs confirm
        result = self.mgr.delete("client-temp", confirm=True)
        self.assertTrue(result["success"])
        workspaces = self.mgr.list()
        self.assertEqual(len(workspaces), 0)

    def test_invalid_id_rejected(self):
        result = self.mgr.create("invalid id with spaces")
        self.assertFalse(result["success"])
        result = self.mgr.create("valid-id-123")
        self.assertTrue(result["success"])

    def test_get_stats(self):
        self.mgr.create("client-one")
        self.mgr.create("client-two")
        grid_one = self.mgr.get_grid("client-one")
        grid_one.fact("Entry 1", agent_id="a")
        grid_one.fact("Entry 2", agent_id="a")

        stats = self.mgr.get_stats()
        self.assertEqual(stats["workspace_count"], 2)
        self.assertGreaterEqual(stats["total_entries"], 2)

    def test_sqlite_backend(self):
        result = self.mgr.create("client-sqlite", backend="sqlite")
        self.assertTrue(result["success"])
        self.assertEqual(result["backend"], "sqlite")
        grid = self.mgr.get_grid("client-sqlite")
        grid.fact("SQLite test", tags=["test"], agent_id="test")
        info = grid.info()
        self.assertGreaterEqual(info["total_entries"], 1)

    def test_cached_grid_instances(self):
        """Same workspace returns the same Grid instance."""
        self.mgr.create("client-cache")
        g1 = self.mgr.get_grid("client-cache")
        g2 = self.mgr.get_grid("client-cache")
        self.assertIs(g1, g2)

    def test_get_grid_raises_for_nonexistent(self):
        with self.assertRaises(ValueError):
            self.mgr.get_grid("nonexistent-workspace")

    def test_list_empty(self):
        workspaces = self.mgr.list()
        self.assertEqual(workspaces, [])


if __name__ == "__main__":
    unittest.main()


class TestWorkspaceLeak(unittest.TestCase):
    """Regression tests proving workspace A cannot read workspace B."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.dir_a = os.path.join(self.tmpdir, "ws_a")
        self.dir_b = os.path.join(self.tmpdir, "ws_b")
        self.grid_a = LocalGrid(store_dir=self.dir_a)
        self.grid_b = LocalGrid(store_dir=self.dir_b)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_workspace_a_cannot_see_b(self):
        """Data written to workspace A should not appear in workspace B."""
        self.grid_a.fact("SECRET_A: database password rotated", tags=["security"], agent_id="admin")
        self.grid_b.fact("SECRET_B: API key rotated", tags=["security"], agent_id="admin")

        q_a = self.grid_a.query(tags=["security"])
        for e in q_a["entries"]:
            self.assertNotIn("SECRET_B", e["content"], "Workspace A leaked data from B")

        q_b = self.grid_b.query(tags=["security"])
        for e in q_b["entries"]:
            self.assertNotIn("SECRET_A", e["content"], "Workspace B leaked data from A")

    def test_workspace_a_isolated_after_write(self):
        """Multiple writes to A should not affect B's counts."""
        for i in range(10):
            self.grid_a.fact(f"Entry {i}", tags=["bulk"], agent_id="loader")
        info_a = self.grid_a.info()
        info_b = self.grid_b.info()
        self.assertGreaterEqual(info_a["total_entries"], 10)
        self.assertEqual(info_b["total_entries"], 0)

    def test_stores_separate_directories(self):
        """Each workspace store lives in a physically separate directory."""
        self.grid_a.fact("A data", tags=["test"])
        self.grid_b.fact("B data", tags=["test"])

        # Read store files directly
        import json
        with open(os.path.join(self.dir_a, "store.json")) as f:
            store_a = json.load(f)
        with open(os.path.join(self.dir_b, "store.json")) as f:
            store_b = json.load(f)

        contents_a = [e["content"] for e in store_a["entries"]]
        contents_b = [e["content"] for e in store_b["entries"]]
        self.assertIn("A data", contents_a)
        self.assertNotIn("B data", contents_a)
        self.assertIn("B data", contents_b)
        self.assertNotIn("A data", contents_b)

    def test_workspace_id_stored(self):
        """Entries should capture workspace_id when provided."""
        r = self.grid_a.write(agent_id="test", type="fact", content="test",
                               workspace_id="ws-a")
        # Verify via store file
        import json
        with open(os.path.join(self.dir_a, "store.json")) as f:
            store = json.load(f)
        entry = next(e for e in store["entries"] if e["id"] == r["entry_id"])
        self.assertEqual(entry.get("workspace_id"), "ws-a")

    def test_workspace_sqlite_isolation(self):
        """Workspace isolation works with SQLite backend."""
        from grid_memory.sqlite_backend import SQLiteBackend
        db_a = os.path.join(self.tmpdir, "test_a.db")
        db_b = os.path.join(self.tmpdir, "test_b.db")
        backend_a = SQLiteBackend(db_a)
        backend_b = SQLiteBackend(db_b)
        grid_a = LocalGrid(backend=backend_a)
        grid_b = LocalGrid(backend=backend_b)

        grid_a.fact("Secret for A", tags=["confidential"], agent_id="admin")
        grid_b.fact("Secret for B", tags=["confidential"], agent_id="admin")

        q_a = grid_a.query(tags=["confidential"])
        self.assertEqual(len(q_a["entries"]), 1)
        self.assertIn("Secret for A", q_a["entries"][0]["content"])

        q_b = grid_b.query(tags=["confidential"])
        self.assertEqual(len(q_b["entries"]), 1)
        self.assertIn("Secret for B", q_b["entries"][0]["content"])

        backend_a.close()
        backend_b.close()


class TestWorkspaceIsolationRegression(unittest.TestCase):
    """Prove workspace A cannot access workspace B's data through any path."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.dir_a = os.path.join(self.tmpdir, "ws_a")
        self.dir_b = os.path.join(self.tmpdir, "ws_b")
        self.grid_a = LocalGrid(store_dir=self.dir_a)
        self.grid_b = LocalGrid(store_dir=self.dir_b)
        self.grid_a.fact("SECRET_A", tags=["confidential"], agent_id="admin", workspace_id="ws-a")
        self.grid_b.fact("SECRET_B", tags=["confidential"], agent_id="admin", workspace_id="ws-b")

    def tearDown(self):
        import shutil; shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_a_cannot_query_b(self):
        q = self.grid_a.query(tags=["confidential"])
        for e in q["entries"]:
            self.assertNotIn("SECRET_B", e["content"])

    def test_a_cannot_inject_b(self):
        block = self.grid_a.inject()
        self.assertNotIn("SECRET_B", block.get("block", ""))

    def test_a_cannot_export_b(self):
        exported = self.grid_a.export_json()
        self.assertNotIn("SECRET_B", exported)

    def test_b_cannot_see_a(self):
        q = self.grid_b.query(tags=["confidential"])
        for e in q["entries"]:
            self.assertNotIn("SECRET_A", e["content"])

    def test_separate_stores_dont_share_entries(self):
        info_a = self.grid_a.info()
        info_b = self.grid_b.info()
        self.assertEqual(info_a["total_entries"], 1)
        self.assertEqual(info_b["total_entries"], 1)

    def test_workspace_id_stored_in_backend(self):
        import json
        with open(os.path.join(self.dir_a, "store.json")) as f:
            store = json.load(f)
        entry = store["entries"][0]
        self.assertEqual(entry.get("workspace_id"), "ws-a")
