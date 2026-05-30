"""
federation.py — Grid Federation Module

Allows multiple Grid instances to sync with each other as peers.
- Each Grid can act as a "peer" connecting to other Grids via HTTP.
- Peers share entries tagged with "grid:federation" (configurable).
- Sync is pull-based: each Grid periodically fetches new entries from peers.
- Conflict resolution: same entry_id wins on most recent created_at.
- Entries synced from peers get a special "grid:federation" tag for filtering.

Usage:
    from grid_memory.federation import GridFederation
    from grid_memory import LocalGrid

    grid = LocalGrid()
    fed = GridFederation(grid=grid)

    # Register a peer
    fed.add_peer("team-sf", "http://sf-grid.internal:8080")

    # Manual sync
    fed.sync()

    # Or start background sync
    fed.start_auto_sync(interval_seconds=60)

    # Status
    status = fed.status()
"""

import datetime
import hashlib
import hmac
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from grid_memory.local_grid import LocalGrid


__all__ = ["GridFederation"]


# ─── HMAC-SHA256 Signing (mirrors Node.js federation.js) ───────────────────────

def sign_request(body: str, secret: str) -> tuple:
    """
    Sign a request body with HMAC-SHA256 using the shared secret.
    
    Args:
        body: The request body as a string
        secret: Shared secret string
    
    Returns:
        Tuple of (signature_hex, timestamp_str)
    """
    timestamp = str(int(time.time()))
    payload = timestamp + "." + body
    sig = hmac.new(
        secret.encode('utf-8'),
        payload.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return sig, timestamp


def verify_request_signature(body: str, signature: str, timestamp: str, secret: str) -> dict:
    """
    Verify an incoming HMAC-SHA256 signature.
    
    Args:
        body: The request body as a string
        signature: The hex HMAC signature from the X-Grid-Signature header
        timestamp: The timestamp from the X-Grid-Timestamp header
        secret: The peer's shared secret
    
    Returns:
        dict with {"valid": bool, "reason": str}
    """
    if not secret or not signature or not timestamp:
        return {"valid": False, "reason": "Missing signature data"}
    
    payload = timestamp + "." + body
    expected = hmac.new(
        secret.encode('utf-8'),
        payload.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    
    # Constant-time comparison
    if len(expected) != len(signature):
        return {"valid": False, "reason": "Signature length mismatch"}
    
    # Use hmac.compare_digest for constant-time comparison
    if not hmac.compare_digest(expected, signature):
        return {"valid": False, "reason": "Signature mismatch"}
    
    # Reject signatures older than 5 minutes
    now_ts = int(time.time())
    try:
        sig_ts = int(timestamp)
    except ValueError:
        return {"valid": False, "reason": "Invalid timestamp"}
    
    if now_ts - sig_ts > 300:
        return {"valid": False, "reason": "Signature expired"}
    
    return {"valid": True}


def validate_incoming_request(headers: dict, raw_body: str, peers: dict) -> dict:
    """
    Validate an incoming request's signature against all registered peers.
    
    Args:
        headers: Request headers dict (should include x-grid-signature, x-grid-timestamp)
        raw_body: Raw request body string
        peers: Dict of peer_name -> PeerConfig
    
    Returns:
        dict with {"valid": bool, "peer": str or None, "reason": str or None}
    """
    # Normalize header keys to lowercase
    sig_headers = {k.lower(): v for k, v in headers.items()}
    signature = sig_headers.get('x-grid-signature')
    timestamp = sig_headers.get('x-grid-timestamp')
    
    if not signature or not timestamp:
        return {"valid": False, "reason": "No signature provided", "peer": None}
    
    for name, cfg in peers.items():
        secret = getattr(cfg, 'shared_secret', None) or getattr(cfg, 'sharedSecret', None)
        if not secret:
            continue
        body = raw_body if raw_body is not None else ''
        result = verify_request_signature(body, signature, timestamp, secret)
        if result.get("valid"):
            trust = getattr(cfg, 'trust_level', None) or getattr(cfg, 'trustLevel', 'unverified')
            return {"valid": True, "peer": name, "trust_level": trust}
    
    return {"valid": False, "reason": "No matching peer found for signature", "peer": None}

logger = logging.getLogger("grid.federation")

_DEFAULT_FEDERATION_TAG = "grid:federation"
_DEFAULT_STATE_FILE = "federation_state.json"


class PeerConfig:
    """Configuration for a single peer in the federation.

    Args:
        name: Human-readable peer name (used as identifier)
        url: Base URL of the peer's Grid HTTP API
        federation_tag: Tag used to filter entries shared by this peer
        timeout_seconds: HTTP request timeout for this peer
    """

    def __init__(self, name: str, url: str,
                 federation_tag: str = _DEFAULT_FEDERATION_TAG,
                 timeout_seconds: int = 10):
        self.name = name
        self.url = url.rstrip("/")
        self.federation_tag = federation_tag
        self.timeout_seconds = timeout_seconds

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "url": self.url,
            "federation_tag": self.federation_tag,
            "timeout_seconds": self.timeout_seconds,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "PeerConfig":
        return cls(
            name=data["name"],
            url=data["url"],
            federation_tag=data.get("federation_tag", _DEFAULT_FEDERATION_TAG),
            timeout_seconds=data.get("timeout_seconds", 10),
        )


class GridFederation:
    """Federation layer for syncing entries between Grid instances.

    Each Grid instance can be registered as a peer. Sync is pull-based:
    the local Grid queries each peer for entries tagged with the federation
    tag that were created after the last successful sync time.

    Conflict resolution: If the same entry_id already exists locally,
    the newer created_at wins (the entry is overwritten).

    Args:
        grid: LocalGrid instance to sync entries into
        state_dir: Directory for persisting sync state (default: grid's store_dir)
        federation_tag: Tag applied to all synced entries (default: "grid:federation")
    """

    def __init__(self, grid: LocalGrid,
                 state_dir: Optional[str] = None,
                 federation_tag: str = _DEFAULT_FEDERATION_TAG):
        self._grid = grid
        self._federation_tag = federation_tag

        # Determine state directory — use grid's store_dir if not specified
        if state_dir:
            self._state_dir = state_dir
        else:
            # Read the grid's store_dir (private attribute, fallback to default)
            self._state_dir = getattr(grid, "_store_dir", None) or _default_store_dir()

        # Ensure state directory exists
        Path(self._state_dir).mkdir(parents=True, exist_ok=True)

        # Peer registry: name -> PeerConfig
        self._peers: Dict[str, PeerConfig] = {}

        # Sync state: peer_name -> {last_sync_time (ISO), entries_pulled (int)}
        self._sync_state: Dict[str, Dict] = {}

        # Load persisted state
        self._load_state()

        # Auto-sync thread control
        self._auto_sync_thread: Optional[threading.Thread] = None
        self._auto_sync_stop = threading.Event()

        # Track existing entry_ids locally for dedup
        self._local_entry_ids: Set[str] = set()
        self._refresh_local_ids()

        logger.info("GridFederation initialized (state_dir=%s, tag=%s)",
                     self._state_dir, self._federation_tag)

    # ── State Persistence ──────────────────────────────────────────────────────

    def _state_path(self) -> str:
        return os.path.join(self._state_dir, _DEFAULT_STATE_FILE)

    def _save_state(self):
        """Persist sync state to disk."""
        data = {
            "federation_tag": self._federation_tag,
            "peers": {name: cfg.to_dict() for name, cfg in self._peers.items()},
            "sync_state": {
                peer: {
                    "last_sync_time": state.get("last_sync_time"),
                    "entries_pulled": state.get("entries_pulled", 0),
                }
                for peer, state in self._sync_state.items()
            },
            "updated_at": _now_iso(),
        }
        try:
            with open(self._state_path(), "w") as f:
                json.dump(data, f, indent=2)
        except IOError as e:
            logger.error("Failed to save federation state: %s", e)

    def _load_state(self):
        """Load persisted sync state from disk."""
        path = self._state_path()
        if not os.path.exists(path):
            return
        try:
            with open(path, "r") as f:
                data = json.load(f)
            # Restore peers
            for name, cfg_data in data.get("peers", {}).items():
                self._peers[name] = PeerConfig.from_dict(cfg_data)
            # Restore sync state
            for peer, state in data.get("sync_state", {}).items():
                self._sync_state[peer] = {
                    "last_sync_time": state.get("last_sync_time"),
                    "entries_pulled": state.get("entries_pulled", 0),
                }
            logger.info("Loaded federation state: %d peers, %d with sync history",
                        len(self._peers), len(self._sync_state))
        except (IOError, json.JSONDecodeError) as e:
            logger.warning("Could not load federation state: %s", e)

    # ── Local Entry ID Cache ───────────────────────────────────────────────────

    def _refresh_local_ids(self):
        """Refresh the set of entry_ids known locally."""
        info = self._grid.info()
        # Query all alive entries
        result = self._grid.query(max=50)
        ids = set()
        for entry in result.get("entries", []):
            ids.add(entry["id"])
        self._local_entry_ids = ids

    # ── Peer Management ────────────────────────────────────────────────────────

    def add_peer(self, name: str, url: str,
                 federation_tag: Optional[str] = None,
                 timeout_seconds: int = 10) -> bool:
        """Register a new peer for federation.

        Args:
            name: Human-readable peer name (must be unique)
            url: Base URL of the peer's Grid HTTP API
            federation_tag: Override the federation tag for this peer
                            (defaults to instance-level tag)
            timeout_seconds: HTTP request timeout

        Returns:
            True if added, False if already exists
        """
        if name in self._peers:
            logger.warning("Peer '%s' already registered", name)
            return False

        cfg = PeerConfig(
            name=name,
            url=url,
            federation_tag=federation_tag or self._federation_tag,
            timeout_seconds=timeout_seconds,
        )
        self._peers[name] = cfg

        # Initialize sync state if not present
        if name not in self._sync_state:
            self._sync_state[name] = {
                "last_sync_time": None,
                "entries_pulled": 0,
            }

        self._save_state()
        logger.info("Added peer '%s' at %s (tag=%s)", name, url, cfg.federation_tag)
        return True

    def remove_peer(self, name: str) -> bool:
        """Remove a registered peer.

        Args:
            name: Peer name to remove

        Returns:
            True if removed, False if not found
        """
        if name not in self._peers:
            logger.warning("Peer '%s' not found, cannot remove", name)
            return False

        del self._peers[name]
        self._sync_state.pop(name, None)
        self._save_state()
        logger.info("Removed peer '%s'", name)
        return True

    def get_peers(self) -> Dict[str, Dict]:
        """Get all registered peers and their configs."""
        return {name: cfg.to_dict() for name, cfg in self._peers.items()}

    # ── Core Sync Engine ───────────────────────────────────────────────────────

    def sync(self, peer_names: Optional[List[str]] = None) -> Dict:
        """Pull new entries from registered peers.

        Queries each peer's GET /query endpoint with:
          ?since={last_sync_time}&tags={federation_tag}

        New entries are written to the local Grid with the federation tag.
        Duplicates are skipped (same entry_id already exists locally).
        Conflicts (same entry_id, newer data) overwrite.

        Args:
            peer_names: Optional list of peer names to sync from.
                        If None, syncs from all registered peers.

        Returns:
            Dict with per-peer results and overall summary.
        """
        targets = peer_names or list(self._peers.keys())
        peer_results: Dict[str, Dict] = {}
        total_pulled = 0
        total_errors = 0

        # Refresh local entry IDs to ensure accurate dedup
        self._refresh_local_ids()

        for peer_name in targets:
            if peer_name not in self._peers:
                peer_results[peer_name] = {
                    "error": f"Peer '{peer_name}' not registered",
                    "entries_pulled": 0,
                }
                total_errors += 1
                continue

            cfg = self._peers[peer_name]
            state = self._sync_state.get(peer_name, {})
            last_sync = state.get("last_sync_time")
            current_entries_pulled = state.get("entries_pulled", 0)

            try:
                entries, pulled = self._sync_from_peer(cfg, last_sync)
                self._sync_state[peer_name] = {
                    "last_sync_time": _now_iso(),
                    "entries_pulled": current_entries_pulled + pulled,
                }
                peer_results[peer_name] = {
                    "connected": True,
                    "entries_pulled": pulled,
                    "last_sync": _now_iso(),
                }
                total_pulled += pulled
            except Exception as e:
                logger.error("Sync from peer '%s' failed: %s", peer_name, e)
                peer_results[peer_name] = {
                    "connected": False,
                    "error": str(e),
                    "entries_pulled": 0,
                    "last_sync": last_sync,
                }
                total_errors += 1

        self._save_state()
        self._refresh_local_ids()

        return {
            "peers": peer_results,
            "summary": {
                "total_peers_synced": len(targets),
                "total_entries_pulled": total_pulled,
                "total_errors": total_errors,
                "synced_at": _now_iso(),
            },
        }

    def _sync_from_peer(self, cfg: PeerConfig,
                        last_sync: Optional[str]) -> Tuple[List[Dict], int]:
        """Execute a single peer sync: fetch entries and write them locally.

        Args:
            cfg: Peer configuration
            last_sync: ISO timestamp of last successful sync (None for initial)

        Returns:
            Tuple of (entries_received, entries_new_written)
        """
        # Build the query URL
        params: Dict[str, str] = {"tags": cfg.federation_tag}
        if last_sync:
            params["since"] = last_sync

        query_url = f"{cfg.url}/query?{urllib.parse.urlencode(params)}"

        logger.debug("Fetching from peer '%s': %s", cfg.name, query_url)

        # Build request with optional HMAC signing
        headers = {}
        secret = getattr(cfg, 'shared_secret', None) or getattr(cfg, 'sharedSecret', None)
        if secret:
            sig, ts = sign_request('', secret)
            headers['X-Grid-Signature'] = sig
            headers['X-Grid-Timestamp'] = ts

        # HTTP GET
        try:
            req = urllib.request.Request(query_url, headers=headers, method="GET")
            with urllib.request.urlopen(req, timeout=cfg.timeout_seconds) as resp:
                response_data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            raise PeerSyncError(
                f"HTTP {e.code} from {cfg.name}: {body}"
            )
        except urllib.error.URLError as e:
            raise PeerSyncError(
                f"Connection error for '{cfg.name}': {e.reason}"
            )
        except (json.JSONDecodeError, IOError) as e:
            raise PeerSyncError(
                f"Invalid response from '{cfg.name}': {e}"
            )

        entries = response_data.get("entries", [])
        if not entries:
            logger.debug("No new entries from peer '%s'", cfg.name)
            return [], 0

        # Write to local grid
        written_count = 0
        for entry in entries:
            eid = entry.get("id")
            created_at = entry.get("created_at")

            # Ensure it has the federation tag
            tags = list(entry.get("tags", []))
            if cfg.federation_tag not in tags:
                tags.append(cfg.federation_tag)

            # Deduplication check: if same entry_id exists locally, compare timestamps
            if eid in self._local_entry_ids:
                # Conflict: check if the peer's version is newer
                existing = self._find_local_entry(eid)
                if existing:
                    existing_created = existing.get("created_at", "")
                    if existing_created and created_at and created_at <= existing_created:
                        # Our version is same age or newer — skip
                        logger.debug("Skipping entry %s (local is newer or equal)", eid)
                        continue

                # Newer version from peer — forget local and re-write
                try:
                    self._grid.forget(eid)
                    self._local_entry_ids.discard(eid)
                except Exception:
                    # If forget fails (e.g. backend), overwrite in place by
                    # removing from our tracking set
                    logger.warning("Could not forget local entry %s, overwriting", eid)
                    self._local_entry_ids.discard(eid)

            # Write the entry to local grid
            try:
                result = self._grid.write(
                    agent_id=entry.get("agent_id", "federation"),
                    type=entry.get("type", "observation"),
                    content=entry.get("content", ""),
                    tags=tags,
                    ttl_seconds=entry.get("ttl_seconds"),
                    session_id=entry.get("session_id", ""),
                    parent_entry=entry.get("parent_entry"),
                )
                self._local_entry_ids.add(result["entry_id"])
                written_count += 1
            except Exception as e:
                logger.warning("Failed to write synced entry %s: %s", eid, e)
                # Continue with next entry
                continue

        logger.info("Synced %d new entries from peer '%s'", written_count, cfg.name)
        return entries, written_count

    def _find_local_entry(self, entry_id: str) -> Optional[Dict]:
        """Find a local entry by ID. Returns None if not found."""
        # Query for the specific entry using the query API (no direct get by ID)
        result = self._grid.query(max=50)
        for entry in result.get("entries", []):
            if entry["id"] == entry_id:
                return entry
        return None

    # ── Auto-Sync ──────────────────────────────────────────────────────────────

    def start_auto_sync(self, interval_seconds: int = 60) -> bool:
        """Start background thread that periodically syncs from all peers.

        The thread runs as a daemon and will stop when the main process exits.

        Args:
            interval_seconds: Seconds between sync cycles (min: 10)

        Returns:
            True if started, False if already running
        """
        if self._auto_sync_thread and self._auto_sync_thread.is_alive():
            logger.warning("Auto-sync already running")
            return False

        interval = max(interval_seconds, 10)
        self._auto_sync_stop.clear()

        def _sync_loop():
            logger.info("Auto-sync started (interval=%ds)", interval)
            while not self._auto_sync_stop.is_set():
                try:
                    result = self.sync()
                    total = result["summary"]["total_entries_pulled"]
                    errors = result["summary"]["total_errors"]
                    if total > 0 or errors > 0:
                        logger.info("Auto-sync: %d entries pulled, %d errors",
                                    total, errors)
                except Exception as e:
                    logger.error("Auto-sync cycle failed: %s", e)
                # Sleep in intervals to allow clean shutdown
                for _ in range(interval):
                    if self._auto_sync_stop.is_set():
                        break
                    time.sleep(1)

            logger.info("Auto-sync stopped")

        self._auto_sync_thread = threading.Thread(
            target=_sync_loop,
            name="grid-federation-auto-sync",
            daemon=True,
        )
        self._auto_sync_thread.start()
        return True

    def stop_auto_sync(self) -> bool:
        """Stop the background auto-sync thread.

        Returns:
            True if stopped, False if not running
        """
        if not self._auto_sync_thread:
            return False

        self._auto_sync_stop.set()
        self._auto_sync_thread.join(timeout=5)
        # Always clear the thread reference regardless of clean exit
        was_alive = self._auto_sync_thread.is_alive() if hasattr(self._auto_sync_thread, 'is_alive') else False
        self._auto_sync_thread = None
        if was_alive:
            logger.warning("Auto-sync thread did not stop cleanly")
        return True

    # ── Status ─────────────────────────────────────────────────────────────────

    def status(self) -> Dict:
        """Get current federation status for all peers.

        Returns:
            Dict mapping peer names to their connection state and sync stats.
        """
        result: Dict[str, Dict] = {}
        for name, cfg in self._peers.items():
            state = self._sync_state.get(name, {})
            # Check basic connectivity by hitting health endpoint
            connected = False
            try:
                health_url = f"{cfg.url}/health"
                req = urllib.request.Request(health_url, method="GET")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status == 200:
                        connected = True
            except Exception:
                connected = False

            result[name] = {
                "connected": connected,
                "url": cfg.url,
                "entries_pulled": state.get("entries_pulled", 0),
                "last_sync": state.get("last_sync_time"),
            }

        # Add auto-sync info
        thread_alive = (self._auto_sync_thread is not None
                        and hasattr(self._auto_sync_thread, 'is_alive')
                        and self._auto_sync_thread.is_alive())
        result["_meta"] = {
            "auto_sync_running": thread_alive,
            "federation_tag": self._federation_tag,
            "total_peers": len(self._peers),
        }

        return result


class PeerSyncError(Exception):
    """Raised when syncing from a peer fails."""
    pass


# ─── Helpers ────────────────────────────────────────────────────────────────────


def _now_iso() -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}Z"


def _default_store_dir() -> str:
    return os.path.join(
        os.path.expanduser("~"),
        ".openclaw", "workspace", "skills", "shared-memory-grid", "data"
    )
