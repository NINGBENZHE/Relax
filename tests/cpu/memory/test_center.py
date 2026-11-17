# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Real lifecycle and HTTP regressions for the single-operator center demo."""

import json
import threading
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from relax.memory.center import SPACE, Center, make_center_server
from relax.memory.store import MemoryStore


def body():
    return {
        "title": "Test memory",
        "summary": "Check evidence",
        "content": "Measured only in a test",
        "kind": "lesson",
        "topic": "performance",
        "tags": ["trace"],
        "conditions": "test only",
        "source": "test evidence",
        "evidence_level": "tested",
        "owner": "maintainer",
        "review_after": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
    }


def test_center_submit_review_revision_reject_and_restart(tmp_path):
    center = Center(tmp_path)
    entry = center.act("submit", {"body": body(), "actor": "author"})["id"]
    with MemoryStore(center.database) as store:
        assert not store.create_snapshot(SPACE)["records"]
    center.act("approve", {"id": entry, "version": 1, "note": "test evidence reviewed", "actor": "reviewer"})
    item = center.list()["entries"][0]
    assert item["needs_review"] and item["state"] == "active"
    with MemoryStore(center.database) as store:
        old = store.create_snapshot(SPACE)
        assert len(old["records"]) == 1
    with pytest.raises(ValueError, match="刷新"):
        center.act("expire", {"id": entry, "version": 1, "note": "stale write"})
    updated = body() | {"content": "Revised hypothesis", "evidence_level": "hypothesis"}
    center.act("revise", {"id": entry, "version": 2, "body": updated})
    with MemoryStore(center.database) as store:
        assert not store.create_snapshot(SPACE)["records"]
        assert store.snapshot(SPACE, old["snapshot_id"]) == old
    center.act("reject", {"id": entry, "version": 3, "note": "Missing benchmark"})
    reopened = Center(tmp_path)
    state = reopened.list()
    assert state["entries"][0]["state"] == "rejected"
    assert len(state["events"]) == 4
    assert state["events"][-1]["body"]["content"] == body()["content"]
    reopened.act("revise", {"id": entry, "version": 4, "body": body()})
    reopened.act("approve", {"id": entry, "version": 5, "note": "Evidence rechecked"})
    assert reopened.list()["entries"][0]["state"] == "active"


def test_center_ttl_excludes_new_snapshots_preserves_old(tmp_path, monkeypatch):
    center = Center(tmp_path)
    item = center.act("submit", {"body": body()})
    center.act("approve", {"id": item["id"], "version": 1, "note": "Evidence"})
    with MemoryStore(center.database) as store:
        before = store.create_snapshot(SPACE)
        future = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
        monkeypatch.setattr("relax.memory.store.now", lambda: future)
        # No center sweep is needed for TTL exclusion at the core snapshot boundary.
        assert not store.create_snapshot(SPACE)["records"]
        assert store.snapshot(SPACE, before["snapshot_id"]) == before
    monkeypatch.setattr("relax.memory.center.now", lambda: future)
    state = center.list()
    assert state["entries"][0]["state"] == "expired"
    assert state["events"][0]["action"] == "auto_expire"
    assert len(center.list()["events"]) == len(state["events"])
    with pytest.raises(ValueError):
        center.act("submit", {"body": body() | {"expires_at": "2027-01-01T00:00:00"}})


def test_center_http_auth_origin_and_real_mutation(tmp_path):
    center = Center(tmp_path)
    server = make_center_server(center, "test-secret", "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(endpoint) as response:
            assert "记忆词条中心" in response.read().decode()
        with pytest.raises(HTTPError) as missing:
            urlopen(endpoint + "/api/state")
        assert missing.value.code == 403
        request = Request(
            endpoint + "/api/action",
            data=json.dumps({"action": "submit", "args": {"body": body()}}).encode(),
            headers={
                "Authorization": "Bearer test-secret",
                "Content-Type": "application/json",
                "Origin": "https://foreign.invalid",
            },
        )
        with pytest.raises(HTTPError) as foreign:
            urlopen(request)
        assert foreign.value.code == 403
        request.remove_header("Origin")
        with urlopen(request) as response:
            assert json.loads(response.read())["id"]
        with urlopen(Request(endpoint + "/api/state", headers={"Authorization": "Bearer test-secret"})) as response:
            assert json.loads(response.read())["entries"][0]["state"] == "pending"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_center_seed_is_repeatable_and_preview_filters(tmp_path):
    center = Center(tmp_path)
    center.seed()
    center.seed()
    assert len(center.list()["entries"]) == 6
    assert len(center.act("preview", {})["items"]) == 3


def test_center_workflow_and_core_rollback_together(tmp_path, monkeypatch):
    center = Center(tmp_path)
    entry = center.act("submit", {"body": body()})["id"]
    original_event = center.event

    def interrupt(*args, **kwargs):
        raise OSError("Simulated interruption after core mutation")

    monkeypatch.setattr(center, "event", interrupt)
    with pytest.raises(OSError):
        center.act("approve", {"id": entry, "version": 1, "note": "Checked"})
    assert center.list()["entries"][0]["state"] == "pending"
    with MemoryStore(center.database) as store:
        assert not store.create_snapshot(SPACE)["records"]
    monkeypatch.setattr(center, "event", original_event)
    center.act("approve", {"id": entry, "version": 1, "note": "Checked"})
    monkeypatch.setattr(center, "event", interrupt)
    with pytest.raises(OSError):
        center.act("expire", {"id": entry, "version": 2, "note": "Outdated"})
    assert center.list()["entries"][0]["state"] == "active"
    with MemoryStore(center.database) as store:
        assert len(store.create_snapshot(SPACE)["records"]) == 1
    monkeypatch.setattr(center, "event", original_event)
    center.act("expire", {"id": entry, "version": 2, "note": "Outdated"})
    assert center.list()["entries"][0]["state"] == "expired"
