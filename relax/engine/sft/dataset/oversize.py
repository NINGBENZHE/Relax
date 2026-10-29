# Copyright (c) 2026 Relax Authors. All Rights Reserved.

"""SFT sample length policies independent of the microbatch packing budget."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from torch import Tensor


def keep_within_sequence_limit(
    *, tokens: Tensor, loss_mask: Tensor, capacity: int, idx: int
) -> tuple[Tensor, Tensor] | None:
    """Keep long samples intact up to the launcher's configured sequence limit.

    The launcher sets SFT_MAX_SAMPLE_TOKENS from its SEQ_LENGTH setting. The
    dataset calls this hook after expanding multimodal tokens and only when the
    sample exceeds the packing budget. Returning the same tensors preserves
    image alignment and the assistant loss mask.
    """
    limit = int(os.environ["SFT_MAX_SAMPLE_TOKENS"])
    if not 0 < capacity <= limit:
        raise ValueError("SFT packing capacity must be positive and no greater than SFT_MAX_SAMPLE_TOKENS")
    return (tokens, loss_mask) if tokens.shape[0] <= limit else None
