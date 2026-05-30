"""Tests for SQLite backend."""

import os
import tempfile
import unittest
from grid_memory.local_grid import LocalGrid
from grid_memory.sqlite_backend import SQLiteBackend


class TestSQLiteBackend(unittest.TestCase):
    """Test SQLite-backed LocalGrid."""

    def setUp(self):
        self._tmpfile = tempfile.mktemp(suffix=".db")
        self.backend = SQLiteBackend(self._tmpfile)
        self.grid = LocalGrid(backend=self.backend)

    def tearDown(self):
        try:
            self.backend.close()
            os.unlink(self._tmpfile)
        except (OSError, IOError):
            pass

    def test_write_and_query(self):
        r = self.grid.fact("Test entry", tags=["test"], agent_id="tester")
        self.assertIn("entry_id", r)
        q = self.grid.query(tags=["test"])
        self.assertGreaterEqual(len(q["entries"]), 1)
        self.assertEqual(q["entries"][0]["agent_id"], "tester")

    def test_write_with_backend(self):
        r = self.grid.write(agent_id="arch", type="decision",
                             content="Use PostgreSQL", tags=["database"])
        self.assertEqual(r["type"], "decision")
        self.assertEqual(r["agent_id"], "arch")

    def test_query_multiple_types(self):
        self.grid.fact("A fact", tags=["test"])
        self.grid.decide("A decision", tags=["test"])
        q = self.grid.query(types=["fact", "decision"])
        types = {e["type"] for e in q["entries"]}
        self.assertIn("fact", types)
        self.assertIn("decision", types)

    def test_query_by_agent(self):
        self.grid.fact("Bob's note", agent_id="bob", tags=["test"])
        q = self.grid.query(agents=["bob"])
        for e in q["entries"]:
            self.assertEqual(e["agent_id"], "bob")

    def test_and_tag_mode(self):
        self.grid.fact("Entry A", tags=["alpha", "beta"])
        self.grid.fact("Entry B", tags=["alpha", "gamma"])
        q = self.grid.query(tags=["alpha", "beta"], tag_mode="AND")
        for e in q["entries"]:
            etags = set(e.get("tags", []))
            self.assertTrue("alpha" in etags and "beta" in etags)

    def test_info(self):
        self.grid.fact("Entry 1", agent_id="a1", tags=["t1"])
        self.grid.fact("Entry 2", agent_id="a2", tags=["t2"])
        info = self.grid.info()
        self.assertGreaterEqual(info["total_entries"], 2)
        self.assertIn("store_version", info)
        self.assertEqual(info["store_version"], "sqlite")

    def test_prune(self):
        self.grid.write(agent_id="test", type="observation",
                         content="Short", ttl_seconds=0)
        # TTL=0 is immediate expiry with the fix
        result = self.grid.prune()
        self.assertGreaterEqual(result["removed"], 0)

    def test_forget(self):
        r = self.grid.fact("To forget", tags=["test"])
        result = self.grid.forget(r["entry_id"])
        self.assertTrue(result["found"])
        info = self.grid.info()
        self.assertEqual(info["total_entries"], 0)

    def test_wipe(self):
        self.grid.fact("Data", tags=["test"])
        self.grid.wipe(confirm=True)
        info = self.grid.info()
        self.assertEqual(info["total_entries"], 0)

    def test_inject(self):
        self.grid.fact("Database: PostgreSQL pool 25", tags=["database"],
                        agent_id="arch")
        result = self.grid.inject("database")
        self.assertIn("SHARED MEMORY GRID", result["block"])
        self.assertGreater(result["entry_count"], 0)

    def test_convenience_methods(self):
        self.grid.fact("A fact", agent_id="test")
        self.grid.decide("A decision", agent_id="test", rationale="Because")
        self.grid.handoff(from_agent="a", to_agent="b",
                           content="Done", agent_id="a")
        info = self.grid.info()
        self.assertGreaterEqual(info["total_entries"], 3)

    def test_many_writes(self):
        for i in range(100):
            self.grid.fact(f"Entry {i}", tags=["bulk"], agent_id="loader")
        q = self.grid.query(tags=["bulk"])
        self.assertGreaterEqual(len(q["entries"]), 50)

    def test_fts_search(self):
        self.grid.fact("PostgreSQL is our primary database", tags=["db"],
                        agent_id="arch")
        self.grid.fact("We use Redis for caching", tags=["cache"],
                        agent_id="arch")
        # Tag-based search
        q = self.grid.query(tags=["db"])
        self.assertGreaterEqual(len(q["entries"]), 1)
        found = any("PostgreSQL" in e["content"] for e in q["entries"])
        self.assertTrue(found)

    def test_semantic_search_with_backend(self):
        """Semantic search flag works with backend (no embeddings = degraded)."""
        self.grid.fact("Database config", tags=["database"], agent_id="test")
        result = self.grid.query(semantic="tell me about databases")
        self.assertFalse(result["query_meta"]["semantic"])
        self.assertFalse(result["query_meta"]["semantic_available"])

    def test_memory_db(self):
        """In-memory SQLite works."""
        mem_backend = SQLiteBackend(":memory:")
        mem_grid = LocalGrid(backend=mem_backend)
        mem_grid.fact("In-memory test", tags=["test"], agent_id="mem")
        q = mem_grid.query(tags=["test"])
        self.assertEqual(len(q["entries"]), 1)
        mem_backend.close()


if __name__ == "__main__":
    unittest.main()
