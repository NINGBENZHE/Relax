# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Temporary MTP dispatch for images predating the static MCore entry point."""

import inspect
import sys
from functools import wraps


def install_chunked_mtp_compat() -> None:
    try:
        from megatron.core.models.gpt import gpt_model
    except ModuleNotFoundError as error:
        if error.name != "megatron":
            raise
        # CPU tools import backend utilities without installing Megatron.
        # Only an absent backend is optional; broken installed dependencies
        # must still fail rather than silently disabling MTP dispatch.
        return
    from megatron.core.transformer import multi_token_prediction

    from relax.models.common import chunked_mtp_loss

    native = multi_token_prediction.process_mtp_loss
    if getattr(native, "_relax_chunked_mtp_compat", False):
        return
    signature = inspect.signature(native)

    @wraps(native)
    def dispatch(*args, **kwargs):
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        config = bound.arguments["config"]
        fused_linear = config.cross_entropy_loss_fusion and config.cross_entropy_fusion_impl == "linear"
        if chunked_mtp_loss._chunked_mtp_enabled() and not fused_linear:
            # Legacy MCore places packed_seq_params directly after cp_group;
            # the common helper adds tp_group, so positional forwarding is unsafe.
            return chunked_mtp_loss.process_mtp_loss(**bound.arguments)
        return native(*args, **kwargs)

    dispatch._relax_chunked_mtp_compat = True
    multi_token_prediction.process_mtp_loss = dispatch
    gpt_model.process_mtp_loss = dispatch
    mamba = sys.modules.get("megatron.core.models.mamba.mamba_model")
    if mamba is not None and hasattr(mamba, "process_mtp_loss"):
        mamba.process_mtp_loss = dispatch
