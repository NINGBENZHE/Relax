# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""An unrecognized Cowork release must never execute on the client machine."""

import io
import json
import sys
from unittest.mock import patch

import pytest

from scripts.tools.memory_remote import client


def test_enable_rejects_changed_bundle_before_running_installer(tmp_path, monkeypatch):
    prefix = tmp_path / "install"
    marker = tmp_path / "executed"
    token_file = tmp_path / "application-token"
    token_file.write_text("test-only")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "memory",
            "enable",
            "--endpoint",
            "https://example.invalid",
            "--app-token-file",
            str(token_file),
            "--prefix",
            str(prefix),
        ],
    )
    bundle = {"client.py": f"from pathlib import Path\nPath({str(marker)!r}).touch()", "bridge.py": ""}
    with patch.object(client, "build_opener") as opener:
        opener.return_value.open.return_value = io.BytesIO(json.dumps(bundle).encode())
        with pytest.raises(ValueError, match="client version"):
            client.main()
    assert not marker.exists()
    assert not prefix.exists()
