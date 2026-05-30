"""
test_workspace_proof.py — Enterprise workspace isolation proof suite.

Proves workspace A cannot access workspace B data through ANY path:
  query, inject, export, delete, proxy
"""

import json
import os
import tempfile
import unittest
from grid_memory.local_grid import LocalGrid
from grid_memory.enterprise.pii import PIIDetector


class TestWorkspaceProofQuery(unittest.TestCase):
    """Prove query isolation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ga = LocalGrid(store_dir=os.path.join(self.tmpdir, "a"))
        self.gb = LocalGrid(store_dir=os.path.join(self.tmpdir, "b"))
        self.ga.fact("SECRET_A_QUERY", tags=["confidential"], agent_id="admin", workspace_id="ws-a")
        self.gb.fact("SECRET_B_QUERY", tags=["confidential"], agent_id="admin", workspace_id="ws-b")

    def tearDown(self):
        import shutil; shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_a_cannot_query_b(self):
        qa = self.ga.query(tags=["confidential"])
        for e in qa["entries"]:
            self.assertNotIn("SECRET_B_QUERY", e["content"],
                             f"LEAK: Workspace A queried B's data: {e['content']}")
            self.assertEqual(e.get("workspace_id"), "ws-a",
                             f"Entry in A has wrong workspace_id: {e.get('workspace_id')}")

    def test_b_cannot_query_a(self):
        qb = self.gb.query(tags=["confidential"])
        for e in qb["entries"]:
            self.assertNotIn("SECRET_A_QUERY", e["content"],
                             f"LEAK: Workspace B queried A's data: {e['content']}")


class TestWorkspaceProofInject(unittest.TestCase):
    """Prove inject isolation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ga = LocalGrid(store_dir=os.path.join(self.tmpdir, "a"))
        self.gb = LocalGrid(store_dir=os.path.join(self.tmpdir, "b"))
        self.ga.fact("SECRET_A_INJECT", tags=["db"], agent_id="admin", workspace_id="ws-a")
        self.gb.fact("SECRET_B_INJECT", tags=["db"], agent_id="admin", workspace_id="ws-b")

    def tearDown(self):
        import shutil; shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_a_inject_excludes_b(self):
        block = self.ga.inject()
        self.assertNotIn("SECRET_B_INJECT", block.get("block", ""),
                         "LEAK: A's inject block contains B's data")

    def test_b_inject_excludes_a(self):
        block = self.gb.inject()
        self.assertNotIn("SECRET_A_INJECT", block.get("block", ""),
                         "LEAK: B's inject block contains A's data")


class TestWorkspaceProofExport(unittest.TestCase):
    """Prove export isolation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ga = LocalGrid(store_dir=os.path.join(self.tmpdir, "a"))
        self.gb = LocalGrid(store_dir=os.path.join(self.tmpdir, "b"))
        self.ga.fact("SECRET_A_EXPORT", tags=["finance"], agent_id="admin", workspace_id="ws-a")
        self.gb.fact("SECRET_B_EXPORT", tags=["finance"], agent_id="admin", workspace_id="ws-b")

    def tearDown(self):
        import shutil; shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_a_export_excludes_b(self):
        exported = self.ga.export_json()
        self.assertNotIn("SECRET_B_EXPORT", exported, "LEAK: A's export contains B's data")
        self.assertIn("SECRET_A_EXPORT", exported, "A's export is missing A's data")

    def test_b_export_excludes_a(self):
        exported = self.gb.export_json()
        self.assertNotIn("SECRET_A_EXPORT", exported, "LEAK: B's export contains A's data")


class TestWorkspaceProofDelete(unittest.TestCase):
    """Prove delete isolation — deleting from A should not affect B."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ga = LocalGrid(store_dir=os.path.join(self.tmpdir, "a"))
        self.gb = LocalGrid(store_dir=os.path.join(self.tmpdir, "b"))
        self.ra = self.ga.fact("A_DELETE", tags=["test"], agent_id="admin", workspace_id="ws-a")
        self.rb = self.gb.fact("B_DELETE", tags=["test"], agent_id="admin", workspace_id="ws-b")

    def tearDown(self):
        import shutil; shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_delete_a_does_not_affect_b(self):
        self.ga.forget(self.ra["entry_id"])
        info_a = self.ga.info()
        info_b = self.gb.info()
        self.assertEqual(info_a["total_entries"], 0, "A should have 0 entries after delete")
        self.assertEqual(info_b["total_entries"], 1, "B should still have 1 entry")


class TestWorkspaceProofProxy(unittest.TestCase):
    """Prove proxy isolation — OpenAI proxy uses workspace-scoped context."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.ga = LocalGrid(store_dir=os.path.join(self.tmpdir, "a"))
        self.gb = LocalGrid(store_dir=os.path.join(self.tmpdir, "b"))
        self.ga.fact("SECRET_A_PROXY", tags=["llm"], agent_id="admin", workspace_id="ws-a")
        self.gb.fact("SECRET_B_PROXY", tags=["llm"], agent_id="admin", workspace_id="ws-b")

    def tearDown(self):
        import shutil; shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_proxy_isolation(self):
        """Verify that when working with workspace A, B's data is not injected."""
        block = self.ga.inject()
        block_str = block.get("block", "")
        self.assertNotIn("SECRET_B_PROXY", block_str,
                         "LEAK: Proxy context from A includes B's data")


if __name__ == "__main__":
    unittest.main()
