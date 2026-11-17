# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Prevent inflated timing claims, unsafe input execution and publication
leaks."""

import json

import pytest

from examples.memory.performance import diagnose, inspect_input, render, seed
from examples.memory.performance_demo import run
from relax.memory.store import MemoryStore


def test_performance_trace_overlap_and_log_contract(tmp_path):
    trace = tmp_path / "synthetic.trace.json"
    trace.write_text(
        json.dumps(
            {
                "traceEvents": [
                    {"ph": "X", "cat": "kernel", "pid": 1, "tid": 1, "name": "gemm", "ts": 0, "dur": 100},
                    {"ph": "X", "cat": "kernel", "pid": 1, "tid": 2, "name": "nccl", "ts": 50, "dur": 100},
                    {"ph": "X", "cat": "kernel", "pid": 2, "tid": 1, "name": "gemm", "ts": 0, "dur": 80},
                    {"ph": "X", "cat": "cpu_op", "pid": 1, "name": "annotation", "ts": 0, "dur": 900},
                ]
            }
        )
    )
    result = inspect_input(trace, "trace")
    assert result["kernel_union_us_by_pid"] == {"1": 150, "2": 80}
    log = tmp_path / "synthetic.log"
    log.write_text("MEMORY_METRIC step=1 duration_s=12.5\nCUDA out of memory\nsecret=value\n")
    result = inspect_input(log, "log")
    assert result["step_samples"] == [{"step": 1, "duration_s": 12.5}]
    assert result["oom_mentions"] == 1
    assert "secret" not in json.dumps(result)
    log.write_text("arbitrary duration=2")
    assert inspect_input(log, "log")["step_samples"] == []


def test_performance_script_not_executed_and_html_escaped(tmp_path):
    marker = tmp_path / "executed"
    script = tmp_path / "untrusted.sh"
    script.write_text(f"touch {marker}\n--attention-backend fused\n")
    assert inspect_input(script, "script")["settings"][0]["value"] == "--attention-backend fused"
    assert not marker.exists()
    report = {key: [] for key in ("observations", "cases", "suggestions", "candidate", "read_receipt", "limitations")}
    report["cases"] = [{"title": "<script>alert(1)</script>", "summary": "<img src=x onerror=alert(1)>"}]
    assert "<script>alert(1)</script>" not in render(report)
    with pytest.raises(ValueError):
        inspect_input(script, "unknown")


def test_performance_actual_http_mcp_and_offline_roundtrip(tmp_path):
    result = run(tmp_path / "walkthrough")
    assert all(result["checks"].values())
    assert result["checks"]["historical_cases_loaded"] >= 4


def test_performance_current_log_and_trace_change_diagnostic_plan(tmp_path):
    log = tmp_path / "synthetic.log"
    log.write_text("CUDA out of memory\nMEMORY_METRIC step=1 duration_s=12.5\n")
    trace = tmp_path / "synthetic.trace.json"
    trace.write_text(
        json.dumps(
            {
                "traceEvents": [
                    {"ph": "X", "cat": "kernel", "pid": 1, "tid": 1, "name": "flash_attention", "ts": 0, "dur": 100}
                ]
            }
        )
    )
    with MemoryStore(tmp_path / "memory.sqlite") as store:
        seed(store, "p")
        report = diagnose(store, "p", [("log", log), ("trace", trace)], "Kimi MLA", tmp_path / "observed")
        mla = next(item for item in report["suggestions"] if "MLA" in item["title"])
        assert {item["kind"] for item in mla["observation_refs"]} == {"log", "trace"}
        assert "OOM" in mla["next_step"]
        log.write_text("unrecognized log format")
        unknown = diagnose(store, "p", [("log", log)], "Kimi MLA", tmp_path / "unknown")
        mla_unknown = next(item for item in unknown["suggestions"] if "MLA" in item["title"])
        assert not mla_unknown["observation_refs"]
        assert mla_unknown["next_step"] != mla["next_step"]
        assert "没有直接支持" in mla_unknown["relevance"]
