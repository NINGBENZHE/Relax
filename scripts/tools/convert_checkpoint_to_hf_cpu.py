# Copyright (c) 2026 Relax Authors. All Rights Reserved.

"""Stream a torch_dist checkpoint to HF on CPU without constructing a model.

DCP global offsets recover TP/PP/EP shards; mappings consume only model
tensors. PLE tables and stacked vision layers use range-sized destination
buffers. DCP deserializes whole source chunks, which are included in the
preflight memory reservation. The mapping module selects supported layouts from
the HF configuration and rejects unsupported architectures or tensors.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import resource
import shutil
import struct
import sys
import tempfile
import time
from pathlib import Path
from typing import Any


if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from relax.utils.logging_utils import get_logger
from scripts.tools.convert_checkpoint_mapping import TensorSlice, build_conversions, model_key


logger = get_logger(__name__)


def _needs_owned_copy(tensor: Any) -> bool:
    return (
        not tensor.is_contiguous()
        or tensor.storage_offset() != 0
        or tensor.untyped_storage().nbytes() != tensor.numel() * tensor.element_size()
    )


def _dtype_name(dtype: Any) -> str:
    return {
        "torch.float64": "F64",
        "torch.float32": "F32",
        "torch.float16": "F16",
        "torch.bfloat16": "BF16",
        "torch.int64": "I64",
        "torch.int32": "I32",
        "torch.int16": "I16",
        "torch.int8": "I8",
        "torch.uint8": "U8",
        "torch.bool": "BOOL",
    }[str(dtype)]


def resolve_checkpoint(path: Path) -> Path:
    if (path / ".metadata").is_file():
        return path.resolve()
    tracker = path / "latest_checkpointed_iteration.txt"
    tag = tracker.read_text().strip()
    if tag == "release":
        path = path / tag
    elif tag.isdecimal():
        path = path / f"iter_{int(tag):07d}"
    else:
        raise ValueError(f"Invalid checkpoint tracker: {tracker}")
    if not (path / ".metadata").is_file():
        raise FileNotFoundError(path / ".metadata")
    return path.resolve()


def read_hf_schema(path: Path) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    index = path / "model.safetensors.index.json"
    weight_map = json.loads(index.read_text())["weight_map"] if index.is_file() else None
    filenames = sorted(set(weight_map.values())) if weight_map is not None else ["model.safetensors"]
    schema: dict[str, dict[str, Any]] = {}
    actual_map: dict[str, str] = {}
    for filename in filenames:
        if Path(filename).name != filename:
            raise ValueError(f"Expected a flat HF shard filename: {filename}")
        with (path / filename).open("rb") as handle:
            size = struct.unpack("<Q", handle.read(8))[0]
            if not 0 < size < 100_000_000:
                raise ValueError(f"Invalid safetensors header: {filename}")
            header = json.loads(handle.read(size))
        for name, entry in header.items():
            if name == "__metadata__":
                continue
            if name in schema:
                raise ValueError(f"Duplicate HF tensor: {name}")
            schema[name] = {"shape": entry["shape"], "dtype": entry["dtype"]}
            actual_map[name] = filename
            if entry["data_offsets"][1] + size + 8 > (path / filename).stat().st_size:
                raise ValueError(f"Truncated HF shard: {filename}")
    if weight_map is not None and weight_map != actual_map:
        raise ValueError("HF index does not match safetensors headers")
    if not schema:
        raise ValueError("Empty HF model")
    return actual_map, schema


def check_chunks(key: str, metadata: Any) -> None:
    """Reject holes and overlaps before DCP can leave uninitialized values."""
    shape = tuple(metadata.size)
    rectangles = []
    volume = 0
    for chunk in metadata.chunks:
        offset, size = tuple(chunk.offsets), tuple(chunk.sizes)
        if (
            len(offset) != len(shape)
            or len(size) != len(shape)
            or any(a < 0 or b <= 0 or a + b > n for a, b, n in zip(offset, size, shape))
        ):
            raise ValueError(f"Invalid DCP chunk bounds: {key}")
        volume += math.prod(size)
        rectangles.append((offset, tuple(a + b for a, b in zip(offset, size))))
    if volume != math.prod(shape):
        raise ValueError(f"Incomplete DCP tensor: {key}")
    if shape:
        axis = max(range(len(shape)), key=lambda i: len({start[i] for start, _ in rectangles}))
        active = []
        for start, end in sorted(rectangles, key=lambda item: item[0][axis]):
            active = [(a, b) for a, b in active if b[axis] > start[axis]]
            if any(
                all(a < d and c < b for a, b, c, d in zip(start, end, other_start, other_end))
                for other_start, other_end in active
            ):
                raise ValueError(f"Overlapping DCP chunks: {key}")
            active.append((start, end))


def load_slices(reader: Any, items: tuple[TensorSlice, ...], metadata: Any) -> dict[str, Any]:
    import torch
    import torch.distributed.checkpoint as dcp
    from torch.distributed.checkpoint.metadata import ChunkStorageMetadata
    from torch.distributed.checkpoint.planner import LoadPlan
    from torch.distributed.checkpoint.planner_helpers import create_read_items_for_chunk_list

    class SlicePlanner(dcp.DefaultLoadPlanner):
        def resolve_tensor(self, read_item: Any) -> Any:
            # dest_index.offset describes the global range; our plain tensor
            # holds only that range. dest_offsets are already relative to it.
            return self.transform_tensor(read_item, self.state_dict[read_item.dest_index.fqn])

        def create_local_plan(self) -> LoadPlan:
            requests = []
            for item in items:
                chunk = ChunkStorageMetadata(torch.Size(item.offset), torch.Size(item.shape))
                requests.extend(
                    create_read_items_for_chunk_list(item.key, metadata.state_dict_metadata[item.key], [chunk])
                )
            return LoadPlan(requests)

    state = {
        item.key: torch.empty(item.shape, dtype=metadata.state_dict_metadata[item.key].properties.dtype, device="cpu")
        for item in items
    }
    # Explicit no_dist prevents an inherited environment from initializing Gloo.
    # Disabling flattening preserves the literal persistent Megatron keys.
    dcp.load(
        state,
        storage_reader=reader,
        planner=SlicePlanner(flatten_state_dict=False, flatten_sharded_tensors=False),
        no_dist=True,
    )
    return state


class ShardWriter:
    def __init__(self, path: Path, shard_bytes: int) -> None:
        self.path = path
        self.shard_bytes = shard_bytes
        self.pending: dict[str, Any] = {}
        self.pending_bytes = 0
        self.weight_map: dict[str, str] = {}
        self.total_bytes = 0
        self.files: list[str] = []

    def add(self, name: str, tensor: Any) -> None:
        import torch

        if name in self.weight_map or name in self.pending:
            raise ValueError(f"Duplicate output tensor: {name}")
        if tensor.device.type != "cpu":
            raise ValueError(f"Expected CPU tensor: {name}")
        size = tensor.numel() * tensor.element_size()
        if self.pending_bytes + size > self.shard_bytes:
            self.flush()
        # Own views so a small projection cannot pin a huge input allocation.
        if _needs_owned_copy(tensor):
            tensor = tensor.clone(memory_format=torch.contiguous_format)
        self.pending[name] = tensor
        self.pending_bytes += size
        self.total_bytes += size
        if self.pending_bytes >= self.shard_bytes:
            self.flush()

    def flush(self) -> None:
        from safetensors.torch import save_file

        if not self.pending:
            return
        filename = f"shard-{len(self.files) + 1:05d}.safetensors"
        save_file(self.pending, self.path / filename, metadata={"format": "pt"})
        self.files.append(filename)
        self.weight_map.update(dict.fromkeys(self.pending, filename))
        self.pending.clear()
        self.pending_bytes = 0

    def finish(self) -> None:
        self.flush()
        renames = {}
        for index, old in enumerate(self.files, 1):
            new = f"model-{index:05d}-of-{len(self.files):05d}.safetensors"
            (self.path / old).rename(self.path / new)
            renames[old] = new
        self.weight_map = {key: renames[value] for key, value in self.weight_map.items()}
        (self.path / "model.safetensors.index.json").write_text(
            json.dumps({"metadata": {"total_size": self.total_bytes}, "weight_map": self.weight_map}, indent=2) + "\n"
        )


def _fallback_group(key: str) -> str | None:
    if key.startswith("model.visual."):
        return "vision"
    if re.search(r"\.ple\.ple_embedding\.", key):
        return "ple"
    if key.startswith("mtp."):
        return "mtp"
    return None


def _copy_assets(source: Path, output: Path) -> None:
    names = {
        "config.json",
        "generation_config.json",
        "tokenizer_config.json",
        "tokenizer.json",
        "special_tokens_map.json",
        "added_tokens.json",
        "vocab.json",
        "merges.txt",
        "vocab.txt",
        "preprocessor_config.json",
        "processor_config.json",
        "video_preprocessor_config.json",
        "chat_template.json",
    }
    for item in source.iterdir():
        if item.is_file() and (item.name in names or item.suffix in (".model", ".tiktoken", ".jinja", ".py")):
            shutil.copyfile(item, output / item.name)
    if (source / "chat_templates").is_dir():
        shutil.copytree(source / "chat_templates", output / "chat_templates")


def export_checkpoint(
    checkpoint: Path,
    model: Path,
    output: Path,
    *,
    shard_bytes: int = 2 * 1024**3,
    memory_budget: int = 64 * 1024**3,
    allow_base_fallback: tuple[str, ...] = (),
    dry_run: bool = False,
) -> dict[str, Any]:
    import torch
    import torch.distributed.checkpoint as dcp
    from safetensors import safe_open
    from torch.distributed.checkpoint.metadata import TensorStorageMetadata

    if torch.cuda.is_initialized() or torch.distributed.is_initialized():
        raise RuntimeError("CPU conversion must run without CUDA or a distributed process group")
    if shard_bytes <= 0 or memory_budget <= 0:
        raise ValueError("Shard size and memory budget must be positive")
    checkpoint, model, output = resolve_checkpoint(checkpoint), model.resolve(), output.resolve()
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}; choose a fresh output directory")
    if output.is_relative_to(checkpoint) or output.is_relative_to(model):
        raise ValueError("Output must be outside the source checkpoint/model directories")
    config = json.loads((model / "config.json").read_text())
    if config.get("quantization_config") or config.get("text_config", {}).get("quantization_config"):
        raise ValueError("Quantized source models are not supported")
    fingerprint = hashlib.sha256((checkpoint / ".metadata").read_bytes()).hexdigest()
    reader = dcp.FileSystemReader(checkpoint)
    metadata = reader.read_metadata()
    # Metadata can be large; each partial load reuses this exact snapshot.
    reader.read_metadata = lambda: metadata
    tensors = {
        key: value
        for key, value in metadata.state_dict_metadata.items()
        if isinstance(value, TensorStorageMetadata) and model_key(key) and "_extra_state" not in key
    }
    if not tensors:
        raise ValueError("Checkpoint contains no supported model tensors")
    for key, value in tensors.items():
        check_chunks(key, value)
    weight_map, schema = read_hf_schema(model)
    jobs = build_conversions(tensors, config, schema)
    expected: dict[str, tuple[tuple[int, ...], Any]] = {}
    expected_schema = dict(schema)
    dtype_changes = {}
    max_input = planned_tensor_buffers = 0
    for job in jobs:
        for item in job.inputs:
            full_shape = tensors[item.key].size
            if (
                len(item.shape) != len(full_shape)
                or len(item.offset) != len(full_shape)
                or any(
                    start < 0 or size <= 0 or start + size > full
                    for start, size, full in zip(item.offset, item.shape, full_shape)
                )
            ):
                raise ValueError(f"Invalid checkpoint slice: {item}")
        state = {
            item.key: torch.empty(item.shape, dtype=tensors[item.key].properties.dtype, device="meta")
            for item in job.inputs
        }
        max_input = max(max_input, sum(t.numel() * t.element_size() for t in state.values()))
        converted = job.apply(state, config)
        # Meta tensors preserve aliases. Count each allocation once, including
        # when the converted tensors share storage with their DCP input.
        storages = {
            tensor.untyped_storage()._cdata: tensor.untyped_storage().nbytes()
            for tensor in (*state.values(), *converted.values())
        }
        owned_copy_bytes = sum(
            tensor.numel() * tensor.element_size() for tensor in converted.values() if _needs_owned_copy(tensor)
        )
        largest_output = max(tensor.numel() * tensor.element_size() for tensor in converted.values())
        planned_tensor_buffers = max(
            planned_tensor_buffers,
            sum(storages.values()) + owned_copy_bytes + shard_bytes + max(shard_bytes, largest_output),
        )
        for name, tensor in converted.items():
            if name in expected or name not in schema or list(tensor.shape) != schema[name]["shape"]:
                raise ValueError(f"Duplicate/unexpected HF key or shape mismatch: {name}: {tuple(tensor.shape)}")
            expected[name] = (tuple(tensor.shape), tensor.dtype)
            dtype = _dtype_name(tensor.dtype)
            if dtype != schema[name]["dtype"]:
                floating = {"F64", "F32", "F16", "BF16"}
                if dtype not in floating or schema[name]["dtype"] not in floating:
                    raise ValueError(f"Incompatible checkpoint dtype: {name}: {dtype} vs {schema[name]['dtype']}")
                dtype_changes[name] = {"base": schema[name]["dtype"], "export": dtype}
            expected_schema[name] = {"shape": list(tensor.shape), "dtype": dtype}
    missing = sorted(schema.keys() - expected.keys())
    forbidden = [key for key in missing if _fallback_group(key) not in allow_base_fallback]
    if forbidden:
        raise ValueError(
            f"Missing {len(forbidden)} HF tensors; base fallback is disabled for these keys: {forbidden[:5]}"
        )
    # DCP's official reader deserializes each source chunk before slicing. Account
    # for that workspace too; partial loading does not bound original chunk size.
    chunk_bytes = max(
        math.prod(chunk.sizes) * torch.empty((), dtype=value.properties.dtype).element_size()
        for value in tensors.values()
        for chunk in value.chunks
    )
    archive_bytes = max(
        (info.length for index, info in metadata.storage_data.items() if index.fqn in tensors), default=0
    )
    fallback_bytes = max((math.prod(schema[key]["shape"]) * 8 for key in missing), default=0)
    reservation = max(
        planned_tensor_buffers + chunk_bytes + archive_bytes,
        2 * fallback_bytes + shard_bytes + max(shard_bytes, fallback_bytes),
    )
    report = {
        "checkpoint": str(checkpoint),
        "model": str(model),
        "output": str(output),
        "model_tensors": len(tensors),
        "conversion_groups": len(jobs),
        "hf_tensors": len(schema),
        "base_fallback_keys": missing,
        "max_input_bytes": max_input,
        "planned_buffer_bytes": reservation,
        "memory_budget_bytes": memory_budget,
        "metadata_sha256": fingerprint,
        "dtype_changes": dtype_changes,
    }
    if reservation > memory_budget:
        raise ValueError(
            f"Planned buffers need {reservation / 1024**3:.1f} GiB, above budget {memory_budget / 1024**3:.1f} GiB; increase --memory-budget-gb. This excludes Python and OS overhead."
        )
    logger.info("CPU export plan: %s", json.dumps(report, ensure_ascii=False))
    if dry_run:
        return report
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=output.name + ".incomplete-", dir=output.parent))
    started = time.monotonic()
    try:
        writer = ShardWriter(staging, shard_bytes)
        for number, job in enumerate(jobs, 1):
            state = load_slices(reader, job.inputs, metadata)
            converted = job.apply(state, config)
            for name in list(converted):
                tensor = converted.pop(name)
                if (tuple(tensor.shape), tensor.dtype) != expected[name]:
                    raise ValueError(f"Conversion changed after preflight: {name}")
                writer.add(name, tensor)
                del tensor
            del state, converted
            if number % 20 == 0 or number == len(jobs):
                logger.info("Converted %d/%d tensor groups", number, len(jobs))
        for name in missing:
            with safe_open(model / weight_map[name], framework="pt", device="cpu") as handle:
                writer.add(name, handle.get_tensor(name).clone())
        _copy_assets(model, staging)
        writer.finish()
        _, actual = read_hf_schema(staging)
        if actual != expected_schema:
            raise ValueError("Final HF schema verification failed")
        if hashlib.sha256((checkpoint / ".metadata").read_bytes()).hexdigest() != fingerprint:
            raise RuntimeError("Checkpoint metadata changed during conversion")
        report.update(
            status="complete",
            seconds=time.monotonic() - started,
            total_bytes=writer.total_bytes,
            peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
            cuda_initialized=torch.cuda.is_initialized(),
            distributed_initialized=torch.distributed.is_initialized(),
        )
        (staging / "conversion-result.json").write_text(json.dumps(report, indent=2) + "\n")
        if output.exists():
            raise FileExistsError(output)
        staging.rename(output)
    except BaseException:
        logger.error("Conversion failed; incomplete files retained at %s", staging)
        raise
    logger.info("CPU conversion complete: %s", output)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, default=os.environ.get("CHECKPOINT_PATH"))
    parser.add_argument("--origin-hf-dir", type=Path, default=os.environ.get("MODEL_PATH"))
    parser.add_argument("--output-dir", type=Path, default=os.environ.get("OUTPUT_DIR"))
    parser.add_argument(
        "--max-shard-size-gb", type=float, default=2, help="Target shard size in GiB; a single tensor may exceed it"
    )
    parser.add_argument(
        "--memory-budget-gb", type=float, default=64, help="Conservative tensor-buffer budget in GiB, not an RSS limit"
    )
    parser.add_argument("--cpu-threads", type=int, default=2)
    parser.add_argument(
        "--allow-base-fallback",
        choices=("vision", "ple", "mtp"),
        action="append",
        default=[],
        help="Explicitly copy missing tensors in this group from the exact training base",
    )
    parser.add_argument(
        "--dry-run",
        "--print-plan",
        action="store_true",
        help="Validate metadata/mappings/memory without reading weight values or writing output",
    )
    args = parser.parse_args()
    if any(value is None for value in (args.input_dir, args.origin_hf_dir, args.output_dir)):
        parser.error("Set CHECKPOINT_PATH, MODEL_PATH, OUTPUT_DIR or the equivalent CLI options")
    if args.cpu_threads <= 0:
        parser.error("--cpu-threads must be positive")
    if int(os.environ.get("WORLD_SIZE", "1")) != 1 or "LOCAL_RANK" in os.environ:
        parser.error("Run as one CPU process, without torchrun")
    import torch

    torch.set_num_threads(args.cpu_threads)
    export_checkpoint(
        args.input_dir,
        args.origin_hf_dir,
        args.output_dir,
        shard_bytes=int(args.max_shard_size_gb * 1024**3),
        memory_budget=int(args.memory_budget_gb * 1024**3),
        allow_base_fallback=tuple(args.allow_base_fallback),
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
