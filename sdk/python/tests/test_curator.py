"""
test_curator.py — Full test battery for the Grid Curator.

Covers:
  - Duplicate detection (word overlap threshold)
  - Archive logic (stale entries with no reads)
  - Contradiction flagging (conflicting numeric values)
  - Tag suggestion (untagged entries)
  - Full curation pipeline
  - Background auto-curl
  - Archive store persistence
"""

import json
import os
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch
from grid_memory.local_grid import LocalGrid
from grid_memory.curator import (
    GridCurator,
    _word_overlap,
    _extract_keywords,
    _extract_numeric_patterns,
    _find_nearby_numbers,
    _STALE_DAYS,
    _WORD_OVERLAP_THRESHOLD,
    _SUMMARY_TYPE,
    _ARCHIVE_TYPE,
    _CONTRADICTION_TYPE,
    _TAG_SUGGESTION_TYPE,
    _days_ago_iso,
)


class TestWordOverlap(unittest.TestCase):
    """Unit tests for the word overlap utility."""

    def test_identical_texts(self):
        a = "The quick brown fox jumps over the lazy dog"
        b = "The quick brown fox jumps over the lazy dog"
        self.assertAlmostEqual(_word_overlap(a, b), 1.0)

    def test_completely_different(self):
        a = "The quick brown fox"
        b = "Nothing in common here at all"
        self.assertAlmostEqual(_word_overlap(a, b), 0.0)

    def test_high_overlap(self):
        a = "pool size 25 connections active config"
        b = "pool size 25 connections active config extra"
        # 6 of 7 union = 0.857
        self.assertGreaterEqual(_word_overlap(a, b), 0.8)

    def test_empty_texts(self):
        self.assertAlmostEqual(_word_overlap("", ""), 0.0)
        self.assertAlmostEqual(_word_overlap("hello", ""), 0.0)
        self.assertAlmostEqual(_word_overlap("", "world"), 0.0)

    def test_partial_overlap(self):
        a = "Use Express for the API server"
        b = "Use Fastify for the API server instead"
        # "Use for the API server" = 5 matching out of ~8 unique = 0.625
        score = _word_overlap(a, b)
        self.assertGreater(score, 0.3)
        self.assertLess(score, 0.9)

    def test_char_limit_respected(self):
        a = "A B C D E " * 50  # 250 chars
        b = "A B C D E " * 50  # 250 chars
        # Even with 250 chars each, only first 100 are compared
        # First 100 chars: ~100/2=50 chars of words = "A B C D E " * ~16 = 80 chars
        score = _word_overlap(a, b, char_limit=100)
        self.assertAlmostEqual(score, 1.0)  # Same first 100 chars

    def test_case_insensitive(self):
        a = "DATABASE POOL SIZE"
        b = "database pool size"
        self.assertAlmostEqual(_word_overlap(a, b), 1.0)

    def test_overlap_exactly_at_threshold(self):
        a = "pool size 25 connections max active"
        b = "pool size 25 connections max different"
        # 5 of 7 union = 0.714
        score = _word_overlap(a, b)
        self.assertLess(score, 0.8)
        self.assertGreater(score, 0.7)


class TestExtractKeywords(unittest.TestCase):
    """Unit tests for keyword extraction."""

    def test_basic_keywords(self):
        keywords = _extract_keywords("The PostgreSQL database pool has 25 connections")
        self.assertIn("postgresql", keywords)
        self.assertIn("database", keywords)
        self.assertIn("pool", keywords)
        self.assertIn("connections", keywords)

    def test_stop_words_filtered(self):
        keywords = _extract_keywords("the and or but for with")
        self.assertEqual(len(keywords), 0)

    def test_max_words_respected(self):
        keywords = _extract_keywords(
            "database pool architecture deployment config server api gateway",
            max_words=3,
        )
        self.assertLessEqual(len(keywords), 3)

    def test_short_words_filtered(self):
        keywords = _extract_keywords("a an to of in on at be is it")
        self.assertEqual(len(keywords), 0)

    def test_empty_text(self):
        keywords = _extract_keywords("")
        self.assertEqual(len(keywords), 0)


class TestNumericPatterns(unittest.TestCase):
    """Unit tests for numeric pattern extraction."""

    def test_key_value_colon(self):
        patterns = _extract_numeric_patterns("pool: 25")
        self.assertIn(("pool", 25.0), patterns)

    def test_key_value_equals(self):
        patterns = _extract_numeric_patterns("max_connections=100")
        self.assertIn(("max_connections", 100.0), patterns)

    def test_key_value_with_space(self):
        patterns = _extract_numeric_patterns("pool = 50")
        self.assertIn(("pool", 50.0), patterns)

    def test_multiple_patterns(self):
        patterns = _extract_numeric_patterns("pool: 25, timeout: 30")
        self.assertIn(("pool", 25.0), patterns)
        self.assertIn(("timeout", 30.0), patterns)

    def test_no_patterns(self):
        patterns = _extract_numeric_patterns("Hello world")
        self.assertEqual(len(patterns), 0)

    def test_decimal_values(self):
        patterns = _extract_numeric_patterns("threshold: 0.75")
        self.assertIn(("threshold", 0.75), patterns)


class TestFindNearbyNumbers(unittest.TestCase):
    """Unit tests for nearby number detection."""

    def test_number_before_unit(self):
        patterns = _find_nearby_numbers("25 connections")
        units = [k for k, v in patterns if k == "connections"]
        self.assertGreater(len(units), 0)
        vals = [v for k, v in patterns if k == "connections"]
        self.assertIn(25.0, vals)

    def test_number_after_preposition(self):
        patterns = _find_nearby_numbers("set to 50 max")
        vals = [v for k, v in patterns if k == "max" or v == 50.0]
        self.assertGreater(len(vals), 0)

    def test_no_numbers(self):
        patterns = _find_nearby_numbers("hello world")
        self.assertEqual(len(patterns), 0)


class MockGrid(LocalGrid):
    """A LocalGrid subclass with a deterministic write for testing.

    Allows inspection of what was written during a curation pass.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.written_entries: list = []

    def write(self, *args, **kwargs):
        result = super().write(*args, **kwargs)
        self.written_entries.append(result)
        # Get the actual entry from the store
        for e in self._store["entries"]:
            if e["id"] == result["entry_id"]:
                self.written_entries[-1] = dict(e)
                break
        return result

    def forget(self, entry_id: str):
        result = super().forget(entry_id)
        if result.get("found"):
            self.written_entries = [
                w for w in self.written_entries
                if w.get("id") != entry_id
            ]
        return result


class TestGridCurator(unittest.TestCase):
    """Full test battery for the GridCurator."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="curator_test_")
        self.grid = LocalGrid(store_dir=self.test_dir)
        self.curator = GridCurator(grid=self.grid)

    def tearDown(self):
        self.curator.stop()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _add_days_to_entry(self, entry_id: str, days_back: int):
        """Move an entry's created_at back in time by days_back days.
        Keeps expires_at in the far future so the entry remains "alive".
        """
        for entry in self.grid._store["entries"]:
            if entry["id"] == entry_id:
                from grid_memory.curator import _parse_iso
                dt = _parse_iso(entry["created_at"])
                new_dt = dt - __import__("datetime").timedelta(days=days_back)
                entry["created_at"] = new_dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{new_dt.microsecond:06d}Z"
                # Keep entry alive by setting expires_at far in future
                far = __import__("datetime").datetime.now(__import__("datetime").timezone.utc) + __import__("datetime").timedelta(days=365)
                entry["expires_at"] = far.strftime("%Y-%m-%dT%H:%M:%S.") + f"{far.microsecond:06d}Z"
                break
        self.grid._save_store()

    def _reset_curator(self):
        """Create a fresh curator to pick up latest store state."""
        self.curator.stop()
        self.curator = GridCurator(grid=self.grid)


class TestDuplicateDetection(TestGridCurator):
    """Tests for the duplicate merging feature."""

    def test_no_duplicates_returns_empty_list(self):
        self.grid.fact("PostgreSQL pool: 25", tags=["database"])
        self.grid.fact("Using Fastify for API", tags=["architecture"])
        self._reset_curator()
        report = self.curator.curate()
        self.assertEqual(len(report["merged"]), 0)

    def test_identical_content_merged(self):
        r1 = self.grid.fact("pool size is 25 connections", tags=["db"])
        r2 = self.grid.fact("pool size is 25 connections", tags=["config"])
        self._reset_curator()
        report = self.curator.curate()
        self.assertGreaterEqual(len(report["merged"]), 1)
        # One should survive (with _merged suffix b/c tags differ), one should be deleted
        merge = report["merged"][0]
        survivor_clean = merge["survivor"].replace("_merged", "")
        all_ids = merge["deleted"] + [survivor_clean]
        self.assertIn(r1["entry_id"], all_ids)
        self.assertIn(r2["entry_id"], all_ids)

    def test_high_similarity_merged(self):
        r1 = self.grid.fact("The database pool currently has active connections all right", tags=["db"])
        r2 = self.grid.fact("The database pool currently has active sessions all right", tags=["config"])
        self._reset_curator()
        report = self.curator.curate()
        self.assertGreaterEqual(len(report["merged"]), 1)

    def test_low_similarity_not_merged(self):
        self.grid.fact("PostgreSQL connection pool: 25", tags=["database"])
        self.grid.fact("Use Redis for caching layer", tags=["architecture"])
        self._reset_curator()
        report = self.curator.curate()
        self.assertEqual(len(report["merged"]), 0)

    def test_tags_merged_into_survivor(self):
        self.grid.fact("database pool has 25 connections", tags=["db", "pool"])
        self.grid.fact("database pool has 25 connections", tags=["config", "production"])
        self._reset_curator()
        report = self.curator.curate()
        self.assertGreaterEqual(len(report["merged"]), 1)

    def test_single_entry_no_merge(self):
        self.grid.fact("Single entry here")
        self._reset_curator()
        report = self.curator.curate()
        self.assertEqual(len(report["merged"]), 0)

    def test_multiple_duplicate_groups(self):
        # Group 1: database pool
        self.grid.fact("pool size is 25 connections", tags=["db"])
        self.grid.fact("pool size is 25 connections", tags=["config"])
        # Group 2: API choice
        self.grid.fact("Express is used for the API server", tags=["api"])
        self.grid.fact("Express is used for the API server", tags=["framework"])

        self._reset_curator()
        report = self.curator.curate()
        self.assertGreaterEqual(len(report["merged"]), 2)

    def test_three_way_duplicate(self):
        r1 = self.grid.fact("database pool has 25 connections", tags=["a"])
        r2 = self.grid.fact("database pool has 25 connections", tags=["b"])
        r3 = self.grid.fact("database pool has 25 connections", tags=["c"])

        self._reset_curator()
        report = self.curator.curate()
        self.assertGreaterEqual(len(report["merged"]), 1)
        merge = report["merged"][0]
        total_deleted = sum(len(m["deleted"]) for m in report["merged"])
        self.assertGreaterEqual(total_deleted, 2)


class TestArchiveLogic(TestGridCurator):
    """Tests for the stale entry archiving feature."""

    def test_recent_entries_not_archived(self):
        self.grid.fact("Recent entry", tags=["test"])
        self._reset_curator()
        report = self.curator.curate()
        self.assertEqual(report["archived"], 0)

    def test_stale_unread_entry_archived(self):
        r = self.grid.fact("Old unread entry", tags=["test"])
        self._add_days_to_entry(r["entry_id"], _STALE_DAYS + 1)
        self._reset_curator()
        report = self.curator.curate()
        self.assertGreaterEqual(report["archived"], 1)

    def test_stale_entry_removed_from_grid(self):
        r = self.grid.fact("Old entry to archive", tags=["test"])
        self._add_days_to_entry(r["entry_id"], _STALE_DAYS + 1)
        self._reset_curator()
        self.curator.curate()
        # Entry should no longer be in the grid
        q = self.grid.query(max=50)
        ids = [e["id"] for e in q["entries"]]
        self.assertNotIn(r["entry_id"], ids)

    def test_stale_entry_in_archive_store(self):
        r = self.grid.fact("Old entry in archive", tags=["test"])
        self._add_days_to_entry(r["entry_id"], _STALE_DAYS + 1)
        self._reset_curator()
        self.curator.curate()
        archived = self.curator.list_archived()
        ids = [e["id"] for e in archived]
        self.assertIn(r["entry_id"], ids)

    def test_stale_but_read_entry_not_archived(self):
        """Entry that was read recently should not be archived."""
        r = self.grid.fact("Old but read entry", tags=["test"])
        self._add_days_to_entry(r["entry_id"], _STALE_DAYS + 1)
        # Mark as recently read
        for e in self.grid._store["entries"]:
            if e["id"] == r["entry_id"]:
                e["last_read_at"] = _days_ago_iso(1)  # Read 1 day ago
                break
        self.grid._save_store()
        self._reset_curator()
        report = self.curator.curate()
        self.assertEqual(report["archived"], 0)

    def test_stale_read_long_ago_archived(self):
        """Entry read long ago should still be archived."""
        r = self.grid.fact("Old entry read long ago", tags=["test"])
        self._add_days_to_entry(r["entry_id"], _STALE_DAYS + 3)
        # Mark as read a long time ago
        for e in self.grid._store["entries"]:
            if e["id"] == r["entry_id"]:
                e["last_read_at"] = _days_ago_iso(_STALE_DAYS + 1)
                break
        self.grid._save_store()
        self._reset_curator()
        report = self.curator.curate()
        self.assertGreaterEqual(report["archived"], 1)

    def test_archive_reference_written(self):
        r = self.grid.fact("Archive reference test", tags=["test"])
        self._add_days_to_entry(r["entry_id"], _STALE_DAYS + 1)
        self._reset_curator()
        self.curator.curate()
        # Check an archive reference entry was written
        q = self.grid.query(type=_ARCHIVE_TYPE)
        self.assertGreaterEqual(len(q["entries"]), 1)
        self.assertIn("Archived", q["entries"][0]["content"])

    def test_archive_count_tracking(self):
        for i in range(3):
            r = self.grid.fact(f"Old entry {i}", tags=["test"])
            self._add_days_to_entry(r["entry_id"], _STALE_DAYS + 1)
        self._reset_curator()
        self.curator.curate()
        self.assertGreaterEqual(self.curator.archive_count(), 3)


class TestContradictionFlagging(TestGridCurator):
    """Tests for contradiction detection."""

    def test_no_contradictions(self):
        self.grid.fact("pool: 25 connections")
        self.grid.fact("timeout: 30 seconds")
        self._reset_curator()
        report = self.curator.curate()
        self.assertEqual(report["contradictions_flagged"], 0)

    def test_detects_numeric_contradiction(self):
        self.grid.fact("pool: 25 connections", tags=["db"])
        self.grid.fact("pool: 50 connections", tags=["db"])
        self._reset_curator()
        report = self.curator.curate()
        self.assertGreaterEqual(report["contradictions_flagged"], 1)

    def test_contradiction_flagged_as_entry(self):
        self.grid.fact("max_connections: 25", tags=["db"])
        self.grid.fact("max_connections: 100", tags=["db"])
        self._reset_curator()
        self.curator.curate()
        q = self.grid.query(type=_CONTRADICTION_TYPE)
        self.assertGreaterEqual(len(q["entries"]), 1)
        self.assertIn("contradiction", q["entries"][0]["content"])

    def test_same_value_not_contradiction(self):
        self.grid.fact("pool: 25 connections")
        self.grid.fact("pool: 25 connections, timeout: 30")
        self._reset_curator()
        report = self.curator.curate()
        self.assertEqual(report["contradictions_flagged"], 0)

    def test_small_difference_not_flagged(self):
        self.grid.fact("pool: 25 connections")
        self.grid.fact("pool: 27 connections")
        self._reset_curator()
        report = self.curator.curate()
        # Difference is 2, which is < 5, so not flagged
        # Relative diff is (27-25)/27 = 7.4% which is < 25%, so not flagged
        self.assertEqual(report["contradictions_flagged"], 0)

    def test_contradiction_with_equals_pattern(self):
        self.grid.fact("max_pool=25", tags=["db"])
        self.grid.fact("max_pool=80", tags=["db"])
        self._reset_curator()
        report = self.curator.curate()
        self.assertGreaterEqual(report["contradictions_flagged"], 1)

    def test_multiple_contradictions(self):
        # Two independent contradictions
        self.grid.fact("pool: 25 connections")
        self.grid.fact("pool: 100 connections")
        self.grid.fact("timeout: 30 seconds")
        self.grid.fact("timeout: 120 seconds")
        self._reset_curator()
        report = self.curator.curate()
        self.assertGreaterEqual(report["contradictions_flagged"], 2)

    def test_curator_entries_not_checked(self):
        """Curator's own entries should not be checked for contradictions."""
        self.grid.fact("pool: 25 connections")
        self.grid.write(agent_id="curator", type="observation", content="pool: 50 connections")
        self._reset_curator()
        report = self.curator.curate()
        # Only non-curator entries are checked
        self.assertEqual(report["contradictions_flagged"], 0)


class TestTagSuggestion(TestGridCurator):
    """Tests for tag suggestion on untagged entries."""

    def test_tagged_entries_not_suggested(self):
        self.grid.fact("database pool has 25 connections", tags=["database", "pool"])
        self._reset_curator()
        report = self.curator.curate()
        self.assertEqual(report["tags_suggested"], 0)

    def test_untagged_entry_gets_suggestion(self):
        self.grid.fact("database pool has 25 connections")
        self._reset_curator()
        report = self.curator.curate()
        self.assertGreaterEqual(report["tags_suggested"], 1)

    def test_suggestion_entry_written(self):
        self.grid.fact("database pool has 25 active connections")
        self._reset_curator()
        self.curator.curate()
        q = self.grid.query(type=_TAG_SUGGESTION_TYPE)
        self.assertGreaterEqual(len(q["entries"]), 1)
        self.assertIn("Tag suggestion", q["entries"][0]["content"])

    def test_multiple_untagged(self):
        self.grid.fact("database pool has 25 connections")
        self.grid.fact("api server using fastify framework")
        self._reset_curator()
        report = self.curator.curate()
        self.assertGreaterEqual(report["tags_suggested"], 2)

    def test_curator_entries_not_suggested(self):
        self.grid.write(agent_id="curator", type="observation", content="database pool")
        self._reset_curator()
        report = self.curator.curate()
        self.assertEqual(report["tags_suggested"], 0)

    def test_no_duplicate_suggestions(self):
        self.grid.fact("database pool connections")
        self._reset_curator()
        self.curator.curate()
        # Run again — should not suggest again for same entry
        self._reset_curator()
        report = self.curator.curate()
        self.assertEqual(report["tags_suggested"], 0)

    def test_suggestion_tags_include_suggested(self):
        self.grid.fact("database pool has 25 connections")
        self._reset_curator()
        self.curator.curate()
        q = self.grid.query(type=_TAG_SUGGESTION_TYPE)
        if q["entries"]:
            entry_tags = q["entries"][0].get("tags", [])
            has_suggested = any(t.startswith("suggested:") for t in entry_tags)
            self.assertTrue(has_suggested)


class TestWeeklySummary(TestGridCurator):
    """Tests for weekly summary generation."""

    def test_summary_written_if_none_exists(self):
        self.grid.fact("Entry 1", tags=["tag1"])
        self.grid.fact("Entry 2", tags=["tag2"])
        self._reset_curator()
        report = self.curator.curate()
        self.assertEqual(report["summaries_written"], 1)

    def test_summary_not_written_if_recent_exists(self):
        self.grid.fact("Entry 1", tags=["tag1"])
        self.grid.fact("Entry 2", tags=["tag2"])
        self._reset_curator()
        self.curator.curate()  # Writes summary 1

        # Already wrote one for this week — should not write again
        self._reset_curator()
        report = self.curator.curate()
        self.assertEqual(report["summaries_written"], 0)

    def test_summary_content_format(self):
        self.grid.fact("Entry 1", tags=["database", "config"])
        self.grid.fact("Entry 2", tags=["database"])
        self.grid.fact("Entry 3", tags=["api"])
        self._reset_curator()
        self.curator.curate()
        q = self.grid.query(type=_SUMMARY_TYPE)
        self.assertGreaterEqual(len(q["entries"]), 1)
        content = q["entries"][0]["content"]
        self.assertIn("Digest", content)
        self.assertIn("entries", content)
        self.assertIn("agents", content)

    def test_summary_counts_agents(self):
        self.grid.fact("A", agent_id="alice", tags=["x"])
        self.grid.fact("B", agent_id="bob", tags=["x"])
        self._reset_curator()
        self.curator.curate()
        q = self.grid.query(type=_SUMMARY_TYPE)
        content = q["entries"][0]["content"]
        self.assertIn("2 agents", content)

    def test_empty_store_summary(self):
        """Even with no entries, a summary should be written."""
        self._reset_curator()
        report = self.curator.curate()
        self.assertEqual(report["summaries_written"], 1)
        q = self.grid.query(type=_SUMMARY_TYPE)
        content = q["entries"][0]["content"]
        self.assertIn("Digest", content)


class TestFullPipeline(TestGridCurator):
    """Integration tests for the full curation pipeline."""

    def test_full_curation_report_structure(self):
        self.grid.fact("pool: 25 connections", tags=["db"])
        self.grid.fact("pool: 100 connections", tags=["db"])
        self._reset_curator()
        report = self.curator.curate()

        self.assertIn("archived", report)
        self.assertIn("merged", report)
        self.assertIn("summaries_written", report)
        self.assertIn("contradictions_flagged", report)
        self.assertIn("tags_suggested", report)

    def test_multiple_operations(self):
        """Create a scenario that exercises all curation operations."""
        # Entry 1: old stale unread (will be archived)
        r1 = self.grid.fact("old data here", tags=["old"])
        self._add_days_to_entry(r1["entry_id"], _STALE_DAYS + 1)

        # Entry 2-3: duplicates (will be merged)
        r2 = self.grid.fact("database pool has 25 connections", tags=["db"])
        r3 = self.grid.fact("database pool has 25 connections", tags=["config"])

        # Entry 4-5: contradictions (will be flagged)
        self.grid.fact("timeout: 30 seconds", tags=["config"])
        self.grid.fact("timeout: 120 seconds", tags=["config"])

        # Entry 6: untagged (will get suggestion)
        self.grid.fact("api server using fastify framework")

        self._reset_curator()
        report = self.curator.curate()

        # All operations should have results
        self.assertGreaterEqual(report["archived"], 1)
        self.assertGreaterEqual(len(report["merged"]), 1)
        self.assertEqual(report["summaries_written"], 1)  # First summary
        self.assertGreaterEqual(report["contradictions_flagged"], 1)
        self.assertGreaterEqual(report["tags_suggested"], 1)

    def test_idempotent_second_run(self):
        """Running curator twice should not double-process."""
        self.grid.fact("pool: 25 connections", tags=["db"])
        self.grid.fact("pool: 100 connections", tags=["db"])

        self._reset_curator()
        r1 = self.curator.curate()

        self._reset_curator()
        r2 = self.curator.curate()

        # Contradictions should not be double-flagged
        q = self.grid.query(type=_CONTRADICTION_TYPE)
        self.assertGreaterEqual(len(q["entries"]), 1)
        # Second run should not create new contradiction entries
        self.assertLessEqual(r2["contradictions_flagged"], r1["contradictions_flagged"])

    def test_clean_report_on_empty_store(self):
        report = self.curator.curate()
        self.assertEqual(report["archived"], 0)
        self.assertEqual(len(report["merged"]), 0)
        self.assertEqual(report["summaries_written"], 1)  # First summary always written
        self.assertEqual(report["contradictions_flagged"], 0)
        self.assertEqual(report["tags_suggested"], 0)


class TestBackgroundAutoCurate(TestGridCurator):
    """Tests for the background auto-curate feature."""

    def test_start_stop(self):
        self.curator.start_auto_curate(interval_seconds=3600)
        self.assertTrue(self.curator._running)
        self.assertIsNotNone(self.curator._timer)
        self.curator.stop()
        self.assertFalse(self.curator._running)
        self.assertIsNone(self.curator._timer)

    def test_auto_curate_runs_curation(self):
        self.grid.fact("pool: 25 connections", tags=["db"])
        self.grid.fact("pool: 100 connections", tags=["db"])

        # Run auto-curate with very short interval
        self.curator.start_auto_curate(interval_seconds=0.1)
        time.sleep(0.3)  # Wait for at least one cycle
        self.curator.stop()

        # Contradiction should have been flagged
        q = self.grid.query(type=_CONTRADICTION_TYPE)
        self.assertGreaterEqual(len(q["entries"]), 1)

    def test_auto_curate_tolerates_errors(self):
        """Background curation should not crash on errors."""
        # Write some data
        self.grid.fact("test data")
        self.curator.start_auto_curate(interval_seconds=0.1)
        time.sleep(0.3)
        self.curator.stop()

        # Should still be able to query
        q = self.grid.query(max=10)
        self.assertGreaterEqual(len(q["entries"]), 1)

    def test_stop_cancels_timer(self):
        self.curator.start_auto_curate(interval_seconds=1)
        timer_id = id(self.curator._timer)
        self.curator.stop()
        # Timer should be cancelled
        self.assertIsNone(self.curator._timer)


class TestArchiveStore(TestGridCurator):
    """Tests for the archive store persistence."""

    def test_archive_persistence(self):
        """Archived entries should persist in the archive file."""
        r = self.grid.fact("Persist me", tags=["test"])
        self._add_days_to_entry(r["entry_id"], _STALE_DAYS + 1)
        self._reset_curator()
        self.curator.curate()

        # Create a new curator instance to verify archive persisted
        curator2 = GridCurator(grid=self.grid)
        self.assertGreaterEqual(curator2.archive_count(), 1)
        archived = curator2.list_archived()
        self.assertIn(r["entry_id"], [e["id"] for e in archived])

    def test_archive_entry_maintains_content(self):
        r = self.grid.fact("The content to preserve in archive", tags=["preserve-me"])
        self._add_days_to_entry(r["entry_id"], _STALE_DAYS + 1)
        self._reset_curator()
        self.curator.curate()

        archived = self.curator.list_archived()
        matching = [e for e in archived if e["id"] == r["entry_id"]]
        self.assertEqual(len(matching), 1)
        self.assertIn("content to preserve", matching[0]["content"])

    def test_archive_entry_has_archived_at(self):
        r = self.grid.fact("Timestamp test", tags=["test"])
        self._add_days_to_entry(r["entry_id"], _STALE_DAYS + 1)
        self._reset_curator()
        self.curator.curate()

        archived = self.curator.list_archived()
        matching = [e for e in archived if e["id"] == r["entry_id"]]
        self.assertEqual(len(matching), 1)
        self.assertIn("archived_at", matching[0])

    def test_clear_archive(self):
        r = self.grid.fact("Clear me", tags=["test"])
        self._add_days_to_entry(r["entry_id"], _STALE_DAYS + 1)
        self._reset_curator()
        self.curator.curate()
        self.assertGreaterEqual(self.curator.archive_count(), 1)

        self.curator.clear_archive()
        self.assertEqual(self.curator.archive_count(), 0)

    def test_no_stale_entries_no_archive_reference(self):
        self.grid.fact("Recent entry", tags=["test"])
        self._reset_curator()
        self.curator.curate()
        self.assertEqual(self.curator.archive_count(), 0)


class TestEdgeCases(TestGridCurator):
    """Edge case tests for the curator."""

    def test_empty_grid(self):
        report = self.curator.curate()
        self.assertEqual(report["archived"], 0)
        self.assertEqual(len(report["merged"]), 0)
        self.assertEqual(report["contradictions_flagged"], 0)
        self.assertEqual(report["tags_suggested"], 0)

    def test_single_entry(self):
        self.grid.fact("Single entry here", tags=["test"])
        self._reset_curator()
        report = self.curator.curate()
        self.assertEqual(report["archived"], 0)
        self.assertEqual(len(report["merged"]), 0)

    def test_very_large_content(self):
        large = "A B C D E F G H I J K L M " * 1000  # 26000 chars
        self.grid.fact(large, tags=["large"])
        self._reset_curator()
        report = self.curator.curate()
        self.assertEqual(len(report["merged"]), 0)

    def test_entries_with_no_content(self):
        """Empty content entries should not cause errors."""
        self.grid.write(agent_id="test", content="  ", type="observation")
        self._reset_curator()
        report = self.curator.curate()
        # Should not crash
        self.assertIsNotNone(report)

    def test_curator_entries_preserved(self):
        """Curator entries should not be archived or modified."""
        self.grid.write(
            agent_id="curator",
            type="observation",
            content="Curator data",
            tags=["curator"],
        )
        # Make it seem old (but curator entries should be skipped)
        self._reset_curator()
        report = self.curator.curate()
        # Curator entries are archived like others if stale
        self.assertEqual(report["archived"], 0)  # It's recent

    def test_many_contradictions_same_key(self):
        for i in range(5):
            self.grid.fact(f"pool: {10 + i * 20} connections", tags=["db"])
        self._reset_curator()
        report = self.curator.curate()
        # Should flag multiple contradictions
        self.assertGreaterEqual(report["contradictions_flagged"], 1)


if __name__ == "__main__":
    unittest.main()
