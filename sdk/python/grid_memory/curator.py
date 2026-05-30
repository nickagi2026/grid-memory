"""
curator.py — Autonomous Memory Curation Agent for the Shared Memory Grid.

Maintains the Grid by:
1. Archiving stale entries (older than 7 days with no reads)
2. Merging duplicates (80%+ word overlap within first 100 chars)
3. Generating weekly summary digests
4. Flagging contradictory values
5. Suggesting tags for untagged entries

Usage:
    from grid_memory.curator import GridCurator
    from grid_memory.local_grid import LocalGrid

    grid = LocalGrid()
    curator = GridCurator(grid=grid)

    # One-time curation pass
    report = curator.curate()

    # Start background curation (every hour)
    curator.start_auto_curate(interval_seconds=3600)

    # Stop
    curator.stop()
"""

import datetime
import json
import os
import re
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple


# ─── Constants ──────────────────────────────────────────────────────────────────

_STALE_DAYS = 7                       # Entries older than this with no reads are stale
_WORD_OVERLAP_THRESHOLD = 0.8         # 80%+ word overlap = duplicate
_DUP_CONTEXT_CHARS = 100              # Compare only first N chars for overlap
_SUMMARY_TYPE = "curator_summary"
_ARCHIVE_TYPE = "curator_archive"
_CONTRADICTION_TYPE = "curator_contradiction"
_TAG_SUGGESTION_TYPE = "curator_tag_suggestion"

# Stop words to filter out when suggesting tags
_STOP_WORDS: Set[str] = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "shall", "can", "need",
    "this", "that", "these", "those", "it", "its", "they", "them", "their",
    "we", "us", "our", "you", "your", "he", "she", "him", "her", "his",
    "not", "no", "nor", "so", "if", "then", "than", "too", "very", "just",
    "about", "also", "into", "over", "after", "before", "between", "under",
    "up", "out", "off", "down", "all", "each", "every", "both", "few",
    "more", "most", "some", "any", "none", "one", "two", "get", "got",
    "use", "used", "using", "set", "make", "made", "like", "work", "take",
    "go", "come", "see", "know", "think", "want", "give", "find", "tell",
    "ask", "try", "leave", "call", "run", "move", "return", "put",
    "thing", "stuff", "way", "part", "place", "number", "type", "kind",
    "new", "old", "good", "bad", "big", "small", "high", "low", "long",
    "short", "same", "different", "done", "well", "back", "still", "even",
    "much", "while", "because", "when", "where", "how", "what", "which",
    "who", "whose", "why", "here", "there", "now", "then", "always",
    "never", "often", "sometimes", "usually", "already", "yet", "please",
    "let", "without", "via",
}


# ─── Utility ────────────────────────────────────────────────────────────────────


def _now_iso() -> str:
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}Z"


def _days_ago_iso(days: int) -> str:
    dt = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond:06d}Z"


def _parse_iso(iso_str: str) -> datetime.datetime:
    """Parse an ISO 8601 string, handling Z suffix."""
    if iso_str.endswith("Z"):
        iso_str = iso_str[:-1] + "+00:00"
    return datetime.datetime.fromisoformat(iso_str)


def _word_overlap(a: str, b: str, char_limit: int = _DUP_CONTEXT_CHARS) -> float:
    """Compute word overlap (intersection over union) between first N chars of two texts.

    Args:
        a: First text
        b: Second text
        char_limit: Compare only first N characters

    Returns:
        Overlap ratio 0.0–1.0
    """
    words_a = a[:char_limit].lower().split()
    words_b = b[:char_limit].lower().split()
    if not words_a or not words_b:
        return 0.0
    set_a = set(words_a)
    set_b = set(words_b)
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


def _extract_keywords(text: str, max_words: int = 5) -> List[str]:
    """Extract meaningful keywords from text, excluding stop words.

    Args:
        text: Input text
        max_words: Maximum number of keywords to return

    Returns:
        List of keyword strings
    """
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", text.lower())
    filtered = [w for w in words if w not in _STOP_WORDS and len(w) > 2]
    counter = Counter(filtered).most_common(max_words)
    return [word for word, _ in counter]


def _extract_numeric_patterns(text: str) -> List[Tuple[str, float]]:
    """Extract key-value numeric patterns like 'pool: 25' or 'pool=50'.

    Returns:
        List of (key, value) tuples
    """
    patterns: List[Tuple[str, float]] = []
    # Match patterns like "key: 123", "key = 123", "key=123"
    for match in re.finditer(r"([a-zA-Z_][a-zA-Z0-9_]*)\s*[:=]\s*(\d+(?:\.\d+)?)", text):
        key = match.group(1).lower()
        value = float(match.group(2))
        patterns.append((key, value))
    # Also match standalone numbers that could be values
    # like "pool of 25" or "25 connections"
    for match in re.finditer(r"(\d+(?:\.\d+)?)\s*(%|[a-zA-Z]+)", text):
        key = match.group(2).lower()
        value = float(match.group(1))
        patterns.append((key, value))
    return patterns


def _find_nearby_numbers(text: str) -> List[Tuple[str, float]]:
    """Find patterns like 'is 25' or 'set to 50' or '25 ms'.

    Returns:
        List of (context_word, value) tuples
    """
    patterns: List[Tuple[str, float]] = []
    # "word/s of/about/at/set/is/was 123" 
    for match in re.finditer(r"(?:of|about|at|set|is|was|to|with)\s+(\d+(?:\.\d+)?)", text.lower()):
        value = float(match.group(1))
        # Try to find a meaningful context word before the pattern
        start = max(0, match.start() - 20)
        prefix = text[start:match.start()].lower().split()
        context = prefix[-1] if prefix else "value"
        patterns.append((context, value))
    # "123 connections/ms/seconds/users"
    for match in re.finditer(r"(\d+(?:\.\d+)?)\s+([a-zA-Z]{2,})", text):
        value = float(match.group(1))
        key = match.group(2).lower()
        patterns.append((key, value))
    return patterns


# ─── Archive Store ──────────────────────────────────────────────────────────────


class _ArchiveStore:
    """Persistent storage for archived grid entries.

    A simple JSON file alongside the main grid store.
    Entries are moved here when they become stale.
    """

    def __init__(self, store_dir: str):
        self._dir = os.path.join(store_dir, "archive")
        self._path = os.path.join(self._dir, "archived_entries.json")
        Path(self._dir).mkdir(parents=True, exist_ok=True)
        self._entries: List[Dict] = []
        self._load()

    def _load(self):
        if os.path.exists(self._path):
            try:
                with open(self._path, "r") as f:
                    self._entries = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._entries = []
        else:
            self._entries = []

    def _save(self):
        with open(self._path, "w") as f:
            json.dump(self._entries, f, indent=2)

    def archive(self, entries: List[Dict]) -> int:
        """Move entries to the archive store.

        Each entry gets an 'archived_at' timestamp.
        Returns the number of entries archived.
        """
        now_iso = _now_iso()
        for entry in entries:
            entry_copy = dict(entry)
            entry_copy["archived_at"] = now_iso
            if "embedding" in entry_copy:
                del entry_copy["embedding"]  # Strip large embedding data
            self._entries.append(entry_copy)
        self._save()
        return len(entries)

    def count(self) -> int:
        return len(self._entries)

    def all(self) -> List[Dict]:
        return list(self._entries)

    def clear(self):
        self._entries = []
        self._save()


# ─── The Grid Curator ────────────────────────────────────────────────────────────


class GridCurator:
    """Autonomous curator that maintains the Shared Memory Grid.

    Runs periodic maintenance: archiving, deduplication, summaries,
    contradiction detection, and tag suggestions.

    Args:
        grid: A LocalGrid instance
    """

    def __init__(self, grid):
        self.grid = grid
        self._archive = _ArchiveStore(grid._store_dir)
        self._timer: Optional[threading.Timer] = None
        self._running = False
        self._interval = 3600

        # Extend grid's valid types to include curator-specific types
        # so the curator can write its own entry types (summaries, contradictions, etc.)
        _CURATOR_TYPES = [_SUMMARY_TYPE, _ARCHIVE_TYPE, _CONTRADICTION_TYPE, _TAG_SUGGESTION_TYPE]
        if hasattr(grid, '_config') and 'VALID_TYPES' in grid._config:
            existing = list(grid._config['VALID_TYPES'])
            for ct in _CURATOR_TYPES:
                if ct not in existing:
                    existing.append(ct)
            grid._config['VALID_TYPES'] = existing

    # ── Public API ──

    def curate(self) -> Dict:
        """Execute a single curation pass across all operations.

        Returns:
            Structured report dict:
            {
                "archived": <int>,
                "merged": [{"survivor": "<id>", "deleted": ["<id>", ...]}, ...],
                "summaries_written": <int>,  # 0 or 1 (only on weekly boundary)
                "contradictions_flagged": <int>,
                "tags_suggested": <int>,
            }
        """
        report: Dict = {
            "archived": 0,
            "merged": [],
            "summaries_written": 0,
            "contradictions_flagged": 0,
            "tags_suggested": 0,
        }

        report["archived"] = self._archive_stale()
        report["merged"] = self._merge_duplicates()
        report["summaries_written"] = self._generate_weekly_summary()
        report["contradictions_flagged"] = self._flag_contradictions()
        report["tags_suggested"] = self._suggest_tags()

        return report

    def start_auto_curate(self, interval_seconds: int = 3600):
        """Start background curation on a timer.

        Args:
            interval_seconds: Seconds between curation passes (default: 3600)
        """
        self._interval = interval_seconds
        self._running = True
        self._schedule_next()

    def stop(self):
        """Stop background curation."""
        self._running = False
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    # ── Internal: Entry Access ──

    def _get_all_entries(self) -> List[Dict]:
        """Get all non-expired entries from the grid."""
        if self.grid._backend:
            return self.grid._backend.get_all_alive()
        self.grid._load_store()
        now_iso = _now_iso()
        return [
            e for e in self.grid._store["entries"]
            if e.get("expires_at", "") >= now_iso
        ]

    def _save_store(self):
        """Persist store changes."""
        if self.grid._backend:
            return
        self.grid._save_store()

    # ── Step 1: Archive Stale Entries ──

    def _archive_stale(self) -> int:
        """Move entries older than 7 days with no reads to the archive.

        Returns:
            Number of entries archived.
        """
        entries = self._get_all_entries()
        cutoff = _days_ago_iso(_STALE_DAYS)

        stale = []
        for entry in entries:
            created_at = entry.get("created_at", "")
            last_read = entry.get("last_read_at")

            # Skip if entry is too recent
            if created_at >= cutoff:
                continue

            # Check if entry has never been read, or last read was also stale
            if last_read is None:
                stale.append(entry)
            elif last_read < cutoff:
                stale.append(entry)

        if not stale:
            return 0

        # Write an archive reference entry to the grid
        agent_ids = set(e.get("agent_id", "?") for e in stale)
        all_tags = set()
        for e in stale:
            all_tags.update(e.get("tags", []))

        archive_content = (
            f"Archived {len(stale)} stale entries "
            f"(no reads in {_STALE_DAYS}+ days). "
            f"Agents: {', '.join(sorted(agent_ids))}. "
            f"Tags: {', '.join(sorted(all_tags)) if all_tags else 'none'}."
        )

        self.grid.write(
            agent_id="curator",
            type=_ARCHIVE_TYPE,
            content=archive_content,
            tags=["curator", "archived"],
        )

        # Move stale entries to the archive store
        self._archive.archive(stale)

        # Remove stale entries from the grid
        for entry in stale:
            self.grid.forget(entry["id"])

        return len(stale)

    # ── Step 2: Merge Duplicates ──

    def _merge_duplicates(self) -> List[Dict]:
        """Find and merge duplicate entries (80%+ word overlap in first 100 chars).

        The most recent entry survives, absorbing all tags from duplicates.

        Returns:
            List of merge records: {"survivor": "<id>", "deleted": ["<id>", ...]}
        """
        entries = self._get_all_entries()
        if len(entries) < 2:
            return []

        # Sort by created_at descending (most recent first)
        entries_sorted = sorted(
            entries, key=lambda e: e.get("created_at", ""), reverse=True
        )

        merged_records: List[Dict] = []
        deleted_ids: Set[str] = set()
        surviving: List[Dict] = []

        for entry in entries_sorted:
            if entry["id"] in deleted_ids:
                continue

            dupes: List[Dict] = []
            for other in entries_sorted:
                if other["id"] == entry["id"] or other["id"] in deleted_ids:
                    continue
                if _word_overlap(entry["content"], other["content"]) >= _WORD_OVERLAP_THRESHOLD:
                    dupes.append(other)

            if dupes:
                # survival: most recent (already first in sorted list)
                survivor = entry
                merged_tags = set(survivor.get("tags", []))
                deleted_in_this_group = []

                for dupe in dupes:
                    merged_tags.update(dupe.get("tags", []))
                    deleted_ids.add(dupe["id"])
                    deleted_in_this_group.append(dupe["id"])
                    self.grid.forget(dupe["id"])

                # Update survivor tags if needed
                if set(survivor.get("tags", [])) != merged_tags:
                    # We can't easily update tags in-place (append-only store),
                    # so we write a new entry with merged tags and delete the original
                    merged_content = survivor["content"]
                    merged_tags_list = sorted(merged_tags)

                    self.grid.write(
                        agent_id=survivor.get("agent_id", "curator"),
                        type=survivor.get("type", "observation"),
                        content=merged_content,
                        tags=merged_tags_list,
                        ttl_seconds=survivor.get("ttl_seconds"),
                        session_id=survivor.get("session_id", ""),
                    )

                    # Delete the survivor with merged tags
                    self.grid.forget(survivor["id"])
                    survivor_id = f"{survivor['id']}_merged"
                else:
                    survivor_id = survivor["id"]

                merged_records.append({
                    "survivor": survivor_id,
                    "deleted": deleted_in_this_group,
                })

                surviving.append(survivor)
            else:
                surviving.append(entry)

        return merged_records

    # ── Step 3: Generate Weekly Summary ──

    def _generate_weekly_summary(self) -> int:
        """Generate a summary entry if one hasn't been written in the last 7 days.

        Summary format:
            "Weekly Digest: 47 new entries from 5 agents. Top tags: database(12), architecture(8), deployment(6)"

        Returns:
            1 if a summary was written, 0 if not due yet.
        """
        entries = self._get_all_entries()
        now_iso = _now_iso()

        # Check if a summary was already written in the last 7 days
        cutoff = _days_ago_iso(_STALE_DAYS)
        existing_summaries = [
            e for e in entries
            if e.get("type") == _SUMMARY_TYPE and e.get("created_at", "") >= cutoff
        ]
        if existing_summaries:
            return 0  # Not due yet

        # Count entries from the last 7 days
        recent_entries = [
            e for e in entries
            if e.get("created_at", "") >= cutoff
        ]

        total_new = len(recent_entries)
        unique_agents = set(e.get("agent_id", "?") for e in recent_entries)
        agent_count = len(unique_agents)

        # Find top tags in recent entries
        tag_counter: Counter = Counter()
        for e in recent_entries:
            for tag in e.get("tags", []):
                tag_counter[tag] += 1

        # If no recent entries, fall back to all entries
        if total_new == 0:
            total_new = len(entries)
            unique_agents = set(e.get("agent_id", "?") for e in entries)
            agent_count = len(unique_agents)
            for e in entries:
                for tag in e.get("tags", []):
                    tag_counter[tag] += 1

        top_tags = tag_counter.most_common(5)
        tag_summary = ", ".join(
            f"{tag}({count})" for tag, count in top_tags
        )

        summary_content = (
            f"Weekly Digest: {total_new} new entries from {agent_count} agents. "
            f"Top tags: {tag_summary}"
        )

        self.grid.write(
            agent_id="curator",
            type=_SUMMARY_TYPE,
            content=summary_content,
            tags=["curator", "weekly-digest"],
        )

        return 1

    # ── Step 4: Flag Contradictions ──

    def _flag_contradictions(self) -> int:
        """Find entries with conflicting numeric values and write contradiction flags.

        Looks for entries with same-key numeric patterns (e.g., "pool: 25" vs "pool: 50")
        and flags significant differences.

        Returns:
            Number of contradictions flagged.
        """
        entries = self._get_all_entries()
        if len(entries) < 2:
            return 0

        # Extract all numeric patterns
        entry_patterns: List[Tuple[Dict, List[Tuple[str, float]]]] = []
        for entry in entries:
            # Skip curator entries (our own writes)
            if entry.get("agent_id") == "curator":
                continue
            patterns = _extract_numeric_patterns(entry["content"])
            patterns += _find_nearby_numbers(entry["content"])
            if patterns:
                entry_patterns.append((entry, patterns))

        if len(entry_patterns) < 2:
            return 0

        # Group by key and check for contradictions
        flagged = 0
        key_map: Dict[str, List[Tuple[str, str, float]]] = {}
        for entry, patterns in entry_patterns:
            for key, value in patterns:
                key_map.setdefault(key, []).append(
                    (entry["id"], entry["content"], value)
                )

        for key, entries_with_values in key_map.items():
            if len(entries_with_values) < 2:
                continue

            values = [v for _, _, v in entries_with_values]
            if len(set(values)) < 2:
                continue  # All same value

            # Check for significant differences (> 25% relative diff or absolute diff > 10)
            for i in range(len(entries_with_values)):
                for j in range(i + 1, len(entries_with_values)):
                    id_a, content_a, val_a = entries_with_values[i]
                    id_b, content_b, val_b = entries_with_values[j]

                    if val_a == 0 and val_b == 0:
                        continue

                    # Compute relative difference
                    max_val = max(abs(val_a), abs(val_b))
                    min_val = min(abs(val_a), abs(val_b))
                    if max_val == 0:
                        continue

                    rel_diff = (max_val - min_val) / max_val

                    if rel_diff >= 0.25 and abs(val_a - val_b) >= 5:
                        # Check if we already flagged this contradiction
                        existing = [
                            e for e in entries
                            if e.get("type") == _CONTRADICTION_TYPE
                            and key in e.get("content", "").lower()
                            and f"{val_a}" in e.get("content", "")
                            and f"{val_b}" in e.get("content", "")
                        ]
                        if existing:
                            continue

                        flagged += 1
                        self.grid.write(
                            agent_id="curator",
                            type=_CONTRADICTION_TYPE,
                            content=(
                                f"Potential contradiction: '{key}' has conflicting values "
                                f"({val_a} in entry {id_a[:20]}... vs {val_b} in entry "
                                f"{id_b[:20]}...). Relative difference: {rel_diff:.0%}. "
                                f"Entry A: {content_a[:120]}. Entry B: {content_b[:120]}."
                            ),
                            tags=["curator", "contradiction", f"key:{key}"],
                        )

        return flagged

    # ── Step 5: Suggest Tags ──

    def _suggest_tags(self) -> int:
        """Suggest tags for entries that have none.

        Extracts keywords from content and writes tag-suggestion entries.

        Returns:
            Number of tag suggestions written.
        """
        entries = self._get_all_entries()
        untagged = [
            e for e in entries
            if not e.get("tags") and e.get("content", "").strip()
            and e.get("agent_id") != "curator"
        ]

        suggested = 0
        for entry in untagged:
            keywords = _extract_keywords(entry["content"], max_words=4)
            if not keywords:
                continue

            # Check if a suggestion was already made for this entry
            existing = [
                e for e in entries
                if e.get("type") == _TAG_SUGGESTION_TYPE
                and entry["id"] in e.get("content", "")
            ]
            if existing:
                continue

            suggested += 1
            tags_str = ", ".join(keywords)
            self.grid.write(
                agent_id="curator",
                type=_TAG_SUGGESTION_TYPE,
                content=(
                    f"Tag suggestion for entry:{entry['id']}: "
                    f"suggested tags: {tags_str}. "
                    f"Context: {entry['content'][:100]}"
                ),
                tags=["curator", "tag-suggestion"] + [f"suggested:{t}" for t in keywords],
            )

        return suggested

    # ── Background Loop ──

    def _schedule_next(self):
        if not self._running:
            return
        self._timer = threading.Timer(self._interval, self._curate_loop)
        self._timer.daemon = True
        self._timer.start()

    def _curate_loop(self):
        try:
            self.curate()
        except Exception:
            # Suppress errors in background loop to keep running
            pass
        self._schedule_next()

    # ── Archive Query ──

    def archive_count(self) -> int:
        """Get the count of archived entries."""
        return self._archive.count()

    def list_archived(self) -> List[Dict]:
        """Get all archived entries."""
        return self._archive.all()

    def clear_archive(self):
        """Clear all archived entries (for testing/cleanup)."""
        self._archive.clear()
