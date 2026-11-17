# Copyright (c) 2026 Relax Authors. All Rights Reserved.

"""MemOS product protocol tests using HTTP fixtures, not a real MemOS
deployment."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from relax.memory.memos import MemOSClient


@pytest.fixture
def upstream():
    state = {
        "calls": [],
        "response": {
            "code": 200,
            "data": {
                "text_mem": [
                    {
                        "cube_id": "cube-a",
                        "memories": [
                            {
                                "id": "m1",
                                "memory": "A verified workflow",
                                "metadata": {"version": 2, "info": {"relax_memory_id": "r1"}},
                            }
                        ],
                    }
                ]
            },
        },
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            state["calls"].append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            data = json.dumps(state["response"]).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    yield MemOSClient(f"http://127.0.0.1:{server.server_port}", "user", "cube-a"), state
    server.shutdown()
    server.server_close()
    worker.join(timeout=5)


def test_memos_nested_metadata_and_explicit_cube_binding(upstream):
    client, state = upstream
    candidates = client.search("workflow")
    assert candidates[0]["content"]["source"]["info"]["relax_memory_id"] == "r1"
    assert "verification" not in candidates[0]
    path, payload = state["calls"][0]
    assert path == "/product/search"
    assert payload["readable_cube_ids"] == ["cube-a"]
    assert (
        not payload["include_preference"] and not payload["search_tool_memory"] and not payload["include_skill_memory"]
    )
    assert "session_id" not in payload
    client.add("record", {"relax_memory_id": "r1"})
    assert state["calls"][1][1]["async_mode"] == "sync"
    assert state["calls"][1][1]["info"] == {"relax_memory_id": "r1"}


@pytest.mark.parametrize(
    "response",
    [
        {"code": 500, "data": {}},
        {"code": 200, "data": {"text_mem": [{"cube_id": "other", "memories": []}]}},
        {"code": 200, "data": {"text_mem": [{"memories": []}]}},
        {"code": 200, "data": []},
    ],
)
def test_memos_rejects_foreign_cubes_and_malformed_responses(upstream, response):
    client, state = upstream
    state["response"] = response
    with pytest.raises(ValueError):
        client.search("workflow")
