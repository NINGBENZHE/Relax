#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.

"""Bootstrap the release-pinned Cowork MCP client using Python's standard
library."""

import argparse
import getpass
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


# Update together with the tested Cowork client release.
FILES = {
    "client.py": "10562c85eae2675d3d67761da9e18dc5c0ecdf23128c570a6eb043a30734321a",
    "bridge.py": "b1a86edbb189b3696550dd892a586ff5ce7aed2052ef408394ab0cb07f182083",
}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument(
        "--prefix",
        type=Path,
        default=Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "relax-memory-remote",
    )
    prefix_args, arguments = parser.parse_known_args()
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    parser.add_argument(
        "--endpoint", default=os.environ.get("RELAX_MEMORY_COWORK_ENDPOINT") or os.environ.get("RELAX_MEMORY_ENDPOINT")
    )
    parser.add_argument("--app-token-file", type=Path)
    parser.add_argument("--via-relay", action="store_true")
    args, rest = parser.parse_known_args(arguments)
    prefix = prefix_args.prefix.expanduser().resolve()
    command = next((value for value in rest if not value.startswith("-")), "")
    original = ["--prefix", str(prefix), *arguments]
    if not command or "--help" in rest or "-h" in rest:
        print("Usage: memory.sh enable [--endpoint HTTPS_BASE] [--prefix DIR] [--read-only | --login-url URL]")
        print("          [--app-token-file PATH | --via-relay] [--name NAME] [--client codex|config]")
        print("          [--replace --replace-mcp]")
        print("For local memory run memory.sh up, status or verify.")
        return 0
    if command not in {"enable", "connect", "setup", "install"} and (prefix / "client.py").is_file():
        return subprocess.call([sys.executable, str(prefix / "client.py"), *original])
    saved = json.loads((prefix / "config.json").read_text()) if (prefix / "config.json").exists() else {}
    endpoint = (args.endpoint or saved.get("endpoint") or "").rstrip("/")
    url = urlsplit(endpoint)
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError("Set RELAX_MEMORY_COWORK_ENDPOINT or --endpoint to the Cowork HTTPS application base")
    git_markers = (parent / ".git" for parent in (prefix, *prefix.parents))
    if any(marker.is_file() or (marker / "HEAD").is_file() for marker in git_markers):
        raise ValueError("Choose an installation directory outside Git")
    if (
        command in {"enable", "connect", "install", "setup"}
        and "--endpoint" not in original
        and not any(x.startswith("--endpoint=") for x in original)
    ):
        original = [*original, "--endpoint", endpoint]
    if all(
        (prefix / name).is_file() and hashlib.sha256((prefix / name).read_bytes()).hexdigest() == digest
        for name, digest in FILES.items()
    ):
        return subprocess.call([sys.executable, str(prefix / "client.py"), *original])
    supplied = args.app_token_file
    if not supplied and endpoint == saved.get("endpoint"):
        existing = prefix / "cowork-app-token"
        if existing.is_file():
            supplied = existing
    with tempfile.TemporaryDirectory(prefix="relax-memory-install-") as directory:
        stage = Path(directory)
        headers = {"Content-Type": "application/json"}
        if not args.via_relay:
            if supplied is None:
                if not sys.stdin.isatty():
                    raise ValueError("Supply --app-token-file for noninteractive installation")
                with warnings.catch_warnings():
                    warnings.simplefilter("error", getpass.GetPassWarning)
                    value = getpass.getpass("Cowork platform Token or file path (hidden): ").strip()
                if value.startswith(("/", "~/", "./", "../")):
                    supplied = Path(value).expanduser()
                else:
                    supplied = stage / "app-token"
                    supplied.write_text(value)
                    supplied.chmod(0o600)
            headers["App-Api-Token"] = supplied.expanduser().read_text().strip()
            if args.app_token_file is None and command in {"enable", "install", "connect", "setup"}:
                original = [*original, "--app-token-file", str(supplied)]
        req = Request(endpoint + "/api/network/client-bundle", data=b'{"bundle_version":2}', headers=headers)
        with build_opener(NoRedirect()).open(req, timeout=30) as response:
            raw = response.read(256 * 1024 + 1)
        if len(raw) > 256 * 1024:
            raise ValueError("Cowork client release is too large")
        package = json.loads(raw)
        if not isinstance(package, dict) or set(package) != set(FILES):
            raise ValueError("Unexpected Cowork client release")
        for name, digest in FILES.items():
            if not isinstance(package[name], str) or hashlib.sha256(package[name].encode()).hexdigest() != digest:
                raise ValueError("Cowork client version differs from this Relax release")
            (stage / name).write_bytes(package[name].encode())
        return subprocess.call([sys.executable, str(stage / "client.py"), *original])


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except HTTPError as exc:
        sys.exit(f"Cowork client download failed (HTTP {exc.code})")
    except (OSError, ValueError, getpass.GetPassWarning) as exc:
        sys.exit(
            str(exc)
            if type(exc) is ValueError
            else "Cannot load Cowork client; check the endpoint and credential file"
        )
