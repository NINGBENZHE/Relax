# Copyright (c) 2026 Relax Authors. All Rights Reserved.

"""SFT sample length policies independent of the microbatch packing budget."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from argparse import Namespace

    from torch import Tensor


def keep_within_sequence_limit(
    *, tokens: Tensor, loss_mask: Tensor, capacity: int, idx: int, config: Namespace
) -> tuple[Tensor, Tensor] | None:
    """Keep long samples intact up to the configured ``--seq-length``.

    The SFT producer binds its training configuration when loading this hook.
    The dataset calls it after expanding multimodal tokens and only when the
    sample exceeds the packing budget. Returning the same tensors preserves
    image alignment and the assistant loss mask.
    """
    limit = config.seq_length
    if limit is None or not 0 < capacity <= limit:
        raise ValueError("SFT packing capacity must be positive and no greater than --seq-length")
    return (tokens, loss_mask) if tokens.shape[0] <= limit else None
