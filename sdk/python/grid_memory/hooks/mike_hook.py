"""
mike_hook.py — Auto-wiring for MIKE sessions.

Called automatically when MIKE starts a session. Writes session context
to the Grid so every MIKE interaction is captured as memory.

Add to MIKE's session init:
  from grid_memory.hooks.mike_hook import MikeGridHook
  MikeGridHook().on_session_start("client-acme")
"""

import datetime
import json
import os
import sys
from typing import Dict, Optional

from grid_memory.workspace import WorkspaceManager
from grid_memory.pipeline import PipelineOrchestrator


class MikeGridHook:
    """Auto-wires MIKE sessions into the Grid.

    Usage (in MIKE's session init):
        hook = MikeGridHook()
        hook.on_session_start(workspace_id="client-acme")
        hook.on_decision("Use PostgreSQL", rationale="Ecosystem", tags=["database"])
        hook.on_blocker("Database connection timeout")
        hook.on_session_end("Completed architecture review")
    """

    def __init__(self, auto_switch_workspace: bool = True):
        self.mgr = WorkspaceManager()
        self.grid = None
        self.pipe = None
        self.current_workspace = None

    def on_session_start(self, workspace_id: str = "") -> Dict:
        """Called when a MIKE session starts.

        Auto-switches to the right workspace, records the session,
        and runs a light pipeline scan.

        Args:
            workspace_id: Client workspace to use

        Returns:
            Dict with session context (decisions, blockers, lessons)
        """
        # Determine workspace
        ws = workspace_id or self.mgr.get_active()
        if not ws:
            return {"error": "No workspace specified or active"}

        self.current_workspace = ws

        try:
            self.grid = self.mgr.get_grid(ws)
        except ValueError:
            # Auto-create workspace if it doesn't exist
            self.mgr.create(ws)
            self.grid = self.mgr.get_grid(ws)

        self.mgr.set_active(ws)
        self.pipe = PipelineOrchestrator(self.grid, ws)

        # Record session start
        self.grid.fact(
            f"MIKE session started: {workspace_id or ws}",
            tags=["mike-session", f"workspace:{ws}"],
            agent_id="mike",
        )

        # Load recent context for this workspace
        recent = self.grid.query(max=20)
        context = {
            "workspace": ws,
            "session_started": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "recent_entries": [
                {"type": e.get("type"), "content": e.get("content", "")[:100],
                 "created_at": e.get("created_at")}
                for e in recent.get("entries", [])
            ],
            "decisions": [
                e.get("content", "")[:200] for e in recent.get("entries", [])
                if e.get("type") == "decision"
            ][-3:],
        }

        return context

    def on_decision(self, decision: str, rationale: str = "",
                    tags: Optional[list] = None) -> Dict:
        """Record a decision made during a MIKE session."""
        if not self.grid:
            return {"error": "No active workspace. Call on_session_start first."}

        result = self.grid.decide(
            decision,
            rationale=rationale,
            tags=(tags or []) + [f"workspace:{self.current_workspace}"],
            agent_id="mike",
        )
        return {"recorded": True, "id": result.get("entry_id")}

    def on_blocker(self, blocker: str, tags: Optional[list] = None) -> Dict:
        """Record a blocker encountered during a MIKE session."""
        if not self.grid:
            return {"error": "No active workspace"}

        result = self.grid.write(
            agent_id="mike",
            type="blocker",
            content=blocker,
            tags=(tags or []) + [f"workspace:{self.current_workspace}"],
        )
        return {"recorded": True, "id": result.get("entry_id")}

    def on_lesson(self, content: str, category: str = "worked",
                  severity: str = "insight") -> Dict:
        """Record a lesson learned during a MIKE session."""
        if not self.grid:
            return {"error": "No active workspace"}

        from grid_memory.lessons import LessonsEngine
        engine = LessonsEngine(self.grid)
        result = engine.add(
            content=content,
            category=category,
            severity=severity,
            client=self.current_workspace or "",
            agent="mike",
        )
        return {"recorded": True, "id": result.get("id")}

    def on_opportunity(self, title: str, description: str = "",
                       estimated_value: float = 0) -> Dict:
        """Record an opportunity identified during a MIKE session."""
        if not self.grid:
            return {"error": "No active workspace"}

        from grid_memory.opportunity_lifecycle import OpportunityLifecycle
        lifecycle = OpportunityLifecycle(self.grid)
        result = lifecycle.create(
            title=title,
            description=description,
            estimated_value=estimated_value,
            client=self.current_workspace or "",
            source="mike-session",
        )
        return {"recorded": True, "id": result.get("entry_id")}

    def on_session_end(self, summary: str = "") -> Dict:
        """Called when a MIKE session ends.

        Auto-extracts lessons, runs radar, and records the session end.
        """
        if not self.grid:
            return {"error": "No active workspace"}

        # Record end
        self.grid.fact(
            f"MIKE session ended: {summary or 'No summary'}",
            tags=["mike-session", f"workspace:{self.current_workspace}"],
            agent_id="mike",
        )

        # Auto-extract lessons from this session
        if self.pipe:
            self.pipe.full_loop(
                run_radar=False,
                extract_lessons=True,
                scan_patterns=False,
            )

        return {
            "ended": True,
            "workspace": self.current_workspace,
            "summary": summary,
        }

    def get_session_context(self, n_recent: int = 10) -> str:
        """Get a formatted context block for MIKE's system prompt.

        This is what MIKE reads at the start of every session to
        understand what's happened before.
        """
        if not self.grid:
            return "[Grid Memory] No active workspace."

        # Get recent entries
        result = self.grid.query(max=n_recent)
        entries = result.get("entries", [])
        info = self.grid.info()

        lines = [
            f"[Grid Memory] Workspace: {self.current_workspace}",
            f"[Grid Memory] Total entries: {info.get('total_entries', 0)}",
            f"[Grid Memory] Recent entries:",
        ]

        for e in entries[:5]:
            etype = e.get("type", "?")
            content = e.get("content", "")[:80].replace("\n", " ")
            lines.append(f"  [{etype}] {content}")

        return "\n".join(lines)


def auto_patch():
    """Auto-patch the calling session to use the Grid.

    Designed to be called from MIKE's session init without any config.
    """
    import inspect

    hook = MikeGridHook()

    # Try to determine the workspace from environment
    ws = os.environ.get("GRID_WORKSPACE", "")
    if ws:
        context = hook.on_session_start(ws)
        if "error" not in context:
            print(f"[Grid Memory] Wired to workspace: {ws}")
            print(f"[Grid Memory] {context.get('recent_entries', [])} recent entries")
            return hook

    # Try active workspace
    active = hook.mgr.get_active()
    if active:
        context = hook.on_session_start(active)
        print(f"[Grid Memory] Wired to workspace: {active}")
        return hook

    print("[Grid Memory] No workspace configured. Set GRID_WORKSPACE or use grid workspace switch.")
    return hook
