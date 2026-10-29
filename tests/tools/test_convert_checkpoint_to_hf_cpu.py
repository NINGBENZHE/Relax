# Copyright (c) 2026 Relax Authors. All Rights Reserved.

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest
import torch
import torch.distributed.checkpoint as dcp
from safetensors import safe_open
from safetensors.torch import save_file
from torch.distributed.checkpoint.metadata import ChunkStorageMetadata, TensorProperties, TensorStorageMetadata

from scripts.tools.convert_checkpoint_mapping import TensorSlice
from scripts.tools.convert_checkpoint_to_hf_cpu import check_chunks, export_checkpoint, load_slices, resolve_checkpoint


def _fixture(tmp_path: Path) -> tuple[Path, Path, dict[str, torch.Tensor]]:
    model, checkpoint = tmp_path / "model", tmp_path / "checkpoints" / "iter_0000007"
    model.mkdir()
    config = {
        "model_type": "qwen4_exp",
        "text_config": {
            "hidden_size": 4,
            "num_attention_heads": 4,
            "num_key_value_heads": 2,
            "head_dim": 2,
            "make_ngram_vocab_size_divisible_by": 2,
        },
        "vision_config": {"depth": 2, "hidden_size": 4, "num_heads": 2},
    }
    (model / "config.json").write_text(json.dumps(config))
    (model / "tokenizer.json").write_text("{}")
    state, expected = {}, {}

    def pair(source: str, target: str, tensor: torch.Tensor) -> None:
        state[source] = tensor
        expected[target] = tensor.clone()

    src = "language_model.decoder.layers.0."
    dst = "model.language_model.layers.0."
    pair(
        src + "mlp.experts.experts.linear_fc1.weight",
        dst + "mlp.experts.gate_up_proj",
        torch.arange(32.0).reshape(2, 4, 4),
    )
    pair(
        src + "mlp.experts.experts.linear_fc2.weight",
        dst + "mlp.experts.down_proj",
        torch.arange(16.0).reshape(2, 4, 2),
    )
    for suffix, target in (("in_proj.weight", "in_proj_qkv.weight"), ("conv1d.weight", "conv1d.weight")):
        pieces = []
        for index, part in enumerate(("query", "key", "value")):
            shape = (2, 4) if suffix.startswith("in_proj") else (2, 1, 3)
            tensor = torch.full(shape, float(index + 3))
            state[src + "self_attention." + suffix + "." + part] = tensor
            pieces.append(tensor)
        expected[dst + "linear_attn." + target] = torch.cat(pieces)
    for part, target in (("z", "z"), ("beta", "b"), ("alpha", "a")):
        pair(
            src + "self_attention.in_proj.weight." + part,
            dst + f"linear_attn.in_proj_{target}.weight",
            torch.arange(8.0).reshape(2, 4),
        )
    state[src + "self_attention.out_norm.weight"] = torch.tensor([-1.0, 0.0, 2.0])
    expected[dst + "linear_attn.norm.weight"] = torch.tensor([0.0, 1.0, 3.0])
    for root, target in (
        ("language_model.decoder.layers.1.", "model.language_model.layers.1."),
        ("language_model.mtp.layers.0.mtp_model_layer.layers.0.", "mtp.layers.0."),
    ):
        # Independent HF -> checkpoint packing: per group [Q heads, gates, K, V].
        q = torch.arange(64.0).reshape(4, 2, 2, 4)
        k, v = torch.full((2, 2, 4), 100.0), torch.full((2, 2, 4), 200.0)
        packed = []
        for group in range(2):
            packed.extend(
                (
                    q[2 * group : 2 * group + 2, 0].reshape(4, 4),
                    q[2 * group : 2 * group + 2, 1].reshape(4, 4),
                    k[group],
                    v[group],
                )
            )
        state[root + "self_attention.linear_qkv.weight"] = torch.cat(packed)
        expected[target + "self_attn.q_proj.weight"] = q.reshape(16, 4)
        expected[target + "self_attn.k_proj.weight"] = k.reshape(4, 4)
        expected[target + "self_attn.v_proj.weight"] = v.reshape(4, 4)
    pair("language_model.mtp.layers.0.hnorm.weight", "mtp.pre_fc_norm_hidden.weight", torch.arange(16.0))
    pair(
        src + "self_attention_hyper_connection.hc_norm.weight",
        dst + "attn_hyper_connection.hc_norm.weight",
        torch.arange(4.0),
    )
    state["language_model.embedding.word_embeddings.weight"] = torch.arange(24.0).reshape(6, 4)
    expected["model.language_model.embed_tokens.weight"] = state["language_model.embedding.word_embeddings.weight"][
        :5
    ].clone()
    table = torch.arange(20.0).reshape(10, 2)
    state[src + "per_layer_embedding.ple_embedding.ngram_embedding.weight"] = table
    for index in range(3):
        expected[dst + f"ple.ple_embedding.ngram_embedding.shard_{index}.weight"] = table[
            index * 3 : index * 3 + 3
        ].clone()
    for field, tail in (("weight", (4,)), ("bias", ())):
        layers = []
        for layer in range(2):
            qkv = torch.arange(12 * (4 if tail else 1), dtype=torch.float32).reshape(3, 2, 2, *tail) + layer * 100
            layers.append(qkv.transpose(0, 1).reshape(12, *tail))
            expected[f"model.visual.blocks.{layer}.attn.qkv.{field}"] = qkv.reshape(12, *tail)
        state[f"vision_model.decoder.layers.self_attention.linear_qkv.{field}"] = torch.stack(layers)
    pair("vision_model.merger.patch_norm.weight", "model.visual.merger.norm.weight", torch.arange(4.0))
    state["optimizer.state.exp_avg"] = torch.ones(2)
    dcp.save(state, checkpoint_id=checkpoint, no_dist=True)
    (checkpoint.parent / "latest_checkpointed_iteration.txt").write_text("7\n")
    base = {key: torch.zeros_like(value) for key, value in expected.items()}
    base[dst + "linear_attn.norm.weight"] = base[dst + "linear_attn.norm.weight"].to(torch.bfloat16)
    save_file(base, model / "model.safetensors")
    return checkpoint, model, expected


def test_cpu_export_round_trip_without_model_or_cuda(tmp_path: Path) -> None:
    checkpoint, model, expected = _fixture(tmp_path)
    output = tmp_path / "export"
    report = export_checkpoint(checkpoint.parent, model, output, shard_bytes=512, memory_budget=1024**2)
    index = json.loads((output / "model.safetensors.index.json").read_text())
    assert set(index["weight_map"]) == set(expected)
    for name, value in expected.items():
        with safe_open(output / index["weight_map"][name], framework="pt", device="cpu") as handle:
            assert torch.equal(handle.get_tensor(name), value), name
            assert handle.get_tensor(name).dtype == value.dtype
    assert index["metadata"]["total_size"] == sum(t.numel() * t.element_size() for t in expected.values())
    assert report["max_input_bytes"] < 1024
    assert not report["cuda_initialized"] and not report["distributed_initialized"]
    assert report["dtype_changes"]["model.language_model.layers.0.linear_attn.norm.weight"] == {
        "base": "BF16",
        "export": "F32",
    }
    assert (output / "config.json").read_bytes() == (model / "config.json").read_bytes()
    assert (output / "tokenizer.json").exists()
    assert not list(tmp_path.glob("export.incomplete-*"))


@pytest.mark.parametrize("entrypoint", ["shell", "python", "module"])
def test_cpu_export_entrypoint_dry_run(tmp_path: Path, entrypoint: str) -> None:
    checkpoint, model, _ = _fixture(tmp_path)
    output = tmp_path / "export"
    root = Path(__file__).resolve().parents[2]
    script = root / "scripts/tools/convert_checkpoint_to_hf_cpu"
    commands = {
        "shell": ["bash", str(script.with_suffix(".sh"))],
        "python": [sys.executable, str(script.with_suffix(".py"))],
        "module": [sys.executable, "-m", "scripts.tools.convert_checkpoint_to_hf_cpu"],
    }
    env = {
        **os.environ,
        "CHECKPOINT_PATH": str(checkpoint),
        "MODEL_PATH": str(model),
        "OUTPUT_DIR": str(output),
        "PYTHON_BIN": sys.executable,
    }
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [*commands[entrypoint], "--dry-run"],
        cwd=root if entrypoint == "module" else tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "CPU export plan" in result.stdout + result.stderr
    assert not output.exists()


def test_cpu_export_parameter_layout_hc_ple_mtp_and_frozen_weights(tmp_path: Path) -> None:
    model, checkpoint, output = (tmp_path / name for name in ("model", "checkpoint", "output"))
    model.mkdir()
    (model / "config.json").write_text(json.dumps({"model_type": "qwen4_exp", "text_config": {}}))
    state, expected = {}, {}
    norm = torch.tensor([-1.0, 0.0, 2.0, 3.0], dtype=torch.bfloat16)

    def pair(source: str, target: str, tensor: torch.Tensor = norm) -> None:
        state[source] = tensor.clone()
        expected[target] = tensor.clone()

    hc_fields = {
        "hc_norm_weight": "hc_norm.weight",
        "input_mix_weight_down": "input_mix_weight_down.weight",
        "input_mix_weight_up": "input_mix_weight_up.weight",
        "block_inject_weight": "block_inject_weight.weight",
    }
    for source, target in (
        ("decoder.hc_head_contraction.", "model.language_model.hyper_connection_mixer."),
        ("mtp.layers.0.hc_head_contraction.", "mtp.hyper_connection_mixer."),
    ):
        for field in ("hc_norm_weight", "input_mix_weight_down", "input_mix_weight_up"):
            pair(source + field, target + hc_fields[field])
    for source, target in (
        ("decoder.layers.1.", "model.language_model.layers.1."),
        ("mtp.layers.0.transformer_layer.", "mtp.layers.0."),
    ):
        for src_hc, dst_hc in (
            ("self_attention_hyper_connection.", "attn_hyper_connection."),
            ("mlp_hyper_connection.", "mlp_hyper_connection."),
        ):
            for field, hf_field in hc_fields.items():
                pair(source + src_hc + field, target + dst_hc + hf_field)
        for field in ("q_layernorm", "k_layernorm"):
            pair(source + "self_attention.indexer." + field, target + "self_attn.indexer." + field + ".weight")
    for field, hf_field in (
        ("norm_key", "norm_key.weight"),
        ("norm_query", "norm_query.weight"),
        ("norm_conv", "norm_conv.weight"),
        ("conv1d_weight", "conv1d.weight"),
        ("key_proj.weight", "key_proj.weight"),
        ("value_proj.weight", "value_proj.weight"),
    ):
        pair(
            "decoder.layers.1.self_attention_hyper_connection.ple." + field,
            "model.language_model.layers.1.ple." + hf_field,
        )
    for field in ("norm.weight", "conv1d.weight", "in_proj_qkv.weight", "A_log"):
        pair(
            "decoder.layers.0.self_attention.linear_attn." + field,
            "model.language_model.layers.0.linear_attn." + field,
            norm.float() if field == "A_log" else norm,
        )
    for field, hf_field in (
        ("e_proj.weight", "fc_embedding.weight"),
        ("h_proj.weight", "fc_hidden.weight"),
        ("enorm.weight", "pre_fc_norm_embedding.weight"),
        ("hnorm.weight", "pre_fc_norm_hidden.weight"),
    ):
        pair("mtp.layers.0." + field, "mtp." + hf_field)
    base = {name: torch.zeros_like(value, dtype=torch.bfloat16) for name, value in expected.items()}
    frozen = {
        "model.visual.pos_embed.weight": torch.arange(8, dtype=torch.bfloat16).reshape(2, 4),
        "model.language_model.layers.1.ple.ple_embedding.layer_multipliers": torch.tensor([3, 7, 11]),
        "model.language_model.layers.1.ple.ple_embedding.ngram_embedding.shard_0.weight": norm,
    }
    base.update(frozen)
    expected.update(frozen)
    dcp.save(state, checkpoint_id=checkpoint, no_dist=True)
    save_file(base, model / "model.safetensors")
    with pytest.raises(ValueError, match="Missing"):
        export_checkpoint(checkpoint, model, output, dry_run=True)
    report = export_checkpoint(checkpoint, model, output, shard_bytes=128, allow_base_fallback=("vision", "ple"))
    assert report["base_fallback_keys"] == sorted(frozen)
    index = json.loads((output / "model.safetensors.index.json").read_text())["weight_map"]
    assert set(index) == set(expected)
    for name, value in expected.items():
        with safe_open(output / index[name], framework="pt", device="cpu") as handle:
            actual = handle.get_tensor(name)
            assert actual.dtype == value.dtype and torch.equal(actual, value), name


@pytest.mark.parametrize("mtp_layer", ["transformer_layer", "mtp_model_layer"])
def test_cpu_export_standard_norms_and_individual_mtp_experts(tmp_path: Path, mtp_layer: str) -> None:
    model, checkpoint, output = (tmp_path / name for name in ("model", "checkpoint", "output"))
    model.mkdir()
    config = {"model_type": "qwen3_5_moe", "text_config": {"hidden_size": 4}}
    (model / "config.json").write_text(json.dumps(config))
    src = "language_model."
    layer = f"{src}mtp.layers.0.{mtp_layer}."
    norm = torch.tensor([-1.0, 0.0, 2.0, 3.0], dtype=torch.bfloat16)
    fc1 = torch.arange(32, dtype=torch.bfloat16).reshape(2, 4, 4)
    fc2 = torch.arange(16, dtype=torch.bfloat16).reshape(2, 4, 2)
    state = {
        src + "decoder.final_layernorm.weight": norm,
        src + "decoder.layers.0.pre_mlp_layernorm.weight": norm,
        src + "decoder.layers.0.self_attention.in_proj.layer_norm_weight": norm,
        src + "decoder.layers.0.self_attention.out_norm.weight": norm,
        src + "mtp.layers.0.eh_proj.weight": torch.arange(32, dtype=torch.bfloat16).reshape(4, 8),
        src + "mtp.layers.0.final_layernorm.weight": norm,
        layer + "self_attention.linear_qkv.layer_norm_weight": norm,
        layer + "mlp.experts.experts.linear_fc1.weight": fc1,
        layer + "mlp.experts.experts.linear_fc2.weight": fc2,
    }
    expected = {
        "model.language_model.norm.weight": norm,
        "model.language_model.layers.0.post_attention_layernorm.weight": norm,
        "model.language_model.layers.0.input_layernorm.weight": norm,
        "model.language_model.layers.0.linear_attn.norm.weight": norm + 1,
        "mtp.fc.weight": state[src + "mtp.layers.0.eh_proj.weight"],
        "mtp.norm.weight": norm,
        "mtp.layers.0.input_layernorm.weight": norm,
    }
    for expert in range(2):
        expected[f"mtp.layers.0.mlp.experts.{expert}.gate_proj.weight"] = fc1[expert, :2]
        expected[f"mtp.layers.0.mlp.experts.{expert}.up_proj.weight"] = fc1[expert, 2:]
        expected[f"mtp.layers.0.mlp.experts.{expert}.down_proj.weight"] = fc2[expert]
    dcp.save(state, checkpoint_id=checkpoint, no_dist=True)
    save_file({name: torch.zeros_like(value) for name, value in expected.items()}, model / "model.safetensors")
    export_checkpoint(checkpoint, model, output, shard_bytes=128)
    index = json.loads((output / "model.safetensors.index.json").read_text())["weight_map"]
    assert set(index) == set(expected)
    for name, value in expected.items():
        with safe_open(output / index[name], framework="pt", device="cpu") as handle:
            assert torch.equal(handle.get_tensor(name), value), name


@pytest.mark.parametrize("failure", ["missing", "unknown", "memory", "existing"])
def test_cpu_export_rejects_invalid_inputs_before_write(tmp_path: Path, failure: str) -> None:
    checkpoint, model, expected = _fixture(tmp_path)
    output = tmp_path / "export"
    kwargs = {}
    if failure == "missing":
        expected["mtp.fc_hidden.weight"] = torch.ones(4, 4)
        save_file(expected, model / "model.safetensors")
    elif failure == "unknown":
        checkpoint = tmp_path / "unknown"
        dcp.save(
            {"language_model.decoder.layers.0.unsupported.weight": torch.ones(2)},
            checkpoint_id=checkpoint,
            no_dist=True,
        )
    elif failure == "memory":
        kwargs["memory_budget"] = 1
    else:
        output.mkdir()
        (output / "keep").write_text("previous export")
    with pytest.raises((ValueError, FileExistsError)):
        export_checkpoint(checkpoint, model, output, **kwargs)
    assert not list(tmp_path.glob("export.incomplete-*"))
    if failure == "existing":
        assert (output / "keep").read_text() == "previous export"
    else:
        assert not output.exists()


def test_cpu_export_missing_weights_require_explicit_group(tmp_path: Path) -> None:
    checkpoint, model, expected = _fixture(tmp_path)
    name = "model.visual.patch_embed.proj.weight"
    expected[name] = torch.full((2, 3), 42.0)
    save_file(expected, model / "model.safetensors")
    with pytest.raises(ValueError, match="Missing"):
        export_checkpoint(checkpoint, model, tmp_path / "rejected", dry_run=True)
    output = tmp_path / "allowed"
    report = export_checkpoint(checkpoint, model, output, allow_base_fallback=("vision",))
    assert report["base_fallback_keys"] == [name]
    index = json.loads((output / "model.safetensors.index.json").read_text())
    with safe_open(output / index["weight_map"][name], framework="pt", device="cpu") as handle:
        assert torch.equal(handle.get_tensor(name), expected[name])


def test_cpu_dcp_partial_read_crosses_source_chunks(tmp_path: Path) -> None:
    # Write an actual DCP archive with two persistent chunks, as TP shards do.
    from torch.distributed.checkpoint import DefaultSavePlanner
    from torch.distributed.checkpoint.planner import SavePlan, WriteItem, WriteItemType
    from torch.distributed.checkpoint.planner_helpers import _create_write_item_for_tensor

    tensor = torch.arange(24.0).reshape(8, 3)

    class ChunkPlanner(DefaultSavePlanner):
        def create_local_plan(self) -> SavePlan:
            items = []
            for index, part in enumerate(tensor.chunk(2)):
                item = _create_write_item_for_tensor("table", part)
                # MetadataIndex is frozen; create one with the global offset.
                from torch.distributed.checkpoint.metadata import MetadataIndex

                item = replace(
                    item,
                    type=WriteItemType.SHARD,
                    index=MetadataIndex("table", (index * 4, 0)),
                    tensor_data=replace(
                        item.tensor_data,
                        size=tensor.size(),
                        chunk=ChunkStorageMetadata(torch.Size((index * 4, 0)), part.size()),
                    ),
                )
                items.append(item)
            return SavePlan(items)

        def resolve_data(self, write_item: WriteItem) -> torch.Tensor:
            start = write_item.index.offset[0]
            return tensor[start : start + 4].clone()

    dcp.save({"table": tensor}, checkpoint_id=tmp_path, planner=ChunkPlanner(flatten_state_dict=False), no_dist=True)
    reader = dcp.FileSystemReader(tmp_path)
    metadata = reader.read_metadata()
    assert len(metadata.state_dict_metadata["table"].chunks) == 2
    check_chunks("table", metadata.state_dict_metadata["table"])
    actual = load_slices(reader, (TensorSlice("table", (3, 3), (3, 0)),), metadata)["table"]
    assert torch.equal(actual, tensor[3:6])


def test_cpu_dcp_rejects_holes_and_overlaps() -> None:
    properties = TensorProperties(dtype=torch.float32)
    hole = TensorStorageMetadata(
        properties, torch.Size((4,)), [ChunkStorageMetadata(torch.Size((0,)), torch.Size((2,)))]
    )
    with pytest.raises(ValueError, match="Incomplete"):
        check_chunks("weight", hole)
    overlap = TensorStorageMetadata(
        properties,
        torch.Size((4,)),
        [
            ChunkStorageMetadata(torch.Size((0,)), torch.Size((2,))),
            ChunkStorageMetadata(torch.Size((1,)), torch.Size((2,))),
        ],
    )
    with pytest.raises(ValueError, match="Overlapping"):
        check_chunks("weight", overlap)


def test_cpu_checkpoint_resolves_selected_iteration(tmp_path: Path) -> None:
    checkpoint, _, _ = _fixture(tmp_path)
    assert resolve_checkpoint(checkpoint.parent) == checkpoint
    (checkpoint.parent / "latest_checkpointed_iteration.txt").write_text("999")
    assert resolve_checkpoint(checkpoint) == checkpoint
    with pytest.raises(FileNotFoundError):
        resolve_checkpoint(checkpoint.parent)
