"""
pipeline.py — Operational Loop Orchestrator.

Closes the loop automatically:

  Engagement change → Lesson extraction → Pattern promotion → Opportunity radar → QBR generation

Every client engagement becomes a self-reinforcing intelligence loop
without manual intervention.
"""

import datetime
import json
import os
import threading
import time
from typing import Dict, List, Optional, Any

from grid_memory.local_grid import LocalGrid
from grid_memory.workspace import WorkspaceManager
from grid_memory.engagement import EngagementGraph
from grid_memory.lessons import LessonsEngine
from grid_memory.patterns import PatternEngine
from grid_memory.opportunity_radar import OpportunityRadar
from grid_memory.opportunity_lifecycle import OpportunityLifecycle


class PipelineOrchestrator:
    """Orchestrates the full operational loop across all Grid features.

    Args:
        grid: LocalGrid instance (scoped to a workspace/client)
        client: Client identifier
    """

    def __init__(self, grid: LocalGrid, client: str = ""):
        self.grid = grid
        self.client = client
        self.engagement = EngagementGraph(grid)
        self.lessons = LessonsEngine(grid)
        self.patterns = PatternEngine(grid)
        self.radar = OpportunityRadar(grid)
        self.lifecycle = OpportunityLifecycle(grid)

    def full_loop(self, run_radar: bool = True,
                  extract_lessons: bool = True,
                  scan_patterns: bool = True) -> Dict:
        """Run the full operational loop and return results.

        Args:
            run_radar: Run opportunity radar scan
            extract_lessons: Auto-extract lessons from entries
            scan_patterns: Scan for patterns

        Returns:
            Dict with all loop results
        """
        results = {
            "client": self.client,
            "ran_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "engagement": None,
            "radar": None,
            "lessons": None,
            "patterns": None,
            "pipeline_value": 0,
        }

        # 1. Get current engagement state
        if self.client:
            eng = self.engagement.get_engagement(self.client)
            results["engagement"] = eng
            results["pipeline_value"] = eng.get("total_activities", 0)

        # 2. Run opportunity radar
        if run_radar:
            radar_results = self.radar.scan()
            results["radar"] = {
                "opportunities_found": radar_results.get("total_opportunities", 0),
                "total_value": radar_results.get("total_annual_value", 0),
            }
            # Auto-create lifecycle opportunities from radar
            for opp in radar_results.get("opportunities", [])[:5]:
                self.lifecycle.create_from_radar(opp)
            results["pipeline_value"] += radar_results.get("total_annual_value", 0)

        # 3. Extract lessons
        if extract_lessons:
            lessons_result = self.lessons.auto_extract(
                project=self.client,
                client=self.client,
            )
            results["lessons"] = {
                "extracted": lessons_result.get("total", 0),
                "by_category": {
                    k: len(v) for k, v in lessons_result.items()
                    if k != "total" and isinstance(v, list)
                },
            }

        # 4. Scan for patterns
        if scan_patterns:
            pattern_result = self.patterns.scan(
                domain=self.client,
                min_occurrences=2,
            )
            results["patterns"] = {
                "found": pattern_result.get("total", 0),
                "promotion_candidates": len(pattern_result.get("promotion_candidates", [])),
            }

        return results

    def on_engagement_change(self, client: str, phase: str,
                             activity: str) -> Dict:
        """Trigger when an engagement phase changes.

        Auto-runs radar + lessons + patterns.
        """
        # Record the activity
        self.engagement.track(client, phase, activity, "", "pipeline")

        # Auto-extract on phase changes that indicate progress
        extract_phases = ["assessment", "build", "deploy", "operate"]
        if phase in extract_phases:
            self.lessons.auto_extract(project=client, client=client)

        # Run radar on key phases
        radar_phases = ["discovery", "expand"]
        if phase in radar_phases:
            radar_result = self.radar.scan()
            for opp in radar_result.get("opportunities", [])[:5]:
                self.lifecycle.create_from_radar(opp)

        # Pattern scan on major milestones
        pattern_phases = ["deploy", "operate"]
        if phase in pattern_phases:
            self.patterns.scan(domain=client, min_occurrences=2)

        return {
            "client": client,
            "phase": phase,
            "activity": activity,
            "triggered_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

    def generate_client_report(self, quarter: str = "") -> Dict:
        """Generate a complete client intelligence report.

        Combines: QBR + lessons summary + pattern report + radar scan.
        """
        # QBR
        qbr = self.engagement.generate_qbr(self.client, quarter)

        # Lessons summary
        lesson_summary = self.lessons.summary(client=self.client)

        # Patterns
        pattern_result = self.patterns.scan(domain=self.client)

        # Radar
        radar_result = self.radar.scan()

        # Pipeline
        pipeline = self.lifecycle.get_pipeline(client=self.client)

        return {
            "client": self.client,
            "quarter": quarter or "current",
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "qbr": qbr,
            "lessons": lesson_summary,
            "patterns": {
                "total": pattern_result.get("total", 0),
                "promotion_candidates": len(pattern_result.get("promotion_candidates", [])),
            },
            "radar": {
                "opportunities": radar_result.get("total_opportunities", 0),
                "annual_value": radar_result.get("total_annual_value", 0),
            },
            "pipeline": pipeline.get("summary", {}),
        }


# ─── Auto-Scheduler (background QBR generation) ───────────────────────────────


class AutoScheduler:
    """Background scheduler for periodic Grid operations.

    Currently supports: auto-QBR generation for all active clients.

    Args:
        mgr: WorkspaceManager instance
        interval_hours: How often to run scheduled tasks
    """

    def __init__(self, mgr: WorkspaceManager, interval_hours: int = 24):
        self.mgr = mgr
        self.interval_hours = interval_hours
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()

    def start(self):
        """Start the background scheduler."""
        if self._running:
            return False
        self._running = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        """Stop the background scheduler."""
        if not self._running:
            return False
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        self._running = False
        return True

    @property
    def is_running(self) -> bool:
        return self._running

    def _run_loop(self):
        """Run the scheduled loop."""
        last_qbr: Dict[str, str] = {}

        while not self._stop.is_set():
            try:
                workspaces = self.mgr.list()
                now = datetime.datetime.now(datetime.timezone.utc).isoformat()

                for ws in workspaces:
                    ws_id = ws.get("id", "")
                    if not ws_id:
                        continue

                    # Check if QBR is due (weekly for active clients)
                    last = last_qbr.get(ws_id, "")
                    if not last or self._is_qbr_due(last):
                        try:
                            grid = self.mgr.get_grid(ws_id)
                            pipe = PipelineOrchestrator(grid, ws_id)
                            result = pipe.generate_client_report()
                            # Write QBR to Grid
                            grid.fact(
                                f"Auto-QBR: {ws_id} — "
                                f"{result.get('radar', {}).get('opportunities', 0)} opportunities, "
                                f"${result.get('radar', {}).get('annual_value', 0):,.0f}/yr identified",
                                tags=["auto-qbr", f"client:{ws_id}"],
                                agent_id="auto-scheduler",
                            )
                            last_qbr[ws_id] = now
                        except Exception as e:
                            pass  # Skip failed workspaces

            except Exception:
                pass  # Don't crash the loop

            # Sleep with interrupt check
            for _ in range(self.interval_hours * 60):
                if self._stop.is_set():
                    return
                time.sleep(60)

    def _is_qbr_due(self, last_run: str) -> bool:
        """Check if a QBR is due (weekly)."""
        try:
            last_dt = datetime.datetime.fromisoformat(last_run.replace("Z", "+00:00"))
            days_since = (datetime.datetime.now(datetime.timezone.utc) - last_dt).days
            return days_since >= 7
        except (ValueError, AttributeError):
            return True


# ─── CLI Integration ───────────────────────────────────────────────────────────


def cmd_pipeline(args):
    """Run the full operational loop."""
    from grid_memory.workspace import WorkspaceManager
    mgr = WorkspaceManager()

    # Determine client/workspace
    client = args.client or mgr.get_active()
    if not client:
        print("\n  No client specified. Use --client or switch to a workspace.\n")
        return

    try:
        grid = mgr.get_grid(client)
    except ValueError:
        print(f"\n  Workspace '{client}' not found. Create it: grid workspace create {client}\n")
        return

    pipe = PipelineOrchestrator(grid, client)

    action = args.pipe_action or "run"

    if action == "run":
        print(f"\n  Running full operational loop for {client}...\n")
        result = pipe.full_loop(
            run_radar=not args.no_radar,
            extract_lessons=not args.no_lessons,
            scan_patterns=not args.no_patterns,
        )

        eng = result.get("engagement")
        if eng:
            print(f"  Engagement: {eng.get('total_activities', 0)} activities, "
                  f"phase: {eng.get('current_phase', 'none')}")

        radar = result.get("radar")
        if radar:
            print(f"  Radar: {radar.get('opportunities_found', 0)} opportunities "
                  f"(${radar.get('total_value', 0):,.0f}/yr)")

        lessons = result.get("lessons")
        if lessons:
            cat = lessons.get("by_category", {})
            print(f"  Lessons extracted: {lessons.get('extracted', 0)} "
                  f"({', '.join(f'{k}: {v}' for k,v in cat.items())})")

        patterns = result.get("patterns")
        if patterns:
            print(f"  Patterns found: {patterns.get('found', 0)} "
                  f"({patterns.get('promotion_candidates', 0)} promotion candidates)")

        print(f"\n  Pipeline value: ${result.get('pipeline_value', 0):,.0f}\n")

    elif action == "track":
        phase = args.phase or "discovery"
        activity = args.activity or f"Phase: {phase}"
        result = pipe.on_engagement_change(client, phase, activity)
        print(f"\n  Tracked: {client} → {result['phase']}: {activity}\n")

    elif action == "report":
        report = pipe.generate_client_report(quarter=args.quarter or "")
        print(f"\n  Client Report: {client}")
        print(f"  {'─' * 50}")
        print(f"  Opportunities: {report['radar']['opportunities']} "
              f"(${report['radar']['annual_value']:,.0f}/yr)")
        print(f"  Lessons: {report['lessons'].get('total', 0)}")
        print(f"  Patterns: {report['patterns']['total']}")
        print(f"  Pipeline: {report['pipeline'].get('total_opportunities', 0)} opps, "
              f"${report['pipeline'].get('total_pipeline_value', 0):,.0f}\n")

    elif action == "auto":
        sched = AutoScheduler(mgr, interval_hours=args.interval or 24)
        if args.stop:
            sched.stop()
            print("\n  Auto-scheduler stopped\n")
        else:
            sched.start()
            print(f"\n  Auto-scheduler started (interval: {args.interval or 24}h)\n")
            print(f"  Runs: auto-QBR generation for all active clients")
            print(f"  Stop with: grid pipeline auto --stop\n")

    else:
        print("\n  Use: pipeline run|track|report|auto\n")
