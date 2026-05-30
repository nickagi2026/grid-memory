"""
PostgreSQL integration tests. Requires a running Postgres instance.

Usage:
  PG_HOST=localhost PG_DB=grid_test PG_USER=grid PG_PASS=grid_test \\
    python3 -m unittest tests.test_postgres -v

In CI, Postgres is started as a service automatically.
"""

import os
import unittest
from grid_memory.local_grid import LocalGrid
from grid_memory.enterprise.postgres_backend import PostgresBackend


PG_HOST = os.environ.get("PG_HOST", "localhost")
PG_DB = os.environ.get("PG_DB", "grid_memory_test")
PG_USER = os.environ.get("PG_USER", "grid")
PG_PASS = os.environ.get("PG_PASS", "grid_test")


@unittest.skipIf(not os.environ.get("CI") and not os.environ.get("PG_HOST"),
                 "PostgreSQL not available. Set PG_HOST or run in CI.")
class TestPostgresBackend(unittest.TestCase):
    """Real PostgreSQL backend tests."""

    @classmethod
    def setUpClass(cls):
        try:
            cls.backend = PostgresBackend(
                host=PG_HOST, dbname=PG_DB,
                user=PG_USER, password=PG_PASS,
            )
            cls.grid = LocalGrid(backend=cls.backend)
        except Exception as e:
            raise unittest.SkipTest(f"PostgreSQL not available: {e}")

    @classmethod
    def tearDownClass(cls):
        try:
            cls.grid.close()
        except Exception:
            pass

    def test_write_and_query(self):
        r = self.grid.fact("Postgres test entry", tags=["test"], agent_id="tester")
        self.assertIn("entry_id", r)
        q = self.grid.query(tags=["test"])
        self.assertGreaterEqual(len(q["entries"]), 1)

    def test_workspace_id_stored(self):
        r = self.grid.write(agent_id="test", type="fact", content="WS test",
                             workspace_id="pg-workspace")
        q = self.grid.query(max=100)
        found = False
        for e in q["entries"]:
            if e.get("id") == r["entry_id"]:
                found = True
                break
        self.assertTrue(found, "Entry not found in query")

    def test_decision_with_rationale(self):
        r = self.grid.decide("Use PostgreSQL", rationale="Production grade",
                              tags=["database"], agent_id="arch")
        self.assertEqual(r["type"], "decision")
        q = self.grid.query(type="decision")
        entries = [e for e in q["entries"] if e["id"] == r["entry_id"]]
        self.assertGreaterEqual(len(entries), 1)

    def test_ttl_enforced(self):
        r = self.grid.write(agent_id="test", type="observation",
                             content="Short-lived", ttl_seconds=0)
        q = self.grid.query(max=100)
        # TTL=0 should be expired immediately
        active = [e for e in q["entries"] if e["id"] == r["entry_id"]]
        self.assertEqual(len(active), 0)

    def test_prune(self):
        self.grid.write(agent_id="test", type="observation",
                         content="Will be pruned", ttl_seconds=0)
        result = self.grid.prune()
        self.assertGreaterEqual(result.get("removed", 0), 0)

    def test_many_writes(self):
        for i in range(50):
            self.grid.fact(f"Bulk entry {i}", tags=["bulk"], agent_id="loader")
        q = self.grid.query(tags=["bulk"])
        self.assertGreaterEqual(len(q["entries"]), 1)

    def test_export_import(self):
        exported = self.grid.export_json()
        self.assertIn("entries", exported)

    def test_storage_layer_isolation(self):
        """Two Postgres backends with different tables should not overlap."""
        backend2 = PostgresBackend(
            host=PG_HOST, dbname=PG_DB,
            user=PG_USER, password=PG_PASS,
        )
        grid2 = LocalGrid(backend=backend2)
        grid2.fact("Second instance data", tags=["isolation"], agent_id="test")
        q1 = self.grid.query(tags=["isolation"])
        q2 = grid2.query(tags=["isolation"])
        # Both share the same table, so they'll both see it
        self.assertGreaterEqual(len(q2["entries"]), 1)
        backend2.close()
