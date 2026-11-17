# Copyright (c) 2026 Relax Authors. All Rights Reserved.
"""Single-operator memory center demo, with persistent review and lifecycle
history."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from relax.memory.store import MemoryStore, digest, encode, now


SPACE = "center/demo"
ASSET = Path(__file__).with_name("center.html")


def date_value(value: Any) -> str | None:
    if not value:
        return None
    date = datetime.fromisoformat(value)
    if date.tzinfo is None:
        raise ValueError("日期必须包含时区")
    return date.astimezone(timezone.utc).isoformat()


class Center:
    """Demo workflow over a dedicated store; one authenticated operator, no SSO
    roles."""

    def __init__(self, state: Path):
        state.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.database = state / "memory.sqlite"
        self.lock = threading.RLock()
        with MemoryStore(self.database) as store:
            store.db.executescript("""
                CREATE TABLE IF NOT EXISTS center_entries (
                    id TEXT PRIMARY KEY, body TEXT NOT NULL, state TEXT NOT NULL,
                    version INTEGER NOT NULL, candidate TEXT, core_id TEXT, core_revision INTEGER,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS center_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, entry_id TEXT NOT NULL,
                    action TEXT NOT NULL, actor TEXT NOT NULL, note TEXT NOT NULL,
                    at TEXT NOT NULL, body TEXT NOT NULL);
            """)

    def event(self, store: MemoryStore, entry: str, action: str, actor: str, note: str, body: Any) -> None:
        store.db.execute(
            "INSERT INTO center_events(entry_id,action,actor,note,at,body) VALUES(?,?,?,?,?,?)",
            (entry, action, actor, note, now(), encode(body)),
        )

    def normalize(self, payload: dict[str, Any]) -> dict[str, Any]:
        fields = {
            "title",
            "summary",
            "kind",
            "topic",
            "tags",
            "conditions",
            "content",
            "source",
            "evidence_level",
            "owner",
            "expires_at",
            "review_after",
        }
        if set(payload) - fields:
            raise ValueError("未知词条字段")
        result = {key: str(payload.get(key, "")).strip() for key in fields - {"tags", "expires_at", "review_after"}}
        for key in ("title", "summary", "content", "source", "owner"):
            if not result[key]:
                raise ValueError("标题、摘要、正文、来源和负责人不能为空")
        if result["kind"] not in {"strategy", "lesson", "episode"}:
            raise ValueError("无效记忆类型")
        if result["evidence_level"] not in {"documented", "tested", "hypothesis"}:
            raise ValueError("无效证据等级")
        tags = payload.get("tags", [])
        if (
            not isinstance(tags, list)
            or len(tags) > 12
            or any(not isinstance(tag, str) or len(tag) > 50 for tag in tags)
        ):
            raise ValueError("最多12个标签，每个50字符")
        result["tags"] = list(dict.fromkeys(tag.strip() for tag in tags if tag.strip()))
        for key in ("expires_at", "review_after"):
            result[key] = date_value(payload.get(key))
        if result["expires_at"] and result["review_after"] and result["review_after"] > result["expires_at"]:
            raise ValueError("复核时间不能晚于失效时间")
        if len(encode(result).encode()) > 48000 or len(result["title"]) > 200:
            raise ValueError("词条过长（标题200字符，整条48KB）")
        return result

    def record(self, body: dict[str, Any], entry_id: str) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "kind": body["kind"],
            "domain": body["topic"] or "project",
            "subtype": "center_entry",
            "title": body["title"],
            "summary": body["summary"],
            "content": {
                "text": body["content"],
                "conditions": body["conditions"],
                "tags": body["tags"],
                "evidence_level": body["evidence_level"],
            },
            "evidence": [{"evidence_id": "center-source:" + digest(body["source"]), "reference": body["source"]}],
            "extensions": {"center": {"entry_id": entry_id, "owner": body["owner"]}},
        }

    def sweep(self, store: MemoryStore) -> int:
        timestamp = now()
        expired = []
        for row in store.db.execute("SELECT * FROM center_entries WHERE state='active'").fetchall():
            body = json.loads(row["body"])
            if body["expires_at"] and body["expires_at"] <= timestamp:
                expired.append((row, body))
        for row, body in expired:
            # Core snapshot creation independently filters TTL, even between sweeps.
            core = store.expire(SPACE, row["core_id"], row["core_revision"])
            with store.transaction():
                store.db.execute(
                    "UPDATE center_entries SET state='expired',version=version+1,core_revision=?,updated_at=? WHERE id=?",
                    (core["revision"], timestamp, row["id"]),
                )
                self.event(store, row["id"], "auto_expire", "系统", "有效期已到；新任务不再读取，旧快照保留", body)
        return len(expired)

    def list(self) -> dict[str, Any]:
        with self.lock, MemoryStore(self.database) as store, store.transaction():
            self.sweep(store)
            entries = []
            for row in store.db.execute("SELECT * FROM center_entries ORDER BY updated_at DESC"):
                item = dict(row)
                item["body"] = json.loads(item["body"])
                review = item["body"]["review_after"]
                item["needs_review"] = item["state"] == "active" and bool(review and review <= now())
                entries.append(item)
            events = [dict(row) for row in store.db.execute("SELECT * FROM center_events ORDER BY seq DESC LIMIT 150")]
            for event in events:
                event["body"] = json.loads(event["body"])
            return {
                "entries": entries,
                "events": events,
                "server_time": now(),
                "namespace": SPACE,
                "mode": "single_operator_demo",
            }

    def act(self, action: str, args: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(args, dict):
            raise ValueError("操作参数必须为对象")
        actor = str(args.get("actor", "演示管理员")).strip()[:100]
        note = str(args.get("note", "")).strip()[:2000]
        if not actor:
            raise ValueError("请填写操作人")
        with self.lock, MemoryStore(self.database) as store, store.transaction():
            self.sweep(store)
            if action == "preview":
                snapshot = store.create_snapshot(SPACE)
                binding = store.bind(SPACE, snapshot["snapshot_id"], "center-preview-" + str(uuid.uuid4()))
                return store.read(
                    store.authenticate(binding["token"]), query=str(args.get("query", "")), max_bytes=65536, limit=20
                )
            if action == "submit":
                body = self.normalize(args["body"])
                entry_id, timestamp = str(uuid.uuid4()), now()
                record = self.record(body, entry_id)
                staged = store.stage(SPACE, "center:" + entry_id, "1", record)
                with store.transaction():
                    store.db.execute(
                        "INSERT INTO center_entries VALUES(?,?,?,1,?,NULL,NULL,?,?)",
                        (entry_id, encode(body), "pending", staged["candidate_id"], timestamp, timestamp),
                    )
                    self.event(store, entry_id, "submit", actor, note or "提交审核", body)
                return {"id": entry_id}
            row = store.db.execute("SELECT * FROM center_entries WHERE id=?", (args.get("id"),)).fetchone()
            if row is None:
                raise ValueError("词条不存在")
            if type(args.get("version")) is not int or args.get("version") != row["version"]:
                raise ValueError("词条已被修改，请刷新后重试")
            body = json.loads(row["body"])
            version, state = row["version"] + 1, row["state"]
            candidate_id, core_id, core_revision = row["candidate"], row["core_id"], row["core_revision"]
            if action == "approve":
                if state != "pending" or not note:
                    raise ValueError("仅待审核词条可批准，且须填写审核依据")
                if body["expires_at"] and body["expires_at"] <= now():
                    raise ValueError("有效期已过，请先修改有效期")
                record = self.record(body, row["id"])
                core = store.commit(
                    SPACE,
                    candidate_id,
                    {
                        "state": "verified",
                        "verifier_id": actor,
                        "claims": [note],
                        "evidence_ids": [item["evidence_id"] for item in record["evidence"]],
                    },
                    record_id=core_id,
                    expected_revision=core_revision,
                    expires_at=body["expires_at"],
                    review_after=body["review_after"],
                )
                core_id, core_revision, state = core["id"], core["revision"], "active"
            elif action == "reject":
                if state != "pending" or not note:
                    raise ValueError("仅待审核词条可驳回，且须填写原因")
                state = "rejected"
            elif action == "expire":
                if state != "active" or not note:
                    raise ValueError("仅生效词条可失效，且须填写原因")
                core = store.expire(SPACE, core_id, core_revision)
                core_revision, state = core["revision"], "expired"
            elif action == "revise":
                body = self.normalize(args["body"])
                # Withdraw the old version until the new content is reviewed.
                if state == "active":
                    core = store.expire(SPACE, core_id, core_revision)
                    core_revision = core["revision"]
                record = self.record(body, row["id"])
                staged = store.stage(SPACE, "center:" + row["id"], str(version), record)
                candidate_id, state = staged["candidate_id"], "pending"
                note = note or "修订后重新审核；旧版本不进入新快照"
            else:
                raise ValueError("未知操作")
            with store.transaction():
                store.db.execute(
                    "UPDATE center_entries SET body=?,state=?,version=?,candidate=?,core_id=?,core_revision=?,updated_at=? WHERE id=?",
                    (encode(body), state, version, candidate_id, core_id, core_revision, now(), row["id"]),
                )
                self.event(store, row["id"], action, actor, note, body)
            return {"id": row["id"], "state": state, "version": version}

    def seed(self) -> None:
        if self.list()["entries"]:
            return
        samples = [
            (
                "区分编译冷启动和稳态训练耗时",
                "strategy",
                "性能优化",
                "documented",
                "首步变快不等于稳态吞吐变快。对照时分别统计冷启动、缓存命中首步及稳定 step。",
                "examples/models/kimi-k3/OPTIMIZE.md",
                "active",
                30,
                14,
            ),
            (
                "长序列 Attention 优化不能直接推广到短序列",
                "lesson",
                "性能优化",
                "documented",
                "历史案例中长序列有收益，短序列局部测试略慢；核对序列分布、后端和依赖版本再做 A/B。",
                "examples/models/kimi-k3/OPTIMIZE.md",
                "active",
                60,
                -1,
            ),
            (
                "记录修复对应的代码状态和测试证据",
                "strategy",
                "Coding",
                "documented",
                "保留代码版本、实际执行命令和测试结果；跳过的测试不能算验证成功。",
                "skills/memory/SKILL.md",
                "active",
                90,
                30,
            ),
            (
                "待评审：统一记录优化实验的基线",
                "episode",
                "实验管理",
                "hypothesis",
                "演示候选：每条优化经验关联基线、变化变量、指标口径和验证范围。尚未验证流程收益。",
                "演示材料：人工录入",
                "pending",
                30,
                7,
            ),
            (
                "演示：失效配置不要进入下一任务",
                "lesson",
                "生命周期",
                "hypothesis",
                "用于展示过期流程的演示词条，不代表实际性能结论。",
                "演示材料：生命周期样例",
                "expired",
                1,
                1,
            ),
            (
                "演示：缺少证据的通用加速结论",
                "episode",
                "性能优化",
                "hypothesis",
                "只根据一次观察声称所有模型都会加速，证据不足。",
                "演示材料：驳回样例",
                "rejected",
                30,
                7,
            ),
        ]
        for title, kind, topic, level, content, source, state, ttl, review in samples:
            timestamp = datetime.now(timezone.utc)
            body = {
                "title": title,
                "summary": content,
                "kind": kind,
                "topic": topic,
                "tags": [topic, "示例"],
                "conditions": "仅在核对当前环境与证据后复用",
                "content": content,
                "source": source,
                "evidence_level": level,
                "owner": "Relax 团队",
                "expires_at": (timestamp + timedelta(days=ttl)).isoformat(),
                "review_after": (timestamp + timedelta(days=review)).isoformat(),
            }
            result = self.act("submit", {"body": body, "actor": "Demo 导入"})
            if state in {"active", "expired"}:
                self.act(
                    "approve",
                    {
                        "id": result["id"],
                        "version": 1,
                        "actor": "Demo 审核",
                        "note": "仅核对来源或演示流程；未重新验证历史性能",
                    },
                )
            if state == "expired":
                self.act("expire", {"id": result["id"], "version": 2, "note": "演示主动失效", "actor": "Demo 审核"})
            if state == "rejected":
                self.act(
                    "reject",
                    {"id": result["id"], "version": 1, "note": "缺少可比基线与适用范围", "actor": "Demo 审核"},
                )


def make_center_server(center: Center, token: str, host: str, port: int) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def send(self, status: int, value: Any, html: bool = False) -> None:
            body = value if html else encode(value).encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8" if html else "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'",
            )
            self.end_headers()
            self.wfile.write(body)

        def authorized(self) -> bool:
            origin = self.headers.get("Origin")
            if origin and urlsplit(origin).netloc != self.headers.get("Host"):
                return False
            return secrets.compare_digest(self.headers.get("Authorization", ""), "Bearer " + token)

        def do_GET(self) -> None:
            if self.path == "/":
                self.send(200, ASSET.read_bytes(), html=True)
            elif self.path == "/api/state":
                if not self.authorized():
                    self.send(403, {"error": "请使用带访问密钥的演示链接"})
                else:
                    self.send(200, center.list())
            elif self.path == "/health":
                self.send(200, {"service": "relax-memory-center"})
            else:
                self.send(404, {"error": "not_found"})

        def do_POST(self) -> None:
            if self.path != "/api/action":
                self.send(404, {"error": "not_found"})
                return
            if not self.authorized():
                self.send(403, {"error": "访问被拒绝"})
                return
            try:
                self.connection.settimeout(10)
                size = int(self.headers.get("Content-Length", 0))
                if not 0 < size <= 65536:
                    raise ValueError("请求过大或为空")
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict) or set(payload) != {"action", "args"}:
                    raise ValueError("请求必须包含 action 和 args")
                result = center.act(payload["action"], payload["args"])
                self.send(200, result)
            except (ValueError, KeyError, TypeError) as exc:
                self.send(400, {"error": str(exc)[:200]})
            except (sqlite3.Error, OSError):
                self.send(503, {"error": "存储暂时不可用，请刷新状态后重试"})

    return ThreadingHTTPServer((host, port), Handler)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--seed-demo", action="store_true")
    args = parser.parse_args()
    center = Center(args.state_dir)
    key_file = args.state_dir / "center-key"
    if not key_file.exists():
        fd = os.open(key_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(secrets.token_urlsafe(32))
    token = key_file.read_text().strip()
    if args.seed_demo:
        center.seed()
    server = make_center_server(center, token, args.host, args.port)
    (args.state_dir / "listen.json").write_text(
        encode({"port": server.server_port, "pid": os.getpid(), "host": args.host})
    )
    stop = threading.Event()

    def age() -> None:
        while not stop.wait(10):
            center.list()

    worker = threading.Thread(target=age, daemon=True)
    worker.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.server_close()
        worker.join(timeout=2)


if __name__ == "__main__":
    main()
