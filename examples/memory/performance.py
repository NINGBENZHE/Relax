# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""CPU-only performance memory prototype.

Never executes supplied scripts.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import json
import re
import sys
import uuid
from pathlib import Path
from typing import Any

from relax.memory.store import MemoryStore, digest, encode, validate_record


ROOT = Path(__file__).resolve().parents[2]
SOURCE = "examples/models/kimi-k3/OPTIMIZE.md"
SCRIPT = "examples/models/kimi-k3/scripts/run-kimi-k3-pokemon-lora-64xblackwell.sh"
LIMIT = 64 * 1024 * 1024


def read_file(path: Path) -> tuple[bytes, str]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rb") as stream:
        data = stream.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError("Input exceeds prototype 64 MiB decoded limit; provide a bounded window")
    return data, hashlib.sha256(data).hexdigest()


def candidate(record: dict[str, Any]) -> dict[str, Any]:
    keys = {
        "schema_version",
        "kind",
        "domain",
        "subtype",
        "title",
        "summary",
        "content",
        "evidence",
        "applicability",
        "relations",
        "extensions",
    }
    return validate_record({key: value for key, value in record.items() if key in keys})


def seed(store: MemoryStore, namespace: str) -> list[dict[str, Any]]:
    """Verify verbatim extraction only, never certify historic benchmark
    claims."""
    data, sha = read_file(ROOT / SOURCE)
    sections = re.split(r"(?m)^## ", data.decode())[1:]
    records = []
    for section in sections:
        title, _, body = section.partition("\n")
        evidence_id = "source:" + sha + ":" + digest(section)[:16]
        record = {
            "schema_version": "1.0",
            "kind": "episode",
            "domain": "performance",
            "subtype": "documented_case",
            "title": title,
            "summary": "Kimi K3 历史文档案例；来源摘录已核对，历史性能结果未重新实测。",
            "content": {
                "source_excerpt": body.strip(),
                "evidence_level": "source_attribution_only",
                "unknowns": ["原始日志、测量重复次数和当前任务适用性需要复核"],
            },
            "evidence": [{"evidence_id": evidence_id, "path": SOURCE, "sha256": sha}],
            "applicability": {"paths": [SOURCE], "match_mode": "manual_review"},
        }
        staged = store.stage(namespace, "source-import", digest(encode(record)), record)
        records.append(
            store.commit(
                namespace,
                staged["candidate_id"],
                {
                    "state": "verified",
                    "verifier_id": "verbatim-source-import",
                    "claims": ["source_attribution_only"],
                    "evidence_ids": [evidence_id],
                },
            )
        )
    return records


def union_duration(intervals: list[tuple[float, float]]) -> float:
    end, total = float("-inf"), 0.0
    for start, stop in sorted(intervals):
        total += max(0.0, stop - max(start, end))
        end = max(end, stop)
    return total


def inspect_input(path: Path, kind: str) -> dict[str, Any]:
    data, sha = read_file(path)
    result: dict[str, Any] = {"kind": kind, "path": str(path), "sha256": sha}
    if kind == "script":
        # Only selected settings, never shell execution or arbitrary environment values.
        lines = data.decode().splitlines()
        patterns = (
            r"--attention-backend\s+\S+",
            r"--(?:tensor|pipeline|context|expert)-model-parallel-size\s+\S+",
            r"RELAX_KIMI_K3_(?:EXPERT_SPLIT|FUSED_SITU|FUSED_ATTN_RES)",
            r"RELAX_KERNEL_CACHE_DIR",
        )
        result["settings"] = [
            {"line": i + 1, "value": match.group()}
            for i, line in enumerate(lines)
            if not line.lstrip().startswith("#")
            for pattern in patterns
            for match in re.finditer(pattern, line)
        ]
        result["limitations"] = ["仅静态文本；不解析 shell 条件、环境覆盖、source 和下游脚本，非实际生效参数"]
    elif kind == "log":
        text = data.decode()
        # Explicit normalized metric grammar; unsupported log formats remain unknown.
        samples = re.findall(r"(?m)^MEMORY_METRIC step=(\d+) duration_s=(\d+(?:\.\d+)?)$", text)
        result["step_samples"] = [{"step": int(step), "duration_s": float(value)} for step, value in samples]
        result["oom_mentions"] = len(re.findall(r"CUDA out of memory", text, re.I))
        result["limitations"] = ["只统计 MEMORY_METRIC 规范行和 OOM 文本；文本出现次数不代表独立故障次数"]
    elif kind == "trace":
        trace = json.loads(data)
        events = trace.get("traceEvents", []) if isinstance(trace, dict) else trace
        if not isinstance(events, list):
            raise ValueError("Expected Chrome traceEvents array")
        groups: dict[str, list[tuple[float, float]]] = {}
        totals: dict[str, dict[str, float]] = {}
        for event in events:
            if event.get("ph") != "X" or event.get("cat") != "kernel":
                continue
            start, duration = float(event["ts"]), float(event["dur"])
            if not (0 <= duration < float("inf") and abs(start) < float("inf")):
                raise ValueError("Invalid trace interval")
            pid = str(event.get("pid", "unknown"))
            groups.setdefault(pid, []).append((start, start + duration))
            name = str(event.get("name", "unknown"))
            aggregate = totals.setdefault(name, {"calls": 0, "summed_duration_us": 0})
            aggregate["calls"] += 1
            aggregate["summed_duration_us"] += duration
        result["kernel_union_us_by_pid"] = {pid: union_duration(values) for pid, values in groups.items()}
        result["top_kernels"] = sorted(totals.items(), key=lambda pair: -pair[1]["summed_duration_us"])[:12]
        result["limitations"] = [
            "单文件 kernel 事件按 pid 跨 stream 求并集；不是 MFU 或整卡利用率",
            "算子累计耗时允许重叠，不能相加作为端到端耗时；未做跨 rank 归因",
        ]
    else:
        raise ValueError("Unknown input kind")
    return result


def suggest(record: dict[str, Any], observations: list[dict[str, Any]]) -> dict[str, Any]:
    title = record["title"]
    if "缓存" in title:
        patterns = ("cache", "compile", "jit", "RELAX_KERNEL_CACHE_DIR")
        action = "分开测量冷启动、热缓存首步和稳态耗时；核对缓存命中及构建指纹。"
    elif "MLA" in title:
        patterns = ("attention", "flash", "cudnn", "fmha")
        action = "核对实际 attention 后端、序列长度和依赖版本；短序列不能照搬长序列收益。"
    elif "Split" in title or "冗余复制" in title:
        patterns = ("fill", "add", "cat", "EXPERT_SPLIT")
        action = "核对独立专家 LoRA 路径、ETP 和 dtype；用调用栈确认 fill/add/cat 是否来自目标路径。"
    else:
        patterns = ("situ", "attn_res", "tanh", "sigmoid")
        action = "核对相关融合算子是否实际启用；同 shape 做输出、梯度和局部耗时对照。"
    triggers = []
    for observation in observations:
        basis: dict[str, Any] = {}
        if observation["kind"] == "script":
            settings = [
                item
                for item in observation["settings"]
                if any(pattern.casefold() in item["value"].casefold() for pattern in patterns)
            ]
            if settings:
                basis = {"static_settings": settings, "interpretation": "相关配置出现在脚本中，运行时生效未知"}
                action = "先核对已有配置在 worker 的实际生效值，避免重复建议开启。" + action
        elif observation["kind"] == "trace":
            kernels = [
                item
                for item in observation["top_kernels"]
                if any(pattern.casefold() in item[0].casefold() for pattern in patterns)
            ]
            if kernels:
                basis = {
                    "matching_top_kernels": kernels,
                    "interpretation": "名称匹配仅用于定位，需核对父栈、shape 与关键路径",
                }
        elif observation["kind"] == "log":
            samples = observation["step_samples"]
            if "缓存" in title and len(samples) >= 2:
                basis = {"step_samples": samples[:8], "interpretation": "需确认工作量可比，不能把首步差异直接归因编译"}
            if observation["oom_mentions"]:
                basis["oom_mentions"] = observation["oom_mentions"]
                action = "输入存在 OOM 文本，先确认失败阶段与显存峰值，暂不扩大 batch 或并发。" + action
        if basis:
            triggers.append({"input_sha256": observation["sha256"], "kind": observation["kind"], "basis": basis})
    return {
        "memory_id": record["id"],
        "revision": record["revision"],
        "title": title,
        "status": "待验证建议，不是当前瓶颈结论",
        "relevance": "当前输入存在相关线索" if triggers else "仅历史备选，当前输入没有直接支持",
        "observation_refs": triggers,
        "next_step": action,
        "missing_conditions": ["实际运行配置、模型与硬件适用性、可比基线、正确性证据"],
    }


def diagnose(
    store: MemoryStore, namespace: str, inputs: list[tuple[str, Path]], query: str, output: Path
) -> dict[str, Any]:
    observations = [inspect_input(path, kind) for kind, path in inputs]
    if not observations:
        raise ValueError("Supply at least one script, log or trace")
    snapshot = store.create_snapshot(namespace)
    session = "diagnose-" + str(uuid.uuid4())
    binding = store.bind(namespace, snapshot["snapshot_id"], session)
    principal = store.authenticate(binding["token"])
    read = store.read(principal, query, max_bytes=65536, limit=10)
    ids = {item["id"] for item in read["items"]}
    cases = [r for r in snapshot["records"] if r["id"] in ids]
    suggestions = [suggest(record, observations) for record in cases]
    evidence = [{"evidence_id": "input:" + item["sha256"], "kind": item["kind"]} for item in observations]
    proposal = {
        "schema_version": "1.0",
        "kind": "episode",
        "domain": "performance",
        "subtype": "diagnostic_plan",
        "title": "性能诊断计划：" + query,
        "summary": "已读取当前材料与历史案例；尚未执行优化或测得新收益。",
        "content": {
            "observations": observations,
            "suggestions": suggestions,
            "read_receipt": read["read_receipt"],
            "unknowns": ["瓶颈归因和收益需实际对照验证"],
        },
        "evidence": evidence,
    }
    staged = store.stage(namespace, session, digest(encode(proposal)), proposal)
    report = {
        "namespace": namespace,
        "snapshot_id": snapshot["snapshot_id"],
        "query": query,
        "observations": observations,
        "read_receipt": read,
        "cases": cases,
        "suggestions": suggestions,
        "candidate": staged,
        "limitations": [
            "规则化诊断原型，未调用模型、未提交训练；关键词命中不证明适用性",
            "脚本配置需结合实际启动回执确认；历史文档收益未重新验证",
        ],
    }
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    (output / "candidate.json").write_text(json.dumps(proposal, ensure_ascii=False, indent=2))
    (output / "report.html").write_text(render(report))
    return report


def render(report: dict[str, Any]) -> str:
    def block(value: Any) -> str:
        return "<pre>" + html.escape(json.dumps(value, ensure_ascii=False, indent=2)) + "</pre>"

    def details(title: str, value: Any) -> str:
        return "<details><summary>" + html.escape(title) + "</summary>" + block(value) + "</details>"

    observations = "".join(
        "<article><b>"
        + html.escape(item["kind"])
        + "</b><p>"
        + html.escape(item["path"])
        + "</p>"
        + details("检查结果与输入指纹", item)
        + "</article>"
        for item in report["observations"]
    )
    cases = "".join(
        "<article><b>"
        + html.escape(item["title"])
        + "</b><p>"
        + html.escape(item["summary"])
        + "</p>"
        + details("查看原始摘录、证据和适用边界", item)
        + "</article>"
        for item in report["cases"]
    )
    suggestions = "".join(
        "<article><span class='badge'>待验证</span><b>"
        + html.escape(item["title"])
        + "</b><p>"
        + html.escape(item["relevance"])
        + "</p><p>"
        + html.escape(item["next_step"])
        + "</p><small>引用 "
        + html.escape(item["memory_id"])
        + " @ "
        + str(item["revision"])
        + "</small>"
        + details("当前观察依据与缺失条件", item)
        + "</article>"
        for item in report["suggestions"]
    )
    panels = [
        ("1 · 当前输入", observations),
        ("2 · 历史案例", cases or "没有匹配案例；不能据此推荐历史优化。"),
        ("3 · 下一步诊断", suggestions or "补充项目、模型和问题描述后重新检索。"),
        (
            "4 · 候选审阅",
            "<p>诊断计划已暂存。确认观察、补充验证结果后，通过 review 命令审核；发布需另行选择。</p>"
            + details("候选标识", report["candidate"]),
        ),
        ("5 · 可追溯读取", details("实际读取内容、快照和字节预算", report["read_receipt"])),
        ("6 · 验证边界", block(report["limitations"])),
    ]
    return (
        """<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Relax 性能记忆诊断</title><style>
body{font:16px system-ui;max-width:1080px;margin:32px auto;padding:20px;background:#f5f7fb;color:#182438}
header{padding:28px;background:#132c48;color:white;border-radius:16px}h1{margin-top:0}
section{background:white;border:1px solid #dbe3ef;border-radius:12px;padding:20px;margin:16px 0}
article{padding:16px 0;border-top:1px solid #e7edf5}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:13px}
summary{cursor:pointer;color:#245d99;padding:8px 0}input{box-sizing:border-box;padding:14px;width:100%;margin-top:20px;
border:1px solid #bdcbe0;border-radius:8px}small{overflow-wrap:anywhere}.badge{background:#fff0c2;color:#765100;
padding:4px 8px;border-radius:5px;margin-right:10px}p{line-height:1.6}</style>
<header><h1>Relax 性能记忆诊断</h1><p>当前材料 → 历史证据 → 诊断建议 → 审核沉淀</p>
<p>离线审阅原型 · 不执行训练 · 不自动发布</p></header>
<input id="filter" aria-label="筛选内容" placeholder="筛选面板内容，例如 MLA、缓存、待验证">
"""
        + "".join("<section><h2>" + title + "</h2>" + body + "</section>" for title, body in panels)
        + """
<script>document.getElementById('filter').addEventListener('input',e=>{
for(const s of document.querySelectorAll('section'))s.hidden=!s.textContent.toLowerCase().includes(e.target.value.toLowerCase());
});</script></html>"""
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--namespace", default="relax/performance")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed")
    run = sub.add_parser("diagnose")
    for kind in ("script", "log", "trace"):
        run.add_argument("--" + kind, type=Path, action="append", default=[])
    run.add_argument("--query", required=True, help="Explicit project/model/problem query; no guessed hardware")
    run.add_argument("--output", type=Path, required=True)
    review = sub.add_parser("review")
    review.add_argument("--candidate-id", required=True)
    review.add_argument("--reviewer", required=True)
    review.add_argument("--claim", required=True, help="What was actually checked; no inferred performance validation")
    sub.add_parser("list")
    args = parser.parse_args()
    args.db.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with MemoryStore(args.db) as store:
        if args.command == "seed":
            value = {"imported": len(seed(store, args.namespace)), "claim": "source_attribution_only"}
        elif args.command == "diagnose":
            report = diagnose(
                store,
                args.namespace,
                [(kind, path) for kind in ("script", "log", "trace") for path in getattr(args, kind)],
                args.query,
                args.output,
            )
            value = {
                "report": str(args.output / "report.html"),
                "candidate": report["candidate"],
                "matched_cases": len(report["cases"]),
            }
        elif args.command == "review":
            row = next((item for item in store.candidates(args.namespace) if item["id"] == args.candidate_id), None)
            if row is None:
                raise ValueError("Pending candidate not found")
            record = store.commit(
                args.namespace,
                args.candidate_id,
                {
                    "state": "verified",
                    "verifier_id": args.reviewer,
                    "claims": [args.claim],
                    "evidence_ids": [item["evidence_id"] for item in row["record"]["evidence"]],
                },
            )
            value = {"record_id": record["id"], "revision": record["revision"], "claims": [args.claim]}
        else:
            value = {"pending": store.candidates(args.namespace), "snapshot": store.create_snapshot(args.namespace)}
    sys.stdout.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
