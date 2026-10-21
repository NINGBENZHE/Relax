# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Legacy image dispatch stays usable before the static patch lands."""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("enabled,fused", [(False, False), (True, False), (True, True)])
def test_legacy_mtp_dispatch_preserves_named_arguments(monkeypatch, enabled, fused):
    modules = {}
    for name in (
        "megatron",
        "megatron.core",
        "megatron.core.models",
        "megatron.core.models.gpt",
        "megatron.core.models.gpt.gpt_model",
        "megatron.core.transformer",
        "megatron.core.transformer.multi_token_prediction",
        "relax.models.common",
    ):
        modules[name] = ModuleType(name)
        monkeypatch.setitem(sys.modules, name, modules[name])
    native_calls = []

    def native(hidden_states, config, cp_group=None, packed_seq_params=None):
        native_calls.append((hidden_states, config, cp_group, packed_seq_params))
        return "native"

    helper = SimpleNamespace(_chunked_mtp_enabled=lambda: enabled, process_mtp_loss=Mock(return_value="chunked"))
    modules["relax.models.common"].chunked_mtp_loss = helper
    mtp = modules["megatron.core.transformer.multi_token_prediction"]
    gpt = modules["megatron.core.models.gpt.gpt_model"]
    mtp.process_mtp_loss = gpt.process_mtp_loss = native
    path = Path(__file__).resolve().parents[3] / "relax/models/common/chunked_mtp_compat.py"
    spec = importlib.util.spec_from_file_location("isolated_mtp_compat", path)
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    adapter.install_chunked_mtp_compat()
    dispatch = mtp.process_mtp_loss
    adapter.install_chunked_mtp_compat()
    assert mtp.process_mtp_loss is gpt.process_mtp_loss is dispatch
    config = SimpleNamespace(cross_entropy_loss_fusion=fused, cross_entropy_fusion_impl="linear")
    assert gpt.process_mtp_loss("hidden", config, "cp", "packed") == ("chunked" if enabled and not fused else "native")
    if enabled and not fused:
        helper.process_mtp_loss.assert_called_once_with(
            hidden_states="hidden", config=config, cp_group="cp", packed_seq_params="packed"
        )
        assert not native_calls
    else:
        helper.process_mtp_loss.assert_not_called()
        assert native_calls == [("hidden", config, "cp", "packed")]


def test_legacy_dispatch_with_main_head_bypass_preserves_mtp_losses(monkeypatch):
    import ast
    import runpy
    from contextlib import contextmanager

    import torch

    root = Path(__file__).resolve().parents[3]
    helpers = runpy.run_path(str(root / "tests/backends/megatron/test_chunked_mtp_loss.py"))
    from megatron.core.models.gpt import gpt_model

    mtp = helpers["_mtp_mod"]
    monkeypatch.setattr(mtp, "process_mtp_loss", mtp.process_mtp_loss)
    monkeypatch.setattr(gpt_model, "process_mtp_loss", gpt_model.process_mtp_loss)
    adapter = runpy.run_path(str(root / "relax/models/common/chunked_mtp_compat.py"))
    head = helpers["_FakeHead"](helpers["H"], helpers["V"])
    head.sequence_parallel = False
    config = helpers["_make_config"]()
    run = helpers["_run_and_capture"]
    _, expected = run(helpers["_native_process_mtp_loss"], head=head, config=config, monkeypatch=monkeypatch)
    adapter["install_chunked_mtp_compat"]()
    nodes = [
        n
        for n in ast.parse((root / "relax/backends/megatron/model.py").read_text()).body
        if getattr(n, "name", None) in {"_find_lm_output_layer", "_bypass_output_layer"}
    ]
    scope = dict(
        torch=torch,
        contextmanager=contextmanager,
        unwrap_model=lambda model: model,
        mpu=SimpleNamespace(get_tensor_model_parallel_group=lambda: None),
    )
    exec(
        compile(
            ast.Module(body=[ast.parse("from __future__ import annotations").body[0], *nodes], type_ignores=[]),
            "model.py",
            "exec",
        ),
        scope,
    )
    with scope["_bypass_output_layer"](SimpleNamespace(output_layer=head), mtp_output_layer_calls=0):
        hidden, losses = run(
            gpt_model.process_mtp_loss, head=head, config=config, monkeypatch=monkeypatch, chunk_size=2
        )
        main, _ = head(hidden)
        assert main is hidden
    assert len(losses) == len(expected) == helpers["LAYERS"]
    for actual, reference in zip(losses, expected):
        torch.testing.assert_close(actual, reference)


@pytest.mark.parametrize("missing", ["megatron.core", "transformer_engine", "einops"])
def test_installed_backend_dependency_errors_are_not_silenced(monkeypatch, missing):
    import builtins
    import runpy

    adapter = runpy.run_path(str(Path(__file__).resolve().parents[3] / "relax/models/common/chunked_mtp_compat.py"))
    original_import = builtins.__import__

    def broken_import(name, *args, **kwargs):
        if name == "megatron.core.models.gpt":
            raise ModuleNotFoundError(f"No module named {missing!r}", name=missing)
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", broken_import)
    with pytest.raises(ModuleNotFoundError) as error:
        adapter["install_chunked_mtp_compat"]()
    assert error.value.name == missing
