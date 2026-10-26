# Copyright (c) 2026 Relax Authors. All Rights Reserved.

import os

import pytest
import torch
import torch.nn.functional as F


@pytest.mark.skipif(not torch.cuda.is_available(), reason="Packed attention regression requires CUDA")
@pytest.mark.parametrize(
    "backend",
    [
        "te",
        pytest.param(
            "fa4",
            marks=pytest.mark.skipif(
                os.environ.get("RELAX_RUN_B300_GPU_TESTS") != "1",
                reason="Pinned FA4 regression requires the B300 image (RELAX_RUN_B300_GPU_TESTS=1)",
            ),
        ),
    ],
)
@pytest.mark.parametrize(
    ("head_dim", "query_heads", "kv_heads", "causal", "softmax_scale"),
    [(72, 4, 4, False, None), (72, 4, 4, False, 0.2), (256, 6, 1, True, None)],
    ids=["vision-head72", "vision-head72-explicit-scale", "language-cp1-head256-gqa"],
)
def test_qwen38_flash_attn_packed_forward_backward(
    backend: str, head_dim: int, query_heads: int, kv_heads: int, causal: bool, softmax_scale: float | None
) -> None:
    if backend == "fa4":
        from importlib.metadata import version

        from _relax_fa4_pr2968.cute.interface import flash_attn_varlen_func

        assert torch.cuda.get_device_capability() == (10, 3), "Run the selected FA4 gate on B300"
        assert version("nvidia-cutlass-dsl") == "4.6.2", "Use the image-built FA4/CUTLASS runtime"
    else:
        from transformer_engine.pytorch import DotProductAttention

    lengths = (129, 257)
    offsets = (0, lengths[0], sum(lengths))
    cu_seqlens = torch.tensor(offsets, device="cuda", dtype=torch.int32)
    torch.manual_seed(42)
    inputs = [
        torch.randn(sum(lengths), heads, head_dim, device="cuda", dtype=torch.bfloat16)
        for heads in (query_heads, kv_heads, kv_heads)
    ]
    query, key, value = [tensor.detach().requires_grad_() for tensor in inputs]
    if backend == "fa4":
        # Exercise the image's pinned CuTe implementation directly; failures must propagate.
        actual, _ = flash_attn_varlen_func(
            query,
            key,
            value,
            cu_seqlens_q=cu_seqlens,
            cu_seqlens_k=cu_seqlens,
            max_seqlen_q=max(lengths),
            max_seqlen_k=max(lengths),
            causal=causal,
            softmax_scale=softmax_scale,
        )
    else:
        # Qwen3.8's default dense core uses TE dispatch in the CUDA 12 image.
        attention = DotProductAttention(
            num_attention_heads=query_heads,
            kv_channels=head_dim,
            num_gqa_groups=kv_heads,
            qkv_format="thd",
            attn_mask_type="padding_causal" if causal else "padding",
            softmax_scale=softmax_scale,
        )
        actual = attention(
            query,
            key,
            value,
            cu_seqlens_q=cu_seqlens,
            cu_seqlens_kv=cu_seqlens,
            max_seqlen_q=max(lengths),
            max_seqlen_kv=max(lengths),
        ).reshape_as(query)
    upstream = torch.randn_like(actual)
    actual.backward(upstream)

    reference_inputs = [tensor.float().detach().requires_grad_() for tensor in inputs]
    outputs = []
    # Separate documents explicitly to detect accidental attention across packed boundaries.
    with torch.nn.attention.sdpa_kernel(torch.nn.attention.SDPBackend.MATH):
        for start, end in zip(offsets[:-1], offsets[1:], strict=True):
            q, k, v = [tensor[start:end].transpose(0, 1).unsqueeze(0) for tensor in reference_inputs]
            output = F.scaled_dot_product_attention(q, k, v, is_causal=causal, enable_gqa=True, scale=softmax_scale)
            outputs.append(output.squeeze(0).transpose(0, 1))
    expected = torch.cat(outputs)
    expected.backward(upstream.float())

    torch.testing.assert_close(actual.float(), expected, atol=3e-2, rtol=3e-2)
    for tensor, reference in zip((query, key, value), reference_inputs, strict=True):
        assert tensor.grad is not None and reference.grad is not None
        torch.testing.assert_close(tensor.grad.float(), reference.grad, atol=3e-2, rtol=3e-2)
