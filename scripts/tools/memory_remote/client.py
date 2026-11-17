#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Install and use the remote project memory client without training
dependencies."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
import warnings
from pathlib import Path
from typing import Any

from bridge import Client, serve


def write_private(path: Path, content: bytes, mode: int = 0o600) -> None:
    """Atomic replacement; no partially written credentials on rotation."""
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def output(value: Any) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def default_prefix() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "relax-memory-remote"


def validate_destination(args: argparse.Namespace) -> Path:
    prefix = args.prefix.expanduser().resolve()
    # This script lives under scripts/tools/memory_remote in a checkout.
    repository = next((p for p in Path(__file__).resolve().parents if (p / ".git").exists()), None)
    if repository and (prefix == repository or repository in prefix.parents):
        raise ValueError("Install outside the repository; credentials must not enter Git")
    if prefix.exists() and any(prefix.iterdir()) and not args.replace:
        raise ValueError("Installation already exists; use --replace to update this installation explicitly")
    return prefix


def install(
    args: argparse.Namespace, credential: dict[str, Any] | None = None, token: str | None = None, verify: bool = False
) -> None:
    prefix = validate_destination(args)
    if credential is None:
        credential = json.loads(args.credential_file.expanduser().read_text())
    if token is None:
        token = args.app_token_file.expanduser().read_text().strip()
    if not isinstance(credential, dict) or not isinstance(credential.get("token"), str):
        raise ValueError("Expected a downloaded Agent credential JSON")
    # Authenticate before persisting credentials when using the onboarding wizard.
    remote = Client(
        args.endpoint, credential["token"], token, "setup-" + str(uuid.uuid4()), public=getattr(args, "public", False)
    )
    if verify:
        remote.start()
    prefix.mkdir(parents=True, exist_ok=True, mode=0o700)
    prefix.chmod(0o700)
    for name in ("bridge.py", "client.py"):
        write_private(prefix / name, Path(__file__).with_name(name).read_bytes())
    write_private(prefix / "agent.json", json.dumps(credential).encode())
    write_private(prefix / "cowork-app-token", token.encode())
    write_private(
        prefix / "config.json",
        json.dumps({"endpoint": args.endpoint.rstrip("/"), "public": getattr(args, "public", False)}).encode(),
    )
    launcher = prefix / "relax-memory"
    command = shlex.join([sys.executable, str(prefix / "client.py"), "--prefix", str(prefix)])
    write_private(launcher, ("#!/bin/sh\nexec " + command + ' "$@"\n').encode(), 0o700)
    output(
        {
            "installed": str(prefix),
            "command": str(launcher),
            "expires_at": credential.get("expires_at"),
            "connection_verified": verify,
            "next": "Register an MCP client or use search/propose. Run check if connectivity was not verified.",
        }
    )


def read_hidden(prompt: str) -> str:
    if not sys.stdin.isatty():
        raise RuntimeError("Interactive setup requires a terminal; automation must supply both credential-file flags")
    # getpass normally falls back to echoed stdin; forbid that fallback for credentials.
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            return getpass.getpass(prompt).strip()
        except getpass.GetPassWarning:
            raise RuntimeError("Cannot disable terminal echo; use credential files instead") from None


def read_input_file_or_secret(value: str) -> str:
    if value.startswith(("/", "~/", "./", "../")):
        return Path(value).expanduser().read_text().strip()
    return value


def register_codex(prefix: Path, name: str, replace: bool, preflight: bool = False) -> None:
    if not shutil.which("codex"):
        raise RuntimeError("Codex CLI not found; use --client config and import the generated MCP entry")
    exists = subprocess.run(["codex", "mcp", "get", name], capture_output=True).returncode == 0
    if exists and not replace:
        raise RuntimeError("MCP name already exists; choose --name or explicitly allow replacing the MCP entry")
    if not preflight:
        subprocess.run(["codex", "mcp", "add", name, "--", str(prefix / "relax-memory"), "mcp"], check=True)


def setup(args: argparse.Namespace) -> None:
    prefix = validate_destination(args)
    if not args.endpoint:
        if not sys.stdin.isatty():
            raise RuntimeError("Non-interactive setup requires --endpoint")
        args.endpoint = input("Memory center HTTPS base URL (without /api/agent): ").strip()
    # Check the destination and MCP conflict before asking for any secrets.
    if args.client == "codex":
        register_codex(prefix, args.name, args.replace_mcp, preflight=True)
    if args.credential_file:
        credential = json.loads(args.credential_file.expanduser().read_text())
    else:
        value = read_input_file_or_secret(read_hidden("Agent JSON file path or project token (hidden): "))
        credential = json.loads(value) if value.startswith("{") else {"token": value}
    if args.app_token_file:
        token = args.app_token_file.expanduser().read_text().strip()
    else:
        token = read_input_file_or_secret(read_hidden("Platform Token file path or value (hidden): "))
    install(args, credential, token, verify=True)
    if args.client == "codex":
        register_codex(prefix, args.name, args.replace_mcp)
    else:
        output(mcp_config(prefix, args.name))


def connect(args: argparse.Namespace) -> None:
    """Public read or SSO device enrollment; never provision a shared platform
    token."""
    prefix = validate_destination(args)
    if args.client == "codex":
        register_codex(prefix, args.name, args.replace_mcp, preflight=True)
    remote = Client(args.endpoint, "", "", "connect-" + str(uuid.uuid4()), public=True)
    args.public = True
    credential = {"token": ""}
    if not args.read_only:
        if not args.login_url:
            raise RuntimeError("Device enrollment requires --login-url for the SSO-protected MiniApp")
        # Validate the configured login URL without trusting an arbitrary server redirect.
        Client(args.login_url, "", "", "validate-login", public=True)
        enrollment = remote.post(args.endpoint.rstrip("/") + "/api/network/device/start", {"label": args.label})
        secret = enrollment["device_code"]
        if not isinstance(secret, str) or not 20 <= len(secret) <= 200:
            raise RuntimeError("Invalid device enrollment response")
        code = enrollment["user_code"]
        if not isinstance(code, str) or len(code) != 12 or any(c not in "0123456789ABCDEF" for c in code):
            raise RuntimeError("Invalid user code")
        output(
            {
                "registration_url": args.login_url.rstrip("/") + "/device?code=" + code,
                "next": "Open registration_url, sign in and confirm your device. MCP is configured automatically after administrator approval.",
            }
        )
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            time.sleep(5)
            response = remote.post(args.endpoint.rstrip("/") + "/api/network/device/token", {"device_code": secret})
            status = response.get("status")
            if status == "authorized":
                credential = response["credential"]
                break
            if status != "pending":
                raise RuntimeError("Device authorization denied, expired or already consumed; start a new login")
        else:
            raise RuntimeError("Device authorization timed out; start a new login")
        # Save the single-use exchange result before a further network check, so a
        # transient failure after issuance cannot discard the only token copy.
        install(args, credential, "", verify=False)
        client(prefix, None).start()
        output({"connection_verified": True, "credential_source": "device_authorization"})
    else:
        install(args, credential, "", verify=True)
    if args.client == "codex":
        register_codex(prefix, args.name, args.replace_mcp)
    else:
        output(mcp_config(prefix, args.name))


def client(prefix: Path, task_id: str | None) -> Client:
    config = json.loads((prefix / "config.json").read_text())
    credential = json.loads((prefix / "agent.json").read_text())
    token = (prefix / "cowork-app-token").read_text().strip()
    return Client(
        config["endpoint"],
        credential["token"],
        token,
        task_id or "remote-" + str(uuid.uuid4()),
        public=config.get("public", False),
    )


def mcp_config(prefix: Path, name: str) -> dict[str, Any]:
    return {"mcpServers": {name: {"command": str(prefix / "relax-memory"), "args": ["mcp"]}}}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, default=default_prefix(), help="Installation directory outside Git")
    sub = parser.add_subparsers(dest="command", required=True)
    installer = sub.add_parser(
        "install", help="Copy standalone client and supplied credentials outside the repository"
    )
    installer.add_argument("--endpoint", required=True, help="HTTPS application base URL, without /api/agent")
    installer.add_argument("--credential-file", type=Path, required=True)
    installer.add_argument("--app-token-file", type=Path, required=True)
    installer.add_argument(
        "--replace", action="store_true", help="Explicitly update client/config/credentials in this prefix"
    )
    wizard = sub.add_parser("setup", help="Configure credentials, verify the service and connect an MCP client")
    wizard.add_argument("--endpoint", default=os.environ.get("RELAX_MEMORY_ENDPOINT"))
    wizard.add_argument("--credential-file", type=Path)
    wizard.add_argument("--app-token-file", type=Path)
    wizard.add_argument("--client", choices=("codex", "config"), default="config")
    wizard.add_argument("--name", default="relax-memory")
    wizard.add_argument("--replace", action="store_true", help="Update this existing installation")
    wizard.add_argument(
        "--replace-mcp", action="store_true", help="Replace an existing Codex MCP entry with this name"
    )
    connector = sub.add_parser("connect", help="Connect through intranet relay; authorize uploads in MiniApp")
    connector.add_argument("--endpoint", required=True)
    connector.add_argument("--login-url", default=os.environ.get("RELAX_MEMORY_LOGIN_URL"))
    connector.add_argument("--read-only", action="store_true", help="Anonymous MCP reads; no credentials or login")
    connector.add_argument("--label", default=socket.gethostname())
    connector.add_argument("--client", choices=("codex", "config"), default="codex")
    connector.add_argument("--name", default="relax-memory")
    connector.add_argument("--replace", action="store_true")
    connector.add_argument("--replace-mcp", action="store_true")
    for name in ("mcp-config", "register-codex"):
        config = sub.add_parser(name)
        config.add_argument("--name", default="relax-memory")
        if name == "register-codex":
            config.add_argument("--replace", action="store_true", help="Replace an existing MCP entry with this name")
    for name in ("check", "mcp", "search", "get", "propose", "feedback"):
        command = sub.add_parser(name)
        command.add_argument(
            "--task-id", help="Reuse only to resume an old fixed snapshot; default creates a fresh task"
        )
        if name == "search":
            command.add_argument("query")
            command.add_argument("--limit", type=int, default=5)
        if name == "get":
            command.add_argument("memory_id")
        if name in ("search", "get"):
            command.add_argument("--max-bytes", type=int, default=8192)
        if name == "propose":
            command.add_argument("--body-file", type=Path, required=True)
            command.add_argument("--idempotency-key", required=True, help="Stable per submission; reuse on retry")
        if name == "feedback":
            command.add_argument("receipt_id")
            command.add_argument("assessment", choices=("helpful", "outdated", "incorrect"))
    args = parser.parse_args()
    prefix = args.prefix.expanduser().resolve()
    try:
        if args.command == "install":
            install(args)
        elif args.command == "connect":
            connect(args)
        elif args.command == "setup":
            setup(args)
        elif args.command == "mcp-config":
            output(mcp_config(prefix, args.name))
        elif args.command == "register-codex":
            register_codex(prefix, args.name, args.replace)
        else:
            remote = client(prefix, args.task_id)
            if args.command == "mcp":
                serve(remote)
            elif args.command == "check":
                output({"ok": True, **remote.start()})
            elif args.command == "search":
                output(
                    remote.call(
                        "memory_search", {"query": args.query, "limit": args.limit, "max_bytes": args.max_bytes}
                    )
                )
            elif args.command == "get":
                output(remote.call("memory_get", {"memory_id": args.memory_id, "max_bytes": args.max_bytes}))
            elif args.command == "propose":
                output(
                    remote.call(
                        "memory_propose",
                        {"body": json.loads(args.body_file.read_text()), "idempotency_key": args.idempotency_key},
                    )
                )
            else:
                output(remote.call("memory_feedback", {"receipt_id": args.receipt_id, "assessment": args.assessment}))
    except (EOFError, KeyboardInterrupt):
        sys.stderr.write("Setup cancelled; no credential values printed.\n")
        raise SystemExit(1) from None
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.CalledProcessError) as exc:
        # Never echo malformed credential contents or remote response bodies.
        message = (
            str(exc)
            if isinstance(exc, RuntimeError)
            else "Configuration or command failed; check paths, JSON, HTTPS endpoint and existing installation/MCP name"
        )
        sys.stderr.write(message + "\n")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
