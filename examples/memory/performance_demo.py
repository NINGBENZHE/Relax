# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Run the prototype with real repository inputs and a disposable remote HTTP
service."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from examples.memory.performance import ROOT, SCRIPT, diagnose, seed
from examples.memory.sync import publish, pull
from relax.memory.client import MemoryClient
from relax.memory.server import make_server
from relax.memory.store import MemoryStore


def run(directory: Path) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    local = directory / "local"
    local.mkdir(mode=0o700)
    remote_db = directory / "remote.sqlite"
    checks = {}
    with MemoryStore(local / "memory.sqlite") as store:
        records = seed(store, "relax/performance")
        report = diagnose(
            store,
            "relax/performance",
            [("script", ROOT / SCRIPT)],
            "Kimi K3 LoRA MLA 编译缓存 性能",
            directory / "diagnosis",
        )
        checks["historical_cases_loaded"] = len(records)
        checks["real_script_inspected"] = bool(report["observations"][0]["settings"])
        checks["diagnosis_stays_pending"] = len(store.candidates("relax/performance")) == 1
        snapshot = store.snapshot("relax/performance", report["snapshot_id"])
        reviewed = store.candidates("relax/performance")[0]
        # Review only the artifact observations, not the unexecuted performance hypotheses.
        store.commit(
            "relax/performance",
            reviewed["id"],
            {
                "state": "verified",
                "verifier_id": "demo-artifact-review",
                "claims": ["input_inspection_and_plan_recorded_not_bottleneck_or_speedup_verified"],
                "evidence_ids": [item["evidence_id"] for item in reviewed["record"]["evidence"]],
            },
        )
        checks["reviewed_plan_visible_only_in_new_snapshot"] = (
            len(store.create_snapshot("relax/performance")["records"]) == len(snapshot["records"]) + 1
            and store.snapshot("relax/performance", snapshot["snapshot_id"]) == snapshot
        )
        binding = store.bind("relax/performance", snapshot["snapshot_id"], "mcp-walkthrough")
        credential = local / "agent.json"
        credential.write_text(json.dumps(binding))
        credential.chmod(0o600)
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "memory_search", "arguments": {"query": "Kimi MLA", "max_bytes": 65536}},
            },
        ]
        process = subprocess.run(
            [sys.executable, "-m", "relax.memory", "mcp", "--state-dir", str(local), "--token-file", str(credential)],
            input="".join(json.dumps(item) + "\n" for item in requests),
            text=True,
            capture_output=True,
            timeout=20,
            cwd=ROOT,
            env=dict(os.environ, PYTHONPATH=str(ROOT)),
            check=True,
        )
        responses = [json.loads(line) for line in process.stdout.splitlines()]
        checks["local_mcp_without_http"] = responses[-1]["result"]["isError"] is False
        (directory / "mcp-response.json").write_text(json.dumps(responses, ensure_ascii=False, indent=2))
        with MemoryStore(remote_db) as remote:
            admin_token = remote.bootstrap()
            before = remote.create_snapshot("team/performance")
            writer = remote.bind("team/performance", before["snapshot_id"], "selected-publication")
        gateway = make_server(remote_db, port=0)
        thread = threading.Thread(target=gateway.serve_forever, daemon=True)
        thread.start()
        try:
            endpoint = f"http://127.0.0.1:{gateway.server_port}"
            client = MemoryClient(endpoint, writer["token"])
            selected = next(item for item in records if "缓存" in item["title"])
            published = publish(client, store, "relax/performance", snapshot["snapshot_id"], [selected["id"]])
            checks["selected_publication_staged"] = published[0]["status"] == "staged"
            checks["unreviewed_remote_invisible"] = not client.search("Kimi")["items"]
            # Trusted demo reviewer certifies only verbatim source attribution.
            admin = MemoryClient(endpoint, admin_token)
            pending = admin.call("candidate_list", namespace="team/performance")
            checks["only_selected_record_uploaded"] = len(pending) == 1
            approved = admin.call(
                "candidate_commit",
                namespace="team/performance",
                candidate_id=pending[0]["id"],
                verification={
                    "state": "verified",
                    "verifier_id": "demo-source-review",
                    "claims": ["source_attribution_only_no_performance_revalidation"],
                    "evidence_ids": [item["evidence_id"] for item in selected["evidence"]],
                },
            )
            checks["old_task_snapshot_unchanged"] = not client.search("Kimi")["items"]
            after = admin.call("snapshot_create", namespace="team/performance")
            reader = admin.call(
                "session_bind", namespace="team/performance", snapshot_id=after["snapshot_id"], session_id="next-task"
            )
            next_client = MemoryClient(endpoint, reader["token"])
            cache = pull(next_client, store, "cache/team/performance", "Kimi 编译缓存", endpoint)
            checks["next_task_pulled_one_selected_case"] = cache["copied"] == 1
            repeated = pull(next_client, store, "cache/team/performance", "Kimi 编译缓存", endpoint)
            checks["repeated_pull_isolated_selection"] = (
                repeated["cache_namespace"] != cache["cache_namespace"]
                and repeated["copied"] == 1
                and len(store.snapshot(repeated["cache_namespace"], repeated["cache_snapshot_id"])["records"]) == 1
            )
            replay = next_client.replay(cache["remote_receipt"]["read_receipt"])
            checks["remote_read_replayed_exactly"] = replay == cache["remote_receipt"]
            other = admin.call("snapshot_create", namespace="other-team/performance")
            other_binding = admin.call(
                "session_bind",
                namespace="other-team/performance",
                snapshot_id=other["snapshot_id"],
                session_id="isolated",
            )
            checks["other_business_isolated"] = not MemoryClient(endpoint, other_binding["token"]).search("Kimi")[
                "items"
            ]
            (directory / "sync-receipt.json").write_text(
                json.dumps(
                    {
                        "selected_record_id": selected["id"],
                        "remote_record_id": approved["id"],
                        "cache": cache,
                        "checks": checks,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        finally:
            gateway.shutdown()
            gateway.server_close()
            thread.join(timeout=5)
        offline = diagnose(
            store,
            cache["cache_namespace"],
            [("script", ROOT / SCRIPT)],
            "Kimi 编译缓存",
            directory / "offline-diagnosis",
        )
        checks["offline_after_remote_stopped"] = len(offline["cases"]) == 1
    if not all(checks.values()):
        raise AssertionError(checks)
    result = {
        "checks": checks,
        "report": str(directory / "diagnosis/report.html"),
        "limitations": [
            "真实仓库脚本和历史文档；远端为本机临时 HTTP 服务，非已部署云服务",
            "没有真实运行日志或 trace，没有执行训练或验证新性能收益",
            "HTML 是可筛选只读审阅页；审核与发布走 CLI/API，非完整 Web 管理后台",
            "同步为显式选择发布和固定快照检索缓存，非增量全库同步",
        ],
    }
    (directory / "walkthrough.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    sys.stdout.write(json.dumps(run(args.output.resolve()), ensure_ascii=False, indent=2) + "\n")
