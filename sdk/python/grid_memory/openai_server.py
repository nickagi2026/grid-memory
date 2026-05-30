"""
openai_server.py — OpenAI-compatible server for LocalGrid

Starts an HTTP server that exposes:
- GET  /v1/models
- POST /v1/chat/completions

Every request transparently injects Grid context into the system message,
then forwards to the upstream LLM.

Usage:
    # With upstream LLM
    GRID_UPSTREAM_API_KEY=sk-... GRID_UPSTREAM_URL=https://api.openai.com \\
        python -m grid_memory.openai_server

    # Debug mode (no upstream — shows enriched messages)
    python -m grid_memory.openai_server

    # Any framework with custom base_url:
    #   base_url = "http://localhost:8080/v1"
    #   api_key = "not-needed"
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, List, Optional, Any

from grid_memory.local_grid import LocalGrid


# ─── Configuration ──────────────────────────────────────────────────────────────

UPSTREAM_URL = os.environ.get("GRID_UPSTREAM_URL", "https://api.openai.com").rstrip("/")
UPSTREAM_API_KEY = os.environ.get("GRID_UPSTREAM_API_KEY", "")
DEFAULT_MODEL = os.environ.get("GRID_UPSTREAM_MODEL", "")
PROXY_TIMEOUT = int(os.environ.get("GRID_PROXY_TIMEOUT", "60"))
STORE_DIR = os.environ.get("GRID_STORE_DIR", None)
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8080"))


# ─── Helpers ────────────────────────────────────────────────────────────────────


def obfuscate_key(key: str) -> str:
    if not key or len(key) < 8:
        return key or ""
    return key[:4] + "..." + key[-4:]


# ─── Context Injection ─────────────────────────────────────────────────────────


def inject_into_messages(
    messages: List[Dict], context_block: str
) -> List[Dict]:
    """Inject Grid context into the system message."""
    if not context_block or not messages:
        return messages

    preamble = (
        f"\u2500\u2500\u2500 SHARED MEMORY GRID CONTEXT \u2500\u2500\u2500\n"
        f"{context_block}"
        f"\n\u2500\u2500\u2500 END GRID CONTEXT \u2500\u2500\u2500\n\n"
    )

    # Find the system message
    for i, msg in enumerate(messages):
        if msg.get("role") == "system":
            enriched = list(messages)
            existing = enriched[i].get("content", "")
            enriched[i] = {**enriched[i], "content": preamble + existing}
            return enriched

    # No system message — prepend one
    return [
        {
            "role": "system",
            "content": preamble
            + "You are a helpful assistant with access to shared team memory.",
        },
        *messages,
    ]


# ─── Upstream Forwarder ────────────────────────────────────────────────────────


def forward_to_upstream(body: Dict) -> Dict:
    """Forward a chat completion request to the upstream LLM."""
    data = json.dumps(body).encode()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {UPSTREAM_API_KEY}",
    }

    req = urllib.request.Request(
        f"{UPSTREAM_URL}/v1/chat/completions",
        data=data,
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=PROXY_TIMEOUT) as resp:
            return {"status": resp.status, "body": json.loads(resp.read())}
    except urllib.error.HTTPError as e:
        body = e.read()
        try:
            detail = json.loads(body)
        except json.JSONDecodeError:
            detail = {"error": body.decode()}
        return {"status": e.code, "body": detail}
    except urllib.error.URLError as e:
        return {"status": 502, "body": {"error": {"message": f"Upstream error: {e.reason}"}}}


# ─── Request Handler ───────────────────────────────────────────────────────────


class GridProxyHandler(BaseHTTPRequestHandler):
    """HTTP handler for the OpenAI-compatible proxy."""

    grid: LocalGrid = None

    def log_message(self, format, *args):
        sys.stderr.write(f"[Grid Proxy] {args[0]} {args[1]} {args[2]}\n")

    def _respond(self, status: int, data: Any):
        body = json.dumps(data, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _error(self, message: str, status: int = 400, code: str = "INVALID_PARAMETER"):
        self._respond(status, {
            "error": {"message": message, "type": "error", "code": code, "param": None}
        })

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        if self.path == "/v1/models":
            self._handle_models()
        elif self.path.startswith("/v1/"):
            self._error(f"Not found: GET {self.path}", 404, "NOT_FOUND")
        else:
            self._error(f"Not found: GET {self.path}", 404, "NOT_FOUND")

    def do_POST(self):
        if self.path == "/v1/chat/completions":
            self._handle_chat()
        elif self.path.startswith("/v1/"):
            self._error(f"Not found: POST {self.path}", 404, "NOT_FOUND")
        else:
            self._error(f"Not found: POST {self.path}", 404, "NOT_FOUND")

    def _handle_models(self):
        models = [{
            "id": "grid-proxy",
            "object": "model",
            "created": int(time.time()),
            "owned_by": "grid",
            "description": "Grid Memory proxy — injects context, forwards to upstream LLM",
        }]
        if DEFAULT_MODEL:
            models.insert(0, {
                "id": DEFAULT_MODEL,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "grid-proxy",
            })
        self._respond(200, {"object": "list", "data": models})

    def _handle_chat(self):
        # Parse body
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            return self._error("Request body is required")

        raw = self.rfile.read(content_length)
        try:
            body = json.loads(raw)
        except json.JSONDecodeError:
            return self._error("Invalid JSON in request body")

        # Validate
        messages = body.get("messages", [])
        if not messages or not isinstance(messages, list):
            return self._error("messages is required and must be a non-empty array")

        # Get context hint from last user message
        context_hint = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                context_hint = msg.get("content", "")
                break

        # Inject Grid context
        context_block = ""
        try:
            inject_result = self.grid.inject(context=context_hint)
            context_block = inject_result.get("block", "")
        except Exception as e:
            print(f"[Grid Proxy] Context injection failed: {e}", file=sys.stderr)

        # Enrich messages
        enriched = inject_into_messages(messages, context_block)

        # Build forward body
        forward_body: Dict[str, Any] = {
            "model": body.get("model") or DEFAULT_MODEL or "gpt-4o",
            "messages": enriched,
        }
        for key in ("temperature", "max_tokens", "top_p", "frequency_penalty",
                     "presence_penalty", "stop", "stream"):
            if key in body:
                forward_body[key] = body[key]

        # Check upstream
        if not UPSTREAM_API_KEY:
            # Debug mode — return enriched messages
            entry_count = context_block.count("\n[") if context_block else 0
            self._respond(200, {
                "id": f"grid_{int(time.time() * 1000)}",
                "object": "chat.completion",
                "created": int(time.time()),
                "model": forward_body["model"],
                "choices": [{
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": (
                            f"[Grid Proxy] No upstream API key configured "
                            f"(GRID_UPSTREAM_API_KEY).\n\n"
                            f"Enriched messages would have been:\n\n"
                            f"{json.dumps(enriched, indent=2)}"
                        ),
                    },
                    "finish_reason": "stop",
                }],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                "_grid_context_injected": bool(context_block),
                "_grid_entry_count": entry_count,
            })
            return

        # Forward to upstream
        try:
            upstream = forward_to_upstream(forward_body)
        except Exception as e:
            return self._error(f"Upstream LLM error: {e}", 502)

        # Log exchange to Grid
        try:
            user_preview = context_hint[:200].replace("\n", " ")
            assistant_content = (
                upstream.get("body", {})
                .get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
            )
            assistant_preview = assistant_content[:200].replace("\n", " ")
            self.grid.fact(
                f"[LLM] User: {user_preview}\nAssistant: {assistant_preview}",
                tags=["llm-exchange", f"model:{forward_body['model']}"],
                agent_id="openai-proxy",
                ttl_seconds=3600,
            )
        except Exception as e:
            print(f"[Grid Proxy] Logging failed: {e}", file=sys.stderr)

        # Return response
        response = upstream.get("body", {})
        if isinstance(response, dict):
            response["_grid_context_injected"] = bool(context_block)
            response["_grid_entry_count"] = context_block.count("\n[") if context_block else 0

        self._respond(upstream.get("status", 502), response)


# ─── Server ─────────────────────────────────────────────────────────────────────


def run_server():
    grid = LocalGrid(store_dir=STORE_DIR)

    # Monkey-patch the grid instance onto the handler class
    GridProxyHandler.grid = grid

    server = HTTPServer((HOST, PORT), GridProxyHandler)

    print(f"\u2550\u2550\u2550 Grid Memory Proxy (OpenAI-compatible) \u2550\u2550\u2550")
    print(f"Listening on http://{HOST}:{PORT}")
    print(f"Endpoints:")
    print(f"  GET  /v1/models             \u2014 List available models")
    print(f"  POST /v1/chat/completions   \u2014 Chat completions with context injection")
    if UPSTREAM_API_KEY:
        print(f"Upstream: {UPSTREAM_URL} (key: {obfuscate_key(UPSTREAM_API_KEY)})")
    else:
        print(f"Upstream: NOT CONFIGURED \u2014 set GRID_UPSTREAM_API_KEY. Returns debug responses.")
    print(f"Store dir: {grid._store_dir}")
    print(f"\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550\u2550")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.server_close()


if __name__ == "__main__":
    run_server()
