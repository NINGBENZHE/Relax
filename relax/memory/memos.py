# Copyright (c) 2026 Relax Authors. All Rights Reserved.

"""MemOS product API adapter: external results are candidates, never trusted
records."""

from __future__ import annotations

from typing import Any

from relax.memory.client import post_json
from relax.memory.store import digest, encode


MEMOS_REVISION = "d326a6419467c2205041b58533b0ebfdf4f38173"


class MemOSClient:
    """One configured user/cube binding. Caller must supply authorized
    bindings.

    This is the self-hosted /product API, not the hosted /api/openmem/v1 API.
    MemOS session_id is not an isolation boundary. The endpoint stays private.
    """

    def __init__(self, endpoint: str, user_id: str, cube_id: str, authorization: str = "", timeout: float = 60):
        self.endpoint = endpoint.rstrip("/")
        self.user_id, self.cube_id = user_id, cube_id
        self.authorization, self.timeout = authorization, timeout
        if not user_id or not cube_id:
            raise ValueError("An explicit user_id and cube_id are required")

    def request(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = post_json(self.endpoint + "/product/" + path, payload, self.authorization, self.timeout)
        if result.get("code") != 200:
            raise ValueError("MemOS returned an unsuccessful application response")
        return result

    def create_cube(self) -> dict[str, Any]:
        return self.request(
            "create_cube", {"cube_name": self.cube_id, "owner_id": self.user_id, "cube_id": self.cube_id}
        )

    def add(self, text: str, mapping: dict[str, Any] | None = None) -> dict[str, Any]:
        """Do not automatically retry writes: upstream has no proven
        idempotency contract."""
        return self.request(
            "add",
            {
                "user_id": self.user_id,
                "writable_cube_ids": [self.cube_id],
                "messages": [{"role": "user", "content": text}],
                "async_mode": "sync",
                "mode": "fast",
                "info": mapping or {},
                "chat_history": [],
            },
        )

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        if not query or type(limit) is not int or not 1 <= limit <= 20:
            raise ValueError("Nonempty query and limit in [1, 20] required")
        result = self.request(
            "search",
            {
                "query": query,
                "user_id": self.user_id,
                "readable_cube_ids": [self.cube_id],
                "top_k": limit,
                "mode": "fast",
                "dedup": "no",
                "relativity": 0,
                "rerank": False,
                "include_preference": False,
                "pref_top_k": 0,
                "search_tool_memory": False,
                "tool_mem_top_k": 0,
                "include_skill_memory": False,
                "skill_mem_top_k": 0,
                "internet_search": False,
            },
        )
        data = result.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("text_mem"), list):
            raise ValueError("Unsupported MemOS search response")
        candidates = []
        for bucket in data["text_mem"]:
            if not isinstance(bucket, dict) or bucket.get("cube_id") != self.cube_id:
                raise ValueError("MemOS returned a foreign or unscoped cube")
            if not isinstance(bucket.get("memories"), list):
                raise ValueError("Malformed MemOS memory bucket")
            for item in bucket["memories"]:
                if not isinstance(item, dict) or not isinstance(item.get("memory"), str) or not item.get("id"):
                    raise ValueError("Malformed MemOS memory entry")
                metadata = item.get("metadata", {})
                if not isinstance(metadata, dict) or not isinstance(metadata.get("info", {}), dict):
                    raise ValueError("Malformed MemOS metadata")
                text = item["memory"]
                source = {
                    "cube_id": self.cube_id,
                    "memory_id": item["id"],
                    "version": metadata.get("version"),
                    "info": metadata.get("info", {}),
                    "content_sha256": digest(text),
                }
                candidates.append(
                    {
                        "schema_version": "1.0",
                        "kind": "episode",
                        "domain": "knowledge",
                        "subtype": "memos_import",
                        "title": "Imported MemOS knowledge",
                        "summary": text[:240],
                        "content": {"text": text, "source": source},
                        "evidence": [{"evidence_id": "memos:" + digest(encode(source)), "type": "external_memory"}],
                    }
                )
        return candidates[:limit]
