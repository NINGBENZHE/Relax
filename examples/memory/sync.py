# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Explicit selected publication and bounded, immutable remote search cache.

Uses an agent credential, never a remote administrator token. Pull is a
materialized search selection from the credential's fixed snapshot, not a full
incremental sync.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path
from typing import Any

from examples.memory.performance import candidate
from relax.memory.client import MemoryClient
from relax.memory.store import MemoryStore, digest, encode


def publish(
    client: MemoryClient, store: MemoryStore, namespace: str, snapshot_id: str, selected_ids: list[str]
) -> list[dict[str, Any]]:
    if not selected_ids:
        raise ValueError("Explicit record selection required")
    snapshot = store.snapshot(namespace, snapshot_id)
    records = {item["id"]: item for item in snapshot["records"]}
    if set(selected_ids) - records.keys():
        raise ValueError("Selection is not in the local snapshot")
    results = []
    for record_id in dict.fromkeys(selected_ids):
        record = candidate(records[record_id])
        results.append(
            client.call("memory_propose", record=record, idempotency_key="publish:" + digest(encode(record)))
        )
    return results


def pull(client: MemoryClient, store: MemoryStore, cache_namespace: str, query: str, origin: str) -> dict[str, Any]:
    if not cache_namespace.startswith("cache/"):
        raise ValueError("Remote copies require a separate cache/ namespace")
    receipt = client.call("memory_search", query=query, max_bytes=65536, limit=20)
    if digest(receipt["text"]) != receipt["content_sha256"]:
        raise ValueError("Remote receipt hash mismatch")
    remote_records = [json.loads(line) for line in receipt["text"].splitlines()[1:]]
    if [{"id": item["id"], "revision": item["revision"]} for item in remote_records] != receipt["items"]:
        raise ValueError("Remote records disagree with receipt")
    # Validate the entire selection before mutating local state.
    for record in remote_records:
        candidate(record)
    cache_namespace = cache_namespace + "/" + str(uuid.uuid4())
    copied = []
    for remote in remote_records:
        record = candidate(remote)
        record["extensions"] = record.get("extensions", {}) | {
            "remote_source": {
                "origin": origin,
                "namespace": remote["scope"]["namespace"],
                "id": remote["id"],
                "revision": remote["revision"],
                "snapshot_id": receipt["snapshot_id"],
                "receipt_hash": receipt["content_sha256"],
                "verification": remote["verification"],
            }
        }
        staged = store.stage(cache_namespace, "pull", digest(encode(record)), record)
        copied.append(
            store.commit(
                cache_namespace,
                staged["candidate_id"],
                {
                    "state": "verified",
                    "verifier_id": "authorized-remote-copy",
                    "claims": ["copied_from_authorized_fixed_snapshot_not_independently_verified"],
                    "evidence_ids": [item["evidence_id"] for item in record["evidence"]],
                },
            )
        )
    snapshot = store.create_snapshot(cache_namespace)
    return {
        "cache_snapshot_id": snapshot["snapshot_id"],
        "cache_namespace": cache_namespace,
        "copied": len(copied),
        "remote_receipt": receipt,
        "partial": True,
        "semantics": "selected search cache; no automatic refresh, revocation or full-library sync",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--db", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    pub = sub.add_parser("publish")
    pub.add_argument("--namespace", required=True)
    pub.add_argument("--snapshot", required=True)
    pub.add_argument("--record-id", action="append", required=True)
    download = sub.add_parser("pull")
    download.add_argument("--namespace", default="cache/performance")
    download.add_argument("--query", required=True)
    args = parser.parse_args()
    client = MemoryClient(args.endpoint, json.loads(args.token_file.read_text())["token"])
    with MemoryStore(args.db) as store:
        if args.command == "publish":
            result = publish(client, store, args.namespace, args.snapshot, args.record_id)
        else:
            result = pull(client, store, args.namespace, args.query, args.endpoint)
    sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
