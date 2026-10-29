# Copyright (c) 2026 Relax Authors. All Rights Reserved.

"""Exercise configurable sample limits through the real SFT oversize policy."""

import pytest
import torch

from relax.engine.sft.dataset.streaming import apply_oversize_strategy
from relax.utils.misc import load_function


@pytest.mark.parametrize("limit,capacity", [(64, 32), (131072, 65536), (262144, 131072)])
@pytest.mark.parametrize("boundary", ["budget", "budget_plus_one", "limit", "limit_plus_one"])
@pytest.mark.parametrize("has_multimodal", [False, True])
def test_sample_limit_preserves_tokens_and_loss_mask(monkeypatch, limit, capacity, boundary, has_multimodal):
    monkeypatch.setenv("SFT_MAX_SAMPLE_TOKENS", str(limit))
    hook = load_function("relax.engine.sft.dataset.oversize.keep_within_sequence_limit")
    length = {
        "budget": capacity,
        "budget_plus_one": capacity + 1,
        "limit": limit,
        "limit_plus_one": limit + 1,
    }[boundary]
    tokens = torch.arange(length)
    loss_mask = (tokens % 3 == 0).long()
    result = apply_oversize_strategy(
        tokens=tokens,
        loss_mask=loss_mask,
        capacity=capacity,
        strategy="custom",
        custom_fn=hook,
        idx=0,
        has_multimodal=has_multimodal,
    )
    if length > limit:
        assert result is None
    else:
        assert result[0] is tokens
        assert result[1] is loss_mask
