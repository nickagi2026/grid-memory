# grid_memory - Python SDK for the Grid Memory Server
#
# Usage:
#   from grid_memory import Grid
#   grid = Grid("http://localhost:8080")
#
#   # Write
#   grid.fact("PostgreSQL pool: 25", tags=["database", "project:mercury"],
#             agent_id="architect")
#   grid.decide("Use Express over Fastify", tags=["architecture"],
#               rationale="Middleware ecosystem maturity", agent_id="architect")
#   grid.handoff(from_agent="researcher", to_agent="builder",
#                content="API spec ready at docs/api-v2.md", status="ready")
#
#   # Read
#   entries = grid.query(tags=["project:mercury"])
#   context = grid.inject("building the API layer")
#
#   # Admin
#   info = grid.info()
#   grid.prune()

__version__ = "1.1.0"

import json
import urllib.request
import urllib.error
import urllib.parse
from typing import Optional, List, Dict, Any


class GridError(Exception):
    """Raised when the Grid server returns an error."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class Grid:
    """Client for the Grid Memory HTTP API.

    Args:
        url: Grid server URL (default: http://localhost:8080)
        default_agent_id: Default agent_id used by convenience methods
                          when no explicit agent_id is passed (default: "python-sdk")
    """

    def __init__(self, url: str = "http://localhost:8080",
                 default_agent_id: str = "python-sdk",
                 timeout: int = 10):
        self.url = url.rstrip("/")
        self.default_agent_id = default_agent_id
        self.timeout = timeout

    def _get(self, path: str, query: Optional[Dict] = None) -> Dict:
        qs = "?" + urllib.parse.urlencode(query, doseq=True) if query else ""
        try:
            with urllib.request.urlopen(
                f"{self.url}{path}{qs}", timeout=self.timeout
            ) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read()
            try:
                detail = json.loads(body)
                raise GridError(detail.get("error", str(e)), status_code=e.code)
            except (json.JSONDecodeError, GridError):
                raise GridError(f"HTTP {e.code}: {body.decode()}", status_code=e.code)
        except urllib.error.URLError as e:
            raise GridError(f"Connection failed: {e.reason}")

    def _post(self, path: str, body: Dict) -> Dict:
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            f"{self.url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read()
            try:
                detail = json.loads(body)
                raise GridError(detail.get("error", str(e)), status_code=e.code)
            except (json.JSONDecodeError, GridError):
                raise GridError(f"HTTP {e.code}: {body.decode()}", status_code=e.code)
        except urllib.error.URLError as e:
            raise GridError(f"Connection failed: {e.reason}")

    # ── Convenience writes ──

    def fact(self, content: str, tags: Optional[List[str]] = None,
             ttl_seconds: Optional[int] = None,
             agent_id: Optional[str] = None) -> Dict:
        """Write a factual observation to the Grid.

        Args:
            content: The fact content
            tags: Optional list of tags
            ttl_seconds: Time-to-live in seconds (default: 24h)
            agent_id: Agent identifier (defaults to instance default_agent_id)
        """
        return self._post("/write", {
            "agent_id": agent_id or self.default_agent_id,
            "type": "fact",
            "content": content,
            "tags": tags or [],
            "ttl_seconds": ttl_seconds
        })

    def decide(self, content: str, tags: Optional[List[str]] = None,
               rationale: Optional[str] = None,
               ttl_seconds: Optional[int] = None,
               agent_id: Optional[str] = None) -> Dict:
        """Write an architectural or design decision with optional rationale.

        Args:
            content: The decision
            tags: Optional list of tags
            rationale: Optional explanation for the decision
            ttl_seconds: Time-to-live in seconds (default: 7 days)
            agent_id: Agent identifier (defaults to instance default_agent_id)
        """
        text = content
        if rationale:
            text = f"{content}\nRationale: {rationale}"
        return self._post("/write", {
            "agent_id": agent_id or self.default_agent_id,
            "type": "decision",
            "content": text,
            "tags": tags or [],
            "ttl_seconds": ttl_seconds or 604800  # 7 days default for decisions
        })

    def handoff(self, from_agent: str, to_agent: str, content: str,
                status: str = "ready",
                tags: Optional[List[str]] = None,
                agent_id: Optional[str] = None) -> Dict:
        """Record a handoff from one agent to another.

        Args:
            from_agent: Source agent name
            to_agent: Target agent name
            content: Handoff details
            status: Status of the handoff (default: "ready")
            tags: Optional additional tags
            agent_id: Override agent identifier (defaults to from_agent)
        """
        text = f"[{from_agent} \u2192 {to_agent}] ({status}): {content}"
        return self._post("/write", {
            "agent_id": agent_id or from_agent,
            "type": "handoff",
            "content": text,
            "tags": (tags or []) + [f"agent:{to_agent}"],
            "ttl_seconds": 3600  # 1 hour default for handoffs
        })

    def write(self, agent_id: str, type: str, content: str,
              tags: Optional[List[str]] = None,
              ttl_seconds: Optional[int] = None,
              session_id: Optional[str] = None) -> Dict:
        """Write a generic entry to the Grid."""
        return self._post("/write", {
            "agent_id": agent_id,
            "type": type,
            "content": content,
            "tags": tags or [],
            "ttl_seconds": ttl_seconds,
            "session_id": session_id or ""
        })

    # ── Query ──

    def query(self, tags: Optional[List[str]] = None,
              agents: Optional[List[str]] = None,
              type: Optional[str] = None,
              types: Optional[List[str]] = None,
              max: Optional[int] = None,
              since: Optional[str] = None,
              tagMode: str = "OR",
              parent_entry: Optional[str] = None) -> Dict:
        """Query the Grid for matching entries.

        Uses POST for complex queries (avoids URL length limits).

        Args:
            tags: Filter by tags (OR/AND based on tagMode)
            agents: Filter by agent IDs
            type: Filter by single type
            types: Filter by multiple types
            max: Maximum results (1-50)
            since: ISO timestamp, only entries after this time
            tagMode: "OR" or "AND" for tag matching
            parent_entry: Filter by parent entry ID
        """
        body: Dict[str, Any] = {
            "tagMode": tagMode,
        }
        if tags:
            body["tags"] = tags
        if agents:
            body["agents"] = agents
        if type:
            body["type"] = type
        if types:
            body["types"] = types
        if max is not None:
            body["max"] = max
        if since:
            body["since"] = since
        if parent_entry:
            body["parent_entry"] = parent_entry

        return self._post("/query", body)

    def inject(self, context: str = "") -> str:
        """Get a formatted context block for agent injection.

        Returns a markdown-style block ready for system prompts.
        Tries POST first, falls back to GET if server doesn't support POST.

        Args:
            context: Current task context for relevance matching
        """
        try:
            result = self._post("/inject", {"context": context})
            return result.get("block", "")
        except GridError:
            # Fallback to GET for servers that don't support POST /inject
            try:
                result = self._get("/inject", {"context": context})
                return result.get("block", "")
            except GridError:
                return ""

    # ── Admin ──

    def info(self) -> Dict:
        """Get store statistics."""
        return self._get("/info")

    def prune(self) -> Dict:
        """Remove expired entries from the store."""
        return self._post("/prune", {})

    def forget(self, entry_id: str) -> Dict:
        """Remove a specific entry by ID."""
        req = urllib.request.Request(
            f"{self.url}/forget/{entry_id}",
            method="DELETE"
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read()
            try:
                detail = json.loads(body)
                raise GridError(detail.get("error", str(e)), status_code=e.code)
            except (json.JSONDecodeError, GridError):
                raise GridError(f"HTTP {e.code}: {body.decode()}", status_code=e.code)
        except urllib.error.URLError as e:
            raise GridError(f"Connection failed: {e.reason}")


# ── Framework Plugins ──

class AutoGenGridPlugin:
    """Drop-in plugin for AutoGen agents v0.2+.

    Automatically injects Grid context before every message and logs
    agent exchanges to the Grid.

    Usage:
        from grid_memory import AutoGenGridPlugin

        grid_plugin = AutoGenGridPlugin(agent_id="researcher")

        agent = autogen.AssistantAgent(
            name="researcher",
            llm_config=llm_config,
        )

        # Wrap the generate_reply / send methods via the plugin
        agent = grid_plugin.wrap(agent)
    """

    def __init__(self, url: str = "http://localhost:8080",
                 agent_id: str = "autogen-agent",
                 inject_before_message: bool = True):
        self.grid = Grid(url, default_agent_id=agent_id)
        self.agent_id = agent_id
        self.inject_before_message = inject_before_message
        self._original_generate_reply = None
        self._original_send = None

    def get_context(self, message: str) -> str:
        """Get Grid context enriched for an AutoGen agent."""
        ctx = self.grid.inject(context=message)
        if ctx:
            return f"{ctx}\n\n---\n\n{message}"
        return message

    def log_exchange(self, message: str, response: str) -> None:
        """Log an agent exchange to the Grid."""
        msg_preview = message[:200].replace("\n", " ") if message else ""
        resp_preview = response[:200].replace("\n", " ") if response else ""
        self.grid.fact(
            f"[{self.agent_id}] Received: {msg_preview} \u2192 Produced: {resp_preview}",
            tags=[f"agent:{self.agent_id}", "autogen"]
        )

    def wrap(self, agent):
        """Wrap an AutoGen agent's generate_reply and send methods.

        This is a duck-punch approach that works across AutoGen v0.2+
        without relying on specific internal APIs.
        """
        plugin = self

        if hasattr(agent, 'generate_reply') and not getattr(agent, '_grid_wrapped', False):
            orig = agent.generate_reply

            async def wrapped_generate_reply(messages, *args, **kwargs):
                if plugin.inject_before_message and messages:
                    last = messages[-1]
                    if isinstance(last, dict) and 'content' in last:
                        last['content'] = plugin.get_context(last.get('content', ''))
                result = await orig(messages, *args, **kwargs) if hasattr(orig, '__await__') else orig(messages, *args, **kwargs)
                if messages:
                    msg = messages[-1].get('content', '') if isinstance(messages[-1], dict) else str(messages[-1])
                    resp = result.get('content', '') if isinstance(result, dict) else str(result)
                    plugin.log_exchange(msg, resp)
                return result

            agent.generate_reply = wrapped_generate_reply

        if hasattr(agent, 'send') and not getattr(agent, '_grid_wrapped', False):
            orig = agent.send

            async def wrapped_send(message, recipient, *args, **kwargs):
                msg = message.get('content', '') if isinstance(message, dict) else str(message)
                result = await orig(message, recipient, *args, **kwargs) if hasattr(orig, '__await__') else orig(message, recipient, *args, **kwargs)
                resp = result.get('content', '') if isinstance(result, dict) else str(result)
                plugin.log_exchange(msg, resp)
                return result

            agent.send = wrapped_send

        agent._grid_wrapped = True
        return agent


class CrewAITool:
    """CrewAI-compatible tool for reading/writing to the Grid.

    Usage:
        from grid_memory import CrewAITool
        from crewai import Agent, Task

        grid_tool = CrewAITool(agent_id="researcher")

        agent = Agent(
            name="Researcher",
            tools=[grid_tool.query_tool(), grid_tool.write_tool()],
            ...
        )
    """

    def __init__(self, url: str = "http://localhost:8080",
                 agent_id: str = "crewai-agent"):
        self.grid = Grid(url, default_agent_id=agent_id)
        self.agent_id = agent_id

    def query_tool(self):
        """Returns a callable tool for CrewAI agents to query the Grid."""
        def _query(**kwargs):
            tags = kwargs.get("tags", "").split(",") if isinstance(kwargs.get("tags"), str) else kwargs.get("tags", [])
            agents = kwargs.get("agents", "").split(",") if isinstance(kwargs.get("agents"), str) else kwargs.get("agents", [])
            result = self.grid.query(
                tags=tags if tags else None,
                agents=agents if agents else None,
                type=kwargs.get("type"),
                max=kwargs.get("max", 10),
                tagMode=kwargs.get("tag_mode", "OR")
            )
            entries = result.get("entries", [])
            if not entries:
                return "No matching entries found in the Grid."
            lines = ["Found Grid entries:"]
            for e in entries:
                lines.append(f"[{e['type']}] {e['agent_id']}: {e['content'][:200]}")
            return "\n".join(lines)
        _query.__name__ = "grid_query"
        _query.__doc__ = "Query the shared memory grid for relevant context. Args: tags (comma-separated), agents (comma-separated), type, max, tag_mode"
        return _query

    def write_tool(self):
        """Returns a callable tool for CrewAI agents to write to the Grid."""
        def _write(**kwargs):
            content = kwargs.get("content", "")
            if not content:
                return "Error: content is required"
            entry_type = kwargs.get("type", "fact")
            tags = kwargs.get("tags", "").split(",") if isinstance(kwargs.get("tags"), str) else kwargs.get("tags", [])
            result = self.grid.write(
                agent_id=kwargs.get("agent_id", self.agent_id),
                type=entry_type,
                content=content,
                tags=tags if tags else None
            )
            return f"Written to Grid: {result['entry_id']} ({entry_type})"
        _write.__name__ = "grid_write"
        _write.__doc__ = "Write information to the shared memory grid. Args: content (required), type (fact/decision/handoff/observation), tags (comma-separated), agent_id"
        return _write

    def context_tool(self):
        """Returns a callable that injects relevant Grid context."""
        def _get_context(**kwargs):
            task = kwargs.get("task", "")
            block = self.grid.inject(context=task)
            return block if block else "No Grid context available."
        _get_context.__name__ = "grid_context"
        _get_context.__doc__ = "Get relevant context from the shared memory grid for your current task. Args: task (description of what you're working on)"
        return _get_context


def langgraph_grid_node(state_key: str = "messages",
                       grid_url: str = "http://localhost:8080",
                       agent_id: str = "langgraph-agent"):
    """Create a LangGraph node that injects Grid context into the agent state.

    Usage:
        from grid_memory import langgraph_grid_node

        # Create the node function
        inject_context = langgraph_grid_node()

        # Use in your graph
        graph = StateGraph(AgentState)
        graph.add_node("grid_inject", inject_context)
        graph.add_edge("grid_inject", "agent")
    """
    grid = Grid(grid_url, default_agent_id=agent_id)

    def grid_node(state: dict) -> dict:
        """Injects Grid context into the agent state before processing."""
        # Get the last message as context hint
        messages = state.get(state_key, [])
        context_hint = ""
        if messages:
            last = messages[-1]
            if isinstance(last, dict):
                context_hint = last.get("content", "")
            elif hasattr(last, "content"):
                context_hint = last.content

        # Get Grid context
        block = grid.inject(context=context_hint)

        # Store context in state for use by next node
        state["grid_context"] = block
        return state

    return grid_node


# ── Export LocalGrid (embedded engine, no server required) ──

from grid_memory.local_grid import LocalGrid  # noqa: F401
