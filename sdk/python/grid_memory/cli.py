#!/usr/bin/env python3
"""
grid — Grid Memory CLI

Usage:
    grid init                 Initialize a new Grid store in current directory
    grid start                Start embedded server + proxy
    grid write                Write an entry (interactive or flags)
    grid query                Search entries (tag, semantic, or natural)
    grid info                 Show store statistics
    grid log                  Show recent activity
    grid prune                Remove expired entries
    grid patch                Auto-detect and patch framework
    grid ui                   Open dashboard URL
"""

import argparse
import json
import os
import sys
import textwrap
import time
from datetime import datetime
from typing import Dict, List, Optional, Any

# ─── ANSI Colors ────────────────────────────────────────────────────────────────

try:
    # Windows
    if sys.platform == "win32":
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
except Exception:
    pass

_COLORS = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[91m",
    "green": "\033[92m",
    "yellow": "\033[93m",
    "blue": "\033[94m",
    "magenta": "\033[95m",
    "cyan": "\033[96m",
    "white": "\033[97m",
    "bg_blue": "\033[44m",
    "bg_green": "\033[42m",
    "bg_yellow": "\033[43m",
}


def c(code: str, text: str) -> str:
    """Wrap text in ANSI color code."""
    c = _COLORS.get(code, "")
    return f"{c}{text}{_COLORS['reset']}" if c else text


# ─── Type Icons ─────────────────────────────────────────────────────────────────

_TYPE_ICONS = {
    "decision": "\U0001f9e9",   # 🧩
    "fact": "\U0001f4a1",       # 💡
    "handoff": "\U0001f500",    # 🔀
    "question": "\u2753",       # ❓
    "blocker": "\u26a0\ufe0f",  # ⚠️
    "observation": "\U0001f50d", # 🔍
    "task_status": "\U0001f4cb", # 📋
    "artifact_ref": "\U0001f4c4", # 📄
    "state_update": "\U0001f504", # 🔄
}

_TYPE_COLORS = {
    "decision": "magenta",
    "fact": "green",
    "handoff": "cyan",
    "question": "yellow",
    "blocker": "red",
    "observation": "blue",
    "task_status": "white",
    "artifact_ref": "dim",
    "state_update": "cyan",
}


# ─── Backend ────────────────────────────────────────────────────────────────────

def _get_grid(args=None):
    """Create LocalGrid from args or defaults."""
    from grid_memory.local_grid import LocalGrid
    from grid_memory.workspace import WorkspaceManager

    store_dir = None

    # Check for workspace override
    ws_id = None
    if args and hasattr(args, 'ws_id') and args.ws_id:
        ws_id = args.ws_id
    if not ws_id and args and hasattr(args, 'workspace') and args.workspace:
        ws_id = args.workspace

    if ws_id:
        mgr = WorkspaceManager()
        try:
            return mgr.get_grid(ws_id)
        except ValueError:
            print(f"  Workspace '{ws_id}' not found. Create it: grid workspace create {ws_id}")
            import sys
            sys.exit(1)

    if args and args.dir:
        store_dir = args.dir
    else:
        # Check active workspace
        mgr = WorkspaceManager()
        active = mgr.get_active()
        if active:
            try:
                return mgr.get_grid(active)
            except ValueError:
                pass

        # Check for .grid.json in current directory
        local_config = os.path.join(os.getcwd(), ".grid.json")
        if os.path.exists(local_config):
            with open(local_config) as f:
                cfg = json.load(f)
                store_dir = cfg.get("store_dir")

    return LocalGrid(store_dir=store_dir)


def _get_grid_with_embeddings(args=None):
    """Create LocalGrid with embedding engine if configured."""
    from grid_memory.local_grid import LocalGrid
    grid = _get_grid(args)

    # Try to configure embeddings
    api_key = os.environ.get("GRID_EMBEDDING_API_KEY")
    if api_key:
        try:
            from grid_memory.embeddings import EmbeddingEngine
            ee = EmbeddingEngine(
                provider="openai",
                api_key=api_key,
            )
            # Inject into grid
            grid._embedding_engine = ee
        except Exception as e:
            print(f"  {c('yellow', '⚠ Embeddings configured but failed:')} {e}", file=sys.stderr)

    return grid


# ─── Output Formatters ──────────────────────────────────────────────────────────


def _format_entry(entry: Dict, verbose: bool = False) -> str:
    """Format a single entry for human-readable output."""
    etype = entry.get("type", "observation")
    icon = _TYPE_ICONS.get(etype, "\U0001f4ac")
    color = _TYPE_COLORS.get(etype, "white")
    created = entry.get("created_at", "")[11:19]  # HH:MM:SS
    agent = entry.get("agent_id", "?")
    content = entry.get("content", "")
    tags = entry.get("tags", [])
    has_emb = entry.get("has_embedding", False)
    score = entry.get("relevance_score")

    lines = [f"  {icon} {c(color, f'[{etype}]')} {c('dim', created)} — {c('cyan', agent)}"]
    if score is not None:
        lines[0] += f" {c('yellow', f'({score:.1f})')}"
    if has_emb:
        lines[0] += f" {c('green', '\u2728')}"  # ✨

    # Content preview
    if verbose:
        lines.append(f"    {content}")
    else:
        preview = content[:120].replace("\n", " ")
        if len(content) > 120:
            preview += "..."
        lines.append(f"    {preview}")

    if tags:
        tag_str = ", ".join(c("dim", f"#{t}") for t in tags)
        lines.append(f"    {tag_str}")

    return "\n".join(lines)


def _format_info(info: Dict) -> str:
    """Format store info as a nice table."""
    lines = [
        "",
        f"  {c('bold', 'Grid Store Summary')}",
        f"  {'─' * 40}",
        f"  {c('green', '\u25cf')} Total entries: {c('bold', str(info['total_entries']))}",
        f"  {c('green', '\u25cf')} Alive:         {c('bold', str(info['alive_entries']))}",
        f"  {c('red', '\u25cf')} Expired:       {c('dim', str(info['expired_entries']))}",
        f"  {c('blue', '\u25cf')} Unique agents: {c('bold', str(info['unique_agents']))}",
        f"  {c('yellow', '\u25cf')} Unique tags:   {c('bold', str(info['unique_tags']))}",
        f"  {c('dim', '\u25cf')} Store size:    {c('bold', str(info['store_size_kb']))} KB",
    ]
    if info.get("oldest_entry"):
        lines.append(
            f"  {c('dim', '\u25cf')} Range:         "
            f"{info['oldest_entry'][:10]} \u2192 {info['newest_entry'][:10]}"
        )

    # By type breakdown
    if info.get("by_type"):
        lines.extend([
            "",
            f"  {c('bold', 'By Type')}",
        ])
        for etype, count in sorted(info["by_type"].items(), key=lambda x: -x[1]):
            icon = _TYPE_ICONS.get(etype, "\U0001f4ac")
            color_code = _TYPE_COLORS.get(etype, "white")
            lines.append(f"    {icon} {c(color_code, etype)}: {count}")

    # By agent breakdown
    if info.get("by_agent"):
        lines.extend([
            "",
            f"  {c('bold', 'By Agent')}",
        ])
        for agent, count in sorted(info["by_agent"].items(), key=lambda x: -x[1]):
            lines.append(f"    {c('cyan', agent)}: {count}")

    return "\n".join(lines)


# ─── Commands ───────────────────────────────────────────────────────────────────


def cmd_init(args):
    """Initialize a new Grid store in the current or specified directory."""
    from grid_memory.local_grid import LocalGrid

    store_dir = args.dir or os.path.join(os.getcwd(), ".grid")
    os.makedirs(store_dir, exist_ok=True)
    grid = LocalGrid(store_dir=store_dir)

    # Create .grid.json config
    config_path = os.path.join(os.getcwd(), ".grid.json")
    config = {
        "store_dir": store_dir,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "version": 1,
    }
    with open(config_path, "w") as f:
        json.dump(config, f, indent=2)

    print(f"  {c('green', '\u2713')} Grid initialized at {c('bold', store_dir)}")
    print(f"  {c('dim', '.grid.json config created')}")


def cmd_start(args):
    """Start the embedded server + OpenAI proxy."""
    port = args.port or int(os.environ.get("PORT", "8080"))
    host = args.host or os.environ.get("HOST", "0.0.0.0")

    print(f"  {c('green', '\u25b6')} Starting Grid server on {c('bold', f'http://{host}:{port}')}")
    print(f"  {c('green', '\u25b6')} OpenAI-compatible endpoint: {c('bold', f'http://{host}:{port}/v1')}")
    print(f"  {c('dim', 'Dashboard: http://localhost:' + str(port) + '/dashboard/index.html')}")
    print()

    # Import and start server
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from grid_memory.openai_server import run_server

    os.environ["PORT"] = str(port)
    os.environ["HOST"] = host
    run_server()


def cmd_write(args):
    """Write an entry to the Grid."""
    grid = _get_grid(args)

    content = args.content
    if not content:
        content = input("  Content: ")

    etype = args.type or "observation"
    agent = args.agent or "cli"
    tags = args.tags.split(",") if args.tags else []

    result = grid.write(
        agent_id=agent,
        type=etype,
        content=content,
        tags=tags,
        ttl_seconds=args.ttl,
    )

    print(f"  {c('green', '\u2713')} Written {c('bold', result['entry_id'])}")
    print(f"    Type: {result['type']}  Agent: {c('cyan', result['agent_id'])}")
    if tags:
        print(f"    Tags: {', '.join(c('dim', f'#{t}') for t in tags)}")


def cmd_query(args):
    """Query the Grid."""
    grid = _get_grid_with_embeddings(args)

    tags = args.tags.split(",") if args.tags else []
    agents = args.agents.split(",") if args.agents else []
    query_type = args.type
    max_results = args.max or 20

    if args.natural:
        # Natural language query — use semantic search
        result = grid.query(
            semantic=args.natural,
            max=max_results,
            semantic_weight=min(args.weight or 0.7, 1.0),
        )

        meta = result["query_meta"]
        if meta.get("semantic_available"):
            print(f"\n  {c('bold', 'Semantic Search')}")
            print(f"  Query: \"{args.natural}\"")
            print(f"  {c('dim', 'Searching by meaning...')}\n")
        else:
            print(f"\n  {c('yellow', '⚠ No embedding engine configured')}")
            print(f"  {c('dim', 'Set GRID_EMBEDDING_API_KEY for semantic search')}\n")
    else:
        # Tag-based query
        result = grid.query(
            tags=tags,
            agents=agents,
            type=query_type,
            max=max_results,
        )

    entries = result.get("entries", [])
    meta = result.get("query_meta", {})

    if not entries:
        print(f"\n  {c('yellow', 'No matching entries found')}")
        return

    total_filtered = meta.get("total_before_filter", "?")
    print(f"\n  {c('bold', f'Found {len(entries)} entries')} "
          f"{c('dim', f'(filtered from {total_filtered})')}")

    for entry in entries:
        print()
        print(_format_entry(entry, verbose=args.verbose))

    print()


def cmd_info(args):
    """Show store statistics."""
    grid = _get_grid(args)
    info = grid.info()
    print(_format_info(info))
    print()


def cmd_log(args):
    """Show recent activity."""
    grid = _get_grid(args)
    max_entries = args.max or 20

    result = grid.query(max=max_entries)
    entries = result.get("entries", [])

    if not entries:
        print(f"\n  {c('yellow', 'No entries yet')}")
        return

    print(f"\n  {c('bold', 'Recent Activity')}\n")
    for entry in entries:
        print(_format_entry(entry, verbose=args.verbose))
        print()


def cmd_prune(args):
    """Remove expired entries."""
    grid = _get_grid(args)
    result = grid.prune()
    pruned = result.get("removed", 0)
    print(f"\n  {c('green', f'\u2713 Pruned {pruned} expired entries')}")
    remaining_count = result.get("remaining", 0)
    print(f"  {c('dim', f'{remaining_count} entries remaining')}\n")


def cmd_patch(args):
    """Auto-detect and patch the running agent framework."""
    # Detect framework
    framework = None
    framework_detected = False

    try:
        import autogen
        framework = "AutoGen"
        framework_detected = True
    except ImportError:
        pass

    if not framework_detected:
        try:
            import crewai
            framework = "CrewAI"
            framework_detected = True
        except ImportError:
            pass

    if not framework_detected:
        try:
            from langgraph.graph import StateGraph
            framework = "LangGraph"
            framework_detected = True
        except ImportError:
            pass

    if not framework_detected:
        try:
            import langchain
            framework = "LangChain"
            framework_detected = True
        except ImportError:
            pass

    if not framework_detected:
        print(f"\n  {c('yellow', 'No supported framework detected.')}")
        print(f"  {c('dim', 'Install one: pip install pyautogen crewai langgraph langchain')}\n")
        return

    print(f"\n  {c('green', f'\u2713 Detected: {framework}')}")

    from grid_memory.local_grid import LocalGrid
    grid = LocalGrid()

    if framework == "AutoGen":
        import autogen
        from grid_memory import AutoGenGridPlugin
        plugin = AutoGenGridPlugin(agent_id=args.agent or "patched-agent")
        print(f"  {c('dim', 'Usage:')}")
        print(f"    agent = autogen.AssistantAgent(name='agent', llm_config=llm_config)")
        print(f"    agent = plugin.wrap(agent)")

    elif framework == "CrewAI":
        from grid_memory import CrewAITool
        tool = CrewAITool(agent_id=args.agent or "patched-agent")
        print(f"  {c('dim', 'Usage:')}")
        print(f"    tool = CrewAITool()")
        print(f"    agent = Agent(name='agent', tools=[tool.query_tool(), tool.write_tool()])")

    elif framework == "LangGraph":
        from grid_memory import langgraph_grid_node
        print(f"  {c('dim', 'Usage:')}")
        print(f"    inject = langgraph_grid_node()")
        print(f"    graph.add_node('grid_inject', inject)")

    elif framework == "LangChain":
        print(f"  {c('dim', 'Usage:')}")
        print(f"    # Set OpenAI-compatible base_url on your LLM:")
        print(f"    llm = ChatOpenAI(base_url='http://localhost:8080/v1', model='gpt-4o')")

    print(f"\n  {c('green', f'Ready to patch {framework} agents with Grid memory.')}")
    print()


def cmd_curate(args):
    """Run one curation pass on the Grid."""
    from grid_memory.curator import GridCurator
    grid = _get_grid(args)
    curator = GridCurator(grid=grid)
    report = curator.curate()

    print(f"\n  {c('bold', 'Curation Report')}")
    print(f"  {'─' * 40}")
    print(f"  {c('green', '\u2713')} Archived:         {c('bold', str(report['archived']))}")
    print(f"  {c('green', '\u2713')} Merged groups:    {c('bold', str(len(report['merged'])))}")
    for merge in report['merged']:
        print(f"    {c('dim', f"survivor: {merge['survivor'][:24]}...")}")
        for deleted in merge['deleted']:
            print(f"    {c('dim', f'  \u2717 deleted: {deleted[:24]}...')}")
    print(f"  {c('green', '\u2713')} Summaries written: {c('bold', str(report['summaries_written']))}")
    print(f"  {c('green', '\u2713')} Contradictions:   {c('bold', str(report['contradictions_flagged']))}")
    print(f"  {c('green', '\u2713')} Tags suggested:   {c('bold', str(report['tags_suggested']))}")
    print(f"  {c('dim', f'Archived total: {curator.archive_count()}')}")
    print()


def cmd_ui(args):
    """Open the dashboard URL."""
    port = args.port or "8080"
    url = f"http://localhost:{port}/dashboard/index.html"
    print(f"\n  {c('green', '\u25b6')} Dashboard: {c('bold', url)}\n")

    # Try to open browser
    import webbrowser
    try:
        webbrowser.open(url)
        print(f"  {c('dim', 'Browser opened.')}")
    except Exception:
        print(f"  {c('yellow', 'Open manually:')} {url}\n")


# ─── Main Parser ────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Grid Memory — shared persistent memory for multi-agent teams",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              grid init
              grid write --agent architect --type decision --content "Use PostgreSQL" --tags database
              grid query --natural "what database do we use?"
              grid query --tags database --verbose
              grid info
              grid start
              grid ui
              grid patch
              grid curate
        """),
    )
    parser.add_argument("--dir", help="Grid store directory")
    parser.add_argument("--version", action="store_true", help="Show version")

    sub = parser.add_subparsers(dest="command")

    # init
    p_init = sub.add_parser("init", help="Initialize a Grid store")
    p_init.add_argument("--dir", help="Store directory (default: ./.grid)")

    # start
    p_start = sub.add_parser("start", help="Start the embedded server and proxy")
    p_start.add_argument("--port", type=int, help="Port (default: 8080)")
    p_start.add_argument("--host", default="0.0.0.0", help="Host (default: 0.0.0.0)")

    # write
    p_write = sub.add_parser("write", help="Write an entry")
    p_write.add_argument("--agent", default="cli", help="Agent identifier")
    p_write.add_argument("--type", default="observation",
                        choices=["fact", "decision", "handoff", "observation",
                                 "question", "blocker", "task_status", "artifact_ref"])
    p_write.add_argument("--tags", help="Comma-separated tags")
    p_write.add_argument("--ttl", type=int, help="TTL in seconds")
    p_write.add_argument("content", nargs="?", help="Entry content")

    # query
    p_query = sub.add_parser("query", help="Search entries")
    p_query.add_argument("--tags", help="Comma-separated tags to filter")
    p_query.add_argument("--agents", help="Comma-separated agent IDs")
    p_query.add_argument("--type", help="Filter by entry type")
    p_query.add_argument("--natural", help="Natural language query (semantic search)")
    p_query.add_argument("--weight", type=float, default=0.7,
                        help="Semantic weight 0-1 (default: 0.7)")
    p_query.add_argument("--max", type=int, default=20, help="Maximum results")
    p_query.add_argument("--verbose", "-v", action="store_true", help="Show full content")

    # info
    p_info = sub.add_parser("info", help="Show store statistics")

    # log
    p_log = sub.add_parser("log", help="Show recent activity")
    p_log.add_argument("--max", type=int, default=20, help="Number of entries")
    p_log.add_argument("--verbose", "-v", action="store_true", help="Show full content")

    # prune
    p_prune = sub.add_parser("prune", help="Remove expired entries")

    # patch
    p_patch = sub.add_parser("patch", help="Auto-detect and patch framework")
    p_patch.add_argument("--agent", help="Agent name for patching")

    # ui
    p_ui = sub.add_parser("ui", help="Open dashboard in browser")
    p_ui.add_argument("--port", type=int, help="Grid server port")

    # curate
    p_curate = sub.add_parser("curate", help="Run one curation pass (archive, dedup, summarize, flag, suggest)")
    p_curate.add_argument("--dir", help="Grid store directory")
    p_curate.add_argument("--daemon", action="store_true", help="Run continuously in background")

    # tier (sub-commands handled in cmd_tier)
    p_tier = sub.add_parser("tier", help="Memory tier operations (use: tier list|promote|scan)")
    p_tier.add_argument("tier_command", nargs="?", choices=["list", "promote", "scan"], help="Sub-command")
    p_tier.add_argument("entry_id", nargs="?", help="Entry ID (for promote)")
    p_tier.add_argument("tier", nargs="?", choices=["project", "organization"], help="Target tier (for promote)")
    p_tier.add_argument("--dry-run", action="store_true", help="Preview promotions without acting")
    p_tier.add_argument("--dir", help="Store directory")

    # analyze
    p_analyze = sub.add_parser("analyze", help="Run pattern analysis on the Grid")
    p_analyze.add_argument("--dir", help="Store directory")

    # insights
    p_insights = sub.add_parser("insights", help="Get ranked insights from the Grid")
    p_insights.add_argument("--min", type=float, default=0.3, help="Minimum confidence (0-1)")
    p_insights.add_argument("--dir", help="Store directory")

    # radar
    p_radar = sub.add_parser("radar", help="AI Opportunity Radar — find automation opportunities with $ value")
    p_radar.add_argument("--days", type=int, default=90, help="Analysis window in days")
    p_radar.add_argument("--min-confidence", type=float, default=0.3, help="Minimum confidence (0-1)")
    p_radar.add_argument("--min-value", type=float, default=500, help="Minimum annual value in $")
    p_radar.add_argument("--dir", help="Store directory")

    # opportunity
    p_opp = sub.add_parser("opportunity", help="Manage opportunity lifecycle")
    p_opp.add_argument("opp_action", nargs="?", choices=["list", "show", "advance", "stats"],
                       help="Action: list|show|advance|stats")
    p_opp.add_argument("id", nargs="?", help="Opportunity ID (for show/advance)")
    p_opp.add_argument("to_stage", nargs="?", help="Target stage (for advance)")
    p_opp.add_argument("--notes", "-n", help="Transition notes")
    p_opp.add_argument("--stage", help="Filter by stage (for list)")
    p_opp.add_argument("--dir", help="Store directory")

    # workspace
    p_ws = sub.add_parser("workspace", help="Manage client workspaces (multi-tenant)")
    p_ws.add_argument("ws_action", nargs="?",
                      choices=["create", "list", "switch", "info", "delete", "stats"],
                      help="Action: create|list|switch|info|delete|stats")
    p_ws.add_argument("ws_id", nargs="?", help="Workspace ID")
    p_ws.add_argument("--label", "-l", help="Human-readable label")
    p_ws.add_argument("--backend", choices=["file", "sqlite"], default="file",
                      help="Storage backend")
    p_ws.add_argument("--confirm", action="store_true", help="Confirm deletion")
    p_ws.add_argument("--dir", help="Custom workspace base directory")

    # lesson
    p_lesson = sub.add_parser("lesson", help="Lessons Learned — capture what worked/failed/surprised/reusable")
    p_lesson.add_argument("l_action", nargs="?", choices=["add", "list", "extract", "summary"],
                         help="Action: add|list|extract|summary")
    p_lesson.add_argument("content", nargs="?", help="Lesson content (for add)")
    p_lesson.add_argument("--category", "-c", choices=["worked", "failed", "surprised", "reusable"],
                         default="worked", help="Lesson category")
    p_lesson.add_argument("--severity", "-s", choices=["insight", "warning", "critical"],
                         default="insight", help="Lesson severity")
    p_lesson.add_argument("--project", "-p", help="Project name")
    p_lesson.add_argument("--client", help="Client name")
    p_lesson.add_argument("--agent", "-a", help="Agent who learned this")
    p_lesson.add_argument("--max", type=int, default=50, help="Max results (for list)")
    p_lesson.add_argument("--dir", help="Store directory")

    # pattern
    p_pat = sub.add_parser("pattern", help="Pattern Promotion Engine — detect, promote, create playbooks/accelerators")
    p_pat.add_argument("p_action", nargs="?", choices=["scan", "promote", "playbook", "accelerator", "moat"],
                       help="Action: scan|promote|playbook|accelerator|moat")
    p_pat.add_argument("id", nargs="?", help="Pattern ID (for promote)")
    p_pat.add_argument("level", nargs="?", choices=["pattern", "playbook", "accelerator"],
                       help="Target level (for promote)")
    p_pat.add_argument("--title", help="Title (for playbook/accelerator)")
    p_pat.add_argument("--domain", help="Domain name")
    p_pat.add_argument("--description", help="Description (for accelerator)")
    p_pat.add_argument("--value", help="Value estimate (for accelerator)")
    p_pat.add_argument("--steps", help="Semicolon-separated steps (for playbook)")
    p_pat.add_argument("--min-occ", type=int, default=3, help="Min occurrences (for scan)")
    p_pat.add_argument("--dir", help="Store directory")

    # engagement
    p_eng = sub.add_parser("engagement", help="Engagement Graph + QBR Generator — track client lifecycle")
    p_eng.add_argument("e_action", nargs="?", choices=["track", "list", "show", "qbr"],
                       help="Action: track|list|show|qbr")
    p_eng.add_argument("client", nargs="?", help="Client name")
    p_eng.add_argument("phase", nargs="?", choices=["discovery", "assessment", "proposal", "build", "deploy", "operate", "expand"],
                       help="Engagement phase (for track)")
    p_eng.add_argument("-a", "--activity", help="Activity description (for track)")
    p_eng.add_argument("-d", "--detail", help="Activity details")
    p_eng.add_argument("--agent", help="Who performed this")
    p_eng.add_argument("--quarter", help="Quarter label (for qbr), e.g. Q2 2026")
    p_eng.add_argument("--dir", help="Store directory")

    # pipeline
    p_pipe = sub.add_parser("pipeline", help="Operational Loop — run the full client intelligence pipeline")
    p_pipe.add_argument("pipe_action", nargs="?", choices=["run", "track", "report", "auto"],
                       help="Action: run|track|report|auto")
    p_pipe.add_argument("--client", "-c", help="Client/workspace name")
    p_pipe.add_argument("--phase", choices=["discovery", "assessment", "proposal", "build", "deploy", "operate", "expand"],
                       help="Phase (for track)")
    p_pipe.add_argument("--activity", "-a", help="Activity description")
    p_pipe.add_argument("--quarter", "-q", help="Quarter label (for report), e.g. Q2 2026")
    p_pipe.add_argument("--interval", type=int, default=24, help="Auto-schedule interval in hours")
    p_pipe.add_argument("--stop", action="store_true", help="Stop auto-scheduler")
    p_pipe.add_argument("--no-radar", action="store_true", help="Skip radar scan")
    p_pipe.add_argument("--no-lessons", action="store_true", help="Skip lesson extraction")
    p_pipe.add_argument("--no-patterns", action="store_true", help="Skip pattern scan")
    p_pipe.add_argument("--dir", help="Store directory")

    # enterprise
    p_ent = sub.add_parser("enterprise", help="Enterprise features: auth, audit, PII detection")
    p_ent.add_argument("ent_action", nargs="?",
                       choices=["key-create", "key-list", "key-revoke", "audit", "audit-summary", "audit-verify", "pii-scan"],
                       help="Action: key-create|key-list|key-revoke|audit|audit-summary|audit-verify|pii-scan")
    p_ent.add_argument("key_id", nargs="?", help="Key ID (for key-revoke)")
    p_ent.add_argument("--permission", choices=["read", "write", "admin"], default="read",
                       help="Key permission level")
    p_ent.add_argument("--label", help="Key label")
    p_ent.add_argument("--workspace", help="Workspace scope")
    p_ent.add_argument("--content", help="Content to scan for PII")
    p_ent.add_argument("--mode", choices=["detect", "redact", "block"], default="detect",
                       help="PII detection mode")
    p_ent.add_argument("--filter-action", help="Filter audit by action type")
    p_ent.add_argument("--days", type=int, default=30, help="Days for audit summary")
    p_ent.add_argument("--max", type=int, default=50, help="Max audit entries")
    p_ent.add_argument("--dir", help="Store directory")

    # intel
    p_intel = sub.add_parser("intel", help="Enterprise Intelligence — amnesia, DNA, radar v2, readiness")
    p_intel.add_argument("intel_action", nargs="?",
                         choices=["amnesia", "dna", "dna-outcome", "radar2", "readiness"],
                         help="Action: amnesia|dna|dna-outcome|radar2|readiness")
    p_intel.add_argument("--client", "-c", help="Client/workspace")
    p_intel.add_argument("--decision-id", help="Decision ID (for dna-outcome)")
    p_intel.add_argument("--outcome", choices=["success", "failure", "neutral"], default="success",
                         help="Outcome (for dna-outcome)")
    p_intel.add_argument("--value", type=float, default=0, help="Outcome value (for dna-outcome)")
    p_intel.add_argument("--dir", help="Store directory")

    # migrate
    p_mig = sub.add_parser("migrate", help="Database migrations")
    p_mig.add_argument("m_action", nargs="?", choices=["run", "status", "export"],
                       help="Action: run|status|export")
    p_mig.add_argument("--db-type", choices=["sqlite", "postgresql"], default="sqlite",
                       help="Database type")
    p_mig.add_argument("--db-path", help="Database path or connection string")
    p_mig.add_argument("--output", "-o", help="Schema export path")
    p_mig.add_argument("--dir", help="Store directory")

    # tenant
    p_ten = sub.add_parser("tenant", help="Multi-tenant management — organizations, workspaces, users, usage")
    p_ten.add_argument("tenant_action", nargs="?",
                       choices=["create", "list", "show", "user-add", "user-list",
                                "retention", "encryption", "usage", "admin-summary"],
                       help="Action")
    p_ten.add_argument("tenant_id", nargs="?", help="Tenant ID")
    p_ten.add_argument("workspace_id", nargs="?", help="Workspace ID")
    p_ten.add_argument("--name", "-n", help="Tenant/User name")
    p_ten.add_argument("--domain", "-d", help="Tenant domain")
    p_ten.add_argument("--plan", choices=["starter", "growth", "enterprise"], default="starter", help="Tenant plan")
    p_ten.add_argument("--email", "-e", help="User email")
    p_ten.add_argument("--role", "-r", choices=["viewer", "analyst", "architect", "executive", "admin"], default="viewer", help="User role")
    p_ten.add_argument("--days", type=int, default=365, help="Retention days or usage period")
    p_ten.add_argument("--enabled", action="store_true", help="Enable encryption")
    p_ten.add_argument("--dir", help="Store directory")

    # db
    p_db = sub.add_parser("db", help="Database operations: backup, archive, optimize, monitor")
    p_db.add_argument("db_action", nargs="?",
                      choices=["backup", "backup-list", "restore", "archive", "archive-list",
                               "analyze", "status", "indexes", "auto-backup"],
                      help="Action")
    p_db.add_argument("backup_name", nargs="?", help="Backup name (for restore)")
    p_db.add_argument("--label", "-l", help="Backup label")
    p_db.add_argument("--days", type=int, default=365, help="Archive threshold days")
    p_db.add_argument("--delete", action="store_true", help="Delete archived entries from active store")
    p_db.add_argument("--dry-run", action="store_true", help="Preview without acting")
    p_db.add_argument("--interval", type=int, default=24, help="Auto-backup interval in hours")
    p_db.add_argument("--stop", action="store_true", help="Stop auto-backup")
    p_db.add_argument("--dir", help="Store directory")

    # opp (opportunity engine)
    p_opp_e = sub.add_parser("opp", help="Opportunity Engine: track wins/losses, ROI, ranking, analytics")
    p_opp_e.add_argument("opp_e_action", nargs="?",
                         choices=["win", "loss", "roi", "link-proposal", "link-project",
                                  "graph", "analytics", "rank", "summary"],
                         help="Action")
    p_opp_e.add_argument("opportunity_id", nargs="?", help="Opportunity ID")
    p_opp_e.add_argument("link_id", nargs="?", help="Proposal/Project ID (for link-*)")
    p_opp_e.add_argument("--reason", "-r", help="Win/loss reason")
    p_opp_e.add_argument("--revenue", type=float, default=0, help="Win revenue")
    p_opp_e.add_argument("--value", type=float, default=0, help="Loss value")
    p_opp_e.add_argument("--actual", type=float, default=0, help="Actual ROI value")
    p_opp_e.add_argument("--hours", type=int, default=0, help="Actual hours")
    p_opp_e.add_argument("--notes", "-n", help="ROI notes")
    p_opp_e.add_argument("--dir", help="Store directory")

    # dashboard
    p_dash = sub.add_parser("dashboard", help="Business Intelligence: executive, revenue, expansion, portfolio, proposals")
    p_dash.add_argument("dash_action", nargs="?", choices=["executive", "revenue", "expansion", "portfolio", "proposals"], help="View")
    p_dash.add_argument("--client", "-c", help="Client filter")
    p_dash.add_argument("--dir", help="Store directory")

    # governance
    p_gov = sub.add_parser("governance", help="Enterprise governance: compliance, classification, legal hold")
    p_gov.add_argument("gov_action", nargs="?", choices=["classify", "compliance", "legal-hold"], help="Action")
    p_gov.add_argument("--content", help="Content to classify")
    p_gov.add_argument("--framework", choices=["hipaa", "gdpr", "soc2"], default="hipaa", help="Compliance framework")
    p_gov.add_argument("--workspace-id", help="Workspace ID for legal hold")
    p_gov.add_argument("--case-id", help="Case ID for legal hold")
    p_gov.add_argument("--dir", help="Store directory")

    # knowledge
    p_k = sub.add_parser("knowledge", help="Knowledge Operations: audit, accelerators, cross-engagement learning")
    p_k.add_argument("k_action", nargs="?", choices=["audit", "accelerator", "cross"], help="Action")
    p_k.add_argument("--domain", "-d", help="Domain (for accelerator)")
    p_k.add_argument("--min-lessons", type=int, default=3, help="Min lessons for accelerator")
    p_k.add_argument("--dir", help="Store directory")

    # export
    p_export = sub.add_parser("export", help="Export entries as JSON")
    p_export.add_argument("--output", "-o", help="Output file path (default: stdout)")
    p_export.add_argument("--compact", action="store_true", help="Minified JSON")

    # import
    p_import = sub.add_parser("import", help="Import entries from JSON")
    p_import.add_argument("--file", "-f", help="JSON file path")
    p_import.add_argument("--data", "-d", help="JSON string")
    p_import.add_argument("--replace", action="store_true", help="Replace existing store")
    p_import.add_argument("--agent", help="Override agent_id for all entries")
    p_import.add_argument("--tag-prefix", help="Prefix for all imported tags")

    # ask
    p_ask = sub.add_parser("ask", help="Ask a natural language question about the Grid")
    p_ask.add_argument("question", help="Your question")

    args = parser.parse_args()

    if args.version:
        print("grid-memory v1.1.0")
        return

    if not args.command:
        parser.print_help()
        return

    # Route commands
    command_map = {
        "init": cmd_init,
        "start": cmd_start,
        "write": cmd_write,
        "query": cmd_query,
        "info": cmd_info,
        "log": cmd_log,
        "prune": cmd_prune,
        "patch": cmd_patch,
        "ui": cmd_ui,
        "export": cmd_export,
        "import": cmd_import,
        "ask": cmd_ask,
        "curate": cmd_curate,
        "tier": cmd_tier,
        "analyze": cmd_analyze,
        "insights": cmd_insights,
        "radar": cmd_radar,
        "opportunity": cmd_opportunity,
        "workspace": cmd_workspace,
        "lesson": cmd_lesson,
        "pattern": cmd_pattern,
        "engagement": cmd_engagement,
        "pipeline": cmd_pipeline,
        "enterprise": cmd_enterprise,
        "intel": cmd_intel,
        "migrate": cmd_migrate,
        "tenant": cmd_tenant,
        "db": cmd_dbops,
        "opp": cmd_opp_engine,
        "dashboard": cmd_dashboard,
        "governance": cmd_governance,
        "knowledge": cmd_knowledge,
    }

    cmd_fn = command_map.get(args.command)
    if cmd_fn:
        cmd_fn(args)


if __name__ == "__main__":
    main()

# ── New Commands ──


def cmd_export(args):
    """Export all entries as JSON."""
    grid = _get_grid(args)
    result = grid.export_json(output_path=args.output, pretty=not args.compact)
    if args.output:
        print(f"  {c('green', '\u2713')} Exported to {c('bold', result)}")
        print(f"  {c('dim', f'Use: grid import --file {result}')}")
    else:
        print(result)


def cmd_import(args):
    """Import entries from JSON."""
    grid = _get_grid(args)
    source = args.file or args.data
    if not source:
        print(f"  {c('red', '\u2717')} Provide --file or --data")
        return

    result = grid.import_json(
        json_input=source,
        merge=not args.replace,
        agent_override=args.agent,
        tag_prefix=args.tag_prefix,
    )
    print(f"  {c('green', '\u2713')} Imported {result['imported']} entries")
    if result['skipped']:
        skipped_count = result.get("skipped", 0)
        print(f"  {c('yellow', f'\u26a0 {skipped_count} skipped')}")
    if result['errors']:
        for err in result['errors'][:3]:
            print(f"  {c('red', f'  \u2717 {err}')}")


def cmd_ask(args):
    """Ask a natural language question about the Grid."""
    from grid_memory.local_grid import LocalGrid
    grid = _get_grid(args)

    # Get Grid context
    context = grid.inject(context=args.question)
    block = context.get("block", "")

    if not context.get("entry_count", 0):
        print(f"\n  {c('yellow', 'No entries in the Grid yet.')}")
        print(f"  {c('dim', 'Write some data first: grid write --content \"...\"')}\n")
        return

    # Try to use an LLM via the OpenAI proxy
    api_key = os.environ.get("GRID_UPSTREAM_API_KEY")
    upstream_url = os.environ.get("GRID_UPSTREAM_URL", "https://api.openai.com")

    if api_key:
        print(f"\n  {c('green', '\u25b6 Thinking...')}")

        import urllib.request
        body = json.dumps({
            "model": os.environ.get("GRID_UPSTREAM_MODEL", "gpt-4o-mini"),
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a Grid Memory analyst. You have access to shared agent memory. "
                        "Answer questions based ONLY on the context provided.\n\n"
                        f"--- SHARED MEMORY GRID ---\n{block}\n--- END GRID ---"
                    ),
                },
                {"role": "user", "content": args.question},
            ],
            "temperature": 0.3,
            "max_tokens": 1000,
        }).encode()

        req = urllib.request.Request(
            f"{upstream_url}/v1/chat/completions",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                answer = data["choices"][0]["message"]["content"]
                print(f"\n  {answer}\n")
        except Exception as e:
            print(f"\n  {c('red', f'\u2717 LLM error: {e}')}\n")
            print(f"  {c('dim', 'Falling back to context-only mode...')}\n")
            print(f"  {block}\n")
    else:
        # No LLM — just show the context
        print(f"\n  {c('yellow', 'No GRID_UPSTREAM_API_KEY configured.')}")
        print(f"  {c('dim', 'Showing raw Grid context instead:')}\n")
        print(f"  {block}\n")
        print(f"  {c('dim', 'Set GRID_UPSTREAM_API_KEY to get natural language answers.')}\n")


# ── Integrate into main parser ──

# These will be merged into the main() function below
# The commands are registered in the parser build

def cmd_curate(args):
    """Run one curation pass."""
    from grid_memory.curator import GridCurator
    grid = _get_grid(args)
    curator = GridCurator(grid=grid)
    print(f"\n  {c('green', '\u25b6 Running curation...')}\n")
    report = curator.curate()
    print(f"  {c('green', '\u2713 Curated')}")
    print(f"    Archived:              {report.get('archived', 0)}")
    print(f"    Merged:                {sum(len(m.get('deleted', [])) for m in report.get('merged', []))} entries into {len(report.get('merged', []))} survivors")
    print(f"    Summaries written:     {report.get('summaries_written', 0)}")
    print(f"    Contradictions flagged: {report.get('contradictions_flagged', 0)}")
    print(f"    Tags suggested:        {report.get('tags_suggested', 0)}")
    print()

def cmd_tier(args):
    """Memory tier operations."""
    from grid_memory.local_grid import LocalGrid
    from grid_memory.tiers import PromotionEngine

    grid = _get_grid(args)
    engine = PromotionEngine(grid)

    if args.tier_command == "list":
        dist = engine.get_tier_distribution()
        print(f"\n  {c('bold', 'Memory Tier Distribution')}")
        print(f"  {'─' * 40}")
        print(f"  {c('yellow', '\u26a1')} Working:       {c('bold', str(dist.get('working', 0)))}")
        print(f"  {c('cyan', '\U0001f4e6')} Project:       {c('bold', str(dist.get('project', 0)))}")
        print(f"  {c('green', '\U0001f3f0')} Organization:  {c('bold', str(dist.get('organization', 0)))}")
        total = sum(dist.values())
        print(f"  {c('dim', f'Total: {total}')}\n")

    elif args.tier_command == "promote":
        result = engine.promote(args.entry_id, args.tier)
        if result["success"]:
            print(f"\n  {c('green', '\u2713')} Promoted {c('bold', args.entry_id[:16])}... "
                  f"{c('yellow', result['from_tier'])} \u2192 {c('cyan', result['to_tier'])}\n")
        else:
            msg = result.get("reason", "")
            print(f"\n  {c('red', chr(0x2717))} {msg}\n")

    elif args.tier_command == "scan":
        result = engine.scan_and_promote(dry_run=args.dry_run)
        wp = result.get("working_to_project", [])
        po = result.get("project_to_organization", [])

        if args.dry_run:
            print(f"\n  {c('bold', 'Dry Run — Would Promote:')}")
        else:
            print(f"\n  {c('green', '\u2713 Scanned and Promoted:')}")
        print(f"  {'─' * 40}")
        print(f"  \u26a1 Working \u2192 \U0001f4e6 Project:   {c('bold', str(len(wp)))}")
        for item in wp:
            print(f"    {c('dim', item['id'][:16])} {item['content_preview'][:50]}"
                  f"  {c('yellow', ', '.join(item.get('reasons', [])))}")
        print(f"  \U0001f4e6 Project \u2192 \U0001f3f0 Org:      {c('bold', str(len(po)))}")
        for item in po:
            print(f"    {c('dim', item['id'][:16])} {item['content_preview'][:50]}"
                  f"  {c('yellow', ', '.join(item.get('reasons', [])))}")
        if not wp and not po:
            print(f"  {c('dim', 'No eligible entries found.')}")
        print()


def cmd_analyze(args):
    """Run pattern analysis on the Grid."""
    from grid_memory.learning import LearningEngine
    grid = _get_grid(args)
    engine = LearningEngine(grid)

    print(f"\n  {c('green', '\u25b6 Analyzing Grid patterns...')}\n")
    results = engine.analyze()

    # Blockers
    blockers = results.get("recurring_blockers", [])
    if blockers:
        print(f"  {c('red', f'\u26a0 Recurring Blockers ({len(blockers)})')}")
        for b in blockers[:5]:
            print(f"    \u2022 {b['pattern']} ({c('bold', str(b['count']))}x, {b['agents_involved']} agents)")
        print()

    # Decisions
    decisions = results.get("frequent_decisions", [])
    if decisions:
        print(f"  {c('magenta', f'\U0001f9e9 Frequent Decisions ({len(decisions)})')}")
        for d in decisions[:5]:
            print(f"    \u2022 {d['topic']} ({c('bold', str(d['count']))}x, {d['agents_involved']} agents)")
        print()

    # Workflows
    workflows = results.get("workflow_patterns", [])
    if workflows:
        print(f"  {c('cyan', f'\U0001f500 Workflow Patterns ({len(workflows)})')}")
        for w in workflows[:5]:
            print(f"    \u2022 {w['from_agent']} \u2192 {w['to_agent']} "
                  f"({c('bold', str(w['handoff_count']))} handoffs)")
        print()

    # Agents
    agents = results.get("agent_trends", [])
    if agents:
        print(f"  {c('blue', f'\U0001f465 Agent Activity ({len(agents)} agents)')}")
        for a in agents[:5]:
            print(f"    \u2022 {c('cyan', a['agent'])}: {a['total_entries']} entries "
                  f"({c('dim', a['most_common_type'])})")
        print()

    # Top tags
    tags = results.get("top_tags", [])
    if tags:
        print(f"  {c('yellow', f'\U0001f516 Top Tags')}")
        tag_str = ', '.join(f'{c("green", t.get("tag", ""))} ({t.get("count", 0)}x)' for t in tags[:10])
        print(f"    {tag_str}")
        print()

    # Gaps
    gaps = results.get("knowledge_gaps", [])
    if gaps:
        print(f"  {c('yellow', f'\u2753 Knowledge Gaps ({len(gaps)})')}")
        for g in gaps[:3]:
            print(f"    \u2022 {g.get('question', '')[:80]}")
            tags_str = ', '.join(g.get('unanswered_tags', []))
            print(f"      {c('dim', f'unanswered tags: {tags_str}')}")
        print()

    count = results.get('total_entries_analyzed', 0)
    print(f"  {c('dim', f'Analyzed {count} entries')}\n")


def cmd_insights(args):
    """Get ranked insights from the Grid."""
    from grid_memory.learning import LearningEngine
    grid = _get_grid(args)
    engine = LearningEngine(grid)

    print(f"\n  {c('green', '\u25b6 Generating insights...')}\n")
    insights = engine.get_insights(min_confidence=getattr(args, 'min', 0.3))

    if not insights:
        print(f"  {c('yellow', 'Not enough data for insights yet. Add more entries.')}\n")
        return

    print(f"  {c('bold', f'{len(insights)} Insights Found')}")
    print(f"  {'─' * 40}")

    for ins in insights:
        icon = {"recurring_blocker": "\u26a0", "frequent_decision": "\U0001f9e9",
                 "workflow_pattern": "\U0001f500"}.get(ins["type"], "\U0001f4ac")
        confidence_bar = "\u2588" * int(ins["confidence"] * 10) + "\u2591" * (10 - int(ins["confidence"] * 10))
        print(f"  {icon} {ins['summary']}")
        conf = ins.get('confidence', 0)
        print(f"    {c('dim', confidence_bar)} {c('yellow', f'{conf:.0%} confidence')}")
        print()

    print()

def cmd_radar(args):
    """Run the AI Opportunity Radar scan."""
    from grid_memory.opportunity_radar import OpportunityRadar
    grid = _get_grid(args)
    radar = OpportunityRadar(
        grid,
        window_days=args.days or 90,
        min_confidence=args.min_confidence or 0.3,
        min_annual_value=args.min_value or 500,
    )

    data = radar.scan()
    print(radar.report(format="text"))

    # Write radar results to Grid
    if data.get("opportunities"):
        grid.fact(
            f"Opportunity Radar: ${data['total_annual_value']:,.0f}/yr in "
            f"{data['total_opportunities']} opportunities. "
            f"Top: {data['top_opportunity']}",
            tags=["opportunity-radar", "scan"],
            agent_id="opportunity-radar",
        )

def cmd_opportunity(args):
    """Manage opportunity lifecycle."""
    from grid_memory.opportunity_lifecycle import OpportunityLifecycle
    grid = _get_grid(args)
    lifecycle = OpportunityLifecycle(grid)

    action = args.opp_action

    if action == "list":
        stage = args.stage
        result = lifecycle.get_pipeline(stage=stage)
        pipeline = result.get("pipeline", {})
        summary = result.get("summary", {})

        print(f"\n  {_c('bold', 'Opportunity Pipeline')}")
        print(f"  {'─' * 50}")
        print(f"  Total: {summary.get('total_opportunities', 0)} opportunities"
              f"  |  Pipeline Value: ${summary.get('total_pipeline_value', 0):,.0f}")

        for s in ["detected", "reviewed", "accepted", "assessment", "proposed", "won", "lost", "completed"]:
            stage_data = pipeline.get(s, {})
            count = stage_data.get("count", 0)
            if count > 0:
                icon = STAGE_ICONS.get(s, "\u25cf")
                display = stage_display.get(s, s)
                val = stage_data.get("total_value", 0)
                print(f"\n  {icon} {display}: {count} (${val:,.0f})")
                for item in stage_data.get("items", [])[:5]:
                    print(f"    \u2022 {_c('cyan', item.get('title', '')[:60])}")
                    print(f"      {_c('dim', item.get('id', '')[:20])} \u2014 ${item.get('estimated_value', 0):,.0f}")

    elif action == "show":
        result = lifecycle.get_history(args.id)
        if not result.get("success"):
            msg = result.get("reason", "Not found")
            print(f"\n  {_c('red', chr(0x2717))} {msg}\n")
            return
        print(f"\n  {_c('bold', result.get('title', 'Untitled'))}")
        print(f"  Stage: {result.get('stage', '?')}")
        for item in result.get("timeline", []):
            icon = STAGE_ICONS.get(item.get("stage", ""), "\u25cf")
            ts = item.get("created_at", "")[11:19]
            t = item.get("title", "(transition)")
            print(f"  {icon} {_c('dim', ts)} {t}")

    elif action == "advance":
        result = lifecycle.advance(args.id, args.to_stage, notes=args.notes or "")
        if result.get("success"):
            print(f"\n  {_c('green', '\u2713')} {result['from_stage']} \u2192 {result['to_stage']}\n")
        else:
            msg = result.get("reason", "Failed")
            print(f"\n  {_c('red', chr(0x2717))} {msg}\n")

    elif action == "stats":
        stats = lifecycle.get_stats()
        print(f"\n  {_c('bold', 'Opportunity Stats')}")
        print(f"  Total: {stats.get('total_opportunities', 0)}")
        print(f"  Won:  {stats['won']['count']} (${stats['won']['total_value']:,.0f})")
        print(f"  Lost: {stats['lost']['count']} (${stats['lost']['total_value']:,.0f})")
        print(f"  Win Rate: {stats.get('win_rate', 0):.1f}%")
        print(f"  Pipeline: ${stats.get('pipeline_value', 0):,.0f}\n")

    else:
        print(f"  Use: opportunity list|show|advance|stats")


# Need these from the lifecycle module
from grid_memory.opportunity_lifecycle import STAGE_ICONS, STAGE_DISPLAY as stage_display

def cmd_lesson(args):
    """Manage lessons learned."""
    from grid_memory.lessons import LessonsEngine, CATEGORIES, SEVERITIES
    grid = _get_grid(args)
    engine = LessonsEngine(grid)

    action = args.l_action or "list"

    if action == "add":
        cat = args.category or "worked"
        sev = args.severity or "insight"
        content = args.content
        if not content:
            print("\n  Content required\n")
            return
        lesson = engine.add(
            content=content,
            category=cat,
            severity=sev,
            project=args.project or "",
            client=args.client or "",
            agent=args.agent or "",
        )
        icon = CATEGORIES.get(cat, {}).get("icon", "\U0001f4ac")
        sev_icon = SEVERITIES.get(sev, "\U0001f4a1")
        print(f"\n  {icon} {sev_icon} Lesson added")
        print(f"  Category: {cat}  Severity: {sev}")
        if args.project:
            print(f"  Project: {args.project}")
        if args.client:
            print(f"  Client: {args.client}")
        print(f"  ID: {lesson['id']}\n")

    elif action == "list":
        result = engine.list(
            category=args.category,
            project=args.project,
            client=args.client,
            severity=args.severity,
            max_results=args.max or 50,
        )
        lessons = result.get("lessons", [])
        if not lessons:
            print("\n  No lessons found.\n")
            return

        print(f"\n  Lessons ({result['total']})")
        print(f"  By category: {result.get('by_category', {})}")
        print(f"  By severity: {result.get('by_severity', {})}")
        print(f"  {'-' * 60}")
        for l in lessons[:10]:
            icon = CATEGORIES.get(l["category"], {}).get("icon", "\U0001f4ac")
            sev_icon = SEVERITIES.get(l["severity"], "\U0001f4a1")
            proj = f" [{l['project']}]" if l.get("project") else ""
            cli = f" [{l['client']}]" if l.get("client") else ""
            print(f"  {icon} {sev_icon}{proj}{cli}")
            print(f"    {l['content'][:100]}")
            print()

        if result["total"] > 10:
            print(f"  ... and {result['total'] - 10} more\n")

    elif action == "extract":
        result = engine.auto_extract(project=args.project or "", client=args.client or "")
        print(f"\n  Auto-extracted {result['total']} lessons")
        for cat, items in result.items():
            if cat == "total":
                continue
            if items:
                icon = CATEGORIES.get(cat, {}).get("icon", "\U0001f4ac")
                print(f"  {icon} {cat}: {len(items)}")
        print()

    elif action == "summary":
        result = engine.summary(project=args.project, client=args.client)
        if result.get("total", 0) == 0:
            print("\n  No lessons yet.\n")
            return
        print(f"\n  Lessons Summary ({result['total']} total)")
        print(f"  By category: {result.get('category_counts', {})}")
        print(f"  By severity: {result.get('severity_counts', {})}")
        print()
        if result.get("top_critical"):
            print("  Critical:")
            for l in result["top_critical"][:3]:
                print(f"    {l['content'][:80]}")
        if result.get("top_warnings"):
            print("  Warnings:")
            for l in result["top_warnings"][:3]:
                print(f"    {l['content'][:80]}")
        print()

    else:
        print("  Use: lesson add|list|extract|summary")

def cmd_pattern(args):
    """Manage patterns, playbooks, and accelerators."""
    from grid_memory.patterns import PatternEngine
    grid = _get_grid(args)
    engine = PatternEngine(grid)

    action = args.p_action or "scan"

    if action == "scan":
        result = engine.scan(domain=args.domain or "", min_occurrences=args.min_occ or 3)
        print(f"\n  Pattern Scan — {result['total']} patterns found")
        print(f"  Promotion candidates: {len(result['promotion_candidates'])}")
        print(f"  {'-' * 60}")
        for p in result["patterns"][:10]:
            icon = "\U0001f4ca"
            print(f"\n  {icon} {p.get('pattern', '?')}")
            print(f"     {p.get('evidence', '')} — score: {p.get('score', 0):.0f}")
            print(f"     Level: {p.get('current_level', 'observation')} \u2192 suggested: {p.get('suggested_level', 'pattern')}")
        print()

    elif action == "promote":
        result = engine.promote(args.id, args.level)
        if result.get("success"):
            print(f"\n  Promoted from {result['from_level']} to {result['to_level']}\n")
        else:
            print(f"\n  {result.get('reason', 'Failed')}\n")

    elif action == "playbook":
        steps = args.steps.split(";") if args.steps else ["Define scope", "Execute", "Review"]
        result = engine.create_playbook(args.title or "Untitled", args.domain or "", steps)
        print(f"\n  Playbook created: {result['title']} ({result['steps']} steps)\n")

    elif action == "accelerator":
        result = engine.create_accelerator(
            args.title or "Untitled", args.domain or "",
            args.description or "", args.value or ""
        )
        print(f"\n  Accelerator created: {result['title']} [{result['domain']}]\n")

    elif action == "moat":
        report = engine.get_moat_report()
        print(f"\n  MIKE Knowledge Moat Report")
        print(f"  {'-' * 40}")
        print(f"  Patterns:     {report['patterns_count']}")
        print(f"  Playbooks:    {report['playbooks_count']}")
        print(f"  Accelerators: {report['accelerators_count']}")
        print(f"  Domains:      {', '.join(report['domains_covered']) or 'none'}")
        print()


def cmd_engagement(args):
    """Manage engagement graph."""
    from grid_memory.engagement import EngagementGraph
    grid = _get_grid(args)
    eg = EngagementGraph(grid)

    action = args.e_action or "list"

    if action == "track":
        result = eg.track(args.client or "unknown", args.phase or "discovery",
                          args.activity or "Activity recorded", args.detail or "", args.agent or "")
        print(f"\n  Tracked engagement: {result['client']} / {result['phase']}\n")

    elif action == "list":
        result = eg.get_all_clients()
        if result["total"] == 0:
            print("\n  No clients tracked yet.\n")
            return
        print(f"\n  Clients ({result['total']})")
        for c in result["clients"]:
            print(f"  {c['client']} — {c['current']} — {c['total_activities']} activities")
        print()

    elif action == "show":
        eng = eg.get_engagement(args.client or "")
        if eng["total_activities"] == 0:
            print(f"\n  No engagement data for {args.client}\n")
            return
        print(f"\n  Engagement: {eng['client']}")
        print(f"  Activities: {eng['total_activities']}")
        print(f"  Current phase: {eng['current_phase']}")
        print(f"  Phases: {', '.join(eng['phases_involved'])}")
        for item in eng.get("timeline", [])[-10:]:
            print(f"  [{item['phase']}] {item.get('activity', '')[:60]}")
        print()

    elif action == "qbr":
        qbr = eg.generate_qbr(args.client or "", args.quarter or "")
        print(eg.format_qbr_report(qbr))

def cmd_enterprise(args):
    """Enterprise operations: auth, audit, pii."""
    action = args.ent_action or "status"

    if action == "key-create":
        from grid_memory.enterprise.auth import KeyManager
        km = KeyManager()
        perm = args.permission or "read"
        label = args.label or "CLI-generated"
        ws = args.workspace or "*"
        result = km.create_key(label=label, workspace=ws, permission=perm)
        print(f"\n  Key created: {result['key_id']}")
        print(f"  Plaintext key: {result['plaintext_key']}")
        print(f"  Permission: {result['permission']}")
        print(f"  Workspace: {result['workspace']}")
        print(f"  Save this key now — it won't be shown again!\n")

    elif action == "key-list":
        from grid_memory.enterprise.auth import KeyManager
        km = KeyManager()
        keys = km.list_keys(workspace=args.workspace or "")
        if not keys:
            print("\n  No keys found.\n")
            return
        print(f"\n  API Keys ({len(keys)})")
        print(f"  {'─' * 60}")
        for k in keys:
            status = "\u2705" if k.get("enabled") else "\u274c"
            print(f"  {status} {k['key_id']}")
            print(f"     Label: {k.get('label', '')}  Permission: {k['permission']}  Workspace: {k['workspace']}")
            print(f"     Created: {k.get('created_at', '')[:10]}")
        print()

    elif action == "key-revoke":
        from grid_memory.enterprise.auth import KeyManager
        km = KeyManager()
        km.revoke_key(args.key_id)
        print(f"\n  Key {args.key_id} revoked\n")

    elif action == "audit":
        from grid_memory.enterprise.audit import AuditTrail
        audit = AuditTrail()
        entries = audit.query(
            workspace=args.workspace or "",
            action=args.filter_action or "",
            limit=args.max or 50,
        )
        if not entries:
            print("\n  No audit entries found.\n")
            return
        print(f"\n  Audit Log ({len(entries)} entries)")
        print(f"  {'─' * 60}")
        for e in entries[:20]:
            ts = e.get("timestamp", "")[11:19]
            act = e.get("action", "?")
            ent = e.get("entity_id", "")[:20]
            actor = e.get("actor", "?")
            ws = e.get("workspace", "")
            print(f"  {ts} [{act}] {ent} — {actor} ({ws})")
        print()

    elif action == "audit-summary":
        from grid_memory.enterprise.audit import AuditTrail
        audit = AuditTrail()
        ws = args.workspace or ""
        days = args.days or 30
        summary = audit.summary(workspace=ws, days=days)
        print(f"\n  Audit Summary (last {days} days)")
        print(f"  Total events: {summary['total_events']}")
        if ws:
            print(f"  Workspace: {ws}")
        for action_name, count in sorted(summary.get("by_action", {}).items(), key=lambda x: -x[1])[:10]:
            print(f"  {action_name}: {count}")
        print()

    elif action == "audit-verify":
        import urllib.request
        import json
        base = args.url or "http://localhost:8080"
        try:
            req = urllib.request.Request(f"{base}/gateway/audit/verify")
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode())
            if result.get("valid"):
                print(f"\n  ✓ Audit chain integrity verified (valid: {result['valid']})")
            else:
                print(f"\n  ✗ Audit chain BROKEN at index {result.get('brokenAtIndex', '?')}: {result.get('reason', 'unknown')}")
                print("  Investigate immediately.")
        except Exception as e:
            print(f"\n  ✗ Could not verify audit chain: {e}")
        print()

    elif action == "pii-scan":
        from grid_memory.enterprise.pii import PIIDetector
        content = args.content or ""
        if not content:
            print("\n  Provide content to scan: --content \"text\"\n")
            return
        detector = PIIDetector(mode=args.mode or "detect")
        if args.mode == "redact":
            redacted, result = detector.redact(content)
            print(f"\n  PII/PHI Scan Result: {result['total']} items found")
            if result["total"] > 0:
                print(f"  Critical: {result['critical']}  High: {result['high']}")
                for f in result["findings"]:
                    print(f"  [{f['severity'].upper()}] {f['type']}: '{f['match']}'")
                print(f"\n  Redacted text:\n  {redacted[:500]}")
            else:
                print("  No PII/PHI detected")
            print()
        else:
            result = detector.scan(content)
            print(f"\n  PII/PHI Scan: {result['total']} items found")
            if result["total"] > 0:
                for f in result["findings"]:
                    print(f"  [{f['severity'].upper()}] {f['type']}: '{f['match']}'")
            else:
                print("  Clean — no PII/PHI detected")
            print()

    else:
        print("\n  Enterprise commands:")
        print("    key-create  --permission read|write|admin --workspace <ws>")
        print("    key-list    [--workspace <ws>]")
        print("    key-revoke  <key_id>")
        print("    audit       [--workspace <ws>] [--max 50]")
        print("    audit-summary [--workspace <ws>] [--days 30]")
        print("    audit-verify      — Verify audit hash chain integrity")
        print("    pii-scan    --content \"text\" [--mode detect|redact|block]\n")

def cmd_intel(args):
    """Enterprise Intelligence commands."""
    from grid_memory.workspace import WorkspaceManager
    mgr = WorkspaceManager()
    client = args.client or mgr.get_active()
    
    try:
        grid = mgr.get_grid(client) if client else _get_grid(args)
    except ValueError:
        print(f"\n  Workspace '{client}' not found.\n")
        return

    action = args.intel_action or "scan"

    if action == "amnesia":
        from grid_memory.intel.amnesia import AmnesiaDetector
        detector = AmnesiaDetector(grid)
        print(detector.report())

    elif action == "dna":
        from grid_memory.intel.decision_dna import DecisionDNA
        dna = DecisionDNA(grid)
        result = dna.analyze()
        if result.get("total_decisions", 0) == 0:
            print("\n  No decisions tracked yet.\n")
            return
        print(f"\n  Decision DNA Analysis")
        print(f"  {'─' * 50}")
        print(f"  Total decisions: {result['total_decisions']}")
        sr = result.get("success_rate", {})
        if sr:
            print(f"  Success rate: {sr.get('success_rate', 0)}% ({sr.get('successes', 0)}/{sr.get('decisions_with_outcomes', 0)})")
        print(f"\n  Top Decision Makers:")
        for maker in result.get("decision_makers", [])[:5]:
            rate = maker.get('success_rate', 0)
            print(f"    {maker['agent']}: {rate}% success ({maker['successes']}/{maker['tracked_outcomes']})")
        print(f"\n  Patterns:")
        for pat in result.get("common_patterns", [])[:3]:
            print(f"    {pat['insight']}")
        print()

    elif action == "dna-outcome":
        result = dna.track_outcome(args.decision_id, args.outcome or "success", float(args.value or 0))
        print(f"\n  Outcome recorded: {result.get('outcome', '')}\n" if result.get("success") else f"\n  {result.get('reason', 'Failed')}\n")

    elif action == "radar2":
        from grid_memory.intel.radar2 import OpportunityRadar2
        radar = OpportunityRadar2(grid)
        result = radar.scan()
        print(f"\n  Opportunity Radar 2.0")
        print(f"  {'─' * 50}")
        print(f"  Opportunities: {result['total']}")
        print(f"  Total value: ${result['total_annual_value']:,.0f}/yr")
        for opp in result["opportunities"][:5]:
            bar = "\u2588" * int(opp["confidence"] * 10) + "\u2591" * (10 - int(opp["confidence"] * 10))
            print(f"\n  {opp['title']}")
            print(f"    ${opp['annual_value']:,.0f}/yr  Confidence: {bar} {opp['confidence']:.0%}")
            print(f"    {opp['evidence']}")
        print()

    elif action == "readiness":
        from grid_memory.intel.readiness import ReadinessEngine
        engine = ReadinessEngine(grid)
        result = engine.assess(client=client or "")
        print(f"\n  Transformation Readiness Assessment")
        print(f"  Client: {result['client']}")
        print(f"  Overall: {result['overall_readiness']}/100 — {result['readiness_level']}")
        print(f"  {'─' * 50}")
        for name, dim in sorted(result['dimensions'].items(), key=lambda x: -x[1]['score']):
            bar = "\u2588" * int(dim['score'] / 10) + "\u2591" * (10 - int(dim['score'] / 10))
            print(f"  {name.title():12}: {bar} {dim['score']}")
        if result.get("strengths"):
            print(f"\n  Strengths:")
            for s in result["strengths"][:3]:
                print(f"    {s}")
        if result.get("gaps"):
            print(f"\n  Priority Gaps:")
            for g in result["gaps"][:3]:
                print(f"    {g}")
        if result.get("roadmap"):
            print(f"\n  Recommended Roadmap:")
            for item in result["roadmap"][:5]:
                print(f"    Phase {item['phase']}: {item['action']}")
        print()

    else:
        print("\n  Intel commands: amnesia, dna, dna-outcome, radar2, readiness\n")

def cmd_tenant(args):
    """Manage tenants and users."""
    from grid_memory.enterprise.tenant import TenantManager
    tm = TenantManager()

    action = args.tenant_action or "list"

    if action == "create":
        r = tm.create_tenant(args.name or "New Tenant", args.domain or "", args.plan or "starter")
        print(f"\n  Tenant created: {r['name']} ({r['tenant_id']})")
        print(f"  Default workspace: {r['workspace_id']}\n")

    elif action == "list":
        tenants = tm.list_tenants()
        if not tenants:
            print("\n  No tenants yet.\n")
            return
        print(f"\n  Tenants ({len(tenants)})")
        print(f"  {'─' * 60}")
        for t in tenants:
            print(f"  {t['id']}: {t['name']} ({t['plan']}) — {t.get('user_count', 0)} users")
        print()

    elif action == "show":
        t = tm.get_tenant(args.tenant_id)
        if not t:
            print(f"\n  Tenant not found: {args.tenant_id}\n")
            return
        print(f"\n  Tenant: {t['name']}")
        print(f"  ID: {t['id']}  Plan: {t['plan']}  Status: {t['status']}")
        print(f"  Users: {t.get('user_count', 0)}")
        print(f"  API calls: {t.get('total_api_calls', 0)}")
        print(f"  Workspaces:")
        for ws in t.get('workspaces', []):
            print(f"    {ws['id']}: {ws['name']} ({ws['backend']}) retention: {ws.get('retention_days', 365)}d")
        print()

    elif action == "user-add":
        r = tm.create_user(args.tenant_id, args.email or "user@example.com", args.name or "", args.role or "viewer")
        print(f"\n  User added: {r['email']} ({r['role']}) [{r['user_id']}]\n")

    elif action == "user-list":
        users = tm.get_users(args.tenant_id)
        if not users:
            print(f"\n  No users in tenant {args.tenant_id}\n")
            return
        print(f"\n  Users ({len(users)})")
        for u in users:
            print(f"  {u['email']} — {u['role']} ({u['status']})")
        print()

    elif action == "retention":
        r = tm.set_retention_policy(args.workspace_id, args.days or 365)
        print(f"\n  Retention set to {r['retention_days']} days for {r['workspace_id']}\n")

    elif action == "encryption":
        r = tm.set_encryption(args.workspace_id, args.enabled or False)
        print(f"\n  Encryption {'enabled' if r['encryption_enabled'] else 'disabled'} for {r['workspace_id']}\n")

    elif action == "usage":
        usage = tm.get_usage(args.tenant_id, args.days or 30)
        print(f"\n  Usage for {usage['tenant_id']} (last {usage['period_days']} days)")
        print(f"  API calls: {usage['total_api_calls']}")
        print(f"  Entries written: {usage['total_entries_written']}")
        print()

    elif action == "admin-summary":
        s = tm.admin_summary()
        print(f"\n  Multi-Tenant Admin Summary")
        print(f"  {'─' * 40}")
        print(f"  Tenants:     {s['total_tenants']}")
        print(f"  Workspaces:  {s['total_workspaces']}")
        print(f"  Users:       {s['total_users']}")
        print(f"  API calls:   {s['total_api_calls']}")
        print(f"  Entries:     {s['total_entries_written']}\n")

    else:
        print("\n  Tenant commands:")
        print("    create --name <org> --domain <domain> --plan <plan>")
        print("    list | show <tenant_id>")
        print("    user-add <tenant_id> --email <email> --role <role>")
        print("    user-list <tenant_id>")
        print("    retention <workspace_id> --days 90")
        print("    encryption <workspace_id> --enabled")
        print("    usage <tenant_id> --days 30")
        print("    admin-summary\n")

def cmd_dbops(args):
    """Database operations: backup, archive, optimize."""
    grid = _get_grid(args)
    from grid_memory.enterprise.dbops import DatabaseOps
    dbops = DatabaseOps(grid)

    action = args.db_action or "status"

    if action == "backup":
        result = dbops.backup(args.label or "")
        print(f"\n  Backup created: {result['backup_name']}")
        print(f"  Entries: {result['entries']}  Size: {result['size_kb']} KB\n")

    elif action == "backup-list":
        backups = dbops.list_backups()
        if not backups:
            print("\n  No backups found.\n")
            return
        print(f"\n  Backups ({len(backups)})")
        for b in backups:
            print(f"  {b['name']} — {b['entries']} entries ({b['size_kb']} KB)")
        print()

    elif action == "restore":
        result = dbops.restore(args.backup_name, dry_run=args.dry_run)
        if result.get("success"):
            if result.get("dry_run"):
                print(f"\n  Dry run: would restore {result['would_restore']} entries\n")
            else:
                print(f"\n  Restored {result['restored']} entries from {result['backup']}\n")
        else:
            print(f"\n  {result.get('reason', 'Restore failed')}\n")

    elif action == "archive":
        result = dbops.archive(older_than_days=args.days or 365, delete_after_archive=args.delete)
        print(f"\n  Archived {result['archived']} entries to {result.get('archive_path', '')}\n")

    elif action == "archive-list":
        archives = dbops.list_archives()
        if not archives:
            print("\n  No archives found.\n")
            return
        print(f"\n  Archives ({len(archives)})")
        for a in archives:
            print(f"  {a['name']} — {a['entries']} entries ({a['size_kb']} KB)")
        print()

    elif action == "analyze":
        analysis = dbops.analyze_queries()
        print(f"\n  Query Analysis — {analysis['analyzed_entries']} entries")
        for rec in analysis.get("recommendations", []):
            print(f"  [{rec['priority'].upper()}] {rec['finding']}")
            print(f"    \u2192 {rec['recommendation']}")
        print()

    elif action == "status":
        status = dbops.pool_status()
        print(f"\n  Database Status")
        print(f"  Backend: {status['backend_type']}")
        print(f"  Entries: {status['total_entries']} ({status['alive_entries']} alive)")
        print(f"  Agents: {status['unique_agents']}")
        print(f"  Size: {status['store_size_kb']} KB")
        print(f"  Status: {status['status']}\n")

    elif action == "indexes":
        info = dbops.index_info()
        print(f"\n  Index Information ({info['backend']})")
        print(f"  Present: {', '.join(info['indexes_present'])}")
        if info.get("recommended_indexes"):
            for r in info["recommended_indexes"]:
                print(f"  Recommended: {r}")
        print()

    elif action == "auto-backup":
        if args.stop:
            r = dbops.stop_auto_backup()
            print(f"\n  Auto-backup {'stopped' if r.get('stopped') else 'not running'}\n")
        else:
            r = dbops.start_auto_backup(interval_hours=args.interval or 24)
            print(f"\n  Auto-backup started (every {args.interval or 24}h)\n")

def cmd_opp_engine(args):
    """Opportunity engine: links, win/loss, ROI, ranking."""
    grid = _get_grid(args)
    from grid_memory.opportunity_engine import OpportunityEngine
    engine = OpportunityEngine(grid)

    action = args.opp_e_action or "summary"

    if action == "win":
        r = engine.track_win_loss(args.opportunity_id, "won", args.reason or "", args.revenue or 0)
        print(f"\n  Recorded win: ${r['revenue']:,.0f}\n")

    elif action == "loss":
        r = engine.track_win_loss(args.opportunity_id, "lost", args.reason or "", args.value or 0)
        print(f"\n  Recorded loss: {r['reason']}\n")

    elif action == "roi":
        r = engine.track_roi(args.opportunity_id, args.actual or 0, args.hours or 0, args.notes or "")
        print(f"\n  ROI: ${r['actual']:,.0f} actual vs ${r['estimated']:,.0f} estimated ({r['accuracy']}% accurate)\n")

    elif action == "link-proposal":
        r = engine.link_proposal(args.opportunity_id, args.link_id or "")
        print(f"\n  Linked to proposal: {r['proposal_id']}\n")

    elif action == "link-project":
        r = engine.link_project(args.opportunity_id, args.link_id or "")
        print(f"\n  Linked to project: {r['project_id']}\n")

    elif action == "graph":
        g = engine.get_opportunity_graph(args.opportunity_id)
        print(f"\n  Opportunity Graph: {g['opportunity_id'][:20]}")
        for link in g.get("links", []):
            print(f"  {link['type']}: {link.get('id', '')}")
        for o in g.get("outcomes", []):
            print(f"  Result: {o.get('result', '')} — {o.get('reason', '')}")
        if g.get("roi"):
            print(f"  ROI accuracy: {g['roi']['accuracy']}%")
        print()

    elif action == "analytics":
        a = engine.get_opportunity_analytics()
        print(f"\n  Opportunity Analytics")
        print(f"  Win rate: {a['win_rate']}% ({a['wins']} of {a['total_outcomes']})")
        print(f"  Revenue: ${a['total_revenue']:,.0f} (avg ${a['avg_deal_size']:,.0f}/deal)")
        print(f"  Avg accuracy: {a['avg_accuracy']}%")
        if a.get("top_win_reasons"): print(f"  Win reasons: {', '.join(a['top_win_reasons'][:3])}")
        if a.get("top_loss_reasons"): print(f"  Loss reasons: {', '.join(a['top_loss_reasons'][:3])}")
        print()

    elif action == "rank":
        r = engine.rank_opportunities()
        print(f"\n  Ranked Opportunities ({r['total']})")
        for opp in r["ranked"][:10]:
            print(f"  ${opp['priority_score']:>8,.0f} [{opp['stage']}] {opp['content'][:60]}")
        print()

    else:
        s = engine.summary()
        print(f"\n  Opportunity Engine Summary")
        print(f"  Win rate: {s['analytics']['win_rate']}%  Revenue: ${s['analytics']['total_revenue']:,.0f}")
        for stage, count in s.get("by_stage", {}).items():
            if count > 0:
                print(f"  {stage}: {count}")
        print()

def cmd_dashboard(args):
    """Generate business intelligence dashboards."""
    from grid_memory.workspace import WorkspaceManager
    from grid_memory.business.dashboards import ExecutiveDashboard, RevenueDashboard, ExpansionDashboard, PortfolioDashboard, ProposalDashboard
    mgr = WorkspaceManager()
    grid = _get_grid(args)
    client = args.client or mgr.get_active() or ""

    d = args.dash_action or "executive"

    if d == "executive":
        ed = ExecutiveDashboard(grid, client)
        r = ed.generate()
        print(f"\n  Executive Dashboard — {r['client'] or 'All'}")
        print(f"  Entries: {r['total_entries']}  Agents: {r['active_agents']}")
        for t, c in r.get("activity_by_type", {}).items():
            print(f"  {t}: {c}")
        print()

    elif d == "revenue":
        rd = RevenueDashboard(grid)
        r = rd.generate()
        print(f"\n  Revenue Dashboard")
        print(f"  Revenue: ${r['total_revenue']:,.0f}  Win Rate: {r['win_rate']}%")
        print(f"  Avg Deal: ${r['avg_deal_size']:,.0f}  Accuracy: {r['avg_accuracy']}%")
        print(f"  Pipeline: ${r['pipeline_value']:,.0f}\n")

    elif d == "expansion":
        ed = ExpansionDashboard(mgr)
        r = ed.generate()
        print(f"\n  Expansion Dashboard ({r['total']} clients)")
        for c in r.get("clients", [])[:10]:
            print(f"  {c['client']}: {c['won_opportunities']} won, {c['lessons']} lessons")
        print()

    elif d == "portfolio":
        pd = PortfolioDashboard(mgr)
        r = pd.generate()
        print(f"\n  Portfolio Dashboard ({r['total']} clients)")
        for c in r.get("clients", [])[:10]:
            print(f"  {c['id']}: {c['entries']} entries, {c['agents']} agents")
        print()

    elif d == "proposals":
        pd = ProposalDashboard(grid)
        r = pd.generate()
        print(f"\n  Proposal Dashboard")
        print(f"  In proposal: {r['in_proposal']}  In assessment: {r['in_assessment']}\n")


def cmd_governance(args):
    """Enterprise governance operations."""
    grid = _get_grid(args)
    from grid_memory.enterprise.governance import GovernanceEngine
    gov = GovernanceEngine(grid)
    action = args.gov_action or "status"

    if action == "classify":
        content = args.content or ""
        if not content: print("\n  Provide --content\n"); return
        r = gov.classify_content(content)
        print(f"\n  Classification: {r['classification'].upper()}\n  Reason: {r['reason']}\n")

    elif action == "compliance":
        r = gov.compliance_check(framework=args.framework or "hipaa")
        print(f"\n  Compliance Check: {r['framework']} — {r['compliance_score']}% ({r['passed']}/{r['total']})")
        for c in r.get("checks", []):
            icon = "✅" if c["passed"] else "❌"
            print(f"  {icon} {c['rule']}: {c['evidence']}")
        print()

    elif action == "legal-hold":
        ws = args.workspace_id or ""
        if not ws: print("\n  Provide --workspace-id\n"); return
        r = gov.legal_hold(ws, args.case_id or "unknown")
        print(f"\n  Legal hold placed on {r['workspace']}\n")


def cmd_knowledge(args):
    """Knowledge operations."""
    grid = _get_grid(args)
    from grid_memory.knowledge_ops import KnowledgeOps
    ko = KnowledgeOps(grid)
    action = args.k_action or "audit"

    if action == "audit":
        r = ko.audit_knowledge()
        print(f"\n  Knowledge Audit")
        print(f"  Lessons: {r['total_lessons']}  Patterns: {r['total_patterns']}")
        print(f"  Categories: {r['by_category']}")
        print(f"  Projects: {r['projects_covered']}  Clients: {r['clients_covered']}\n")

    elif action == "accelerator":
        domain = args.domain or ""
        if not domain: print("\n  Provide --domain\n"); return
        r = ko.generate_accelerator_from_lessons(domain, args.min_lessons or 3)
        if r.get("generated"):
            print(f"\n  Accelerator generated for '{domain}' from {r['lessons_used']} lessons\n")
        else:
            print(f"\n  {r.get('reason', 'Failed')}\n")

    elif action == "cross":
        r = ko.cross_engagement_learning()
        print(f"\n  Cross-Engagement Learning")
        print(f"  Cross-cutting topics: {r['total_cross_cutting_topics']}")
        for item in r.get("top_cross_cutting", [])[:5]:
            print(f"  '{item['topic']}' across {', '.join(item['projects'][:3])}")
        print()
