# Copyright (c) 2026 Relax Authors. All Rights Reserved.

"""Small HTTP client with no ML or optional service dependencies."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def post_json(url: str, payload: dict[str, Any], authorization: str = "", timeout: float = 30) -> dict[str, Any]:
    """Do not forward credentials across redirects or expose response bodies on
    error."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("Expected an HTTP(S) URL without embedded credentials")
    headers = {"Content-Type": "application/json"}
    if authorization:
        headers["Authorization"] = authorization
    request = Request(url, data=json.dumps(payload, allow_nan=False).encode(), headers=headers, method="POST")
    try:
        with build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError("Response exceeds 4 MiB")
        value = json.loads(raw)
    except HTTPError as exc:
        raise RuntimeError(f"Memory HTTP request failed with status {exc.code}") from None
    except (URLError, TimeoutError, OSError):
        raise RuntimeError("Memory HTTP connection failed or timed out") from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("Memory endpoint returned invalid JSON") from None
    if not isinstance(value, dict):
        raise ValueError("Memory endpoint must return a JSON object")
    return value


class MemoryClient:
    """Use a bound agent token for tools, an administrator token for review
    operations."""

    def __init__(self, endpoint: str, token: str, timeout: float = 30):
        self.endpoint = endpoint.rstrip("/")
        self.token = token
        self.timeout = timeout

    def call(self, action: str, **arguments: Any) -> Any:
        response = post_json(
            self.endpoint + "/v1/memory",
            {"action": action, "arguments": arguments},
            authorization="Bearer " + self.token,
            timeout=self.timeout,
        )
        if "result" not in response:
            raise ValueError("Malformed Memory response")
        return response["result"]

    def search(self, query: str, max_bytes: int = 8192, limit: int = 5) -> dict[str, Any]:
        return self.call("memory_search", query=query, max_bytes=max_bytes, limit=limit)

    def propose(self, record: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        return self.call("memory_propose", record=record, idempotency_key=idempotency_key)

    def replay(self, receipt_id: str) -> dict[str, Any]:
        return self.call("memory_replay", receipt_id=receipt_id)


class LocalMemoryClient:
    """Single-user local transport; filesystem access is a trusted boundary."""

    def __init__(self, database: str | Path, token: str):
        self.database = Path(database)
        self.token = token

    def call(self, action: str, **arguments: Any) -> Any:
        from relax.memory.server import dispatch
        from relax.memory.store import MemoryStore

        if not self.database.is_file():
            raise ValueError("Initialize the local memory database first")
        with MemoryStore(self.database) as store:
            try:
                return dispatch(store, store.authenticate(self.token), action, arguments)
            except PermissionError:
                raise RuntimeError("Memory action forbidden") from None
