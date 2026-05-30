#!/usr/bin/env python3
"""
Enterprise Gateway — Python-based auth/audit server using SQLite.

Replaces the Node.js gateway's JSON file storage with proper SQLite.
All API keys and audit logs are stored in SQLite databases.

Usage:
  python3 enterprise-gateway.py --port 9091

Then configure your Grid server to use this gateway:
  GRID_AUTH_DB=http://localhost:9091  (coming soon)
"""

import datetime
import hashlib
import json
import os
import secrets
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from grid_memory.enterprise.auth import KeyManager
from grid_memory.enterprise.audit import AuditTrail


AUTH_DB = os.environ.get("GRID_AUTH_DB", os.path.expanduser("~/.openclaw/auth/keys.db"))
AUDIT_DB = os.environ.get("GRID_AUDIT_DB", os.path.expanduser("~/.openclaw/audit/audit.db"))
MASTER_KEY = os.environ.get("GATEWAY_MASTER_KEY", "")
PORT = int(os.environ.get("PORT", "9091"))
HOST = os.environ.get("HOST", "0.0.0.0")

km = KeyManager(db_path=AUTH_DB)
audit = AuditTrail(db_path=AUDIT_DB)


class GatewayHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write(f"[Gateway] {args[0]} {args[1]} {args[2]}\n")

    def _check_auth(self, require_admin=False):
        """Check GATEWAY_MASTER_KEY authentication.
        Returns error response if unauthorized, None if allowed.
        """
        if not MASTER_KEY:
            return True  # No auth required if no master key set (dev mode)
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer ") or auth[7:] != MASTER_KEY:
            self._json({"error": "Unauthorized. Set GATEWAY_MASTER_KEY and send Authorization: Bearer <key>"}, 401)
            return False
        return True

    def _json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self):
        if self.path == "/health":
            return self._json({"status": "ok", "auth_backend": "sqlite", "audit_backend": "sqlite"})
        self._json({"error": "Not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        if self.path == "/gateway/key/create":
            if not self._check_auth():
                return
            result = km.create_key(
                label=body.get("label", "api-key"),
                workspace=body.get("workspace", "*"),
                permission=body.get("permission", "viewer"),
                created_by=body.get("created_by", "gateway"),
            )
            return self._json(result)

        if self.path == "/gateway/key/validate":
            result = km.validate_key(
                plaintext_key=body.get("key", ""),
                required_permission=body.get("permission", "read"),
                workspace=body.get("workspace", ""),
            )
            return self._json(result)

        if self.path == "/gateway/audit":
            if not self._check_auth():
                return
            result = audit.log(
                action=body.get("action", "unknown"),
                entity_type=body.get("entity_type", ""),
                entity_id=body.get("entity_id", ""),
                workspace=body.get("workspace", ""),
                actor=body.get("actor", "gateway"),
                detail=body.get("detail", ""),
            )
            return self._json(result)

        self._json({"error": "Not found"}, 404)

    def do_DELETE(self):
        if self.path.startswith("/gateway/key/revoke/"):
            if not self._check_auth():
                return
            key_id = self.path.split("/")[-1]
            result = km.revoke_key(key_id)
            return self._json(result)
        self._json({"error": "Not found"}, 404)


if __name__ == "__main__":
    print(f"Enterprise Gateway (SQLite auth/audit) on http://{HOST}:{PORT}")
    print(f"  Auth DB: {AUTH_DB}")
    print(f"  Audit DB: {AUDIT_DB}")
    server = HTTPServer((HOST, PORT), GatewayHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
