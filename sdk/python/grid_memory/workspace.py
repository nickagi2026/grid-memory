"""
workspace.py — Client Memory Spaces (multi-tenant isolation).

Each client/project gets its own isolated Grid workspace with:
- Separate store file (data/<workspace>/store.json)
- Separate SQLite database if using SQLite backend
- No cross-tenant data leakage at the storage layer
- CLI commands scoped to active workspace

Usage:
    from grid_memory.workspace import WorkspaceManager

    mgr = WorkspaceManager(base_dir="./data")
    mgr.create("client-acme-corp")
    mgr.list()
    grid = mgr.get_grid("client-acme-corp")
    grid.fact("Decision: use PostgreSQL", tags=["architecture"], agent_id="arch")
"""

import datetime
import json
import os
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any

from grid_memory.local_grid import LocalGrid

# ─── Workspace Manager ─────────────────────────────────────────────────────────


class WorkspaceManager:
    """Manages isolated client workspaces.

    Each workspace has its own store directory. The manager handles
    creation, listing, switching, and provides scoped LocalGrid instances.

    Args:
        base_dir: Root directory for all workspaces (default: ~/.openclaw/grid-workspaces)
    """

    def __init__(self, base_dir: Optional[str] = None):
        self.base_dir = base_dir or os.path.join(
            os.path.expanduser("~"), ".openclaw", "grid-workspaces"
        )
        # The active workspace is tracked via env var, file, or parameter
        self._active: Optional[str] = None
        self._cache: Dict[str, LocalGrid] = {}

    # ── Workspace CRUD ──

    def create(self, workspace_id: str, label: str = "",
               backend: str = "file") -> Dict:
        """Create a new isolated workspace.

        Args:
            workspace_id: Unique identifier (e.g. "client-acme-corp")
            label: Human-readable label (e.g. "Acme Corp")
            backend: Storage backend ("file" or "sqlite")

        Returns:
            Dict with workspace info
        """
        if not workspace_id or not workspace_id.strip():
            return {"success": False, "reason": "Workspace ID is required"}

        # Validate ID (alphanumeric, hyphens, underscores only)
        import re
        if not re.match(r'^[a-zA-Z0-9_-]+$', workspace_id):
            return {"success": False, "reason": "Use only letters, numbers, hyphens, underscores"}

        workspace_dir = self._workspace_dir(workspace_id)
        if os.path.exists(workspace_dir):
            return {"success": False, "reason": f"Workspace '{workspace_id}' already exists"}

        os.makedirs(workspace_dir, exist_ok=True)

        # Create workspace metadata
        meta = {
            "id": workspace_id,
            "label": label or workspace_id,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "backend": backend,
            "entry_count": 0,
        }
        with open(os.path.join(workspace_dir, "workspace.json"), "w") as f:
            json.dump(meta, f, indent=2)

        # Initialize the store
        grid = self._create_grid(workspace_id, backend)
        grid.info()  # forces store creation

        self._cache[workspace_id] = grid

        return {
            "success": True,
            "workspace_id": workspace_id,
            "label": meta["label"],
            "path": workspace_dir,
            "backend": backend,
        }

    def list(self) -> List[Dict]:
        """List all workspaces with metadata."""
        workspaces = []
        if not os.path.exists(self.base_dir):
            return workspaces

        for item in sorted(os.listdir(self.base_dir)):
            workspace_dir = os.path.join(self.base_dir, item)
            meta_path = os.path.join(workspace_dir, "workspace.json")
            if os.path.isdir(workspace_dir) and os.path.exists(meta_path):
                with open(meta_path) as f:
                    meta = json.load(f)
                # Get live stats
                try:
                    grid = self.get_grid(item)
                    info = grid.info()
                    meta["entry_count"] = info.get("total_entries", 0)
                    meta["alive_count"] = info.get("alive_entries", 0)
                except Exception:
                    meta["entry_count"] = 0
                    meta["alive_count"] = 0
                workspaces.append(meta)

        return workspaces

    def get_grid(self, workspace_id: str) -> LocalGrid:
        """Get a LocalGrid instance scoped to a workspace.

        The Grid instance is cached — same instance per workspace.
        """
        # Return from cache if available
        if workspace_id in self._cache:
            return self._cache[workspace_id]

        workspace_dir = self._workspace_dir(workspace_id)
        if not os.path.exists(workspace_dir):
            raise ValueError(f"Workspace '{workspace_id}' not found. Create it first.")

        # Read workspace metadata for backend type
        meta_path = os.path.join(workspace_dir, "workspace.json")
        backend = "file"
        if os.path.exists(meta_path):
            with open(meta_path) as f:
                meta = json.load(f)
                backend = meta.get("backend", "file")

        grid = self._create_grid(workspace_id, backend)
        self._cache[workspace_id] = grid
        return grid

    def delete(self, workspace_id: str, confirm: bool = False) -> Dict:
        """Delete a workspace and all its data."""
        workspace_dir = self._workspace_dir(workspace_id)
        if not os.path.exists(workspace_dir):
            return {"success": False, "reason": f"Workspace '{workspace_id}' not found"}

        if not confirm:
            return {"success": False, "reason": "Confirmation required. Pass confirm=True"}

        import shutil
        shutil.rmtree(workspace_dir)

        if workspace_id in self._cache:
            del self._cache[workspace_id]

        return {"success": True, "workspace_id": workspace_id, "deleted": True}

    def get_active(self) -> Optional[str]:
        """Get the currently active workspace."""
        if self._active:
            return self._active
        # Check env var
        env_ws = os.environ.get("GRID_WORKSPACE", "")
        if env_ws:
            return env_ws
        # Check .grid-workspace file in current directory
        ws_file = os.path.join(os.getcwd(), ".grid-workspace")
        if os.path.exists(ws_file):
            with open(ws_file) as f:
                return f.read().strip()
        return None

    def set_active(self, workspace_id: Optional[str]):
        """Set the active workspace."""
        self._active = workspace_id
        # Also persist to env for subprocesses
        if workspace_id:
            os.environ["GRID_WORKSPACE"] = workspace_id
        elif "GRID_WORKSPACE" in os.environ:
            del os.environ["GRID_WORKSPACE"]

    def get_stats(self) -> Dict:
        """Get cross-workspace statistics."""
        workspaces = self.list()
        total_entries = sum(w.get("entry_count", 0) for w in workspaces)
        total_alive = sum(w.get("alive_count", 0) for w in workspaces)

        return {
            "workspace_count": len(workspaces),
            "total_entries": total_entries,
            "total_alive": total_alive,
            "workspaces": workspaces,
        }

    # ── Internal ──

    def _workspace_dir(self, workspace_id: str) -> str:
        return os.path.join(self.base_dir, workspace_id)

    def _create_grid(self, workspace_id: str, backend: str = "file") -> LocalGrid:
        """Create a LocalGrid configured for a specific workspace."""
        workspace_dir = self._workspace_dir(workspace_id)
        os.makedirs(workspace_dir, exist_ok=True)

        if backend == "sqlite":
            from grid_memory.sqlite_backend import SQLiteBackend
            db_path = os.path.join(workspace_dir, "grid.db")
            return LocalGrid(backend=SQLiteBackend(db_path))
        else:
            return LocalGrid(store_dir=workspace_dir)


# ─── CLI Integration ───────────────────────────────────────────


def cmd_workspace(args):
    """Manage client workspaces."""
    mgr = WorkspaceManager()

    action = args.ws_action or "list"

    if action == "create":
        ws_id = args.ws_id
        if not ws_id:
            print("\n  Workspace ID required\n")
            return
        result = mgr.create(ws_id, label=args.label or ws_id, backend=args.backend or "file")
        if result.get("success"):
            print(f"\n  Workspace '{ws_id}' created")
            print(f"  Path: {result['path']}")
            print(f"  Backend: {result['backend']}\n")
        else:
            msg = result.get("reason", "Failed")
            print(f"\n  {msg}\n")

    elif action == "list":
        workspaces = mgr.list()
        if not workspaces:
            print("\n  No workspaces yet. Create one: grid workspace create <id>")
            print()
            return
        print(f"\n  Workspaces ({len(workspaces)})")
        print(f"  {'-' * 60}")
        for ws in workspaces:
            active = " [ACTIVE]" if ws["id"] == mgr.get_active() else ""
            print(f"  {ws['id']}{active}")
            print(f"    Label: {ws.get('label', ws['id'])}")
            print(f"    Entries: {ws.get('entry_count', 0)} ({ws.get('alive_count', 0)} alive)")
            print(f"    Backend: {ws.get('backend', 'file')}")
            print()

    elif action == "switch":
        ws_id = args.ws_id
        if not ws_id:
            print("\n  Workspace ID required\n")
            return
        try:
            mgr.get_grid(ws_id)
            mgr.set_active(ws_id)
            with open(os.path.join(os.getcwd(), ".grid-workspace"), "w") as f:
                f.write(ws_id)
            print(f"\n  Switched to workspace '{ws_id}'\n")
        except ValueError as e:
            print(f"\n  {e}\n")

    elif action == "info":
        ws_id = args.ws_id or mgr.get_active()
        if not ws_id:
            print("\n  No active workspace.\n")
            return
        try:
            grid = mgr.get_grid(ws_id)
            info = grid.info()
            print(f"\n  Workspace: {ws_id}")
            print(f"  Entries: {info.get('total_entries', 0)}")
            print(f"  Alive:   {info.get('alive_entries', 0)}")
            print(f"  Agents:  {info.get('unique_agents', 0)}")
            print(f"  Tags:    {info.get('unique_tags', 0)}")
            print(f"  Size:    {info.get('store_size_kb', 0)} KB\n")
        except ValueError as e:
            print(f"\n  {e}\n")

    elif action == "delete":
        ws_id = args.ws_id
        if not ws_id:
            print("\n  Workspace ID required\n")
            return
        result = mgr.delete(ws_id, confirm=args.confirm)
        if result.get("success"):
            print(f"\n  Deleted workspace '{ws_id}'\n")
        else:
            msg = result.get("reason", "Failed")
            print(f"\n  {msg}")
            print(f"  Add --confirm to delete\n")

    elif action == "stats":
        stats = mgr.get_stats()
        print(f"\n  Workspace Stats")
        print(f"  Workspaces: {stats['workspace_count']}")
        print(f"  Total entries: {stats['total_entries']}")
        print(f"  Total alive:   {stats['total_alive']}\n")
