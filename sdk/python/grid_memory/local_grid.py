"""
local_grid.py - Embedded Grid Memory Engine

Pure Python, zero dependencies (stdlib only). Full clone of the Node.js store.js.
Operates without any server - just pip install and use.

Usage:
    from grid_memory import LocalGrid

    grid = LocalGrid()

    # Write
    entry = grid.fact("PostgreSQL pool: 25", tags=["database"], agent_id="architect")
    grid.decide("Use Express over Fastify", tags=["architecture"],
                rationale="Better middleware ecosystem", agent_id="architect")

    # Query
    results = grid.query(tags=["database"])
    block = grid.inject("building the API layer")

    # Admin
    info = grid.info()
    grid.prune()
    grid.forget(entry["entry_id"])

CLI:
    python -m grid_memory.local_grid write --agent main --type decision --content "..."
    python -m grid_memory.local_grid query --tags database
    python -m grid_memory.local_grid inject --context "hello"
    python -m grid_memory.local_grid info
"""

import datetime
import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Callable


__all__ = ["LocalGrid"]

# Conditional import for embeddings
_EMBEDDINGS_AVAILABLE = False
try:
    from grid_memory.embeddings import EmbeddingEngine, cosine_similarity
    _EMBEDDINGS_AVAILABLE = True
except ImportError:
    pass


# ─── Utilities ──────────────────────────────────────────────────────────────────


def _generate_id() -> str:
    date_part = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
    random_part = hashlib.sha256(os.urandom(16)).hexdigest()[:12]
    return f"grid_{date_part}_{random_part}"


def _now_iso() -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}Z"


def _now_unix() -> int:
    return int(time.time())


# Default store directory
_DEFAULT_STORE_DIR = os.path.join(
    os.path.expanduser("~"),
    ".openclaw", "workspace", "skills", "shared-memory-grid", "data"
)


# ─── Configuration ──────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "MAX_INJECT_SIZE": 4096,
    "DEFAULT_MAX_RESULTS": 10,
    "ABSOLUTE_MAX_RESULTS": 50,
    "MAX_STORE_SIZE_MB": 10,
    "COMPRESSION_THRESHOLD_MB": 5,
    "DEFAULT_TTLS": {
        "decision": 86400,
        "fact": 86400,
        "task_status": 3600,
        "artifact_ref": 604800,
        "handoff": 3600,
        "question": 43200,
        "observation": 86400,
        "blocker": 86400,
        "state_update": 3600,
        "opportunity": 604800,
        "lesson": 604800,
    },
    "VALID_TYPES": [
        "decision", "fact", "task_status", "artifact_ref",
        "handoff", "question", "observation", "blocker", "state_update",
        "opportunity",
        "lesson",
        "pattern",
        "playbook",
        "accelerator",
        "engagement"
    ],
    # Memory tiers (working → project → organization)
    "MEMORY_TIERS": ["working", "project", "organization"],
    "DEFAULT_TIER": "working",
    # TTL overrides per tier (overrides DEFAULT_TTLS when set)
    "TIER_TTLS": {
        "working": None,       # uses DEFAULT_TTLS
        "project": 604800,     # 7 days
        "organization": None,  # no expiry
    },
    # Promotion thresholds
    "PROMOTION_READ_THRESHOLD": 5,       # min reads to consider promotion
    "PROMOTION_RELEVANCE_THRESHOLD": 7,  # min average relevance score
    "PROMOTION_HANDOFF_COUNT": 3,        # references from other entries
}

TIER_ICONS = {
    "working": "\u26a1",       # ⚡
    "project": "\U0001f4e6",    # 📦
    "organization": "\U0001f3f0", # 🏰
}

# Secret patterns that must not be stored
_SECRET_PATTERNS = [
    re.compile(r"PRIVATE_KEY", re.IGNORECASE),
    re.compile(r"-----BEGIN.*PRIVATE KEY-----"),
    re.compile(r"ghp_[a-zA-Z0-9]{36}"),
    re.compile(r"sk-[a-zA-Z0-9]{32,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
]


# ─── The Grid Engine ────────────────────────────────────────────────────────────


class LocalGrid:
    """Embedded shared memory grid - no server required.

    Pure Python, zero dependencies. Mirrors the Node.js store.js API.

    Args:
        store_dir: Directory for store.json and index.json files.
                   Defaults to ~/.openclaw/workspace/skills/shared-memory-grid/data/
        config: Override default configuration values.
    """

    def __init__(self, store_dir: Optional[str] = None,
                 config: Optional[Dict] = None,
                 embedding_engine: Optional[Any] = None,
                 backend: Optional[Any] = None):
        self._config = {**DEFAULT_CONFIG, **(config or {})}
        self._store_dir = store_dir or os.environ.get(
            "GRID_STORE_DIR", _DEFAULT_STORE_DIR
        )
        self._embedding_engine = embedding_engine
        self._backend = backend
        self._store_path = os.path.join(self._store_dir, "store.json")
        self._index_path = os.path.join(self._store_dir, "index.json")
        self._store: Optional[Dict] = None
        self._index: Optional[Dict] = None
        if backend is None:
            self._ensure_dir()

    # ── Initialization ──

    def _ensure_dir(self):
        if self._backend:
            return
        Path(self._store_dir).mkdir(parents=True, exist_ok=True)

    def _load_store(self) -> Dict:
        if self._backend:
            return self._store or {"version": 1, "created_at": _now_iso(), "entries": [], "entries_cache": None}
        if os.path.exists(self._store_path):
            try:
                with open(self._store_path, "r") as f:
                    raw = json.load(f)
                # Migrate v0 → v1 if needed
                if isinstance(raw, list):
                    raw = {
                        "version": 1,
                        "created_at": _now_iso(),
                        "entries": raw,
                    }
                self._store = raw
            except (json.JSONDecodeError, IOError):
                backup = f"{self._store_path}.corrupt.{_now_unix()}"
                import warnings
                warnings.warn(f"[Grid] Store corruption detected. Backing up to {backup}")
                if os.path.exists(self._store_path):
                    shutil.copy2(self._store_path, backup)
                self._store = {
                    "version": 1,
                    "created_at": _now_iso(),
                    "entries": [],
                    "_recovered_from": backup,
                }
        else:
            self._store = {
                "version": 1,
                "created_at": _now_iso(),
                "entries": [],
            }
        return self._store

    def _load_index(self) -> Dict:
        if os.path.exists(self._index_path):
            try:
                with open(self._index_path, "r") as f:
                    self._index = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._index = {"version": 1, "tags": {}, "agents": {}, "types": {}}
        else:
            self._index = {"version": 1, "tags": {}, "agents": {}, "types": {}}
        return self._index

    def _save_store(self):
        with open(self._store_path, "w") as f:
            json.dump(self._store, f, indent=2)

    def _save_index(self):
        with open(self._index_path, "w") as f:
            json.dump(self._index, f, indent=2)

    def _rebuild_index(self):
        index: Dict = {"version": 1, "tags": {}, "agents": {}, "types": {}}
        for entry in self._store["entries"]:
            for tag in entry.get("tags", []):
                index["tags"].setdefault(tag, []).append(entry["id"])
            if entry.get("agent_id"):
                index["agents"].setdefault(entry["agent_id"], []).append(entry["id"])
            if entry.get("type"):
                index["types"].setdefault(entry["type"], []).append(entry["id"])
        self._index = index
        self._save_index()

    # ── Validation ──

    def _validate_write(self, write: Dict):
        assert write.get("agent_id"), "[Grid] agent_id is required"
        assert write.get("content"), "[Grid] content is required"
        assert isinstance(write["content"], str), "[Grid] content must be a string"
        wtype = write.get("type")
        if wtype:
            valid = self._config["VALID_TYPES"]
            assert wtype in valid, (
                f"[Grid] Invalid type '{wtype}'. Valid types: {', '.join(valid)}"
            )
        # Secret detection
        content = write["content"]
        for pat in _SECRET_PATTERNS:
            if pat.search(content):
                raise ValueError(
                    f"[Grid] Write rejected: content appears to contain a secret "
                    f"(matched: {pat.pattern})"
                )

    # ── Write ──

    def write(self, agent_id: str, type: str = "observation", content: str = "",
              tags: Optional[List[str]] = None,
              ttl_seconds: Optional[int] = None,
              session_id: Optional[str] = None,
              parent_entry: Optional[str] = None,
              memory_tier: Optional[str] = None,
              workspace_id: Optional[str] = None,
              force_id: Optional[str] = None,
              force_created_at: Optional[str] = None,
              force_expires_at: Optional[str] = None) -> Dict:
        """Write a generic entry to the Grid.

        Args:
            agent_id: Agent identifier
            type: Entry type (observation, decision, fact, handoff, etc.)
            content: Entry content
            tags: Optional list of tags
            ttl_seconds: Time-to-live in seconds
            session_id: Optional session identifier
            parent_entry: Optional parent entry ID

        Returns:
            Dict with entry_id, agent_id, type, tags, created_at, etc.
        """
        write_data = {
            "agent_id": agent_id,
            "content": content,
            "type": type,
        }
        if tags:
            write_data["tags"] = tags
        if ttl_seconds is not None:
            write_data["ttl_seconds"] = ttl_seconds

        self._validate_write(write_data)
        self._load_store()

        # If using a custom backend, delegate write
        if self._backend:
            ttl = (ttl_seconds if ttl_seconds is not None
                    else self._config["DEFAULT_TTLS"].get(type or "observation", 86400))
            now_iso = _now_iso()
            expires_dt = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=ttl)
            entry = {
                "id": force_id or _generate_id(),
                "session_id": session_id or "",
                "agent_id": agent_id,
                "type": type or "observation",
                "tags": tags or [],
                "content": content.strip(),
                "ttl_seconds": ttl,
                "created_at": force_created_at or now_iso,
                "expires_at": force_expires_at or expires_dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{expires_dt.microsecond:06d}Z",
                "parent_entry": parent_entry or None,
                "last_read_at": None,
                "embedding": None,
                "memory_tier": self._config["DEFAULT_TIER"],
                "read_count": 0,
                "promoted_from": None,
                "workspace_id": workspace_id or "",
            }
            if memory_tier:
                entry["memory_tier"] = memory_tier
            self._backend.write_entry(entry)
            return {
                "entry_id": entry["id"],
                "agent_id": entry["agent_id"],
                "type": entry["type"],
                "tags": entry["tags"],
                "created_at": entry["created_at"],
                "ttl_seconds": entry["ttl_seconds"],
                "expires_at": entry["expires_at"],
                "store_entries_count": len(self._backend.get_all_alive()),
            }

        actual_type = type or "observation"
        ttl = (ttl_seconds if ttl_seconds is not None
                else self._config["DEFAULT_TTLS"].get(actual_type, 86400))
        now_iso = _now_iso()

        expires_dt = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=ttl)
        entry = {
            "id": force_id or _generate_id(),
            "session_id": session_id or "",
            "agent_id": agent_id,
            "type": actual_type,
            "tags": tags or [],
            "content": content.strip(),
            "ttl_seconds": ttl,
            "created_at": force_created_at or now_iso,
            "expires_at": force_expires_at or expires_dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{expires_dt.microsecond:06d}Z",
            "parent_entry": parent_entry or None,
            "last_read_at": None,
            "embedding": None,
            "memory_tier": self._config["DEFAULT_TIER"],
            "read_count": 0,
            "promoted_from": None,
            "workspace_id": workspace_id or "",
        }

        # Override memory_tier if explicitly provided
        if memory_tier:
            entry["memory_tier"] = memory_tier

        # Auto-embed content if an embedding engine is configured
        if self._embedding_engine is not None and content.strip():
            try:
                entry["embedding"] = self._embedding_engine.embed(content.strip())
            except Exception:
                pass  # Embedding failure is non-fatal

        self._store["entries"].append(entry)
        self._save_store()

        # Update index
        self._load_index()
        for tag in entry["tags"]:
            self._index["tags"].setdefault(tag, []).append(entry["id"])
        self._index["agents"].setdefault(agent_id, []).append(entry["id"])
        self._index["types"].setdefault(actual_type, []).append(entry["id"])
        self._save_index()

        # Auto-prune if store is large
        store_size_mb = _estimate_size_mb(self._store)
        if store_size_mb > self._config["COMPRESSION_THRESHOLD_MB"]:
            self.prune()

        return {
            "entry_id": entry["id"],
            "agent_id": entry["agent_id"],
            "type": entry["type"],
            "tags": entry["tags"],
            "created_at": entry["created_at"],
            "ttl_seconds": entry["ttl_seconds"],
            "expires_at": entry["expires_at"],
            "store_entries_count": len(self._store["entries"]),
        }

    # ── Convenience Methods ──

    def fact(self, content: str, tags: Optional[List[str]] = None,
             ttl_seconds: Optional[int] = None,
             agent_id: Optional[str] = None,
             memory_tier: Optional[str] = None,
             workspace_id: Optional[str] = None) -> Dict:
        """Write a factual observation."""
        return self.write(
            agent_id=agent_id or "local-grid",
            type="fact",
            content=content,
            tags=tags or [],
            ttl_seconds=ttl_seconds,
            memory_tier=memory_tier,
            workspace_id=workspace_id,
        )

    def decide(self, content: str, tags: Optional[List[str]] = None,
               rationale: Optional[str] = None,
               ttl_seconds: Optional[int] = None,
               agent_id: Optional[str] = None,
               memory_tier: Optional[str] = None,
               workspace_id: Optional[str] = None) -> Dict:
        """Write an architectural decision with optional rationale."""
        text = content
        if rationale:
            text = f"{content}\nRationale: {rationale}"
        return self.write(
            agent_id=agent_id or "local-grid",
            type="decision",
            content=text,
            tags=tags or [],
            ttl_seconds=ttl_seconds or 604800,
            memory_tier=memory_tier,
            workspace_id=workspace_id,
        )

    def handoff(self, from_agent: str, to_agent: str, content: str,
                status: str = "ready", tags: Optional[List[str]] = None,
                agent_id: Optional[str] = None,
                memory_tier: Optional[str] = None,
                workspace_id: Optional[str] = None) -> Dict:
        """Record a handoff between agents."""
        text = f"[{from_agent} \u2192 {to_agent}] ({status}): {content}"
        combined_tags = (tags or []) + [f"agent:{to_agent}"]
        return self.write(
            agent_id=agent_id or from_agent,
            type="handoff",
            content=text,
            tags=combined_tags,
            ttl_seconds=3600,
            memory_tier=memory_tier,
            workspace_id=workspace_id,
        )

    # ── Query ──

    def query(self, tags: Optional[List[str]] = None,
              agents: Optional[List[str]] = None,
              type: Optional[str] = None,
              types: Optional[List[str]] = None,
              max: Optional[int] = None,
              since: Optional[str] = None,
              tag_mode: str = "OR",
              parent_entry: Optional[str] = None,
              semantic: Optional[str] = None,
              semantic_weight: float = 0.5) -> Dict:
        """Query the Grid for matching entries.

        Args:
            tags: Filter by tags (OR/AND based on tag_mode)
            agents: Filter by agent IDs
            type: Filter by single type
            types: Filter by multiple types
            max: Maximum results (1-50)
            since: ISO timestamp, only entries after this time
            tag_mode: "OR" or "AND" for tag matching
            parent_entry: Filter by parent entry ID
            semantic: Natural language query for semantic search (requires embedding engine)
            semantic_weight: Blend weight 0.0-1.0 (0 = tags only, 1 = semantic only)

        Returns:
            Dict with entries list and query_meta
        """
        if self._backend:
            entries, total = self._backend.query_entries(
                tags=tags, agents=agents, type=type, types=types,
                max=max, since=since, tag_mode=tag_mode,
                parent_entry=parent_entry
            )
            return {
                "entries": [{
                    "id": e["id"], "agent_id": e["agent_id"],
                    "type": e["type"], "tags": e.get("tags", []),
                    "content": e["content"], "created_at": e["created_at"],
                    "expires_at": e["expires_at"],
                    "parent_entry": e.get("parent_entry"),
                    "has_embedding": e.get("embedding") is not None,
                    "memory_tier": e.get("memory_tier", "working"),
                    "read_count": e.get("read_count", 0),
                    "workspace_id": e.get("workspace_id", ""),
                } for e in entries],
                "query_meta": {
                    "total_before_filter": total,
                    "returned": len(entries),
                    "semantic": False,
                    "semantic_available": False,
                    "query": {"tags": tags or [], "agents": agents or [],
                              "types": types or [], "since": since},
                },
            }
        self._load_store()

        max_results = min(
            max or self._config["DEFAULT_MAX_RESULTS"],
            self._config["ABSOLUTE_MAX_RESULTS"]
        )
        now_iso = _now_iso()
        entries = self._store["entries"]

        # Filter expired
        entries = [e for e in entries if e["expires_at"] >= now_iso]

        # Filter by parent
        if parent_entry:
            entries = [
                e for e in entries
                if e.get("parent_entry") == parent_entry or e["id"] == parent_entry
            ]

        # Filter by tags
        if tags:
            if tag_mode.upper() == "AND":
                entries = [
                    e for e in entries
                    if all(t in set(e.get("tags", [])) for t in tags)
                ]
            else:
                entries = [
                    e for e in entries
                    if any(t in set(e.get("tags", [])) for t in tags)
                ]

        # Filter by agents
        if agents:
            agent_set = set(agents)
            entries = [e for e in entries if e.get("agent_id") in agent_set]

        # Filter by type
        if type:
            entries = [e for e in entries if e.get("type") == type]
        elif types:
            type_set = set(types)
            entries = [e for e in entries if e.get("type") in type_set]

        # Filter by time
        if since:
            entries = [e for e in entries if e.get("created_at", "") >= since]

        # Score and sort
        entries = self._score_and_sort(entries, tags or [], agents or [], type or types or [])

        # Semantic scoring (if requested and available)
        if semantic and self._embedding_engine is not None:
            try:
                query_vec = self._embedding_engine.embed(semantic)
                has_embeddings = any(e.get("embedding") for e in entries)
                if has_embeddings:
                    for entry in entries:
                        if entry.get("embedding"):
                            sim = cosine_similarity(query_vec, entry["embedding"])
                            # Blend: semantic_weight controls how much semantic matters
                            entry["_semantic_score"] = sim
                            entry["_score"] = (
                                (1 - semantic_weight) * entry.get("_score", 0) +
                                semantic_weight * sim * 10  # scale to match tag scoring
                            )
                    entries.sort(key=lambda e: -e.get("_score", 0))
            except Exception:
                pass  # Semantic search silently degraded

        # Limit
        results = entries[:max_results]

        # Update last_read_at and read_count
        now_iso_later = _now_iso()
        for entry in results:
            entry["last_read_at"] = now_iso_later
            entry["read_count"] = entry.get("read_count", 0) + 1
        self._save_store()

        total_before = len(self._store["entries"])
        expired_count = total_before - len([
            e for e in self._store["entries"]
            if e["expires_at"] >= now_iso
        ])

        return {
            "entries": [
                {
                    "id": e["id"],
                    "agent_id": e["agent_id"],
                    "type": e["type"],
                    "tags": e.get("tags", []),
                    "content": e["content"],
                    "created_at": e["created_at"],
                    "expires_at": e["expires_at"],
                    "parent_entry": e.get("parent_entry"),
                    "has_embedding": e.get("embedding") is not None,
                    "memory_tier": e.get("memory_tier", "working"),
                    "read_count": e.get("read_count", 0),
                    "workspace_id": e.get("workspace_id", ""),
                    "semantic_score": round(e.get("_semantic_score", 0), 4) if e.get("_semantic_score") else None,
                    "relevance_score": round(e.get("_score", 0), 2) if e.get("_score") else None,
                }
                for e in results
            ],
            "query_meta": {
                "total_before_filter": total_before,
                "expired_filtered": expired_count,
                "returned": len(results),
                "semantic": bool(semantic),
                "semantic_available": self._embedding_engine is not None,
                "query": {
                    "tags": tags or [],
                    "agents": agents or [],
                    "types": types or [],
                    "since": since,
                    "tag_mode": tag_mode,
                    "max_results": max_results,
                },
            },
        }

    def _score_and_sort(self, entries: List[Dict],
                        query_tags: List[str],
                        query_agents: List[str],
                        query_types: List) -> List[Dict]:
        """Score entries by relevance: tag match > type match > recency."""
        now_ts = _now_unix()
        scored = []

        for e in entries:
            score = 0

            # Tag match: +10 per matching tag
            if query_tags:
                e_tags = set(e.get("tags", []))
                match_count = sum(1 for t in query_tags if t in e_tags)
                score += match_count * 10

            # Type match: +5
            q_types = query_types if isinstance(query_types, list) else [query_types]
            if q_types and e.get("type") in q_types:
                score += 5

            # Agent match: +3
            if query_agents and e.get("agent_id") in query_agents:
                score += 3

            # Recency bonus: +5 if < 5 min, +2 if < 30 min
            try:
                created = datetime.datetime.fromisoformat(e["created_at"].replace("Z", "+00:00"))
                age_seconds = now_ts - created.timestamp()
                if age_seconds < 300:
                    score += 5
                elif age_seconds < 1800:
                    score += 2
            except (ValueError, KeyError):
                pass

            scored.append((score, e))

        scored.sort(key=lambda x: -x[0])
        return [e for _, e in scored]

    # ── Inject ──

    def inject(self, context: str = "") -> Dict:
        """Get a formatted context block for agent injection.

        Args:
            context: Current task context (currently unused, reserved for
                     future semantic relevance)

        Returns:
            Dict with block (Markdown string), entry_count, bytes
        """
        if self._backend:
            alive = self._backend.get_all_alive()
            total = len(alive)  # approximate
        else:
            self._load_store()
            now_iso = _now_iso()
            alive = [e for e in self._store["entries"] if e["expires_at"] >= now_iso]
            total = len(self._store["entries"])

        # Sort by recency (newest first)
        alive.sort(key=lambda e: e.get("created_at", ""), reverse=True)

        # Take top entries up to MAX_INJECT_SIZE
        lines = ["\u2500\u2500\u2500 SHARED MEMORY GRID \u2500\u2500\u2500\n"]
        if alive:
            # Group by type for cleaner display
            lines.append(
                f"Recent entries (filtered: {len(alive)} of {total} total):\n"
            )
            chars_used = len(lines[0]) + len(lines[1]) if len(lines) > 1 else len(lines[0])
            for entry in alive:
                tags_str = ", ".join(entry.get("tags", []))
                created = entry["created_at"][11:16]  # HH:MM
                type_icon = {
                    "decision": "\U0001f9e9",  # 🧩
                    "fact": "\U0001f4a1",       # 💡
                    "handoff": "\U0001f500",    # 🔀
                    "question": "\u2753",       # ❓
                    "blocker": "\u26a0\ufe0f",  # ⚠️
                    "observation": "\U0001f50d", # 🔍
                    "task_status": "\U0001f4cb", # 📋
                    "artifact_ref": "\U0001f4c4", # 📄
                    "state_update": "\U0001f504", # 🔄
                }.get(entry["type"], "\U0001f4ac")  # 💬
                entry_line = (
                    f"[{type_icon} {entry['type']}] {created} \u2014 "
                    f"agent:{entry['agent_id']} \u2014 {tags_str}\n"
                    f"{entry['content'][:200]}\n"
                )
                if chars_used + len(entry_line) > self._config["MAX_INJECT_SIZE"]:
                    remaining = len(alive) - alive.index(entry)
                    lines.append(f"\n... and {remaining} more entries (truncated at {self._config['MAX_INJECT_SIZE']} bytes)\n")
                    break
                lines.append(entry_line)
                chars_used += len(entry_line)
        else:
            lines.append("Recent entries (filtered: 0 of 0 total):\n")

        lines.append("\n\u2500\u2500\u2500 END GRID \u2500\u2500\u2500")
        block = "\n".join(lines)

        return {
            "block": block,
            "entry_count": len(alive),
            "bytes": len(block.encode("utf-8")),
        }

    # ── Prune ──

    def prune(self) -> Dict:
        """Remove expired entries from the store."""
        if self._backend:
            removed = self._backend.prune_expired()
            remaining = len(self._backend.get_all_alive())
            return {"removed": removed, "remaining": remaining, "total_before": 0}
        self._load_store()
        before = len(self._store["entries"])
        now_iso = _now_iso()
        alive = [e for e in self._store["entries"] if e["expires_at"] >= now_iso]
        removed = before - len(alive)

        if removed > 0:
            self._store["entries"] = alive
            self._save_store()
            self._rebuild_index()

        store_size_mb = _estimate_size_mb(self._store)
        compressed = store_size_mb > self._config["MAX_STORE_SIZE_MB"]

        return {
            "removed": removed,
            "remaining": len(alive),
            "total_before": before,
            "store_size_mb": round(store_size_mb, 2),
            "compressed": compressed,
        }

    # ── Forget ──

    def forget(self, entry_id: str) -> Dict:
        """Remove a specific entry by ID."""
        if self._backend:
            entry = self._backend.forget_entry(entry_id)
            if entry is None:
                return {"found": False, "message": f"Entry {entry_id} not found"}
            return {"found": True, "entry_id": entry_id, "type": entry.get("type"), "agent_id": entry.get("agent_id")}
        self._load_store()
        found = [e for e in self._store["entries"] if e["id"] == entry_id]
        if not found:
            return {"found": False, "message": f"Entry {entry_id} not found"}

        entry = found[0]
        self._store["entries"] = [e for e in self._store["entries"] if e["id"] != entry_id]
        self._save_store()
        self._rebuild_index()

        return {
            "found": True,
            "entry_id": entry_id,
            "type": entry.get("type"),
            "agent_id": entry.get("agent_id"),
            "message": f"Entry {entry_id} removed",
        }

    # ── Info ──

    def info(self) -> Dict:
        """Get store statistics."""
        if self._backend:
            return self._backend.get_info()
        self._load_store()
        entries = self._store["entries"]
        now_iso = _now_iso()

        by_type: Dict[str, int] = {}
        by_agent: Dict[str, int] = {}
        all_tags: set = set()

        alive = [e for e in entries if e["expires_at"] >= now_iso]

        for e in entries:
            by_type[e["type"]] = by_type.get(e["type"], 0) + 1
            by_agent[e["agent_id"]] = by_agent.get(e["agent_id"], 0) + 1
            all_tags.update(e.get("tags", []))

        expired = len(entries) - len(alive)
        store_size_kb = _estimate_size_kb(self._store)

        return {
            "total_entries": len(entries),
            "alive_entries": len(alive),
            "expired_entries": expired,
            "unique_agents": len(by_agent),
            "unique_tags": len(all_tags),
            "store_size_kb": round(store_size_kb, 1),
            "by_type": by_type,
            "by_agent": by_agent,
            "oldest_entry": entries[0]["created_at"] if entries else None,
            "newest_entry": entries[-1]["created_at"] if entries else None,
            "store_version": self._store.get("version", 1),
        }

    # ── Wipe (for testing) ──

    def close(self):
        """Close the backend connection (for SQLite/PostgreSQL)."""
        if self._backend and hasattr(self._backend, 'close'):
            self._backend.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def wipe(self, confirm: bool = False) -> Dict:
        """Wipe the entire store."""
        if not confirm:
            return {"wiped": False, "message": "Confirmation required. Call wipe(True) to confirm."}
        if self._backend:
            self._backend.wipe()
            return {"wiped": True, "message": "Shared memory grid cleared."}
        self._store = {"version": 1, "created_at": _now_iso(), "entries": []}
        self._index = {"version": 1, "tags": {}, "agents": {}, "types": {}}
        self._save_store()
        self._save_index()
        return {"wiped": True, "message": "Shared memory grid cleared."}

    # ── Export / Import ──

    def export_json(self, output_path: Optional[str] = None,
                    pretty: bool = True) -> str:
        """Export all entries as JSON.
        Works with all backends: JSON file, SQLite, PostgreSQL.

        Args:
            output_path: File path to write to, or None for string return
            pretty: Pretty-print output

        Returns:
            JSON string if output_path is None
        """
        # Use backend for export when available (SQLite, Postgres)
        if self._backend:
            entries = self._backend.get_all_alive()
        else:
            self._load_store()
            entries = self._store["entries"]

        export_data = {
            "version": 2,
            "exported_at": _now_iso(),
            "entry_count": len(entries),
            "entries": []
        }
        for e in entries:
            export_entry = {k: v for k, v in e.items() if k != "embedding"}
            export_data["entries"].append(export_entry)

        indent = 2 if pretty else None
        json_str = json.dumps(export_data, indent=indent)

        if output_path:
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            with open(output_path, "w") as f:
                f.write(json_str)
            return output_path
        return json_str

    def import_json(self, json_input: str, merge: bool = True,
                    agent_override: Optional[str] = None,
                    tag_prefix: Optional[str] = None) -> Dict:
        """Import entries from JSON export. Preserves IDs, timestamps, and parent relationships."""
        if os.path.exists(str(json_input)):
            with open(json_input) as f:
                data = json.load(f)
        else:
            data = json.loads(json_input)

        entries = data.get("entries", [])
        imported = 0
        skipped = 0
        errors = []

        if not merge:
            self.wipe(confirm=True)

        for entry in entries:
            try:
                agent = agent_override or entry.get("agent_id", "imported")
                content = entry.get("content", "")
                etype = entry.get("type", "observation")
                tags = list(entry.get("tags", []))
                if tag_prefix:
                    tags = [f"{tag_prefix}:{t}" for t in tags]

                # Preserve original IDs, timestamps, and parent relationships
                self.write(
                    agent_id=agent, type=etype, content=content,
                    tags=tags, ttl_seconds=entry.get("ttl_seconds"),
                    session_id=entry.get("session_id", ""),
                    parent_entry=entry.get("parent_entry"),
                    memory_tier=entry.get("memory_tier"),
                    workspace_id=entry.get("workspace_id", ""),
                    force_id=entry.get("id"),
                    force_created_at=entry.get("created_at"),
                    force_expires_at=entry.get("expires_at"),
                )
                imported += 1
            except Exception as e:
                errors.append(str(e))
                skipped += 1

        return {"imported": imported, "skipped": skipped,
                "errors": errors, "total_in_source": len(entries)}


# ─── Helpers ────────────────────────────────────────────────────────────────────


def _estimate_size_mb(data: Dict) -> float:
    return len(json.dumps(data)) / (1024 * 1024)


def _estimate_size_kb(data: Dict) -> float:
    return len(json.dumps(data)) / 1024


# ─── CLI ────────────────────────────────────────────────────────────────────────


def main_cli():
    """CLI entry point for 'python -m grid_memory.local_grid'"""
    import argparse

    parser = argparse.ArgumentParser(description="Grid Memory - Local Engine")
    parser.add_argument("--store-dir", help="Override store directory")

    sub = parser.add_subparsers(dest="command")

    p_write = sub.add_parser("write")
    p_write.add_argument("--agent", default="cli")
    p_write.add_argument("--type", default="observation")
    p_write.add_argument("--tags", default="")
    p_write.add_argument("--ttl", type=int)
    p_write.add_argument("--content", required=True)
    p_write.add_argument("--session", default="")

    p_query = sub.add_parser("query")
    p_query.add_argument("--tags", default="")
    p_query.add_argument("--agents", default="")
    p_query.add_argument("--type")
    p_query.add_argument("--max", type=int)
    p_query.add_argument("--since")
    p_query.add_argument("--tag-mode", default="OR")

    p_inject = sub.add_parser("inject")
    p_inject.add_argument("--context", default="")
    sub.add_parser("info")
    sub.add_parser("prune")
    p_forget = sub.add_parser("forget")
    p_forget.add_argument("--id", required=True)
    p_wipe = sub.add_parser("wipe")
    p_wipe.add_argument("--confirm", action="store_true")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    grid = LocalGrid(store_dir=args.store_dir) if args.store_dir else LocalGrid()

    try:
        if args.command == "write":
            result = grid.write(
                agent_id=args.agent, type=args.type,
                tags=args.tags.split(",") if args.tags else [],
                ttl_seconds=args.ttl, content=args.content, session_id=args.session,
            )
        elif args.command == "query":
            result = grid.query(
                tags=args.tags.split(",") if args.tags else [],
                agents=args.agents.split(",") if args.agents else [],
                type=args.type, max=args.max, since=args.since, tag_mode=args.tag_mode,
            )
        elif args.command == "inject":
            result = grid.inject(context=args.context)
        elif args.command == "info":
            result = grid.info()
        elif args.command == "prune":
            result = grid.prune()
        elif args.command == "forget":
            result = grid.forget(args.id)
        elif args.command == "wipe":
            result = grid.wipe(args.confirm)
        else:
            result = {"error": f"Unknown command: {args.command}"}

        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}, indent=2))
        import sys
        sys.exit(1)


if __name__ == "__main__":
    main_cli()
