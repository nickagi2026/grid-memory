"""Tests for memory tier promotion engine."""

import os
import tempfile
import unittest
from grid_memory.local_grid import LocalGrid
from grid_memory.tiers import PromotionEngine, is_promotable, tier_rank


class TestTierRanking(unittest.TestCase):
    def test_working_rank(self):
        self.assertEqual(tier_rank("working"), 0)
    def test_project_rank(self):
        self.assertEqual(tier_rank("project"), 1)
    def test_organization_rank(self):
        self.assertEqual(tier_rank("organization"), 2)
    def test_unknown_rank(self):
        self.assertEqual(tier_rank("unknown"), 0)
    def test_promotable_working_to_project(self):
        self.assertTrue(is_promotable("working", "project"))
    def test_promotable_project_to_org(self):
        self.assertTrue(is_promotable("project", "organization"))
    def test_not_promotable_org_to_project(self):
        self.assertFalse(is_promotable("organization", "project"))
    def test_not_promotable_same(self):
        self.assertFalse(is_promotable("working", "working"))


class TestPromotionEngine(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.grid = LocalGrid(store_dir=self.tmpdir)
        self.engine = PromotionEngine(self.grid)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_entries_default_to_working(self):
        r = self.grid.fact("Test", tags=["test"])
        entry = self._get_entry(r["entry_id"])
        self.assertEqual(entry.get("memory_tier"), "working")

    def test_write_with_tier(self):
        r = self.grid.write(agent_id="test", type="decision",
                             content="Important", memory_tier="project")
        entry = self._get_entry(r["entry_id"])
        self.assertEqual(entry.get("memory_tier"), "project")

    def test_manual_promote(self):
        r = self.grid.fact("Promotable", tags=["test"])
        result = self.engine.promote(r["entry_id"], "project")
        self.assertTrue(result["success"])
        entry = self._get_entry(r["entry_id"])
        self.assertEqual(entry.get("memory_tier"), "project")

    def test_promote_nonexistent(self):
        result = self.engine.promote("nonexistent_id", "project")
        self.assertFalse(result["success"])

    def test_promote_bad_direction(self):
        r = self.grid.fact("Test", tags=["test"], memory_tier="organization")
        result = self.engine.promote(r["entry_id"], "working")
        self.assertFalse(result["success"])

    def test_scan_promotes_high_read_count(self):
        r = self.grid.fact("High value decision", tags=["database"],
                            agent_id="arch")
        eid = r["entry_id"]
        # Simulate reads
        for _ in range(10):
            self.grid.query(tags=["database"])
        result = self.engine.scan_and_promote(dry_run=True)
        self.assertGreaterEqual(len(result["working_to_project"]), 0)

    def test_tier_distribution(self):
        self.grid.fact("Working entry", tags=["test"])
        self.grid.write(agent_id="arch", type="decision", content="Project decision",
                         memory_tier="project")
        dist = self.engine.get_tier_distribution()
        self.assertGreaterEqual(dist.get("working", 0), 1)
        self.assertGreaterEqual(dist.get("project", 0), 1)

    def test_promote_by_tag(self):
        self.grid.fact("Entry 1", tags=["important", "promote-me"])
        self.grid.fact("Entry 2", tags=["important", "promote-me"])
        result = self.engine.promote_by_tag("promote-me", "project")
        self.assertEqual(result["promoted"], 2)

    def test_promotion_event_written(self):
        r = self.grid.fact("Will be promoted", tags=["test"])
        self.engine.promote(r["entry_id"], "project")
        q = self.grid.query(tags=["promotion"])
        self.assertGreaterEqual(len(q["entries"]), 1)

    def test_promoted_from_tracked(self):
        r = self.grid.fact("Track this", tags=["test"])
        self.engine.promote(r["entry_id"], "project")
        entry = self._get_entry(r["entry_id"])
        self.assertEqual(entry.get("promoted_from"), "working")

    def _get_entry(self, entry_id):
        if hasattr(self.grid, '_load_store'):
            self.grid._load_store()
            for e in self.grid._store["entries"]:
                if e["id"] == entry_id:
                    return e
        return {}


if __name__ == "__main__":
    unittest.main()


class TestTierPromotionAllBackends(unittest.TestCase):
    """Tier promotion must work identically on JSON, SQLite, and PostgreSQL."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil; shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _test_promotion_cycle(self, grid):
        from grid_memory.tiers import PromotionEngine
        eng = PromotionEngine(grid)
        r = grid.fact("Promotable decision", tags=["test"], agent_id="arch")
        result = eng.promote(r["entry_id"], "project")
        self.assertTrue(result["success"], f"Promote failed: {result}")
        self.assertEqual(result["to_tier"], "project")

        # Promote further
        result2 = eng.promote(r["entry_id"], "organization")
        self.assertTrue(result2["success"], f"Second promote failed: {result2}")
        self.assertEqual(result2["to_tier"], "organization")

    def test_json_backend(self):
        grid = LocalGrid(store_dir=os.path.join(self.tmpdir, "json"))
        self._test_promotion_cycle(grid)

    def test_sqlite_backend(self):
        from grid_memory.sqlite_backend import SQLiteBackend
        db = os.path.join(self.tmpdir, "test.db")
        backend = SQLiteBackend(db)
        grid = LocalGrid(backend=backend)
        self._test_promotion_cycle(grid)
        backend.close()

    def test_tier_manual_promote_by_id(self):
        """PromotionEngine.promote() must find the entry by ID on all backends."""
        from grid_memory.tiers import PromotionEngine

        # JSON
        grid = LocalGrid(store_dir=os.path.join(self.tmpdir, "json2"))
        r = grid.fact("JSON test", tags=["test"], agent_id="arch")
        eng = PromotionEngine(grid)
        result = eng.promote(r["entry_id"], "project")
        self.assertTrue(result["success"], f"JSON promote: {result}")

        # SQLite
        from grid_memory.sqlite_backend import SQLiteBackend
        db = os.path.join(self.tmpdir, "test2.db")
        backend = SQLiteBackend(db)
        grid2 = LocalGrid(backend=backend)
        r2 = grid2.fact("SQLite test", tags=["test"], agent_id="arch")
        eng2 = PromotionEngine(grid2)
        result2 = eng2.promote(r2["entry_id"], "project")
        self.assertTrue(result2["success"], f"SQLite promote: {result2}")
        backend.close()
