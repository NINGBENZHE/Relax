# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Start, inspect and stop the memory center demo without a foreground
terminal."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["up", "status", "down"])
    parser.add_argument("--state-dir", type=Path, default=Path.home() / ".local/state/relax-memory-center")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--public-host", default="127.0.0.1", help="Hostname used only in the browser URL")
    args = parser.parse_args()
    state = args.state_dir.resolve()
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    listen = state / "listen.json"
    info = json.loads(listen.read_text()) if listen.exists() else {}
    pid = info.get("pid")
    commandline = Path(f"/proc/{pid}/cmdline") if pid else None
    expected = ["-m", "relax.memory.center", "--state-dir", str(state)]
    parts = commandline.read_bytes().decode().split("\0") if commandline and commandline.exists() else []
    ours = any(parts[i : i + len(expected)] == expected for i in range(len(parts)))
    if args.command == "down":
        if ours:
            os.kill(pid, signal.SIGTERM)
            for _ in range(100):
                if not commandline.exists() or not commandline.read_bytes():
                    break
                time.sleep(0.05)
            else:
                raise SystemExit("Stop still pending; inspect the process before restarting")
        sys.stdout.write(json.dumps({"stopped": bool(ours), "data_retained": str(state)}) + "\n")
        return
    if args.command == "up" and not ours:
        listen.unlink(missing_ok=True)
        root = str(Path(__file__).resolve().parents[2])
        with (state / "server.log").open("ab") as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "relax.memory.center",
                    "--state-dir",
                    str(state),
                    "--host",
                    args.host,
                    "--port",
                    str(args.port),
                    "--seed-demo",
                ],
                stdout=log,
                stderr=log,
                start_new_session=True,
                env=dict(os.environ, PYTHONPATH=root + os.pathsep + os.environ.get("PYTHONPATH", "")),
            )
        for _ in range(100):
            if process.poll() is not None:
                raise SystemExit("Demo startup failed; inspect " + str(state / "server.log"))
            if listen.exists():
                info = json.loads(listen.read_text())
                break
            time.sleep(0.1)
        else:
            raise SystemExit("Startup pending; inspect " + str(state / "server.log"))
    elif not ours:
        raise SystemExit("Demo is not running")
    health_host = info.get("host", "127.0.0.1")
    if health_host == "0.0.0.0":
        health_host = "127.0.0.1"
    with urlopen(f"http://{health_host}:{info['port']}/health", timeout=3) as response:
        if json.loads(response.read()).get("service") != "relax-memory-center":
            raise SystemExit("Unexpected service on demo port")
    token = (state / "center-key").read_text().strip()
    sys.stdout.write(
        json.dumps(
            {
                "url": f"http://{args.public_host}:{info['port']}/#access={token}",
                "state_dir": str(state),
                "pid": info["pid"],
                "status": "running",
            }
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
