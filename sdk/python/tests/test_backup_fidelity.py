"""
test_backup_fidelity.py — Backup/restore fidelity proof suite.

Proves that export → import → export produces identical data:
  ids, timestamps, workspace_id, parent_entry, memory_tier
"""

import json
import os
import tempfile
import unittest
from grid_memory.local_grid import LocalGrid


class TestBackupFidelity(unittest.TestCase):
    """Verify full round-trip: export → import → export."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.grid = LocalGrid(store_dir=os.path.join(self.tmpdir, "source"))

        # Write a known dataset with forced IDs and timestamps
        self.r1 = self.grid.write(
            agent_id="arch", type="decision", content="Use PostgreSQL",
            tags=["database"], workspace_id="ws-a", memory_tier="project",
            force_id="grid_fidelity_001",
            force_created_at="2026-01-01T00:00:00.000000Z",
            force_expires_at="2026-06-01T00:00:00.000000Z",
        )
        self.r2 = self.grid.write(
            agent_id="ops", type="handoff", content="Handoff complete",
            tags=["handoff"], workspace_id="ws-a",
            parent_entry=self.r1["entry_id"],
            force_id="grid_fidelity_002",
            force_created_at="2026-01-02T00:00:00.000000Z",
            force_expires_at="2026-06-02T00:00:00.000000Z",
        )

    def tearDown(self):
        import shutil; shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _roundtrip(self):
        """Export → import into fresh grid → export again."""
        exported = self.grid.export_json()
        d = os.path.join(self.tmpdir, "target")
        os.makedirs(d, exist_ok=True)
        g2 = LocalGrid(store_dir=d)
        result = g2.import_json(exported)
        re_exported = g2.export_json()
        return json.loads(exported), json.loads(re_exported), result

    def test_ids_preserved(self):
        orig, re_exp, _ = self._roundtrip()
        orig_ids = sorted(e["id"] for e in orig["entries"])
        re_ids = sorted(e["id"] for e in re_exp["entries"])
        self.assertEqual(orig_ids, re_ids, f"IDs changed: {orig_ids} != {re_ids}")

    def test_timestamps_preserved(self):
        orig, re_exp, _ = self._roundtrip()
        for o in orig["entries"]:
            match = next((e for e in re_exp["entries"] if e["id"] == o["id"]), None)
            self.assertIsNotNone(match, f"Entry {o['id']} missing after import")
            self.assertEqual(o["created_at"], match["created_at"],
                             f"created_at changed for {o['id']}")
            self.assertEqual(o["expires_at"], match["expires_at"],
                             f"expires_at changed for {o['id']}")

    def test_workspace_preserved(self):
        orig, re_exp, _ = self._roundtrip()
        for o in orig["entries"]:
            match = next((e for e in re_exp["entries"] if e["id"] == o["id"]), None)
            self.assertEqual(o.get("workspace_id"), match.get("workspace_id"),
                             f"workspace_id changed for {o['id']}")

    def test_parent_child_preserved(self):
        orig, re_exp, _ = self._roundtrip()
        for o in orig["entries"]:
            match = next((e for e in re_exp["entries"] if e["id"] == o["id"]), None)
            self.assertEqual(o.get("parent_entry"), match.get("parent_entry"),
                             f"parent_entry changed for {o['id']}")

    def test_memory_tier_preserved(self):
        orig, re_exp, _ = self._roundtrip()
        for o in orig["entries"]:
            match = next((e for e in re_exp["entries"] if e["id"] == o["id"]), None)
            self.assertEqual(o.get("memory_tier"), match.get("memory_tier"),
                             f"memory_tier changed for {o['id']}")

    def test_full_roundtrip_identical(self):
        """The ultimate test: every field matches on every entry."""
        orig, re_exp, result = self._roundtrip()
        self.assertEqual(result["imported"], len(orig["entries"]),
                         f"Import count mismatch: {result['imported']} != {len(orig['entries'])}")

        for o in orig["entries"]:
            match = next((e for e in re_exp["entries"] if e["id"] == o["id"]), None)
            self.assertIsNotNone(match)
            for field in ["id", "agent_id", "type", "content", "created_at",
                          "expires_at", "workspace_id", "parent_entry", "memory_tier"]:
                self.assertEqual(o.get(field), match.get(field),
                                 f"Field '{field}' changed for {o['id']}: {o.get(field)} != {match.get(field)}")


if __name__ == "__main__":
    unittest.main()
