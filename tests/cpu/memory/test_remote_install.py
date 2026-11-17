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


def test_setup_hidden_inputs_verify_before_install(tmp_path, monkeypatch, capsys):
    import runpy

    monkeypatch.syspath_prepend(str(SOURCE.parent))
    namespace = runpy.run_path(str(SOURCE))
    prefix = tmp_path / "wizard"
    answers = iter(["rm_onboarding-secret", "platform-onboarding-secret"])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(namespace["getpass"], "getpass", lambda prompt: next(answers))
    calls = []

    def start(self):
        assert not prefix.exists()
        calls.append((self.agent_token, self.app_token))
        return {"snapshot_id": "verified"}

    monkeypatch.setattr(namespace["Client"], "start", start)
    monkeypatch.setattr(
        sys, "argv", [str(SOURCE), "--prefix", str(prefix), "setup", "--endpoint", "https://example.invalid/memory"]
    )
    namespace["main"]()
    assert calls == [("rm_onboarding-secret", "platform-onboarding-secret")]
    assert json.loads((prefix / "agent.json").read_text())["token"] == "rm_onboarding-secret"
    assert (prefix / "cowork-app-token").read_text() == "platform-onboarding-secret"
    captured = capsys.readouterr()
    assert "onboarding-secret" not in captured.out + captured.err
    assert '"connection_verified": true' in captured.out


def test_setup_auth_failure_keeps_existing_credentials(tmp_path, monkeypatch, capsys):
    import runpy

    import pytest

    prefix, result = install(tmp_path)
    assert result.returncode == 0
    before = (prefix / "agent.json").read_bytes()
    replacement = tmp_path / "replacement.json"
    replacement.write_text(json.dumps({"token": "rm_replacement-secret"}))
    monkeypatch.syspath_prepend(str(SOURCE.parent))
    namespace = runpy.run_path(str(SOURCE))

    def fail(self):
        raise RuntimeError("Memory HTTP 401")

    monkeypatch.setattr(namespace["Client"], "start", fail)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SOURCE),
            "--prefix",
            str(prefix),
            "setup",
            "--replace",
            "--endpoint",
            "https://example.invalid/memory",
            "--credential-file",
            str(replacement),
            "--app-token-file",
            str(tmp_path / "input-app-token"),
        ],
    )
    with pytest.raises(SystemExit):
        namespace["main"]()
    assert (prefix / "agent.json").read_bytes() == before
    assert "replacement-secret" not in capsys.readouterr().err


def test_setup_without_terminal_refuses_missing_secrets(tmp_path):
    prefix = tmp_path / "unattended"
    result = subprocess.run(
        [
            sys.executable,
            str(SOURCE),
            "--prefix",
            str(prefix),
            "setup",
            "--endpoint",
            "https://example.invalid/memory",
        ],
        input="do-not-read-secret\n",
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert result.returncode != 0
    assert "requires a terminal" in result.stderr
    assert "do-not-read-secret" not in result.stdout + result.stderr
    assert not prefix.exists()


def test_hidden_prompt_never_falls_back_to_echo(monkeypatch):
    import runpy
    import warnings

    import pytest

    monkeypatch.syspath_prepend(str(SOURCE.parent))
    namespace = runpy.run_path(str(SOURCE))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)

    def unsafe_prompt(prompt):
        warnings.warn("No echo control", namespace["getpass"].GetPassWarning)
        raise AssertionError("Must stop before fallback input")

    monkeypatch.setattr(namespace["getpass"], "getpass", unsafe_prompt)
    with pytest.raises(RuntimeError, match="Cannot disable terminal echo"):
        namespace["read_hidden"]("secret: ")
