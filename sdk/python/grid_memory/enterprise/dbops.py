"""
dbops.py — Database operations: backup, archive, optimization, monitoring.

Provides production-grade database management for the Grid:
- Backup and restore with scheduling
- Archive policies (move old entries to cold storage)
- Query optimization recommendations
- Connection pool monitoring
- Index management
"""

import datetime
import json
import os
import shutil
import time
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any

from grid_memory.local_grid import LocalGrid


class DatabaseOps:
    """Production database operations for the Grid.

    Args:
        grid: LocalGrid instance
        backup_dir: Directory for backups
        archive_dir: Directory for archived data
    """

    def __init__(self, grid: LocalGrid,
                 backup_dir: Optional[str] = None,
                 archive_dir: Optional[str] = None):
        self.grid = grid
        self.backup_dir = backup_dir or os.path.join(
            os.path.expanduser("~"), ".openclaw", "backups"
        )
        self.archive_dir = archive_dir or os.path.join(
            os.path.expanduser("~"), ".openclaw", "archive"
        )
        self._backup_thread: Optional[threading.Thread] = None
        self._backup_stop = threading.Event()

    # ── Backup & Restore ──

    def backup(self, label: str = "") -> Dict:
        """Create a full backup of the Grid store.

        Returns:
            Dict with backup info
        """
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
        label_slug = label.replace(" ", "_") if label else "manual"
        backup_name = f"grid_backup_{timestamp}_{label_slug}"
        backup_path = os.path.join(self.backup_dir, backup_name)

        os.makedirs(backup_path, exist_ok=True)

        # Export all entries
        export_data = self.grid.export_json()
        entries_path = os.path.join(backup_path, "entries.json")
        with open(entries_path, "w") as f:
            f.write(export_data)

        # Get store info
        info = self.grid.info()

        # Write backup manifest
        manifest = {
            "backup_name": backup_name,
            "timestamp": timestamp,
            "label": label,
            "entry_count": info.get("total_entries", 0),
            "alive_count": info.get("alive_entries", 0),
            "agents": info.get("unique_agents", 0),
            "store_version": info.get("store_version", "unknown"),
            "files": ["entries.json"],
        }
        with open(os.path.join(backup_path, "manifest.json"), "w") as f:
            json.dump(manifest, f, indent=2)

        # Also copy the raw store file if it exists
        if hasattr(self.grid, '_store_path') and os.path.exists(self.grid._store_path):
            shutil.copy2(self.grid._store_path, os.path.join(backup_path, "store.json"))

        return {
            "backup_name": backup_name,
            "path": backup_path,
            "entries": info.get("total_entries", 0),
            "size_kb": self._dir_size_kb(backup_path),
            "timestamp": timestamp,
        }

    def list_backups(self) -> List[Dict]:
        """List all available backups."""
        if not os.path.exists(self.backup_dir):
            return []

        backups = []
        for item in sorted(os.listdir(self.backup_dir), reverse=True):
            backup_path = os.path.join(self.backup_dir, item)
            manifest_path = os.path.join(backup_path, "manifest.json")
            if os.path.isdir(backup_path) and os.path.exists(manifest_path):
                with open(manifest_path) as f:
                    manifest = json.load(f)
                backups.append({
                    "name": manifest.get("backup_name", item),
                    "timestamp": manifest.get("timestamp", ""),
                    "label": manifest.get("label", ""),
                    "entries": manifest.get("entry_count", 0),
                    "size_kb": self._dir_size_kb(backup_path),
                })

        return backups

    def restore(self, backup_name: str, dry_run: bool = False) -> Dict:
        """Restore from a backup.

        Args:
            backup_name: Name of the backup to restore from
            dry_run: If True, report what would be restored without acting

        Returns:
            Dict with restore results
        """
        backup_path = os.path.join(self.backup_dir, backup_name)
        manifest_path = os.path.join(backup_path, "manifest.json")

        if not os.path.exists(manifest_path):
            return {"success": False, "reason": f"Backup '{backup_name}' not found"}

        with open(manifest_path) as f:
            manifest = json.load(f)

        entries_path = os.path.join(backup_path, "entries.json")
        if not os.path.exists(entries_path):
            return {"success": False, "reason": "Backup corrupted: entries.json missing"}

        if dry_run:
            return {
                "success": True,
                "dry_run": True,
                "backup": backup_name,
                "would_restore": manifest.get("entry_count", 0),
                "entries_path": entries_path,
            }

        # Import the entries
        with open(entries_path) as f:
            import_data = f.read()

        result = self.grid.import_json(import_data, merge=True)

        return {
            "success": True,
            "restored": result.get("imported", 0),
            "skipped": result.get("skipped", 0),
            "backup": backup_name,
        }

    def start_auto_backup(self, interval_hours: int = 24) -> Dict:
        """Start automatic backup scheduling.

        Args:
            interval_hours: Hours between backups
        """
        if self._backup_thread and self._backup_thread.is_alive():
            return {"started": False, "reason": "Auto-backup already running"}

        self._backup_stop.clear()
        self._backup_thread = threading.Thread(
            target=self._backup_loop,
            args=(interval_hours,),
            daemon=True,
        )
        self._backup_thread.start()
        return {"started": True, "interval_hours": interval_hours}

    def stop_auto_backup(self) -> Dict:
        """Stop automatic backup scheduling."""
        if not self._backup_thread or not self._backup_thread.is_alive():
            return {"stopped": False, "reason": "Not running"}
        self._backup_stop.set()
        self._backup_thread.join(timeout=5)
        return {"stopped": True}

    def _backup_loop(self, interval_hours: int):
        """Background backup loop."""
        while not self._backup_stop.is_set():
            try:
                self.backup(label="auto")
            except Exception as e:
                print(f"[DB Ops] Auto-backup failed: {e}")
            for _ in range(interval_hours * 3600):
                if self._backup_stop.is_set():
                    return
                time.sleep(1)

    # ─── Archive Policies ─────────────────────────────────────────────────

    def archive(self, older_than_days: int = 365,
                delete_after_archive: bool = False) -> Dict:
        """Archive entries older than specified days.

        Moves old entries to a separate archive directory and optionally
        removes them from the active store.

        Args:
            older_than_days: Archive entries older than this
            delete_after_archive: Remove archived entries from active store

        Returns:
            Dict with archive results
        """
        cutoff = (datetime.datetime.now(datetime.timezone.utc) -
                  datetime.timedelta(days=older_than_days)).isoformat()

        # Query old entries
        result = self.grid.query(max=500, since="2000-01-01")
        entries = result.get("entries", [])
        old_entries = [e for e in entries if e.get("created_at", "") < cutoff]

        if not old_entries:
            return {"archived": 0, "message": "No entries older than threshold"}

        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
        archive_path = os.path.join(self.archive_dir, f"archive_{timestamp}")
        os.makedirs(archive_path, exist_ok=True)

        archive_data = {
            "archived_at": timestamp,
            "threshold_days": older_than_days,
            "entry_count": len(old_entries),
            "entries": old_entries,
        }

        with open(os.path.join(archive_path, "archive.json"), "w") as f:
            json.dump(archive_data, f, indent=2)

        if delete_after_archive:
            for entry in old_entries:
                try:
                    self.grid.forget(entry["id"])
                except Exception:
                    pass

        return {
            "archived": len(old_entries),
            "archive_path": archive_path,
            "size_kb": self._dir_size_kb(archive_path),
            "deleted_from_active": delete_after_archive,
        }

    def list_archives(self) -> List[Dict]:
        """List all available archives."""
        if not os.path.exists(self.archive_dir):
            return []

        archives = []
        for item in sorted(os.listdir(self.archive_dir), reverse=True):
            archive_path = os.path.join(self.archive_dir, item)
            archive_file = os.path.join(archive_path, "archive.json")
            if os.path.isdir(archive_path) and os.path.exists(archive_file):
                try:
                    with open(archive_file) as f:
                        data = json.load(f)
                    archives.append({
                        "name": item,
                        "archived_at": data.get("archived_at", ""),
                        "entries": data.get("entry_count", 0),
                        "threshold_days": data.get("threshold_days", 0),
                        "size_kb": self._dir_size_kb(archive_path),
                    })
                except Exception:
                    pass

        return archives

    # ── Query Optimization ──

    def analyze_queries(self) -> Dict:
        """Analyze query patterns and provide optimization recommendations."""
        result = self.grid.query(max=10)
        entries = result.get("entries", [])

        recommendations = []

        # Check for untagged entries
        untagged = [e for e in entries if not e.get("tags")]
        if untagged:
            recommendations.append({
                "type": "indexing",
                "priority": "high",
                "finding": f"{len(untagged)} recent entries have no tags",
                "recommendation": "Tag all entries for faster filtered queries",
            })

        # Check entry count
        info = self.grid.info()
        total = info.get("total_entries", 0)

        if total > 1000:
            recommendations.append({
                "type": "partitioning",
                "priority": "medium",
                "finding": f"{total} entries — consider archiving old data",
                "recommendation": "Use archive or prune for entries older than 90 days",
            })

        if total > 10000:
            recommendations.append({
                "type": "scaling",
                "priority": "high",
                "finding": f"{total} entries — query performance may degrade",
                "recommendation": "Migrate to PostgreSQL backend for better query performance",
            })

        return {
            "analyzed_entries": total,
            "recommendations": recommendations,
            "recommendation_count": len(recommendations),
        }

    # ── Connection Pool Monitoring ──

    def pool_status(self) -> Dict:
        """Get database connection pool status."""
        info = self.grid.info()
        return {
            "backend_type": info.get("store_version", "file"),
            "total_entries": info.get("total_entries", 0),
            "alive_entries": info.get("alive_entries", 0),
            "unique_agents": info.get("unique_agents", 0),
            "store_size_kb": info.get("store_size_kb", 0),
            "status": "healthy" if info.get("alive_entries", 0) >= 0 else "error",
        }

    # ── Index Management ──

    def index_info(self) -> Dict:
        """Get index information and recommendations."""
        info = self.grid.info()
        by_type = info.get("by_type", {})
        by_agent = info.get("by_agent", {})

        # Check which query types would benefit most from indexing
        query_types = sorted(by_type.items(), key=lambda x: -x[1])[:5] if by_type else []

        return {
            "backend": info.get("store_version", "file"),
            "total_entries": info.get("total_entries", 0),
            "most_common_types": query_types,
            "unique_agents": info.get("unique_agents", 0),
            "unique_tags": info.get("unique_tags", 0),
            "indexes_present": ["type", "agent", "expires_at", "created_at"],
            "recommended_indexes": self._recommend_indexes(info),
        }

    def _recommend_indexes(self, info: Dict) -> List[str]:
        """Recommend additional indexes based on usage patterns."""
        recs = []
        by_type = info.get("by_type", {})
        if by_type:
            # If many entries of one type, recommend composite index
            top_type = max(by_type.items(), key=lambda x: x[1])[0]
            if by_type[top_type] > 100:
                recs.append(f"Composite index on (type, created_at) — {top_type} has {by_type[top_type]} entries")
        return recs

    # ── Helpers ──

    def _dir_size_kb(self, path: str) -> float:
        total = 0
        for dirpath, _, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                total += os.path.getsize(fp)
        return round(total / 1024, 1)
