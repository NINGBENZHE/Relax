#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Dependency-free stdio MCP client for the Relax Cowork project memory API."""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


FIELDS = {
    "title": {"type": "string"},
    "summary": {"type": "string"},
    "content": {"type": "string"},
    "source": {"type": "string"},
    "owner": {"type": "string"},
    "conditions": {"type": "string"},
    "topic": {"type": "string"},
    "tags": {"type": "array", "items": {"type": "string"}},
    "kind": {"type": "string", "enum": ["strategy", "lesson", "episode"]},
    "evidence_level": {"type": "string", "enum": ["documented", "tested", "hypothesis"]},
    "expires_at": {"type": ["string", "null"]},
    "review_after": {"type": ["string", "null"]},
}


def tools() -> list[dict[str, Any]]:
    definitions = [
        (
            "memory_search",
            "Search the fixed project snapshot for this task. Only approved, unexpired-at-task-start records are included.",
            {
                "query": {"type": "string"},
                "max_bytes": {"type": "integer", "minimum": 128, "maximum": 65536},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            ["query"],
        ),
        (
            "memory_get",
            "Read an exact memory ID from the same task snapshot.",
            {"memory_id": {"type": "string"}, "max_bytes": {"type": "integer", "minimum": 128, "maximum": 65536}},
            ["memory_id"],
        ),
        (
            "memory_propose",
            "Submit a candidate for administrator review. Pending is not published. Reuse the idempotency key for network retries.",
            {
                "body": {
                    "type": "object",
                    "properties": FIELDS,
                    "required": ["title", "summary", "content", "source", "owner", "kind", "evidence_level"],
                    "additionalProperties": False,
                },
                "idempotency_key": {"type": "string"},
            },
            ["body", "idempotency_key"],
        ),
        (
            "memory_feedback",
            "Report helpful, outdated or incorrect evidence. Feedback does not change approved records.",
            {
                "receipt_id": {"type": "string"},
                "assessment": {"type": "string", "enum": ["helpful", "outdated", "incorrect"]},
            },
            ["receipt_id", "assessment"],
        ),
    ]
    return [
        {
            "name": name,
            "description": desc,
            "inputSchema": {
                "type": "object",
                "properties": props,
                "required": required,
                "additionalProperties": False,
            },
        }
        for name, desc, props, required in definitions
    ]


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


class Client:
    def __init__(self, endpoint: str, agent_token: str, app_token: str, task_id: str) -> None:
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("endpoint must be an HTTPS application base URL without credentials/query/fragment")
        if not isinstance(agent_token, str) or not isinstance(app_token, str) or not agent_token or not app_token:
            raise ValueError("Both project Agent credential and approved Cowork App Token are required")
        if any(
            not token.isascii() or any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in token)
            for token in (agent_token, app_token)
        ):
            raise ValueError("Credentials must be nonempty ASCII values without whitespace")
        self.endpoint = endpoint.rstrip("/") + "/api/agent"
        self.agent_token, self.app_token, self.task_id = agent_token, app_token, task_id
        self.snapshot = None
        self.opener = build_opener(NoRedirect())

    def request(self, action: str, arguments: dict[str, Any]) -> dict[str, Any]:
        req = Request(
            self.endpoint,
            data=json.dumps({"action": action, "arguments": arguments}, allow_nan=False).encode(),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Authorization": "Bearer " + self.agent_token,
                "App-Api-Token": self.app_token,
            },
            method="POST",
        )
        try:
            with self.opener.open(req, timeout=30) as response:
                raw = response.read(5 * 1024 * 1024 + 1)
            if len(raw) > 5 * 1024 * 1024:
                raise ValueError("Response too large")
            value = json.loads(raw)
        except HTTPError as exc:
            # Never print remote bodies, headers or credential values.
            hint = " Check devops domain and platform App Token approval." if exc.code == 401 else ""
            raise RuntimeError(f"Memory HTTP {exc.code}.{hint}") from None
        except (URLError, OSError, TimeoutError):
            raise RuntimeError(
                "Memory connection failed; submission success is unknown. Retry with the same idempotency key."
            ) from None
        except (UnicodeError, json.JSONDecodeError):
            raise RuntimeError("Memory endpoint returned non-JSON; check gateway authentication") from None
        if not isinstance(value, dict) or "result" not in value:
            raise RuntimeError("Unexpected memory API response; not assumed successful")
        return value["result"]

    def start(self) -> dict[str, Any]:
        result = self.request("task_start", {"task_id": self.task_id})
        self.snapshot = result["snapshot_id"]
        return result

    def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if not self.snapshot:
            self.start()
        if name in {"memory_search", "memory_get"}:
            args = {**args, "snapshot_id": self.snapshot}
        return self.request(name, args)


def serve(client: Client, incoming: TextIO = sys.stdin, outgoing: TextIO = sys.stdout) -> None:
    initialized = False
    ready = False
    definitions = {t["name"]: t for t in tools()}
    while True:
        line = incoming.readline(131073)
        if not line:
            return
        identifier = None
        try:
            if len(line.encode()) > 131072 or not line.endswith("\n"):
                raise ValueError("Request too large or missing newline")
            request = json.loads(line)
            if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
                raise ValueError("Invalid JSON-RPC request")
            identifier = request.get("id")
            method = request.get("method")
            params = request.get("params", {})
            if "id" not in request:
                if method == "notifications/initialized" and initialized:
                    ready = True
                continue
            if not isinstance(params, dict):
                raise ValueError("Invalid params")
            if method == "initialize":
                initialized = True
                result = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "relax-project-memory", "version": "2.0.0"},
                }
            elif method == "ping":
                result = {}
            elif not ready:
                raise ValueError("Initialize first")
            elif method == "tools/list":
                result = {"tools": tools()}
            elif method == "tools/call":
                name = params.get("name")
                args = params.get("arguments", {})
                if name not in definitions or not isinstance(args, dict):
                    raise ValueError("Unknown tool")
                schema = definitions[name]["inputSchema"]
                if set(args) - schema["properties"].keys() or not set(schema["required"]) <= args.keys():
                    raise ValueError("Unexpected or missing tool arguments")
                try:
                    value = client.call(name, args)
                    result = {
                        "content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}],
                        "isError": False,
                    }
                except (ValueError, RuntimeError) as exc:
                    result = {"content": [{"type": "text", "text": str(exc)}], "isError": True}
            else:
                outgoing.write(
                    json.dumps(
                        {"jsonrpc": "2.0", "id": identifier, "error": {"code": -32601, "message": "Method not found"}}
                    )
                    + "\n"
                )
                outgoing.flush()
                continue
            response = {"jsonrpc": "2.0", "id": identifier, "result": result}
        except (ValueError, TypeError, KeyError):
            response = {"jsonrpc": "2.0", "id": identifier, "error": {"code": -32602, "message": "Invalid request"}}
        outgoing.write(json.dumps(response, ensure_ascii=False) + "\n")
        outgoing.flush()
