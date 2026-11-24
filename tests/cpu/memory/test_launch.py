# Copyright (c) 2026 Relax Authors. All Rights Reserved.

"""Exercise the actual dependency-free shell entry point and persistent
restart."""

import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

from relax.memory.client import MemoryClient


def test_memory_up_status_verify_and_restart(tmp_path):
    root = Path(__file__).parents[3]
    script = str(root / "scripts/tools/memory.sh")
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    endpoint = f"http://127.0.0.1:{port}"
    environment = dict(
        os.environ,
        RELAX_MEMORY_STATE=str(tmp_path / "state"),
        RELAX_MEMORY_PORT=str(port),
        RELAX_MEMORY_HOST="127.0.0.1",
        RELAX_MEMORY_ENDPOINT=endpoint,
        MEMORY_PYTHON=sys.executable,
    )
    snapshot = None
    for command in ("up", "local"):
        with (tmp_path / f"{command}.log").open("w") as log:
            process = subprocess.Popen(["bash", script, command], env=environment, stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 15
                while True:
                    assert process.poll() is None, "Foreground service exited during startup"
                    try:
                        with urlopen(endpoint + "/health", timeout=0.5) as response:
                            assert json.load(response)["service"] == "relax-memory"
                        break
                    except OSError:
                        assert time.monotonic() < deadline, "Service readiness timed out"
                        time.sleep(0.1)
                result = subprocess.run(
                    ["bash", script, "status"], env=environment, capture_output=True, text=True, check=True, timeout=10
                )
                assert json.loads(result.stdout)["service"] == "relax-memory"
                credential = json.loads((tmp_path / "state/admin.json").read_text())
                admin = MemoryClient(endpoint, credential["token"])
                if snapshot is None:
                    result = subprocess.run(
                        ["bash", script, "verify"],
                        env=environment,
                        capture_output=True,
                        text=True,
                        check=True,
                        timeout=20,
                    )
                    assert json.loads(result.stdout)["gateway"] == "passed"
                    snapshot = admin.call("snapshot_create", namespace="persistent-project")
                else:
                    assert (
                        admin.call("snapshot_get", namespace="persistent-project", snapshot_id=snapshot["snapshot_id"])
                        == snapshot
                    )
            finally:
                if process.poll() is None:
                    process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            assert process.returncode == 0
    result = subprocess.run(["bash", script, "init-env"], env=environment, capture_output=True, text=True, timeout=5)
    assert result.returncode == 2
