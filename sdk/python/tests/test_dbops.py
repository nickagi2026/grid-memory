"""Tests for database operations: backup, archive, optimization."""

import json
import os
import tempfile
import unittest
from grid_memory.local_grid import LocalGrid
from grid_memory.enterprise.dbops import DatabaseOps


class TestDatabaseOps(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.grid = LocalGrid(store_dir=os.path.join(self.tmpdir, "store"))
        self.backup_dir = os.path.join(self.tmpdir, "backups")
        self.archive_dir = os.path.join(self.tmpdir, "archives")
        self.dbops = DatabaseOps(self.grid, self.backup_dir, self.archive_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_backup_creates_files(self):
        self.grid.fact("Backup test", tags=["test"], agent_id="test")
        result = self.dbops.backup("test-backup")
        self.assertIn("backup_name", result)
        self.assertIn("path", result)
        self.assertTrue(os.path.exists(result["path"]))

    def test_backup_contains_manifest(self):
        self.grid.fact("Test data", tags=["test"])
        result = self.dbops.backup("test")
        manifest_path = os.path.join(result["path"], "manifest.json")
        self.assertTrue(os.path.exists(manifest_path))

    def test_list_backups(self):
        self.grid.fact("Test", tags=["test"])
        self.dbops.backup("backup-1")
        self.dbops.backup("backup-2")
        backups = self.dbops.list_backups()
        self.assertGreaterEqual(len(backups), 2)

    def test_restore_dry_run(self):
        self.grid.fact("Data to backup", tags=["test"])
        result = self.dbops.backup("save-me")
        restore = self.dbops.restore(result["backup_name"], dry_run=True)
        self.assertTrue(restore["dry_run"])

    def test_archive_old_entries(self):
        self.grid.fact("Old data", tags=["test"])
        result = self.dbops.archive(older_than_days=0)  # archive everything
        self.assertGreaterEqual(result["archived"], 1)

    def test_list_archives(self):
        self.grid.fact("Test", tags=["test"])
        self.dbops.archive(older_than_days=0)
        archives = self.dbops.list_archives()
        self.assertGreaterEqual(len(archives), 1)

    def test_analyze_queries(self):
        self.grid.fact("Untagged entry")  # no tags
        result = self.dbops.analyze_queries()
        self.assertIn("recommendations", result)
        self.assertIn("recommendation_count", result)

    def test_pool_status(self):
        self.grid.fact("Test data", tags=["test"])
        status = self.dbops.pool_status()
        self.assertIn("backend_type", status)
        self.assertIn("total_entries", status)
        self.assertIn("status", status)

    def test_index_info(self):
        self.grid.fact("Test", tags=["test"])
        info = self.dbops.index_info()
        self.assertIn("backend", info)
        self.assertIn("indexes_present", info)
        self.assertIn("recommended_indexes", info)

    def test_backup_then_restore(self):
        self.grid.fact("Critical data", tags=["critical"], agent_id="arch")
        result = self.dbops.backup("critical-backup")
        restore = self.dbops.restore(result["backup_name"])
        self.assertTrue(restore["success"])

    def test_multiple_entries_in_backup(self):
        for i in range(5):
            self.grid.fact(f"Entry {i}", tags=["bulk"], agent_id="loader")
        result = self.dbops.backup("bulk")
        manifest = os.path.join(result["path"], "manifest.json")
        import json
        with open(manifest) as f:
            m = json.load(f)
        self.assertGreaterEqual(m["entry_count"], 5)


if __name__ == "__main__":
    unittest.main()


class TestBackupFidelity(unittest.TestCase):
    """Prove export → import → export produces identical data."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.grid = LocalGrid(store_dir=os.path.join(self.tmpdir, "store"))

    def tearDown(self):
        import shutil; shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_test_data(self):
        """Write a dataset with known IDs, timestamps, relationships."""
        r1 = self.grid.write(agent_id="arch", type="decision", content="Use PostgreSQL",
                             tags=["database"], workspace_id="ws-a", memory_tier="project",
                             force_id="grid_20260529_importtest_001",
                             force_created_at="2026-05-29T10:00:00.000000Z",
                             force_expires_at="2026-06-29T10:00:00.000000Z")
        r2 = self.grid.write(agent_id="ops", type="handoff", content="Handoff to builder",
                             tags=["handoff"], workspace_id="ws-a",
                             parent_entry=r1["entry_id"],
                             force_id="grid_20260529_importtest_002",
                             force_created_at="2026-05-29T11:00:00.000000Z",
                             force_expires_at="2026-06-29T11:00:00.000000Z")
        return r1, r2

    def test_export_import_preserves_ids(self):
        r1, r2 = self._write_test_data()
        exported = self.grid.export_json()

        # Import into a fresh grid
        d2 = tempfile.mkdtemp()
        grid2 = LocalGrid(store_dir=os.path.join(d2, "store"))
        result = grid2.import_json(exported)
        self.assertEqual(result["imported"], 2, f"Should import 2 entries, got {result}")

        # Export again and compare IDs
        re_exported = json.loads(grid2.export_json())
        orig = json.loads(exported)

        orig_ids = sorted(e["id"] for e in orig["entries"])
        re_ids = sorted(e["id"] for e in re_exported["entries"])
        self.assertEqual(orig_ids, re_ids, "IDs differ after import")

        import shutil; shutil.rmtree(d2, ignore_errors=True)

    def test_export_import_preserves_timestamps(self):
        r1, r2 = self._write_test_data()
        exported = self.grid.export_json()

        d2 = tempfile.mkdtemp()
        grid2 = LocalGrid(store_dir=os.path.join(d2, "store"))
        grid2.import_json(exported)

        re_exported = json.loads(grid2.export_json())
        orig = json.loads(exported)

        for orig_e in orig["entries"]:
            match = next((e for e in re_exported["entries"] if e["id"] == orig_e["id"]), None)
            self.assertIsNotNone(match, f"Entry {orig_e['id']} not found after import")
            self.assertEqual(orig_e["created_at"], match["created_at"],
                             f"created_at differs for {orig_e['id']}")
            self.assertEqual(orig_e["expires_at"], match["expires_at"],
                             f"expires_at differs for {orig_e['id']}")

        import shutil; shutil.rmtree(d2, ignore_errors=True)

    def test_export_import_preserves_relationships(self):
        r1, r2 = self._write_test_data()
        exported = self.grid.export_json()

        d2 = tempfile.mkdtemp()
        grid2 = LocalGrid(store_dir=os.path.join(d2, "store"))
        grid2.import_json(exported)

        re_exported = json.loads(grid2.export_json())
        orig = json.loads(exported)

        for orig_e in orig["entries"]:
            match = next((e for e in re_exported["entries"] if e["id"] == orig_e["id"]), None)
            self.assertIsNotNone(match)
            self.assertEqual(orig_e.get("parent_entry"), match.get("parent_entry"),
                             f"parent_entry differs for {orig_e['id']}")

        import shutil; shutil.rmtree(d2, ignore_errors=True)

    def test_export_import_preserves_metadata(self):
        r1, r2 = self._write_test_data()
        exported = self.grid.export_json()

        d2 = tempfile.mkdtemp()
        grid2 = LocalGrid(store_dir=os.path.join(d2, "store"))
        grid2.import_json(exported)

        re_exported = json.loads(grid2.export_json())
        orig = json.loads(exported)

        for orig_e in orig["entries"]:
            match = next((e for e in re_exported["entries"] if e["id"] == orig_e["id"]), None)
            self.assertIsNotNone(match)
            self.assertEqual(orig_e.get("workspace_id"), match.get("workspace_id"),
                             f"workspace_id differs for {orig_e['id']}")
            self.assertEqual(orig_e.get("memory_tier"), match.get("memory_tier"),
                             f"memory_tier differs for {orig_e['id']}")

        import shutil; shutil.rmtree(d2, ignore_errors=True)

    def test_export_import_roundtrip_identical(self):
        """Full round-trip: export → import → export → same dataset."""
        self._write_test_data()
        exported = json.loads(self.grid.export_json())

        d2 = tempfile.mkdtemp()
        grid2 = LocalGrid(store_dir=os.path.join(d2, "store"))
        grid2.import_json(json.dumps(exported))

        re_exported = json.loads(grid2.export_json())

        self.assertEqual(len(exported["entries"]), len(re_exported["entries"]),
                         "Entry count differs after round-trip")

        # Sort by ID and compare
        orig_sorted = sorted(exported["entries"], key=lambda e: e["id"])
        re_sorted = sorted(re_exported["entries"], key=lambda e: e["id"])

        for o, r in zip(orig_sorted, re_sorted):
            self.assertEqual(o["id"], r["id"])
            self.assertEqual(o["agent_id"], r["agent_id"])
            self.assertEqual(o["type"], r["type"])
            self.assertEqual(o["content"], r["content"])
            self.assertEqual(o.get("parent_entry"), r.get("parent_entry"))
            self.assertEqual(o.get("workspace_id"), r.get("workspace_id"))
            self.assertEqual(o.get("memory_tier"), r.get("memory_tier"))

        import shutil; shutil.rmtree(d2, ignore_errors=True)

    def test_export_import_with_node_ids(self):
        """Test that force_id is accepted by the Node store's write method."""
        # This test verifies the Python-side import preserves IDs for Node-side consumption
        r = self.grid.write(agent_id="test", type="fact", content="ID preservation test",
                            force_id="grid_20260529_custom_id_001",
                            force_created_at="2026-05-29T12:00:00.000000Z")
        self.assertEqual(r["entry_id"], "grid_20260529_custom_id_001",
                         "force_id not applied")
