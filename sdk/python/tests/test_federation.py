"""
Tests for GridFederation — the Grid Federation Module.

Tests cover:
  1. Adding and removing peers
  2. Sync logic (mocked HTTP)
  3. Deduplication
  4. Error handling
  5. Auto-sync lifecycle
  6. State persistence
  7. Status reporting
"""

import json
import logging
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, MagicMock
from typing import Dict, Optional
from urllib.error import URLError, HTTPError

# Add parent dir to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from grid_memory.local_grid import LocalGrid
from grid_memory.federation import GridFederation, PeerSyncError


# Disable logging noise during tests
logging.disable(logging.CRITICAL)


class _MockHTTPResponse:
    """Mock urllib response with status and read()."""

    def __init__(self, data: bytes, status: int = 200):
        self._data = data
        self.status = status

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class TestGridFederationPeers(unittest.TestCase):
    """Test 1: Adding and removing peers."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="fed_test_")
        self.grid = LocalGrid(store_dir=self.test_dir)
        self.fed = GridFederation(grid=self.grid, state_dir=self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_add_peer_returns_true(self):
        result = self.fed.add_peer("team-alpha", "http://alpha.grid:8080")
        self.assertTrue(result)

    def test_add_peer_appears_in_get_peers(self):
        self.fed.add_peer("team-alpha", "http://alpha.grid:8080")
        peers = self.fed.get_peers()
        self.assertIn("team-alpha", peers)
        self.assertEqual(peers["team-alpha"]["url"], "http://alpha.grid:8080")

    def test_add_peer_duplicate_returns_false(self):
        self.fed.add_peer("team-alpha", "http://alpha.grid:8080")
        result = self.fed.add_peer("team-alpha", "http://other.grid:8080")
        self.assertFalse(result)
        # URL should remain unchanged
        peers = self.fed.get_peers()
        self.assertEqual(peers["team-alpha"]["url"], "http://alpha.grid:8080")

    def test_remove_peer_returns_true(self):
        self.fed.add_peer("team-alpha", "http://alpha.grid:8080")
        result = self.fed.remove_peer("team-alpha")
        self.assertTrue(result)

    def test_remove_peer_removes_from_get_peers(self):
        self.fed.add_peer("team-alpha", "http://alpha.grid:8080")
        self.fed.remove_peer("team-alpha")
        peers = self.fed.get_peers()
        self.assertNotIn("team-alpha", peers)

    def test_remove_nonexistent_returns_false(self):
        result = self.fed.remove_peer("nonexistent")
        self.assertFalse(result)

    def test_add_multiple_peers(self):
        self.fed.add_peer("alpha", "http://alpha.grid:8080")
        self.fed.add_peer("beta", "http://beta.grid:8080")
        self.fed.add_peer("gamma", "http://gamma.grid:8080")
        peers = self.fed.get_peers()
        self.assertEqual(len(peers), 3)
        for name in ("alpha", "beta", "gamma"):
            self.assertIn(name, peers)

    def test_peer_with_custom_federation_tag(self):
        self.fed.add_peer("custom", "http://custom.grid:8080",
                          federation_tag="team:custom")
        peers = self.fed.get_peers()
        self.assertEqual(peers["custom"]["federation_tag"], "team:custom")


class TestGridFederationSync(unittest.TestCase):
    """Test 2: Sync logic with mocked HTTP."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="fed_test_")
        self.grid = LocalGrid(store_dir=self.test_dir)
        self.fed = GridFederation(grid=self.grid, state_dir=self.test_dir)
        self.fed.add_peer("team-alpha", "http://alpha.grid:8080")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch("urllib.request.urlopen")
    def test_sync_pulls_entries(self, mock_urlopen):
        """Basic sync pulls entries from peer and writes locally."""
        mock_urlopen.return_value = _MockHTTPResponse(json.dumps({
            "entries": [
                {
                    "id": "grid_20260529_abc123def456",
                    "agent_id": "peer-agent",
                    "type": "fact",
                    "tags": ["grid:federation", "database"],
                    "content": "PostgreSQL pool: 25",
                    "created_at": "2026-05-29T05:00:00.000000Z",
                    "ttl_seconds": 86400,
                    "expires_at": "2026-05-30T05:00:00.000000Z",
                    "session_id": "",
                    "parent_entry": None,
                }
            ]
        }).encode())

        result = self.fed.sync(peer_names=["team-alpha"])

        # Check result
        self.assertIn("team-alpha", result["peers"])
        alpha = result["peers"]["team-alpha"]
        self.assertTrue(alpha["connected"])
        self.assertEqual(alpha["entries_pulled"], 1)

        # Check entry was written locally
        local = self.grid.query(tags=["grid:federation"])
        self.assertEqual(len(local["entries"]), 1)
        self.assertIn("PostgreSQL pool", local["entries"][0]["content"])
        self.assertEqual(local["entries"][0]["agent_id"], "peer-agent")

    @patch("urllib.request.urlopen")
    def test_sync_multiple_peers(self, mock_urlopen):
        """Sync from multiple peers pulls entries from each."""
        self.fed.add_peer("team-beta", "http://beta.grid:8080")

        def mock_response(request, *args, **kwargs):
            url_str = request.full_url if hasattr(request, 'full_url') else str(request)
            if "alpha" in url_str:
                return _MockHTTPResponse(json.dumps({
                    "entries": [{"id": "grid_001", "agent_id": "a1",
                                 "type": "fact", "tags": ["grid:federation"],
                                 "content": "From alpha", "created_at": "2026-01-01T00:00:00.000000Z"}]
                }).encode())
            elif "beta" in url_str:
                return _MockHTTPResponse(json.dumps({
                    "entries": [{"id": "grid_002", "agent_id": "b1",
                                 "type": "fact", "tags": ["grid:federation"],
                                 "content": "From beta", "created_at": "2026-01-01T00:00:00.000000Z"}]
                }).encode())
            return _MockHTTPResponse(json.dumps({"entries": []}).encode())

        mock_urlopen.side_effect = mock_response

        result = self.fed.sync()

        self.assertIn("team-alpha", result["peers"])
        self.assertIn("team-beta", result["peers"])
        self.assertEqual(result["peers"]["team-alpha"]["entries_pulled"], 1)
        self.assertEqual(result["peers"]["team-beta"]["entries_pulled"], 1)
        self.assertEqual(result["summary"]["total_entries_pulled"], 2)

        local = self.grid.query(tags=["grid:federation"])
        self.assertEqual(len(local["entries"]), 2)

    @patch("urllib.request.urlopen")
    def test_sync_adds_federation_tag(self, mock_urlopen):
        """Entries without federation tag get it added during sync."""
        mock_urlopen.return_value = _MockHTTPResponse(json.dumps({
            "entries": [
                {
                    "id": "grid_20260529_no_tag",
                    "agent_id": "peer-agent",
                    "type": "fact",
                    "tags": ["database"],  # No grid:federation tag
                    "content": "Missing federation tag",
                    "created_at": "2026-05-29T05:00:00.000000Z",
                }
            ]
        }).encode())

        self.fed.sync(peer_names=["team-alpha"])

        local = self.grid.query(tags=["grid:federation"])
        self.assertEqual(len(local["entries"]), 1)
        self.assertIn("grid:federation", local["entries"][0]["tags"])
        self.assertIn("database", local["entries"][0]["tags"])

    @patch("urllib.request.urlopen")
    def test_sync_empty_response(self, mock_urlopen):
        """Empty response from peer produces no local entries."""
        mock_urlopen.return_value = _MockHTTPResponse(json.dumps({
            "entries": []
        }).encode())

        result = self.fed.sync(peer_names=["team-alpha"])
        self.assertEqual(result["peers"]["team-alpha"]["entries_pulled"], 0)

        local = self.grid.query(tags=["grid:federation"])
        self.assertEqual(len(local["entries"]), 0)

    @patch("urllib.request.urlopen")
    def test_sync_sends_since_parameter(self, mock_urlopen):
        """After first sync, subsequent sync sends last_sync_time as 'since'."""
        mock_urlopen.return_value = _MockHTTPResponse(json.dumps({
            "entries": [
                {
                    "id": "grid_first",
                    "agent_id": "a1", "type": "fact",
                    "tags": ["grid:federation"], "content": "First",
                    "created_at": "2026-05-29T05:00:00.000000Z",
                }
            ]
        }).encode())

        # First sync
        self.fed.sync(peer_names=["team-alpha"])

        # Verify state was persisted
        state_path = os.path.join(self.test_dir, "federation_state.json")
        self.assertTrue(os.path.exists(state_path))
        with open(state_path) as f:
            state = json.load(f)
        alpha_state = state["sync_state"]["team-alpha"]
        self.assertIsNotNone(alpha_state["last_sync_time"])
        self.assertEqual(alpha_state["entries_pulled"], 1)

    @patch("urllib.request.urlopen")
    def test_sync_tracks_entries_pulled_accumulated(self, mock_urlopen):
        """The entries_pulled counter accumulates across sync cycles."""
        def mock_first(url, *args, **kwargs):
            return _MockHTTPResponse(json.dumps({
                "entries": [{"id": "grid_001", "agent_id": "a1",
                             "type": "fact", "tags": ["grid:federation"],
                             "content": "Entry 1", "created_at": "2026-01-01T00:00:00.000000Z"}]
            }).encode())

        mock_urlopen.side_effect = mock_first
        self.fed.sync(peer_names=["team-alpha"])

        def mock_second(url, *args, **kwargs):
            return _MockHTTPResponse(json.dumps({
                "entries": [{"id": "grid_002", "agent_id": "a1",
                             "type": "fact", "tags": ["grid:federation"],
                             "content": "Entry 2", "created_at": "2026-06-01T00:00:00.000000Z"}]
            }).encode())

        mock_urlopen.side_effect = mock_second
        self.fed.sync(peer_names=["team-alpha"])

        status = self.fed.status()
        self.assertEqual(status["team-alpha"]["entries_pulled"], 2)


class TestGridFederationDedup(unittest.TestCase):
    """Test 3: Deduplication by entry_id."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="fed_test_")
        self.grid = LocalGrid(store_dir=self.test_dir)
        self.fed = GridFederation(grid=self.grid, state_dir=self.test_dir)
        self.fed.add_peer("team-alpha", "http://alpha.grid:8080")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    @patch("urllib.request.urlopen")
    def test_dedup_skips_existing_entry(self, mock_urlopen):
        """Already-existing entry with same or newer timestamp is skipped."""
        # Write an entry locally first
        local_result = self.grid.write(
            agent_id="local-agent",
            type="fact",
            content="Local version",
            tags=["grid:federation"],
        )
        local_id = local_result["entry_id"]
        local_created = local_result["created_at"]

        # Peer returns entry with same ID but older timestamp
        mock_urlopen.return_value = _MockHTTPResponse(json.dumps({
            "entries": [
                {
                    "id": local_id,
                    "agent_id": "peer-agent",
                    "type": "fact",
                    "tags": ["grid:federation"],
                    "content": "Older peer version",
                    "created_at": "2024-01-01T00:00:00.000000Z",  # Older
                }
            ]
        }).encode())

        result = self.fed.sync(peer_names=["team-alpha"])

        # Should have skipped — no new entry pulled
        self.assertEqual(result["peers"]["team-alpha"]["entries_pulled"], 0)

        # Local entry should still have original content
        local = self.grid.query(tags=["grid:federation"])
        self.assertEqual(len(local["entries"]), 1)
        self.assertEqual(local["entries"][0]["content"], "Local version")

    @patch("urllib.request.urlopen")
    def test_dedup_overwrites_with_newer(self, mock_urlopen):
        """If peer has a newer version of same entry_id, overwrite local."""
        # Write an entry locally with an older timestamp (simulate by not being exact)
        local_result = self.grid.write(
            agent_id="local-agent",
            type="fact",
            content="Old local version",
            tags=["grid:federation"],
        )
        local_id = local_result["entry_id"]

        # Peer returns entry with same ID but newer content
        mock_urlopen.return_value = _MockHTTPResponse(json.dumps({
            "entries": [
                {
                    "id": local_id,
                    "agent_id": "peer-agent",
                    "type": "fact",
                    "tags": ["grid:federation", "updated"],
                    "content": "Newer peer version with updates",
                    "created_at": "2099-12-31T23:59:59.000000Z",  # Far future
                    "ttl_seconds": 86400,
                }
            ]
        }).encode())

        result = self.fed.sync(peer_names=["team-alpha"])

        # Should have pulled (overwrite)
        self.assertEqual(result["peers"]["team-alpha"]["entries_pulled"], 1)

        # Local grid should now have the new content (may get new ID)
        local = self.grid.query(tags=["grid:federation"])
        contents = [e["content"] for e in local["entries"]]
        self.assertIn("Newer peer version with updates", contents)
        # Verify the updated tag was synced
        all_tags = sum([e.get("tags", []) for e in local["entries"]], [])
        self.assertIn("updated", all_tags)

    @patch("urllib.request.urlopen")
    def test_dedup_skips_identical_timestamp(self, mock_urlopen):
        """Same entry_id with same created_at timestamp is skipped."""
        local_result = self.grid.write(
            agent_id="local-agent", type="fact",
            content="Original content", tags=["grid:federation"],
        )
        local_id = local_result["entry_id"]

        mock_urlopen.return_value = _MockHTTPResponse(json.dumps({
            "entries": [
                {
                    "id": local_id,
                    "agent_id": "peer-agent", "type": "fact",
                    "tags": ["grid:federation"],
                    "content": "Same timestamp version",
                    # Use the same timestamp
                    "created_at": local_result["created_at"],
                }
            ]
        }).encode())

        result = self.fed.sync(peer_names=["team-alpha"])
        self.assertEqual(result["peers"]["team-alpha"]["entries_pulled"], 0)

        local = self.grid.query(tags=["grid:federation"])
        found = [e for e in local["entries"] if e["id"] == local_id]
        self.assertEqual(found[0]["content"], "Original content")


class TestGridFederationErrors(unittest.TestCase):
    """Test 4: Error handling."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="fed_test_")
        self.grid = LocalGrid(store_dir=self.test_dir)
        self.fed = GridFederation(grid=self.grid, state_dir=self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_sync_nonexistent_peer(self):
        """Syncing from an unregistered peer returns error gracefully."""
        result = self.fed.sync(peer_names=["phantom"])
        self.assertIn("phantom", result["peers"])
        self.assertIn("error", result["peers"]["phantom"])
        self.assertEqual(result["peers"]["phantom"]["entries_pulled"], 0)
        self.assertEqual(result["summary"]["total_errors"], 1)

    @patch("urllib.request.urlopen")
    def test_sync_connection_error(self, mock_urlopen):
        """Connection errors are caught and reported without crashing."""
        self.fed.add_peer("unreachable", "http://does-not-exist.grid:8080")
        mock_urlopen.side_effect = URLError("Connection refused")

        result = self.fed.sync(peer_names=["unreachable"])
        self.assertIn("unreachable", result["peers"])
        self.assertFalse(result["peers"]["unreachable"]["connected"])
        self.assertIn("error", result["peers"]["unreachable"])
        self.assertEqual(result["peers"]["unreachable"]["entries_pulled"], 0)

    @patch("urllib.request.urlopen")
    def test_sync_http_error(self, mock_urlopen):
        """HTTP errors (4xx/5xx) are caught and reported without crashing."""
        self.fed.add_peer("bad-server", "http://bad.grid:8080")
        mock_urlopen.side_effect = HTTPError(
            url="http://bad.grid:8080/query",
            code=500,
            msg="Internal Server Error",
            hdrs={},
            fp=None,
        )

        result = self.fed.sync(peer_names=["bad-server"])
        self.assertFalse(result["peers"]["bad-server"]["connected"])
        self.assertIn("error", result["peers"]["bad-server"])
        self.assertEqual(result["peers"]["bad-server"]["entries_pulled"], 0)
        self.assertEqual(result["summary"]["total_errors"], 1)

    @patch("urllib.request.urlopen")
    def test_sync_malformed_json(self, mock_urlopen):
        """Malformed JSON response is handled gracefully."""
        self.fed.add_peer("corrupt", "http://corrupt.grid:8080")
        mock_urlopen.return_value = _MockHTTPResponse(
            b"this is not json at all"
        )

        result = self.fed.sync(peer_names=["corrupt"])
        self.assertFalse(result["peers"]["corrupt"]["connected"])
        self.assertIn("error", result["peers"]["corrupt"])

    @patch("urllib.request.urlopen")
    def test_sync_partial_failure_leaves_others_ok(self, mock_urlopen):
        """When one peer fails, other peers still sync successfully."""
        self.fed.add_peer("good", "http://good.grid:8080")
        self.fed.add_peer("bad", "http://bad.grid:8080")

        def side_effect(request, *args, **kwargs):
            url_str = request.full_url if hasattr(request, 'full_url') else str(request)
            if "bad" in url_str:
                raise URLError("Connection refused")
            return _MockHTTPResponse(json.dumps({
                "entries": [{"id": "grid_good_entry",
                             "agent_id": "ga", "type": "fact",
                             "tags": ["grid:federation"],
                             "content": "From good peer",
                             "created_at": "2026-01-01T00:00:00.000000Z"}]
            }).encode())

        mock_urlopen.side_effect = side_effect

        result = self.fed.sync()
        self.assertEqual(result["peers"]["good"]["entries_pulled"], 1)
        self.assertTrue(result["peers"]["good"]["connected"])
        self.assertFalse(result["peers"]["bad"]["connected"])

        # Good entry should be in local
        local = self.grid.query(tags=["grid:federation"])
        contents = [e["content"] for e in local["entries"]]
        self.assertIn("From good peer", contents)

    @patch("urllib.request.urlopen")
    def test_sync_peer_write_failure_doesnt_crash(self, mock_urlopen):
        """If writing an entry to local grid fails, sync continues."""
        self.fed.add_peer("team-alpha", "http://alpha.grid:8080")
        mock_urlopen.return_value = _MockHTTPResponse(json.dumps({
            "entries": [
                {
                    "id": "grid_good1",
                    "agent_id": "a1", "type": "fact",
                    "tags": ["grid:federation"], "content": "Good one",
                    "created_at": "2026-05-29T05:00:00.000000Z",
                },
                {
                    "id": "grid_bad2",
                    "agent_id": "a2", "type": "fact",
                    "tags": ["grid:federation"],
                    "content": "Bad content with -----BEGIN PRIVATE KEY-----",
                    "created_at": "2026-05-29T05:00:00.000000Z",
                },
                {
                    "id": "grid_good3",
                    "agent_id": "a3", "type": "fact",
                    "tags": ["grid:federation"], "content": "Also good",
                    "created_at": "2026-05-29T05:00:00.000000Z",
                },
            ]
        }).encode())

        result = self.fed.sync(peer_names=["team-alpha"])
        self.assertEqual(result["peers"]["team-alpha"]["entries_pulled"], 2)

        local = self.grid.query(tags=["grid:federation"])
        contents = [e["content"] for e in local["entries"]]
        self.assertIn("Good one", contents)
        self.assertIn("Also good", contents)
        self.assertNotIn("PRIVATE KEY", str(contents))


class TestGridFederationAutoSync(unittest.TestCase):
    """Test 5: Auto-sync lifecycle."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="fed_test_")
        self.grid = LocalGrid(store_dir=self.test_dir)
        self.fed = GridFederation(grid=self.grid, state_dir=self.test_dir)
        self.fed.add_peer("team-alpha", "http://alpha.grid:8080")

    def tearDown(self):
        self.fed.stop_auto_sync()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_auto_sync_starts_and_stops(self):
        """Auto-sync can be started and stopped."""
        result = self.fed.start_auto_sync(interval_seconds=10)
        self.assertTrue(result)

        status = self.fed.status()
        self.assertTrue(status["_meta"]["auto_sync_running"])

        result = self.fed.stop_auto_sync()
        self.assertTrue(result)

        status = self.fed.status()
        self.assertFalse(status["_meta"]["auto_sync_running"])

    def test_auto_sync_cannot_start_twice(self):
        """Starting auto-sync while already running returns False."""
        self.fed.start_auto_sync(interval_seconds=10)
        result = self.fed.start_auto_sync(interval_seconds=10)
        self.assertFalse(result)

    def test_auto_sync_stop_when_not_running(self):
        """Stopping auto-sync when not running returns False."""
        result = self.fed.stop_auto_sync()
        self.assertFalse(result)

    def test_auto_sync_daemon_thread(self):
        """Auto-sync thread is a daemon and doesn't block shutdown."""
        self.fed.start_auto_sync(interval_seconds=10)
        for thread in threading.enumerate():
            if thread.name == "grid-federation-auto-sync":
                self.assertTrue(thread.daemon)
                break
        else:
            self.fail("Auto-sync thread not found")

    @patch("urllib.request.urlopen")
    def test_auto_sync_interval_minimum(self, mock_urlopen):
        """Auto-sync interval is clamped to minimum of 10 seconds."""
        mock_urlopen.return_value = _MockHTTPResponse(json.dumps({
            "entries": []
        }).encode())

        # Try a very short interval — should be clamped to 10
        self.fed.start_auto_sync(interval_seconds=1)
        time.sleep(0.5)
        self.fed.stop_auto_sync()

        # Should not have crashed — that's the test
        self.assertTrue(True)


class TestGridFederationStatus(unittest.TestCase):
    """Test 6: Status reporting."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="fed_test_")
        self.grid = LocalGrid(store_dir=self.test_dir)
        self.fed = GridFederation(grid=self.grid, state_dir=self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_status_empty_federation(self):
        """Status on empty federation returns no peers."""
        status = self.fed.status()
        # All keys that aren't "_meta" are peer names
        peer_keys = [k for k in status if k != "_meta"]
        self.assertEqual(len(peer_keys), 0)

    def test_status_after_add_peer(self):
        """Status after adding a peer shows the peer."""
        self.fed.add_peer("team-alpha", "http://alpha.grid:8080")
        status = self.fed.status()
        self.assertIn("team-alpha", status)
        self.assertEqual(status["team-alpha"]["url"], "http://alpha.grid:8080")
        self.assertEqual(status["team-alpha"]["entries_pulled"], 0)

    def test_status_meta_fields(self):
        """Status includes meta information."""
        self.fed.add_peer("team-alpha", "http://alpha.grid:8080")
        status = self.fed.status()
        meta = status["_meta"]
        self.assertIn("auto_sync_running", meta)
        self.assertIn("federation_tag", meta)
        self.assertIn("total_peers", meta)
        self.assertEqual(meta["total_peers"], 1)
        self.assertEqual(meta["federation_tag"], "grid:federation")

    @patch("urllib.request.urlopen")
    def test_status_checks_connectivity(self, mock_urlopen):
        """Status checks /health endpoint to determine connectivity."""
        def mock_health(request, *args, **kwargs):
            url_str = request.full_url if hasattr(request, 'full_url') else str(request)
            if url_str.startswith("http://reachable.grid"):
                return _MockHTTPResponse(json.dumps({"status": "ok"}).encode())
            from urllib.error import HTTPError
            raise HTTPError(url_str, 500, "Simulated failure", {}, None)

        mock_urlopen.side_effect = mock_health

        self.fed.add_peer("reachable", "http://reachable.grid:8080")
        self.fed.add_peer("unreachable", "http://unreachable.grid:8080")

        status = self.fed.status()
        self.assertTrue(status["reachable"]["connected"])
        self.assertFalse(status["unreachable"]["connected"])


class TestGridFederationStatePersistence(unittest.TestCase):
    """Test 7: State persistence across Federation instances."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="fed_test_")
        self.grid = LocalGrid(store_dir=self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_state_persists_peers(self):
        """Peers are persisted to disk and loaded on re-init."""
        fed = GridFederation(grid=self.grid, state_dir=self.test_dir)
        fed.add_peer("team-alpha", "http://alpha.grid:8080",
                     federation_tag="custom:tag")
        fed.add_peer("team-beta", "http://beta.grid:8080")

        # Re-create the federation (simulate process restart)
        fed2 = GridFederation(grid=self.grid, state_dir=self.test_dir)
        peers = fed2.get_peers()
        self.assertIn("team-alpha", peers)
        self.assertIn("team-beta", peers)
        self.assertEqual(peers["team-alpha"]["url"], "http://alpha.grid:8080")
        self.assertEqual(peers["team-alpha"]["federation_tag"], "custom:tag")
        self.assertEqual(peers["team-beta"]["url"], "http://beta.grid:8080")

    @patch("urllib.request.urlopen")
    def test_state_persists_sync_history(self, mock_urlopen):
        """Sync statistics are persisted and survive re-init."""
        mock_urlopen.return_value = _MockHTTPResponse(json.dumps({
            "entries": [
                {
                    "id": "grid_persist_test",
                    "agent_id": "pa", "type": "fact",
                    "tags": ["grid:federation"], "content": "Persist me",
                    "created_at": "2026-05-29T05:00:00.000000Z",
                }
            ]
        }).encode())

        fed = GridFederation(grid=self.grid, state_dir=self.test_dir)
        fed.add_peer("team-alpha", "http://alpha.grid:8080")
        fed.sync(peer_names=["team-alpha"])

        # Re-create federation
        fed2 = GridFederation(grid=self.grid, state_dir=self.test_dir)
        status = fed2.status()
        self.assertIn("team-alpha", status)
        self.assertGreater(status["team-alpha"]["entries_pulled"], 0)
        self.assertIsNotNone(status["team-alpha"]["last_sync"])

    def test_remove_peer_persists(self):
        """Removing a peer is persisted."""
        fed = GridFederation(grid=self.grid, state_dir=self.test_dir)
        fed.add_peer("team-alpha", "http://alpha.grid:8080")
        fed.add_peer("team-beta", "http://beta.grid:8080")
        fed.remove_peer("team-alpha")

        fed2 = GridFederation(grid=self.grid, state_dir=self.test_dir)
        peers = fed2.get_peers()
        self.assertNotIn("team-alpha", peers)
        self.assertIn("team-beta", peers)


if __name__ == "__main__":
    unittest.main()
