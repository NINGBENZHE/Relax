# Copyright (c) 2026 Relax Authors. All Rights Reserved.

"""Exercise a running gateway; optionally perform real MemOS
write/search/import."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path

from relax.memory.client import MemoryClient
from relax.memory.memos import MemOSClient


def verify(endpoint: str, admin_file: str, memos_endpoint: str | None = None) -> dict:
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
    result = {
        "gateway": "passed",
        "namespace": namespace,
        "snapshot_isolation": "passed",
        "private_staging": "passed",
        "receipt_replay": "passed",
        "memos": "not_requested",
    }
    if memos_endpoint:
        # A fresh disposable cube avoids changing any business memory. Retain it for inspection.
        cube = "relax-verification-" + uuid.uuid4().hex
        # Cube creation requires a registered owner. Fresh self-hosted MemOS
        # initializes root; existing deployments can select a registered user.
        memos = MemOSClient(
            memos_endpoint,
            os.environ.get("MEMOS_VERIFY_USER", "root"),
            cube,
            os.environ.get("MEMOS_AUTHORIZATION", ""),
        )
        memos.create_cube()
        marker = "Memory verification marker " + uuid.uuid4().hex
        memos.add(marker + ": record code revision before validating a repair.", {"relax_probe": marker})
        candidates = []
        for _ in range(12):
            candidates = memos.search(marker)
            if candidates:
                break
            time.sleep(2)
        assert any(marker in item["content"]["text"] for item in candidates), (
            "Real MemOS write/search did not preserve the probe"
        )
        for index, item in enumerate(candidates):
            staged = reader.propose(item, "memos-probe-" + str(index))
            assert staged["status"] == "staged"
        assert reader.search("regression")["items"] == receipt["items"]
        result.update(memos="passed", memos_cube=cube, imported_candidates=len(candidates))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--admin-file", required=True)
    parser.add_argument("--memos-endpoint")
    args = parser.parse_args()
    sys.stdout.write(json.dumps(verify(args.endpoint, args.admin_file, args.memos_endpoint), indent=2) + "\n")


if __name__ == "__main__":
    main()
