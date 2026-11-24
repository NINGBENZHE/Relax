# Copyright (c) 2026 Relax Authors. All Rights Reserved.

"""Verify local review, snapshot isolation and read receipt replay."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

from relax.memory.client import MemoryClient


def verify(endpoint: str, admin_file: str) -> dict:
    admin = MemoryClient(endpoint, json.loads(Path(admin_file).read_text())["token"])
    namespace = "verification/" + uuid.uuid4().hex
    old = admin.call("snapshot_create", namespace=namespace)
    credentials = admin.call("session_bind", namespace=namespace, snapshot_id=old["snapshot_id"], session_id="a")
    agent = MemoryClient(endpoint, credentials["token"])
    record = json.loads(Path(__file__).with_name("knowledge.json").read_text())
    candidate = agent.propose(record, "first")
    assert agent.propose(record, "first") == candidate
    assert not agent.search("regression")["items"]
    committed = admin.call(
        "candidate_commit",
        namespace=namespace,
        candidate_id=candidate["candidate_id"],
        verification={"state": "verified", "verifier_id": "demo-reviewer", "evidence_ids": ["demo:maintainer-review"]},
    )
    assert not agent.search("regression")["items"], "Old snapshot changed after commit"
    new = admin.call("snapshot_create", namespace=namespace)
    new_credential = admin.call("session_bind", namespace=namespace, snapshot_id=new["snapshot_id"], session_id="b")
    reader = MemoryClient(endpoint, new_credential["token"])
    receipt = reader.search("regression")
    assert receipt["items"] == [{"id": committed["id"], "revision": 1}]
    assert reader.replay(receipt["read_receipt"]) == receipt
    other = admin.call("snapshot_create", namespace=namespace + "/other")
    other_credential = admin.call(
        "session_bind", namespace=namespace + "/other", snapshot_id=other["snapshot_id"], session_id="c"
    )
    assert not MemoryClient(endpoint, other_credential["token"]).search("regression")["items"]
    return {
        "gateway": "passed",
        "namespace": namespace,
        "snapshot_isolation": "passed",
        "private_staging": "passed",
        "receipt_replay": "passed",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--admin-file", required=True)
    args = parser.parse_args()
    sys.stdout.write(json.dumps(verify(args.endpoint, args.admin_file), indent=2) + "\n")


if __name__ == "__main__":
    main()
