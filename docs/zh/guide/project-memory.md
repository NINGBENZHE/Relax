# 项目记忆

Relax 用项目记忆保存可复用的模型配置、排障经验和开发流程。使用 Cowork 与团队共享，经管理员审核后供后续任务检索。个人实验和离线场景可在本机运行。两种方式可以同时注册到 Codex，数据、凭证和审批各自独立，分享本地经验需要显式提交。

| 能力 | Cowork 团队中心 | 本地记忆 |
| --- | --- | --- |
| 运行方式 | 独立 stdio MCP 客户端连接已有 HTTPS 中心 | stdio MCP 通过本机 HTTP 网关或直接访问 SQLite |
| 凭证 | 直连需要获授权的应用 Token，可上报模式另需个人凭证 | 管理员凭证用于审核，Agent 凭证绑定命名空间、任务和快照 |
| 读取 | 只读模式查看当前已批准且未到期的词条。个人任务读取固定快照 | 每个任务读取绑定时创建的固定快照 |
| 候选格式 | `memory_propose(body, idempotency_key)` | `memory_propose(record, idempotency_key)` |

运行安装命令需要 Bash、Python 3.10+ 和包含记忆功能的 Relax checkout，自动注册需要 Codex CLI。两种方式都无需 GPU、Ray、Docker 或模型服务。

## 接入 Cowork

从管理员处获取机器 HTTPS 根地址，设为 `RELAX_MEMORY_ENDPOINT`，不要附加 `/api/agent` 或 `/api/network/agent`。需要设备授权时，将可在浏览器登录的 MiniApp 根地址设为 `RELAX_MEMORY_LOGIN_URL`。机器地址与网页登录地址可能不同，终端匿名访问机器地址返回 401 时，请用管理员给出的浏览器入口。

### 只读

```bash
MEMORY_PYTHON=python3 bash scripts/tools/memory.sh remote connect \
  --endpoint "$RELAX_MEMORY_ENDPOINT" --read-only
```

按隐藏提示提供获授权的应用 Token 或文件路径，也可用 `--app-token-file` 指定文件。安装器检查连接并注册 `relax-memory`，新开会话后可使用 `memory_search` 和 `memory_get`。只读安装无需个人凭证。

### 可上报

```bash
MEMORY_PYTHON=python3 bash scripts/tools/memory.sh remote connect \
  --endpoint "$RELAX_MEMORY_ENDPOINT" --login-url "$RELAX_MEMORY_LOGIN_URL"
```

先提供应用 Token，再在浏览器打开终端输出的 `registration_url`，登录并确认设备。保持安装进程运行，管理员批准后，安装器会领取个人凭证、检查连接并注册 MCP。设备申请等待窗口为 15 分钟。已有个人凭证可用 `remote setup --client codex`，也可以通过 `--credential-file` 和 `--app-token-file` 从文件读取两项凭证。

客户端默认安装到 `${XDG_DATA_HOME:-$HOME/.local/share}/relax-memory-remote`，安装后可脱离 checkout 运行。用 `remote --prefix <目录> connect ...` 自定义位置，目录应在仓库外。其他 stdio MCP 客户端可用 `--client config` 输出配置片段。

升级只读安装或替换已有配置时，用 `--replace --replace-mcp` 更新同一目录和注册。安装器只对相同 endpoint 复用已保存的应用 Token。管理员提供已有内网 relay 时使用 `--via-relay`，此模式由 relay 持有应用 Token。若领取个人凭证后连通检查失败，可用安装后的 `check` 重试，再执行 `register-codex`。

## 启动本地记忆

从仓库根目录在终端 A 运行。状态目录应位于仓库外的个人持久化存储中。

```bash
export RELAX_MEMORY_STATE="${XDG_STATE_HOME:-$HOME/.local/state}/relax-memory"
export RELAX_MEMORY_HOST=127.0.0.1
export RELAX_MEMORY_PORT=8765
export RELAX_MEMORY_ENDPOINT="http://127.0.0.1:$RELAX_MEMORY_PORT"
MEMORY_PYTHON=python3 bash scripts/tools/memory.sh up
```

网关在前台运行，按 Ctrl-C 停止，状态保留。端口占用时可调整 `RELAX_MEMORY_PORT` 和 `RELAX_MEMORY_ENDPOINT`。在终端 B 设置相同的状态目录和本地地址，然后创建任务并注册 MCP。

```bash
MEMORY_PYTHON=python3 bash scripts/tools/memory.sh status
python3 -m relax.memory project \
  --endpoint "$RELAX_MEMORY_ENDPOINT" \
  --token-file "$RELAX_MEMORY_STATE/admin.json" \
  --namespace personal/dev/relax --session task-001 \
  --output-dir "$RELAX_MEMORY_STATE/tasks/task-001"
codex mcp add relax-memory-local --env "PYTHONPATH=$PWD" -- \
  "$(command -v python3)" -m relax.memory mcp \
  --endpoint "$RELAX_MEMORY_ENDPOINT" \
  --token-file "$RELAX_MEMORY_STATE/tasks/task-001/agent.json"
```

命令在任务目录写入 `agent.json` 和其他 stdio MCP 客户端可导入的 `mcp.json`。保留 `admin.json` 给管理员，向 Agent 只提供任务凭证。新开会话后使用 `relax-memory-local`。初次绑定的空库返回空结果是正常的。

完成绑定后，也可将 MCP 注册为下面的直接读取命令，并保留仓库对应的 `PYTHONPATH`。此时可关闭网关。新建任务绑定与管理员审核仍通过 HTTP 完成。

```bash
python3 -m relax.memory mcp \
  --state-dir "$RELAX_MEMORY_STATE" \
  --token-file "$RELAX_MEMORY_STATE/tasks/task-001/agent.json"
```

### 可选的本地网页 Demo

Linux 上可以用独立的网页 Demo 录入、审批和预览词条。运行 `up` 后打开返回的浏览器链接，需要查看地址时运行 `status`，结束后用 `down` 停止。

```bash
python3 examples/memory/center_demo.py up
python3 examples/memory/center_demo.py status
python3 examples/memory/center_demo.py down
```

Demo 默认使用端口 8766 和 `~/.local/state/relax-memory-center`，用独立的数据库和单个管理密钥。返回的链接带管理能力，应私密保存。提交后在审批工作台查看，审核通过后可通过 Agent 读取预览查看新快照。首次启动的种子词条用于演示。备份时停止对应服务后复制完整 SQLite 状态目录，或使用 SQLite backup API。

## 检索、上报与审核

任务开始时可让 Agent 按模型、模块或症状检索，按 ID 展开相关内容，并核对当前代码、版本和适用条件。MCP 的 `max_bytes` 控制返回字节数。具有写权限的客户端可用 `memory_propose` 上报候选，也可按读取回执用 `memory_feedback` 标记有用、过时或错误。反馈不会直接修改词条。

Cowork 的已安装客户端也可直接调用。自定义安装目录时使用安装器输出的路径。

```bash
MEMORY="${XDG_DATA_HOME:-$HOME/.local/share}/relax-memory-remote/relax-memory"
"$MEMORY" check
"$MEMORY" search 'Qwen3.5 OOM' --limit 5
"$MEMORY" get '<memory-id>'
"$MEMORY" propose --body-file ./candidate.json --idempotency-key 'issue-123-oom-v1'
"$MEMORY" feedback '<receipt-id>' helpful
```

一条候选聚焦一个可复用问题，正文写明触发场景、操作、验证方法和限制，来源引用实际代码版本、文档或实验。Cowork 的 `candidate.json` 格式如下，实际提交时替换示例内容。

```json
{
  "title": "Qwen3.5 的 log-probs 显存排查",
  "summary": "先定位 OOM 阶段，再调整对应的 token 预算。",
  "content": "触发：train_log_probs 阶段 OOM。操作：降低 log-probs token 预算。验证：同输入复测峰值与耗时。限制：只覆盖该阶段。",
  "source": "Relax@<commit>; docs/zh/guide/oom-troubleshooting.md",
  "owner": "<维护负责人>",
  "kind": "strategy",
  "evidence_level": "documented",
  "topic": "diagnosis/oom",
  "tags": ["Qwen3.5", "OOM"],
  "conditions": "Megatron 训练路径，需在目标硬件复测。",
  "review_after": null,
  "expires_at": null
}
```

必填字段为 `title`、`summary`、`content`、`source`、`owner`、`kind` 和 `evidence_level`。`kind` 为 `strategy`、`lesson` 或 `episode`。`evidence_level` 区分文档依据（`documented`）、实际测试（`tested`）和待验证假设（`hypothesis`）。日期填写带时区的 ISO8601 或 `null`。复核日是检查提醒，有效期决定还能否进入新快照。相同内容网络重试时复用原幂等键。

Cowork 返回 `pending` 和候选 ID 后，由中心管理员审核。个人 MCP 进程首次调用时取得任务快照，审批后重启 MCP 进程或新开会话以读取更新。只读模式读取中心的当前已批准内容。

本地上报使用 `record`，结构见[本地候选示例](../../../examples/memory/knowledge.json)。管理员检查证据后执行 `candidate_list` 和 `candidate_commit`，详细命令见[本地运维参考](../../../skills/memory/references/operations.md#add-and-review-knowledge)。审核后用新的 session 和目录创建任务绑定，并更新 MCP 凭证路径。普通修订和到期不会改写旧快照。需要分享本地经验时，将其转换为 Cowork 的候选格式并重新审核。

## 排障

| 现象 | 检查方法 |
| --- | --- |
| Cowork 返回 401 或 403 | 核对机器地址、应用 Token、个人凭证到期状态和成员权限，用已安装客户端的 `check` 验证 |
| 本地网关连不上 | 核对 `status`、端口以及 `RELAX_MEMORY_ENDPOINT` 是否仍指向本机 |
| 已批准却搜不到 | 检查当前快照、关键词、有效期和字节预算。个人任务需要刷新绑定或 MCP 进程 |
| 找不到 MCP 或提示同名 | 新开会话检查注册。使用不同名称区分本地和 Cowork，更新同名配置时显式替换 |
| 本地网页打不开 | 查看对应状态目录的 `status` 和 `server.log`，在容器中按需转发 loopback 端口 |

本地网关、网页 Demo 和性能示例默认使用独立数据库。MemOS 导入导出是可选的自托管适配，详见[本地运维参考](../../../skills/memory/references/operations.md)。
