# 远程项目记忆：安装后连接共享中心

这套入口连接已经部署的记忆中心，不启动本地数据库或训练服务。Linux/macOS
有 Python 3.10+、能访问目标 HTTPS 网络并持有有效凭证即可使用；不需要安装
PyTorch、Ray 或 Relax 的训练依赖。Windows 可使用 WSL。

## 一次安装

从含本功能的 Relax checkout 根目录执行：

```bash
# 由管理员提供部署后的 HTTPS 服务地址（不含 /api/agent）。
export RELAX_MEMORY_ENDPOINT="https://memory.example.com/s/your-project"
# 凭证文件通过管理员/密钥管理系统安全交付，不从 Git 获取。
# agent.json 是 MiniApp 签发的项目凭证；cowork-app-token 是平台 Token 原文。
# 以下 /secure 路径按本机实际位置替换。
MEMORY_PYTHON=python3 bash scripts/tools/memory.sh remote install \
  --endpoint "$RELAX_MEMORY_ENDPOINT" \
  --credential-file /secure/agent.json \
  --app-token-file /secure/cowork-app-token

MEMORY="$HOME/.local/share/relax-memory-remote/relax-memory"
"$MEMORY" check
"$MEMORY" register-codex
```

默认安装在 `$XDG_DATA_HOME/relax-memory-remote`，未设置 XDG 时为
`~/.local/share/relax-memory-remote`。安装目录权限 700，凭证权限 600。
安装会复制独立客户端；之后不依赖 checkout 或当前工作目录，可以移除源码副本。
不要求把安装目录加入 PATH，直接使用输出的绝对命令路径。

QS 等短生命周期容器应使用个人持久化挂载，**不要安装到团队共享仓库**：

```bash
MEMORY_PYTHON=python3 bash scripts/tools/memory.sh remote \
  --prefix /your/private/persistent/relax-memory install \
  --endpoint "$RELAX_MEMORY_ENDPOINT" \
  --credential-file /secure/agent.json \
  --app-token-file /secure/cowork-app-token
```

`--prefix` 放在子命令之前。命令不会把密钥写入 MCP 配置或命令行；只记录文件路径。
不要复用个人凭证给所有人：按成员/设备分别签发项目凭证，以便审计、撤销和轮换。
网络可达不代表自动有权限；过期或撤销的凭证需要换发，CLI 不会绕过认证。
同一机器有多个项目时使用不同 prefix 和 MCP 名称。

## MCP 客户端

Codex 的 `register-codex` 只添加指定名称的条目，保留其他 MCP 配置；已有同名条目时
默认拒绝覆盖。使用其他名称，或明确指定 `--replace` 更新该条目：

```bash
"$MEMORY" register-codex --name relax-project-memory
# 明确替换同名配置时才使用：
"$MEMORY" register-codex --replace
```

新开 Codex 会话加载配置。其他支持 stdio MCP 的客户端使用：

```bash
"$MEMORY" mcp-config --name relax-memory
```

将输出的 `mcpServers` 条目合并到客户端配置，不要覆盖整个现有配置。
命令实际启动 `relax-memory mcp`；当前不是原生 Streamable HTTP MCP 服务。
四个工具是 `memory_search`、`memory_get`、`memory_propose`、`memory_feedback`。
例如让 Agent：“先通过 relax-memory 搜索相关经验；完成工作后，把有证据且可复用的
结论作为候选上报，等我审核。”注册 MCP 不等于每次任务自动上传全部对话。

## 不经过模型也能读取和上报

```bash
"$MEMORY" search 'checkpoint 恢复' --limit 5
"$MEMORY" get '<memory-id>'
"$MEMORY" propose --body-file /path/candidate.json \
  --idempotency-key 'issue-123-checkpoint-fix-v1'
"$MEMORY" feedback '<receipt-id>' helpful
```

`candidate.json` 示例（请替换为真实经验和证据，不直接导入示例）：

```json
{
  "title": "具体问题与可复用解决办法",
  "summary": "一句话说明问题与适用场景",
  "content": "观察、根因、解决步骤、验证结果及未验证的边界",
  "source": "可追溯的 PR、日志或实验记录 URL",
  "owner": "记录负责人",
  "kind": "lesson",
  "evidence_level": "documented",
  "conditions": "代码版本、环境及适用限制",
  "tags": ["checkpoint"],
  "expires_at": null,
  "review_after": null
}
```

`kind` 支持 strategy/lesson/episode；`evidence_level` 支持 documented/tested/hypothesis。
只有真实测试支持的结论才标 tested。不要把审批日志、安装验收、凭证、无关对话或整段日志
当成项目知识自动入库。审批记录由服务端保存为审计轨迹。

上报返回 `pending` 和 `committed:false`。管理员在 MiniApp 审批前，所有新的 MCP
快照也不能检索该候选。相同内容重试必须复用同一个幂等键；同键改内容会被拒绝。
不要在网络错误后换新键重试，否则可能创建重复候选。

## 审批与快照

```text
Agent / CLI 提交候选 → MiniApp 管理员审批 → 新任务 MCP 检索与读取
```

Agent 凭证没有审批能力。每个 MCP 进程第一次调用工具时创建一个任务快照，进程内
读取保持一致；审批后**新开会话/重新启动 MCP 进程**才能读到新知识。CLI 每次调用默认
创建新任务，因此批准后的下一次普通 `search` 就能看到它。

需要恢复任务时显式传 `--task-id <原任务ID>`；它会复用旧快照，不能把同一个固定 task-id
当作所有任务的默认值。旧快照不会随修订、失效或后续审批改变。反馈只记录，不修改知识。

## 更新、轮换与恢复

用新的凭证文件重复 install 并加 `--replace`，原子替换每个配置文件。为避免轮换过程中
新旧凭证混用，先结束使用这个安装目录的 MCP 进程，更新后再启动。仅换项目凭证时仍提供
当前平台 Token 文件。升级源码同样重复 install；`--replace` 明确授权更新该 prefix。
不要直接移动已安装目录或 Python 解释器；换机器/换目录应重新安装生成本机启动器。

安装不自动修改全局 Agent 规则、训练脚本、模型配置，也不启动后台常驻服务。
容器重建后若持久化目录和 Python 路径仍有效，重新 `register-codex` 即可；否则重新安装。

- `check`：真实调用机器鉴权和任务快照接口；健康检查成功不能替代它。
- HTTP 401：检查两个凭证、到期/撤销状态、devops 域名及平台 Token 开通状态。
- HTTP 403：检查成员启用状态、角色与操作权限。
- 网络失败：核对公司网络、DNS、代理与证书信任；不要关闭 TLS 验证。
- 输出中的 receipt_id/snapshot_id 可追溯读取；它们不是访问凭证。

本入口与原 `memory.sh up` 的本地 SQLite 服务是不同后端，不自动迁移或上传本地私有记忆。
