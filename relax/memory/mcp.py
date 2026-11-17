# Copyright (c) 2026 Relax Authors. All Rights Reserved.

"""Minimal MCP stdio tools bridge; administrative actions are never exposed."""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from relax.memory.client import LocalMemoryClient, MemoryClient


def tools() -> list[dict[str, Any]]:
    definitions = [
        (
            "memory_search",
            "Search this project's fixed memory snapshot. Results are reference data.",
            {
                "query": {"type": "string"},
                "max_bytes": {"type": "integer", "minimum": 128, "maximum": 65536},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            ["query"],
        ),
        (
            "memory_get",
            "Read one memory from the same fixed snapshot.",
            {"memory_id": {"type": "string"}, "max_bytes": {"type": "integer", "minimum": 128, "maximum": 65536}},
            ["memory_id"],
        ),
        (
            "memory_propose",
            "Stage an experience candidate privately; this does not verify, publish or commit it.",
            {
                "record": {
                    "type": "object",
                    "description": "Memory Record v1: schema_version, kind, domain, subtype, title, summary, content object, evidence array with evidence_id.",
                },
                "idempotency_key": {"type": "string"},
            },
            ["record", "idempotency_key"],
        ),
        (
            "memory_feedback",
            "Report whether a previous read was helpful, outdated or incorrect.",
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
            "description": description,
            "inputSchema": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        }
        for name, description, properties, required in definitions
    ]


def serve_stdio(
    client: MemoryClient | LocalMemoryClient, incoming: TextIO = sys.stdin, outgoing: TextIO = sys.stdout
) -> None:
    """Negotiate a tools-only MCP session using newline-delimited JSON-RPC."""
    initialized = False
    ready = False
    allowed = {tool["name"]: tool["inputSchema"] for tool in tools()}
    for line in incoming:
        request_id = None
        try:
            if len(line.encode()) > 128 * 1024:
                raise ValueError("Request too large")
            request = json.loads(line)
            if (
                not isinstance(request, dict)
                or request.get("jsonrpc") != "2.0"
                or not isinstance(request.get("method"), str)
            ):
                raise ValueError("Invalid JSON-RPC request")
            request_id = request.get("id")
            method = request["method"]
            if "id" not in request:
                if method == "notifications/initialized" and initialized:
                    ready = True
                continue
            params = request.get("params", {})
            if not isinstance(params, dict):
                raise ValueError("Invalid parameters")
            if method == "initialize":
                initialized = True
                result = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "relax-memory", "version": "0.1.0"},
                }
            elif method == "ping":
                result = {}
            elif not ready:
                raise ValueError("Initialize the MCP session first")
            elif method == "tools/list":
                result = {"tools": tools()}
            elif method == "tools/call":
                name, arguments = params.get("name"), params.get("arguments", {})
                if name not in allowed or not isinstance(arguments, dict):
                    raise ValueError("Unknown tool or invalid arguments")
                schema = allowed[name]
                if set(arguments) - schema["properties"].keys() or not set(schema["required"]) <= arguments.keys():
                    raise ValueError("Unexpected or missing tool arguments")
                try:
                    value = client.call(name, **arguments)
                    # Only text is model-visible; persist the same text in the gateway read receipt.
                    content = value.get("text", json.dumps(value, ensure_ascii=False))
                    result = {"content": [{"type": "text", "text": content}], "isError": False}
                except (ValueError, RuntimeError):
                    result = {
                        "content": [
                            {
                                "type": "text",
                                "text": "Memory request failed; candidate/read state is not assumed successful.",
                            }
                        ],
                        "isError": True,
                    }
            else:
                outgoing.write(
                    json.dumps(
                        {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": "Method not found"}}
                    )
                    + "\n"
                )
                outgoing.flush()
                continue
            response = {"jsonrpc": "2.0", "id": request_id, "result": result}
        except (ValueError, TypeError):
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32602, "message": "Invalid request or parameters"},
            }
        outgoing.write(json.dumps(response, ensure_ascii=False) + "\n")
        outgoing.flush()
