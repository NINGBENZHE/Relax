# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Standalone installation contracts, without GPU or network access."""

import json
import os
import subprocess
import sys
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[3] / "scripts/tools/memory_remote/client.py"


def install(tmp_path, prefix=None, replace=False):
    prefix = prefix or tmp_path / "install with spaces"
    agent = tmp_path / "input-agent.json"
    app = tmp_path / "input-app-token"
    agent.write_text(json.dumps({"token": "rm_test-only-secret"}))
    app.write_text("platform-test-only-secret")
    args = [
        sys.executable,
        str(SOURCE),
        "--prefix",
        str(prefix),
        "install",
        "--endpoint",
        "https://example.invalid/s/memory",
        "--credential-file",
        str(agent),
        "--app-token-file",
        str(app),
    ]
    if replace:
        args.append("--replace")
    return prefix, subprocess.run(args, capture_output=True, text=True, timeout=10)


def test_standalone_mcp_install_permissions_and_no_secret_config(tmp_path):
    prefix, result = install(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "rm_test-only-secret" not in result.stdout
    assert os.stat(prefix).st_mode & 0o777 == 0o700
    for name in ["agent.json", "cowork-app-token"]:
        assert os.stat(prefix / name).st_mode & 0o777 == 0o600
    # Installed command works from an unrelated cwd, with spaces in paths.
    config = subprocess.run([str(prefix / "relax-memory"), "mcp-config"], cwd="/", capture_output=True, text=True)
    entry = json.loads(config.stdout)["mcpServers"]["relax-memory"]
    assert "secret" not in config.stdout
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    run = subprocess.run(
        [entry["command"], *entry["args"]],
        input="\n".join(map(json.dumps, messages)) + "\n",
        cwd="/",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert run.returncode == 0
    replies = [json.loads(x) for x in run.stdout.splitlines()]
    assert {t["name"] for t in replies[-1]["result"]["tools"]} == {
        "memory_search",
        "memory_get",
        "memory_propose",
        "memory_feedback",
    }


def test_existing_install_requires_explicit_update(tmp_path):
    prefix, first = install(tmp_path)
    assert first.returncode == 0
    (prefix / "config.json").write_text('{"endpoint":"https://existing.invalid"}')
    _, second = install(tmp_path)
    assert second.returncode != 0
    assert json.loads((prefix / "config.json").read_text())["endpoint"] == "https://existing.invalid"
    _, update = install(tmp_path, replace=True)
    assert update.returncode == 0
    assert json.loads((prefix / "config.json").read_text())["endpoint"] == "https://example.invalid/s/memory"


def test_repo_install_refused_before_writing_secrets(tmp_path):
    prefix = SOURCE.parents[3] / ".remote-install-must-not-exist"
    assert not prefix.exists()
    _, result = install(tmp_path, prefix)
    assert result.returncode != 0
    assert not prefix.exists()


def test_invalid_credential_does_not_echo_secret(tmp_path):
    prefix, result = install(tmp_path)
    assert result.returncode == 0
    (prefix / "agent.json").write_text("PRIVATE_MALFORMED_CREDENTIAL")
    result = subprocess.run([str(prefix / "relax-memory"), "check"], capture_output=True, text=True)
    assert result.returncode != 0
    assert "PRIVATE_MALFORMED_CREDENTIAL" not in result.stderr + result.stdout


def test_cli_propose_keeps_idempotency_key_and_returns_pending(tmp_path, monkeypatch, capsys):
    import runpy

    prefix, result = install(tmp_path)
    assert result.returncode == 0
    body = {"title": "Evidence-backed candidate", "content": "fixture"}
    body_file = tmp_path / "body.json"
    body_file.write_text(json.dumps(body))
    monkeypatch.syspath_prepend(str(SOURCE.parent))
    namespace = runpy.run_path(str(SOURCE))
    requests = []

    def request(self, action, arguments):
        # Substitute only the remote boundary; execute the actual CLI and client binding.
        requests.append((action, arguments))
        if action == "task_start":
            return {"snapshot_id": "fixed-test-snapshot"}
        return {"id": "candidate-id", "state": "pending", "committed": False}

    monkeypatch.setattr(namespace["Client"], "request", request)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SOURCE),
            "--prefix",
            str(prefix),
            "propose",
            "--body-file",
            str(body_file),
            "--idempotency-key",
            "stable-retry-key",
        ],
    )
    namespace["main"]()
    assert requests[-1] == ("memory_propose", {"body": body, "idempotency_key": "stable-retry-key"})
    assert json.loads(capsys.readouterr().out)["committed"] is False
