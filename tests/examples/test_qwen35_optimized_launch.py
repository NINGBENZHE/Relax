# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Render the image-native recipe without submitting a Ray job."""

import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_optimized_launcher_uses_stable_checkpoints_and_image_dependencies():
    environment = dict(
        os.environ,
        MODEL_DIR="/model",
        DATA_DIR="/data",
        SAVE_DIR="/checkpoints",
        EXP_NAME="cpu-validation",
        DRY_RUN="1",
    )
    script = ROOT / "scripts/training/sft/run-qwen35-optimized-64xB300.sh"
    subprocess.run(["bash", "-n", str(script)], check=True)
    outputs = [
        json.loads(subprocess.check_output(["bash", str(script)], env=environment, text=True)) for _ in range(2)
    ]
    for output in outputs:
        argv = output["argv"]
        assert argv[argv.index("--load") + 1] == argv[argv.index("--save") + 1] == "/checkpoints/cpu-validation"
        assert "--sft-wholepack" in argv
        assert "--sft-packing-strategy" not in argv
        assert "--save-interval" in argv
        assert argv[argv.index("--max-tokens-per-gpu") + 1] == "262144"
        worker_env = output["runtime_env"]["env_vars"]
        assert json.loads(argv[argv.index("--train-env-vars") + 1]) == worker_env
        assert "B300_OPT_PREFIX" not in worker_env
        assert "RELAX_SFT_WHOLEPACK" not in worker_env
        assert worker_env["EP_DISABLE_GIN"] == "1"
        assert worker_env["LD_PRELOAD"].startswith("/opt/relax/cublas13.3/nvidia/cu13/lib/libcublasLt.so.13:")


def test_optimized_shell_preserves_worker_environment_and_argument_overrides():
    environment = dict(
        os.environ,
        MODEL_DIR="/model with spaces",
        DATA_DIR="/data with spaces.jsonl",
        SAVE_DIR="/checkpoints with spaces",
        EXP_NAME="cpu-validation",
        DRY_RUN="1",
        RUNTIME_ENV_JSON=json.dumps(
            {"env_vars": {"CUSTOM_WORKER_KEY": "preserved", "NCCL_ALGO": "Ring"}, "pip": ["example-package"]}
        ),
    )
    script = ROOT / "scripts/training/sft/run-qwen35-optimized-64xB300.sh"
    output = json.loads(
        subprocess.check_output(["bash", str(script), "--num-rollout", "3"], env=environment, text=True)
    )
    argv = output["argv"]
    assert argv[-2:] == ["--num-rollout", "3"]
    assert argv[argv.index("--hf-checkpoint") + 1] == "/model with spaces"
    assert argv[argv.index("--prompt-data") + 1] == "/data with spaces.jsonl"
    assert argv[argv.index("--save") + 1] == "/checkpoints with spaces/cpu-validation"
    # The shared model definition sets alltoall; the recipe's later flex setting must win.
    dispatch = [argv[i + 1] for i, value in enumerate(argv) if value == "--moe-token-dispatcher-type"]
    assert dispatch[-1] == "flex"
    assert argv[argv.index("--moe-flex-dispatcher-backend") + 1] == "deepepv2"
    assert argv[argv.index("--custom-megatron-before-train-step-hook-path") + 1] == (
        "relax.models.qwen3_5.recipe.before_step"
    )
    assert output["runtime_env"]["pip"] == ["example-package"]
    assert output["runtime_env"]["env_vars"]["CUSTOM_WORKER_KEY"] == "preserved"
    assert "NCCL_ALGO" not in output["runtime_env"]["env_vars"]
