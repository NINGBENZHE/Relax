# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Temporary entry point for images without the static gradient patch."""

from importlib import import_module


def install_chunked_grad_coalesce() -> None:
    try:
        target = import_module("megatron.core.distributed.finalize_model_grads")
    except ModuleNotFoundError as error:
        if error.name != "megatron":
            raise
        return
    from relax.models.common.chunked_grad_coalesce import _allreduce_non_tensor_model_parallel_grads

    target._allreduce_non_tensor_model_parallel_grads = _allreduce_non_tensor_model_parallel_grads
    target._allreduce_layernorm_grads = _allreduce_non_tensor_model_parallel_grads
