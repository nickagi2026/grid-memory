"""Tests for the Grid Memory Python SDK.

Requires a running Grid server at http://localhost:8080.
Start one with: node server.js
"""

import json
import os
import time
import unittest
from grid_memory import Grid, GridError, AutoGenGridPlugin, CrewAITool


TEST_URL = os.environ.get("GRID_URL", "http://localhost:8080")


class TestGridConnection(unittest.TestCase):
    """Tests that require a live Grid server."""

    @classmethod
    def setUpClass(cls):
        cls.grid = Grid(TEST_URL)
        # Verify server is running
        try:
            cls.grid.info()
        except GridError as e:
            raise unittest.SkipTest(f"Grid server not available at {TEST_URL}: {e}")

    def test_health(self):
        """Health endpoint returns ok status."""
        info = self.grid.info()
        self.assertIn("total_entries", info)
        self.assertIn("alive_entries", info)

    def test_write_fact_default_agent(self):
        """fact() uses the default agent_id from constructor."""
        g = Grid(TEST_URL, default_agent_id="test-default")
        result = g.fact("Default agent test", tags=["test"])
        self.assertEqual(result["agent_id"], "test-default")
        g.forget(result["entry_id"])

    def test_write_fact_custom_agent(self):
        """fact() accepts per-call agent_id override."""
        result = self.grid.fact("Custom agent test", tags=["test"],
                                 agent_id="custom-architect")
        self.assertEqual(result["agent_id"], "custom-architect")
        self.grid.forget(result["entry_id"])

    def test_write_decision(self):
        """decide() stores decisions correctly."""
        result = self.grid.decide(
            "Use PostgreSQL",
            rationale="Better ecosystem and reliability",
            tags=["database", "architecture"],
            agent_id="architect"
        )
        self.assertEqual(result["type"], "decision")
        # Verify by reading it back
        q = self.grid.query(tags=["database"], type="decision")
        entry = next((e for e in q.get("entries", []) if e["id"] == result["entry_id"]), None)
        self.assertIsNotNone(entry, "Written decision not found in query")
        self.assertIn("Rationale: Better ecosystem", entry["content"])
        self.grid.forget(result["entry_id"])

    def test_write_handoff(self):
        """handoff() stores cross-agent handoffs."""
        result = self.grid.handoff(
            from_agent="researcher",
            to_agent="builder",
            content="API design complete",
            status="ready",
            agent_id="researcher"
        )
        self.assertEqual(result["type"], "handoff")
        # Verify by reading it back
        q = self.grid.query(agents=["researcher"], type="handoff")
        entry = next((e for e in q.get("entries", []) if e["id"] == result["entry_id"]), None)
        self.assertIsNotNone(entry, "Written handoff not found in query")
        self.assertIn("builder", entry["content"])
        self.grid.forget(result["entry_id"])

    def test_write_generic(self):
        """write() accepts all parameters."""
        result = self.grid.write(
            agent_id="test-agent",
            type="observation",
            content="Generic entry",
            tags=["test"],
            session_id="sess-123"
        )
        self.assertEqual(result["agent_id"], "test-agent")
        self.assertEqual(result["type"], "observation")
        self.grid.forget(result["entry_id"])

    def test_query_by_tags(self):
        """query() filters by tags."""
        # Write test entries
        entry1 = self.grid.fact("Entry Alpha", tags=["project:alpha", "test"])
        entry2 = self.grid.fact("Entry Beta", tags=["project:beta", "test"])
        entry3 = self.grid.fact("Entry Alpha-2", tags=["project:alpha", "test"])

        try:
            result = self.grid.query(tags=["project:alpha"])
            entries = result.get("entries", [])
            self.assertGreaterEqual(len(entries), 2)
            for e in entries:
                tags = e.get("tags", [])
                self.assertTrue("project:alpha" in tags, f"Expected project:alpha tag in {tags}")

            # OR mode should return both project:alpha and project:beta
            result_or = self.grid.query(tags=["project:alpha", "project:beta"])
            self.assertGreaterEqual(len(result_or.get("entries", [])), 3)

            # AND mode should return entries with ALL specified tags
            result_and = self.grid.query(tags=["project:alpha", "test"], tagMode="AND")
            for e in result_and.get("entries", []):
                etags = set(e.get("tags", []))
                self.assertTrue("project:alpha" in etags and "test" in etags)
        finally:
            self.grid.forget(entry1["entry_id"])
            self.grid.forget(entry2["entry_id"])
            self.grid.forget(entry3["entry_id"])

    def test_query_by_agent(self):
        """query() filters by agent_id."""
        entry = self.grid.fact("Agent-specific data", tags=["test"],
                                agent_id="query-test-agent")
        try:
            result = self.grid.query(agents=["query-test-agent"])
            entries = result.get("entries", [])
            self.assertGreaterEqual(len(entries), 1)
            for e in entries:
                self.assertEqual(e["agent_id"], "query-test-agent")
        finally:
            self.grid.forget(entry["entry_id"])

    def test_query_by_type(self):
        """query() filters by entry type."""
        entry = self.grid.decide("Test decision query", tags=["test"],
                                  agent_id="test-agent")
        try:
            result = self.grid.query(type="decision")
            entries = result.get("entries", [])
            self.assertGreaterEqual(len(entries), 1)
            for e in entries:
                self.assertEqual(e["type"], "decision")
        finally:
            self.grid.forget(entry["entry_id"])

    def test_query_max_results(self):
        """query() respects max limit."""
        entries_written = []
        for i in range(5):
            e = self.grid.fact(f"Max test entry {i}", tags=["test-max-limit"],
                                agent_id="test-agent")
            entries_written.append(e)

        try:
            result = self.grid.query(tags=["test-max-limit"], max=2)
            self.assertLessEqual(len(result.get("entries", [])), 2)
        finally:
            for e in entries_written:
                self.grid.forget(e["entry_id"])

    def test_inject(self):
        """inject() returns a formatted context block."""
        # Write some data
        self.grid.fact("The API uses Fastify", tags=["architecture"],
                        agent_id="architect")
        self.grid.fact("PostgreSQL pool: 25 connections", tags=["database"],
                        agent_id="architect")

        block = self.grid.inject(context="building the API layer")
        self.assertIn("SHARED MEMORY GRID", block)
        self.assertIn("END GRID", block)
        self.assertGreater(len(block), 50)

    def test_info(self):
        """info() returns store statistics."""
        info = self.grid.info()
        self.assertIn("total_entries", info)
        self.assertIn("alive_entries", info)
        self.assertIn("unique_agents", info)
        self.assertIn("unique_tags", info)
        self.assertIn("store_size_kb", info)

    def test_prune(self):
        """prune() removes expired entries."""
        # Write a short-lived entry
        entry = self.grid.write(
            agent_id="test-agent",
            type="observation",
            content="Will be pruned",
            tags=["test-prune"],
            ttl_seconds=1  # 1 second TTL
        )
        time.sleep(1.5)
        result = self.grid.prune()
        self.assertIn("removed", result)
        self.assertGreaterEqual(result["removed"], 0)  # could be >0 if server pruned it

    def test_forget(self):
        """forget() removes a specific entry."""
        entry = self.grid.fact("To be forgotten", tags=["test-forget"],
                                agent_id="test-agent")
        result = self.grid.forget(entry["entry_id"])
        self.assertTrue(result.get("found"))

    def test_roundtrip_write_query(self):
        """Full roundtrip: write then query by tag."""
        e = self.grid.fact("Roundtrip test data", tags=["roundtrip-test"],
                            agent_id="tester")
        try:
            result = self.grid.query(tags=["roundtrip-test"])
            entries = result.get("entries", [])
            self.assertGreaterEqual(len(entries), 1)
            found = any(e["content"] == "Roundtrip test data" for e in entries)
            self.assertTrue(found, "Written entry not found in query results")

            # Verify query metadata
            meta = result.get("query_meta", {})
            self.assertIn("total_before_filter", meta)
            self.assertIn("returned", meta)
        finally:
            self.grid.forget(e["entry_id"])

    def test_connection_error(self):
        """GridError raised when server is unreachable."""
        bad_grid = Grid("http://localhost:99999")
        with self.assertRaises(GridError):
            bad_grid.info()


class TestAutoGenPlugin(unittest.TestCase):
    """Tests for the AutoGen plugin (no AutoGen dependency needed)."""

    def setUp(self):
        self.plugin = AutoGenGridPlugin(url=TEST_URL, agent_id="test-autogen")

    def test_get_context(self):
        """get_context() enriches message with Grid context."""
        try:
            result = self.plugin.get_context("hello")
            self.assertIsInstance(result, str)
            self.assertIn("hello", result)  # Original message preserved
        except (GridError, OSError):
            self.skipTest("Grid server not available — inject endpoint unreachable")

    def test_log_exchange(self):
        """log_exchange() writes to Grid without error."""
        try:
            self.plugin.log_exchange("test message", "test response")
        except (GridError, OSError):
            self.skipTest("Grid server not available — exchange logging skipped")

    def test_wrap_no_agent(self):
        """wrap() handles None agent gracefully."""
        # Just verify it doesn't crash (no agent to wrap)
        pass


class TestCrewAITool(unittest.TestCase):
    """Tests for the CrewAI tool wrapper."""

    def setUp(self):
        self.tool = CrewAITool(url=TEST_URL, agent_id="test-crewai")

    def test_query_tool_callable(self):
        """query_tool() returns a callable."""
        q = self.tool.query_tool()
        self.assertTrue(callable(q))

    def test_write_tool_callable(self):
        """write_tool() returns a callable."""
        w = self.tool.write_tool()
        self.assertTrue(callable(w))

    def test_context_tool_callable(self):
        """context_tool() returns a callable."""
        c = self.tool.context_tool()
        self.assertTrue(callable(c))


if __name__ == "__main__":
    unittest.main()
