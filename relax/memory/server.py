# Copyright (c) 2026 Relax Authors. All Rights Reserved.

"""Authenticated single-process Memory gateway for trusted private networks."""

from __future__ import annotations

import json
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from relax.memory.store import MemoryStore, encode


def dispatch(store: MemoryStore, principal: dict[str, Any], action: str, args: dict[str, Any]) -> Any:
    if principal["role"] == "agent":
        if action == "memory_search":
            return store.read(principal, **args)
        if action == "memory_get":
            if set(args) - {"memory_id", "max_bytes"} or "memory_id" not in args:
                raise ValueError("memory_get requires memory_id and optional max_bytes")
            return store.read(principal, **args)
        if action == "memory_propose":
            return store.stage(principal["namespace"], principal["session"], **args)
        if action == "memory_feedback":
            return store.feedback(principal, **args)
        if action == "memory_replay":
            return store.receipt(principal, **args)
        raise PermissionError("Action is not available to this credential")
    if principal["role"] != "admin":
        raise PermissionError("Administrator credential required")
    operations = {
        "snapshot_create": store.create_snapshot,
        "snapshot_get": store.snapshot,
        "session_bind": store.bind,
        "candidate_list": store.candidates,
        "candidate_stage": store.stage,
        "candidate_commit": store.commit,
        "record_expire": store.expire,
    }
    if action not in operations:
        raise ValueError("Unknown administrator action")
    return operations[action](**args)


def make_server(database: str | Path, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    """Bind loopback by default; terminate TLS at a gateway for remote
    access."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            # HTTP paths and request content can contain private project data.
            return

        def respond(self, status: int, data: dict[str, Any]) -> None:
            body = encode(data).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            self.respond(200 if self.path == "/health" else 404, {"service": "relax-memory"})

        def do_POST(self) -> None:
            self.connection.settimeout(30)
            if self.path != "/v1/memory":
                self.respond(404, {"error": "not_found"})
                return
            # No browser use or cross-origin credential forwarding in this API.
            if self.headers.get("Origin"):
                self.respond(403, {"error": "browser_origin_not_supported"})
                return
            try:
                with MemoryStore(database) as store:
                    authorization = self.headers.get("Authorization", "")
                    if not authorization.startswith("Bearer "):
                        raise PermissionError("Missing credential")
                    principal = store.authenticate(authorization.removeprefix("Bearer "))
                    size = int(self.headers.get("Content-Length", "0"))
                    if not 0 < size <= 128 * 1024:
                        raise ValueError("Invalid body length")
                    payload = json.loads(self.rfile.read(size))
                    if not isinstance(payload, dict) or set(payload) != {"action", "arguments"}:
                        raise ValueError("Expected action and arguments")
                    if not isinstance(payload["action"], str) or not isinstance(payload["arguments"], dict):
                        raise ValueError("Invalid action or arguments")
                    result = dispatch(store, principal, payload["action"], payload["arguments"])
                self.respond(200, {"result": result})
            except PermissionError:
                self.respond(403, {"error": "forbidden"})
            except (ValueError, TypeError, KeyError, UnicodeDecodeError):
                self.respond(400, {"error": "invalid_request_or_conflict"})
            except (sqlite3.Error, OSError):
                self.respond(503, {"error": "storage_or_transport_unavailable"})

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server
