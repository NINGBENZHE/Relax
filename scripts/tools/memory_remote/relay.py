#!/usr/bin/env python3
# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Private-network relay.

The platform credential stays on this server.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request

from bridge import Client


ROUTES = {"/api/network/agent", "/api/network/device/start", "/api/network/device/token"}


class Relay(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], endpoint: str, token: str) -> None:
        # Reuse strict HTTPS validation and the no-redirect transport.
        self.upstream = Client(endpoint, "", token, "relay", public=True)
        self.base = endpoint.rstrip("/")
        self.token = token
        self.slots = threading.BoundedSemaphore(16)
        self.rate_lock = threading.Lock()
        self.rates: dict[str, tuple[float, int]] = {}
        super().__init__(address, Handler)

    def process_request(self, request: Any, address: tuple[str, int]) -> None:
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request: Any, address: tuple[str, int]) -> None:
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()

    def allow(self, host: str) -> bool:
        with self.rate_lock:
            now = time.monotonic()
            self.rates = {key: value for key, value in self.rates.items() if now - value[0] < 60}
            since, count = self.rates.get(host, (now, 0))
            if count >= 120 or (host not in self.rates and len(self.rates) >= 4096):
                return False
            self.rates[host] = (since, count + 1)
            return True


class Handler(BaseHTTPRequestHandler):
    server: Relay

    def setup(self) -> None:
        self.request.settimeout(35)
        super().setup()

    def log_message(self, format: str, *args: Any) -> None:
        # Never log authorization, device secrets, request bodies, or URLs.
        pass

    def reply(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path not in ROUTES:
            self.reply(404, b'{"error":"Route not available"}')
            return
        if not self.server.allow(self.client_address[0]):
            self.reply(429, b'{"error":"Rate limit exceeded"}')
            return
        try:
            lengths = self.headers.get_all("Content-Length", [])
            if len(lengths) != 1 or self.headers.get("Transfer-Encoding"):
                raise ValueError
            length = int(lengths[0])
            if not 0 < length <= 65536 or self.headers.get_content_type() != "application/json":
                raise ValueError
            raw = self.rfile.read(length)
            if len(raw) != length or not isinstance(json.loads(raw), dict):
                raise ValueError
        except (ValueError, OSError):
            self.reply(400, b'{"error":"Invalid JSON request"}')
            return
        # Never forward cookies, SSO identity headers, forwarding headers, or a
        # caller-supplied platform token. This relay cannot access admin routes.
        headers = {"Content-Type": "application/json", "App-Api-Token": self.server.token}
        if self.headers.get("Authorization"):
            headers["Authorization"] = self.headers["Authorization"]
        request = Request(self.server.base + self.path, data=raw, headers=headers, method="POST")
        try:
            with self.server.upstream.opener.open(request, timeout=30) as response:
                body = response.read(5 * 1024 * 1024 + 1)
                if len(body) > 5 * 1024 * 1024 or not isinstance(json.loads(body), dict):
                    raise ValueError
            self.reply(200, body)
        except HTTPError as exc:
            # Do not relay gateway HTML, redirects, or sensitive diagnostic bodies.
            status = exc.code if exc.code in {400, 401, 403, 404, 409, 413, 415, 429, 503} else 502
            self.reply(status, json.dumps({"error": "Upstream request rejected", "status": status}).encode())
        except (URLError, OSError, ValueError):
            self.reply(502, b'{"error":"Upstream unavailable; reuse submission idempotency key"}')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="127.0.0.1", help="Loopback or a specific private IPv4; never 0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--endpoint", required=True, help="Existing Cowork machine HTTPS base URL")
    parser.add_argument("--app-token-file", type=Path, required=True)
    parser.add_argument("--cert-file", type=Path)
    parser.add_argument("--key-file", type=Path)
    args = parser.parse_args()
    address = ipaddress.IPv4Address(args.bind)
    first, second, _, _ = address.packed
    # RFC1918 prefixes, expressed as octets (not deployment-specific addresses).
    private = first == 10 or (first == 172 and 16 <= second <= 31) or (first == 192 and second == 168)
    if not address.is_loopback and not private:
        parser.error("Bind only to loopback or an explicit RFC1918 IPv4 address")
    if bool(args.cert_file) != bool(args.key_file) or (not address.is_loopback and not args.cert_file):
        parser.error("Non-loopback listeners require a trusted TLS certificate and private key")
    token = args.app_token_file.read_text().strip()
    if not token:
        parser.error("Platform credential file is empty")
    with Relay((args.bind, args.port), args.endpoint, token) as server:
        if args.cert_file:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(args.cert_file, args.key_file)
            server.socket = context.wrap_socket(server.socket, server_side=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
