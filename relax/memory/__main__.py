# Copyright (c) 2026 Relax Authors. All Rights Reserved.

"""Local deployment, trusted review operations and MCP entry point."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from relax.memory.client import LocalMemoryClient, MemoryClient
from relax.memory.mcp import serve_stdio
from relax.memory.memos import MemOSClient
from relax.memory.server import make_server
from relax.memory.store import MemoryStore, digest, encode


def output(value: Any, destination: str | None) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if destination:
        path = Path(destination)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(text)
    else:
        sys.stdout.write(text)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init")
    init.add_argument("--state-dir", required=True)
    server = sub.add_parser("serve")
    server.add_argument("--state-dir", required=True)
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8765)
    for name in ("request", "mcp", "project", "memos-import", "memos-export"):
        command = sub.add_parser(name)
        command.add_argument("--endpoint", default=os.environ.get("RELAX_MEMORY_ENDPOINT", "http://127.0.0.1:8765"))
        command.add_argument("--token-file", required=True)
        if name == "mcp":
            command.add_argument("--state-dir", help="Use local SQLite directly; no HTTP service needed")
        if name != "mcp":
            command.add_argument("--output")
        if name == "request":
            command.add_argument("action")
            command.add_argument("--args-file", required=True)
        if name == "project":
            command.add_argument("--namespace", required=True)
            command.add_argument("--session", required=True)
            command.add_argument("--output-dir", required=True)
        if name.startswith("memos-"):
            command.add_argument("--memos-endpoint", required=True)
            command.add_argument("--memos-user", required=True)
            command.add_argument("--cube", required=True)
            command.add_argument("--authorization-env", default="MEMOS_AUTHORIZATION")
            command.add_argument("--namespace", required=True)
            if name == "memos-import":
                command.add_argument("--query", required=True)
                command.add_argument("--session", required=True)
            else:
                command.add_argument("--snapshot", required=True)
    args = parser.parse_args()
    if args.command == "init":
        state = Path(args.state_dir).resolve()
        state.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(state, 0o700)
        with MemoryStore(state / "memory.sqlite") as store:
            if not (state / "admin.json").exists():
                output({"token": store.bootstrap()}, str(state / "admin.json"))
        output({"state_dir": str(state), "admin_credential": str(state / "admin.json")}, None)
        return
    if args.command == "serve":
        database = Path(args.state_dir) / "memory.sqlite"
        if not database.is_file():
            parser.error("Initialize the state directory first")
        with make_server(database, args.host, args.port) as gateway:
            try:
                gateway.serve_forever()
            except KeyboardInterrupt:
                pass
        return
    credential = json.loads(Path(args.token_file).read_text())
    client = (
        LocalMemoryClient(Path(args.state_dir) / "memory.sqlite", credential["token"])
        if args.command == "mcp" and args.state_dir
        else MemoryClient(args.endpoint, credential["token"])
    )
    if args.command == "mcp":
        serve_stdio(client)
    elif args.command == "project":
        directory = Path(args.output_dir).resolve()
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        token_file = directory / "agent.json"
        if token_file.exists():
            parser.error("Output directory already contains agent.json; choose a new task directory")
        snapshot = client.call("snapshot_create", namespace=args.namespace)
        binding = client.call(
            "session_bind", namespace=args.namespace, snapshot_id=snapshot["snapshot_id"], session_id=args.session
        )
        output(binding, str(token_file))
        configuration = {
            "mcpServers": {
                "relax-memory": {
                    "command": sys.executable,
                    "args": [
                        "-m",
                        "relax.memory",
                        "mcp",
                        "--endpoint",
                        args.endpoint,
                        "--token-file",
                        str(token_file),
                    ],
                    "env": {"PYTHONPATH": str(Path(__file__).resolve().parents[2])},
                }
            }
        }
        output(configuration, str(directory / "mcp.json"))
        output(
            {
                "snapshot_id": snapshot["snapshot_id"],
                "agent_credential": str(token_file),
                "mcp_config": str(directory / "mcp.json"),
            },
            args.output,
        )
    elif args.command == "request":
        arguments = json.loads(Path(args.args_file).read_text())
        if args.action == "session_bind" and not args.output:
            parser.error("session_bind requires --output to keep credentials off terminal output")
        output(client.call(args.action, **arguments), args.output)
    else:
        memos = MemOSClient(
            args.memos_endpoint, args.memos_user, args.cube, os.environ.get(args.authorization_env, "")
        )
        if args.command == "memos-import":
            candidates = memos.search(args.query)
            results = [
                client.call(
                    "candidate_stage",
                    namespace=args.namespace,
                    session=args.session,
                    idempotency_key="memos:" + digest(encode(record)),
                    record=record,
                )
                for record in candidates
            ]
            output({"candidates": results, "status": "staged_only"}, args.output)
        else:
            snapshot = client.call("snapshot_get", namespace=args.namespace, snapshot_id=args.snapshot)
            # Explicit export is a trusted operation, not an agent tool. No retries.
            results = []
            for record in snapshot["records"]:
                results.append(
                    memos.add(
                        encode(record),
                        {
                            "relax_memory_id": record["id"],
                            "relax_revision": record["revision"],
                            "relax_content_hash": record["integrity"]["content_sha256"],
                        },
                    )
                )
            output({"exported": len(results), "upstream_responses": results}, args.output)


if __name__ == "__main__":
    main()
