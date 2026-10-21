# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Import the real backend and exercise its installed TP reduction entry."""

import subprocess
import sys
from pathlib import Path


def test_backend_import_installs_bounded_tp_reduction():
    script = """
import importlib
import os
import sys
from types import ModuleType, SimpleNamespace
import torch
from torch._utils import _flatten_dense_tensors, _unflatten_dense_tensors

os.environ["RELAX_GRAD_COALESCE_CHUNK_BYTES"] = "8"
# Only optional Megatron boundaries are substituted; backend registration,
# compatibility installation and the gradient reducer are real modules.
for name in (
    "megatron", "megatron.core", "megatron.core.distributed",
    "megatron.core.parallel_state", "megatron.core.models",
    "megatron.core.models.gpt", "megatron.core.models.gpt.gpt_model",
    "megatron.core.transformer", "megatron.core.transformer.multi_token_prediction",
    "megatron.core.distributed.finalize_model_grads",
):
    module = ModuleType(name)
    module.__path__ = []
    sys.modules[name] = module
    parent, _, attr = name.rpartition(".")
    if parent:
        setattr(sys.modules[parent], attr, module)
target = sys.modules["megatron.core.distributed.finalize_model_grads"]
target._flatten_dense_tensors = _flatten_dense_tensors
target._unflatten_dense_tensors = _unflatten_dense_tensors
target._get_main_grad_attr = lambda param: "main_grad"
target._unshard_if_dtensor = lambda grad: grad
target._reshard_if_dtensor = lambda grad, original: grad
target.get_attr_wrapped_model = getattr
# Megatron exports a function with the same name as its submodule.
sys.modules["megatron.core.distributed"].finalize_model_grads = lambda: None
mtp = sys.modules["megatron.core.transformer.multi_token_prediction"]
mtp.process_mtp_loss = lambda config: None
helper = ModuleType("relax.models.common.chunked_mtp_loss")
sys.modules[helper.__name__] = helper

import relax.backends.megatron
from relax.models.common import chunked_grad_coalesce as helper
from relax.models.common.chunked_grad_coalesce_compat import install_chunked_grad_coalesce
install_chunked_grad_coalesce()
assert target._allreduce_non_tensor_model_parallel_grads is helper._allreduce_non_tensor_model_parallel_grads
assert target._allreduce_layernorm_grads is helper._allreduce_non_tensor_model_parallel_grads
params = [torch.nn.Parameter(torch.zeros(2)) for _ in range(2)]
for param in params:
    param.sequence_parallel = True
    param.main_grad = torch.ones(2)
group = SimpleNamespace(size=lambda: 2)
calls = []
def reduce(tensor, op, group):
    calls.append(tensor.numel())
    tensor.mul_(2)
torch.distributed.all_reduce = reduce
model = SimpleNamespace(ddp_config=SimpleNamespace(), named_parameters=lambda: enumerate(params))
target._allreduce_non_tensor_model_parallel_grads(
    [model], SimpleNamespace(sequence_parallel=True, qk_layernorm=False), group
)
assert calls == [2, 2], calls
for param in params:
    torch.testing.assert_close(param.main_grad, torch.full((2,), 2.0))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
