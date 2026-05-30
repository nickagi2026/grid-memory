"""
Tests for the OpenAI-compatible proxy server (Python).

Requires a running Python proxy at the configured URL.
Start one with:
    PORT=9098 python -m grid_memory.openai_server
"""

import json
import os
import shutil
import tempfile
import time
import unittest
import urllib.error
import urllib.request

TEST_URL = os.environ.get("GRID_URL", "http://localhost:9098")


def post(path, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{TEST_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def get(path):
    try:
        with urllib.request.urlopen(f"{TEST_URL}{path}", timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


class TestOpenAIProxyPython(unittest.TestCase):
    """Tests for the Python OpenAI-compatible proxy."""

    @classmethod
    def setUpClass(cls):
        # Verify server is running
        try:
            status, _ = get("/v1/models")
            if status != 200:
                raise unittest.SkipTest(f"Proxy server not available at {TEST_URL}")
        except Exception as e:
            raise unittest.SkipTest(f"Proxy server not available at {TEST_URL}: {e}")

    def test_01_models_endpoint(self):
        """GET /v1/models returns model list."""
        status, data = get("/v1/models")
        self.assertEqual(status, 200)
        self.assertEqual(data["object"], "list")
        self.assertTrue(len(data["data"]) >= 1)
        model_ids = [m["id"] for m in data["data"]]
        self.assertIn("grid-proxy", model_ids)

    def test_02_chat_debug_response(self):
        """POST /v1/chat/completions returns debug response without upstream key."""
        status, data = post("/v1/chat/completions", {
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "Hello"},
            ],
        })
        self.assertEqual(status, 200)
        self.assertIn("id", data)
        self.assertEqual(data["object"], "chat.completion")
        self.assertTrue(len(data["choices"]) >= 1)
        content = data["choices"][0]["message"]["content"]
        self.assertIn("SHARED MEMORY GRID CONTEXT", content)
        self.assertIn("Enriched messages", content)

    def test_03_context_injection(self):
        """Grid context is injected into the system message."""
        # Write data to the grid first (proxy shares LocalGrid)
        status, write_data = post("/v1/chat/completions", {
            "model": "gpt-4o",
            "messages": [
                {"role": "system", "content": "Record this fact."},
                {"role": "user", "content": "The API server runs on port 3000"},
            ],
        })
        self.assertEqual(status, 200)

        # Now query about the API
        status, data = post("/v1/chat/completions", {
            "model": "gpt-4o",
            "messages": [
                {"role": "user", "content": "What port does the API run on?"},
            ],
        })
        self.assertEqual(status, 200)
        self.assertTrue(data.get("_grid_context_injected", False),
                        "Context should be injected")

    def test_04_empty_messages(self):
        """Empty messages returns 400."""
        status, data = post("/v1/chat/completions", {
            "model": "gpt-4o",
            "messages": [],
        })
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_05_missing_messages(self):
        """Missing messages returns 400."""
        status, data = post("/v1/chat/completions", {"model": "gpt-4o"})
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_06_creates_system_message_when_missing(self):
        """When no system message exists, one is created with Grid context."""
        status, data = post("/v1/chat/completions", {
            "model": "gpt-4o",
            "messages": [
                {"role": "user", "content": "Just a test"},
            ],
        })
        self.assertEqual(status, 200)
        content = data["choices"][0]["message"]["content"]
        self.assertIn("SHARED MEMORY GRID CONTEXT", content)

    def test_07_response_structure(self):
        """Response has the expected OpenAI-compatible structure."""
        status, data = post("/v1/chat/completions", {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Hi"}],
        })
        self.assertEqual(status, 200)
        self.assertIn("id", data)
        self.assertIn("created", data)
        self.assertIn("model", data)
        self.assertIn("choices", data)
        self.assertIn("usage", data)

        choice = data["choices"][0]
        self.assertIn("index", choice)
        self.assertIn("message", choice)
        self.assertIn("finish_reason", choice)
        self.assertIn("role", choice["message"])
        self.assertIn("content", choice["message"])

    def test_08_grid_metadata(self):
        """Response includes grid metadata."""
        status, data = post("/v1/chat/completions", {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "metadata test"}],
        })
        self.assertEqual(status, 200)
        self.assertIn("_grid_context_injected", data)
        self.assertIn("_grid_entry_count", data)

    def test_09_unknown_model(self):
        """Unknown model gracefully handled."""
        status, data = post("/v1/chat/completions", {
            "model": "nonexistent-model-9000",
            "messages": [{"role": "user", "content": "Hi"}],
        })
        self.assertEqual(status, 200)  # Still returns debug response

    def test_10_streaming_flag(self):
        """Streaming flag is accepted (returns debug response, not actual stream)."""
        status, data = post("/v1/chat/completions", {
            "model": "gpt-4o",
            "messages": [{"role": "user", "content": "Stream test"}],
            "stream": True,
        })
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main()
