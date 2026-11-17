# Copyright (c) 2026 Relax Authors. All Rights Reserved.

"""CPU regressions for private staging, snapshot replay and the actual HTTP
boundary."""

from __future__ import annotations

import copy
import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from relax.memory.client import MemoryClient
from relax.memory.mcp import serve_stdio
from relax.memory.server import dispatch, make_server
from relax.memory.store import MemoryStore, digest


@pytest.fixture
def record():
    return json.loads((Path(__file__).parents[3] / "examples/memory/knowledge.json").read_text())


def approve(store, namespace, candidate):
    return store.commit(
        namespace,
        candidate["candidate_id"],
        {"state": "verified", "verifier_id": "test", "evidence_ids": ["demo:maintainer-review"]},
    )


def bind(store, namespace, snapshot, session):
    return store.authenticate(store.bind(namespace, snapshot["snapshot_id"], session)["token"])


def test_memory_staging_idempotency_isolation_and_snapshot_restore(tmp_path, record):
    path = tmp_path / "memory.sqlite"
    with MemoryStore(path) as store:
        empty = store.create_snapshot("business-a/dev/project")
        a = bind(store, "business-a/dev/project", empty, "a")
        b = bind(store, "business-a/dev/project", empty, "b")
        staged = store.stage(a["namespace"], "a", "key", record)
        assert store.stage(a["namespace"], "a", "key", record) == staged
        altered = record | {"summary": "different"}
        with pytest.raises(ValueError, match="conflict"):
            store.stage(a["namespace"], "a", "key", altered)
        assert not store.read(b)["items"]
        first = approve(store, a["namespace"], staged)
        assert not store.read(b)["items"]
        populated = store.create_snapshot(a["namespace"])
        c = bind(store, a["namespace"], populated, "c")
        receipt = store.read(c, "regression")
        assert receipt["items"] == [{"id": first["id"], "revision": 1}]
        assert digest(receipt["text"]) == receipt["content_sha256"]
        assert store.read(c, max_bytes=128)["bytes"] <= 128
        assert not store.read(c, max_bytes=128)["items"]
        with pytest.raises(ValueError, match="receipt"):
            store.receipt(b, receipt["read_receipt"])
        foreign = store.create_snapshot("business-b/dev/project")
        d = bind(store, "business-b/dev/project", foreign, "c")
        assert not store.read(d, "regression")["items"]
        with pytest.raises(ValueError, match="Snapshot"):
            store.bind(d["namespace"], populated["snapshot_id"], "cross")
        store.expire(a["namespace"], first["id"], 1)
        assert not store.create_snapshot(a["namespace"])["records"]
    with MemoryStore(path) as restarted:
        assert restarted.snapshot(a["namespace"], populated["snapshot_id"]) == populated
        assert restarted.receipt(c, receipt["read_receipt"]) == receipt
        assert restarted.read(c)["items"] == receipt["items"]


def test_memory_verification_revision_and_dedup(tmp_path, record):
    with MemoryStore(tmp_path / "memory.sqlite") as store:
        first = store.stage("p", "a", "first", record)
        with pytest.raises(ValueError, match="verified"):
            store.commit("p", first["candidate_id"], {"state": "unverified"})
        with pytest.raises(ValueError, match="cover"):
            store.commit(
                "p", first["candidate_id"], {"state": "verified", "verifier_id": "x", "evidence_ids": ["unrelated"]}
            )
        committed = approve(store, "p", first)
        assert approve(store, "p", first) == committed
        second = store.stage("p", "b", "another", record)
        assert approve(store, "p", second) == committed
        third = store.stage("p", "c", "third", record | {"summary": "Updated workflow"})
        decision = {"state": "verified", "verifier_id": "x", "evidence_ids": ["demo:maintainer-review"]}
        with pytest.raises(ValueError, match="Revision"):
            store.commit("p", third["candidate_id"], decision, committed["id"], 0)
        updated = store.commit("p", third["candidate_id"], decision, committed["id"], 1)
        assert updated["revision"] == 2
        assert len(store.create_snapshot("p")["records"]) == 1


def test_memory_simultaneous_commit_is_idempotent(tmp_path, record):
    path = tmp_path / "memory.sqlite"
    with MemoryStore(path) as store:
        candidate = store.stage("p", "a", "k", record)

    def commit_once(_):
        with MemoryStore(path) as connection:
            return approve(connection, "p", candidate)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(commit_once, range(2)))
    assert results[0] == results[1]


@pytest.fixture
def gateway(tmp_path):
    path = tmp_path / "memory.sqlite"
    with MemoryStore(path) as store:
        admin_token = store.bootstrap()
    server = make_server(path, port=0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    endpoint = f"http://127.0.0.1:{server.server_port}"
    yield MemoryClient(endpoint, admin_token), endpoint, path
    server.shutdown()
    server.server_close()
    worker.join(timeout=5)


def test_memory_http_and_mcp_do_not_expose_administration(gateway, record):
    admin, endpoint, path = gateway
    snapshot = admin.call("snapshot_create", namespace="p")
    binding = admin.call("session_bind", namespace="p", snapshot_id=snapshot["snapshot_id"], session_id="a")
    client = MemoryClient(endpoint, binding["token"])
    with pytest.raises(RuntimeError, match="403"):
        client.call("snapshot_create", namespace="foreign")
    with pytest.raises(RuntimeError, match="400"):
        client.call("memory_search", query="anything", namespace="foreign")
    staged = client.propose(record, "key")
    admin.call(
        "candidate_commit",
        namespace="p",
        candidate_id=staged["candidate_id"],
        verification={"state": "verified", "verifier_id": "test", "evidence_ids": ["demo:maintainer-review"]},
    )
    populated = admin.call("snapshot_create", namespace="p")
    binding = admin.call("session_bind", namespace="p", snapshot_id=populated["snapshot_id"], session_id="b")
    client = MemoryClient(endpoint, binding["token"])
    messages = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        },
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "memory_search", "arguments": {"query": "regression"}},
        },
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "candidate_commit", "arguments": {}}},
    ]
    output = io.StringIO()
    serve_stdio(client, io.StringIO("\n".join(json.dumps(item) for item in messages)), output)
    replies = [json.loads(line) for line in output.getvalue().splitlines()]
    assert len(replies) == 4
    assert {tool["name"] for tool in replies[1]["result"]["tools"]} == {
        "memory_search",
        "memory_get",
        "memory_propose",
        "memory_feedback",
    }
    assert replies[2]["result"]["isError"] is False
    assert replies[3]["error"]["code"] == -32602
    text = replies[2]["result"]["content"][0]["text"]
    with MemoryStore(path) as store:
        principal = store.authenticate(binding["token"])
        stored = store.db.execute("SELECT body FROM receipts WHERE session='b'").fetchone()
        receipt = json.loads(stored["body"])
        assert store.receipt(principal, receipt["read_receipt"])["text"] == text


@pytest.mark.parametrize(
    "mutation",
    [
        {"schema_version": "99.0"},
        {"verified": True},
        {"evidence": []},
        {"evidence": [{"evidence_id": ""}]},
        {"applicability": {"paths": "src/module.py"}},
        {"applicability": {"paths": ["../../secrets"]}},
    ],
)
def test_memory_rejects_untrusted_record_fields(tmp_path, record, mutation):
    with MemoryStore(tmp_path / "memory.sqlite") as store:
        with pytest.raises(ValueError):
            store.stage("p", "s", "k", copy.deepcopy(record) | mutation)


def test_memory_eval_namespace_and_candidate_scope(tmp_path, record):
    with MemoryStore(tmp_path / "memory.sqlite") as store:
        staged = store.stage("business/train", "s", "k", record)
        with pytest.raises(ValueError, match="Candidate"):
            approve(store, "business/eval", staged)
        evaluation = store.create_snapshot("business/eval")
        principal = bind(store, "business/eval", evaluation, "s")
        with pytest.raises(PermissionError):
            dispatch(store, principal, "candidate_list", {"namespace": "business/train"})


def test_memory_chinese_retrieval_matches_content_not_namespace(tmp_path, record):
    with MemoryStore(tmp_path / "memory.sqlite") as store:
        record.update(title="验证代码修复", summary="回归测试要记录修改后的代码版本。")
        committed = approve(store, "privateproject", store.stage("privateproject", "s", "key", record))
        snapshot = store.create_snapshot("privateproject")
        principal = bind(store, "privateproject", snapshot, "reader")
        assert store.read(principal, "如何验证代码修复？")["items"] == [{"id": committed["id"], "revision": 1}]
        assert not store.read(principal, "privateproject")["items"]
