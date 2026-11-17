# 远程项目记忆：安装后连接共享中心

这套入口连接已经部署的记忆中心，不启动本地数据库或训练服务。Linux/macOS
有 Python 3.10+、能访问目标 HTTPS 网络并持有有效凭证即可使用；不需要安装
PyTorch、Ray 或 Relax 的训练依赖。Windows 可使用 WSL。

## 推荐：直连，平台 Token 只配置一次

Cowork 机器入口仍要求平台代理 Token；它与最长 90 天的个人设备凭证是两种凭证。
使用你获准使用的应用 Token，不要将他人的 Token 分发给同事或写入 Git、聊天、日志和命令参数。
平台 Token 持续有效期间无需每次启动重新申请；撤销或轮换后需更新本机配置。

先拉取包含本脚本的分支，在仓库根目录执行。只需 Python 3.10+；自动注册 Codex 还需 Codex CLI。
`RELAX_MEMORY_ENDPOINT` 设置为管理员提供的 Cowork 机器 HTTPS 根地址（不含 `/api/agent`）。

### 只读：无需个人 JSON

```bash
bash scripts/tools/memory.sh remote connect \
  --endpoint "$RELAX_MEMORY_ENDPOINT" --read-only
```

首次安装会隐藏输入平台代理 Token（也可输入 Token 文件绝对路径）。连通性验证成功后，
安装器将 Token 保存到仓库外的个人目录并自动注册 Codex MCP；不创建个人 `agent.json`。
MCP 仅提供 `memory_search`、`memory_get`，只能读取当前已批准且未失效的知识。
后续直接使用 MCP，不必重复执行安装或粘贴 Token。

### 上报：登录和管理员授权，自动领取个人凭证

```bash
bash scripts/tools/memory.sh remote connect \
  --endpoint "$RELAX_MEMORY_ENDPOINT" --login-url "$RELAX_MEMORY_LOGIN_URL"
```

`RELAX_MEMORY_LOGIN_URL` 是浏览器可登录的 MiniApp 根地址，可与机器地址不同；未指定时使用机器根地址。
首次隐藏输入平台 Token 后，终端显示注册链接。打开链接、公司登录、确认设备，管理员先确认
贡献者成员资格，再批准设备。保持安装进程运行；安装器自动领取并私密保存个人凭证，然后注册 MCP。
无需手填设备码、下载 JSON 或复制个人 Token。平台 Token 只发往配置的机器地址，不放入注册链接。
设备申请 15 分钟过期；个人凭证最长 90 天，可撤销；上报仍进入待审批候选，不授予机器审批权限。

已有只读安装升级为可上报时，使用相同 endpoint 加 `--replace --replace-mcp`；自动复用已保存平台 Token。
仅在 endpoint 完全相同（忽略尾部斜线）时复用，地址变化会要求重新输入，避免把 Token 发往其他服务。
显式提供 `--app-token-file /absolute/path/cowork-app-token` 可用于非交互安装或 Token 轮换；
此参数优先于已保存 Token。更新安装需 `--replace`，替换已有同名 MCP 需 `--replace-mcp`。

默认目录为 `~/.local/share/relax-memory-remote`（遵循 `XDG_DATA_HOME`），目录权限 700、凭证文件 600。
可在 `connect` 前加 `--prefix /private/absolute/path` 自定义目录。
没有 Codex CLI 时加 `--client config` 输出 MCP 配置，供其他客户端导入，保留其已有配置。
若凭证领取后网络检查失败，个人凭证已保存；运行安装目录中的 `relax-memory check` 重试，
再用 `relax-memory register-codex` 完成注册（同名替换加 `--replace`）。

## 内网免平台 Token 接入（新增）

部署模型是：设备 → 内网 HTTPS 接入服务 → 原有记忆中心。**不申请应用外发，不关闭
Cowork 的 SSO**。平台 Token 仅保存在内网服务上，新设备只会获得自己的个人凭证。
内网接入服务必须先由管理员部署；本命令不能让旧 Cowork 地址自动变成匿名入口。

管理员提供 `RELAX_MEMORY_ENDPOINT`（内网接入服务地址）和 `RELAX_MEMORY_LOGIN_URL`
（原 MiniApp 的 SSO 地址）后，新机器运行：

```bash
MEMORY_PYTHON=python3 bash scripts/tools/memory.sh remote connect --via-relay \
  --endpoint "$RELAX_MEMORY_ENDPOINT" --login-url "$RELAX_MEMORY_LOGIN_URL" --client codex
```

终端显示 `registration_url`。在任意可访问公司内网的浏览器打开该链接，登录公司账号，
核对设备名称并点击“确认这是我的设备”，无需手填设备码。管理员核对申请人及设备名称，
先授予贡献者角色，再批准设备。
终端自动领取 90 天个人凭证，保存到私有目录并注册 MCP。`connect` 默认注册 Codex，
其他 MCP 客户端可使用 `--client config` 获取配置。注册链接不包含领取凭证的设备密钥。凭证只允许读取、上报和反馈，
不含审批权限；上报仍是候选，必须另外审批才能被其他设备读取。设备码 15 分钟过期，
凭证只领取一次；领取响应丢失时重新登录，管理员可撤销此前未使用的凭证。
授权后若连通性检查失败，已领取的凭证仍保留，可用 `check` 重试。

只需要内网匿名读取时，不必登录或领取凭证：

```bash
MEMORY_PYTHON=python3 bash scripts/tools/memory.sh remote connect --via-relay \
  --endpoint "$RELAX_MEMORY_ENDPOINT" --read-only --client codex
```

匿名 MCP 只提供 search/get，读取**当前**已审批、未过期知识，不提供历史快照、回执、
候选内容、审批记录或成员信息。匿名结果可能随审批变化；有个人凭证的读取继续使用任务固定快照。
两种安装都不会覆盖已有目录或同名 MCP；显式更新需 `--replace` / `--replace-mcp`。

### 管理员部署内网接入服务

服务端需先安装包含 `/api/network/*` 和设备授权功能的 MiniApp 版本。
`relay.py` 只转发三个明确的 Agent/设备接口，过滤客户端 Cookie、身份头和平台 Token；
不转发管理、审批和成员接口。不增加训练依赖，也不分发共享平台凭证。

```bash
python3 scripts/tools/memory_remote/relay.py \
  --endpoint "$COWORK_MACHINE_ENDPOINT" \
  --app-token-file /secure/cowork-app-token \
  --bind "$PRIVATE_LISTEN_IP" --port 8765 \
  --cert-file /secure/tls.crt --key-file /secure/tls.key
```

`PRIVATE_LISTEN_IP` 须是明确的 RFC1918 私网 IPv4，不接受 `0.0.0.0` 或公网 IP。
非 loopback 必须配置受客户端信任的 HTTPS 证书，客户端不提供跳过证书验证选项。
也可默认监听 `127.0.0.1`，由公司批准的内网 HTTPS 反向代理转发；**不得接到公网入口**。
网络 ACL 限制公司内网/VPN，禁止公网端口映射。使用进程管理器保持服务常驻，平台凭证
文件限服务账号可读。内置限制为每源 IP 每分钟 120 次请求、最多 16 个并发和 64 KiB 请求体；
反向代理场景按实际容量配置入口限流，进程自带限流不信任客户端转发 IP 头。

新增测试覆盖设备授权、拒绝、匿名工具边界以及接入服务的路径/身份头隔离；均为 CPU
测试，无外部网络或 GPU 依赖。MiniApp 另用实际 PostgreSQL 验证审批和一次性领取。

## 原有双凭证接入（兼容模式）

下面的 `setup` / `install` 连接旧机器入口，仍需要现有两项凭证。

## 一条命令完成凭证配置和 MCP 接入

从本分支拉取最新代码后，在交互式终端运行：

```bash
MEMORY_PYTHON=python3 bash scripts/tools/memory.sh remote setup --client codex
```

向导依次询问服务 HTTPS 地址、项目凭证、平台 Token。两项凭证使用隐藏输入，
可以输入已有文件的绝对路径（也支持 `~/`），或直接粘贴对应 Token 原文。
项目凭证选择 MiniApp 下载的 JSON 文件路径最方便，无需打开或手工拆分 JSON。
直接粘贴项目 Token 时，保存的 JSON 不含到期元数据，但服务端仍强制执行到期与撤销。

向导会先验证真实机器鉴权和任务快照，再创建安装目录并保存两个凭证文件，最后注册
Codex 的 `relax-memory` MCP。新开 Codex 会话即可使用。不含 Codex 的机器去掉
`--client codex`，向导会输出供其他 stdio MCP 客户端导入的配置。

### 申请、查看和粘贴凭证

平台 Token **不是每个人默认都有**，它按应用审批。个人记忆凭证则绑定项目成员和设备，
两者不可互换。安装 skill 应先根据当前部署提供可点击的 Cowork 申请入口和 MiniApp 链接。

1. 打开已确认的 Cowork 门户，访问 `/sso-application?hideNavigationBar=true`，
   选择“服务端 API Token”，再选择目标应用。已有申请先查看审批进度，不要重复申请；
   此流程不需要选择“应用外发”。
2. 获批后，在申请人自己的 Hi 中查找 Cowork 部署服务号发送的 Token 通知。
   申请页用于查看进度，不保证展示 Token 明文。应用已有 Token 不表示其他员工也能领取；
   未收到通知或无申请权限时，按官方指南联系平台确认，不借用他人的 Token。
3. 打开目标 MiniApp → “MCP 与成员”，由管理员为你的成员账号签发个人 Agent 凭证。
   使用下载的 JSON 文件，或在隐藏输入时粘贴 JSON 中的 `token` 值。
4. 运行上面的 `remote setup`。依次输入目标机器 HTTPS 地址、个人凭证、平台 Token。
   两项凭证支持隐藏粘贴，不要发送到聊天，也不要写入命令行参数或 Git。

门户地址、MiniApp 地址和官方文档链接由部署上下文提供；本公开仓库不内置组织内部域名。
此方式直接连接 Cowork，不依赖另行部署内网接入服务。

**凭证从哪里来：**

- 项目凭证：管理员在 MiniApp 的“MCP 与成员”中先添加/启用成员，再为成员或设备
  签发凭证，下载 `agent.json`，通过公司允许的安全渠道交付给使用者。
- 平台 Token：应用管理员完成平台的服务端 Token 申请，获批后从平台通知中领取。
  已经开通的应用无需每台机器重新申请；申请人按平台允许的范围配置自己的调用机器。
  不向其他成员转发平台 Token；普通成员应向平台确认其应用调用授权。
- 两项都不从公开仓库下载，不放到命令行、聊天、截图或共享配置中。隐藏输入也需要
  使用者已经合法取得凭证；向导不是匿名领钥或自动审批服务。

`setup` 默认不会覆盖已有安装或同名 MCP。更换凭证使用 `--replace`；确需替换
已有 Codex MCP 条目时另外加 `--replace-mcp`。网络或鉴权验证失败时不覆盖原凭证；
若后续 Codex 注册失败，已安装目录保留，可修复客户端后运行 `register-codex`。

自动化环境必须使用文件参数，不允许从管道回退到可能回显密钥的输入方式：

```bash
MEMORY_PYTHON=python3 bash scripts/tools/memory.sh remote setup \
  --endpoint "$RELAX_MEMORY_ENDPOINT" \
  --credential-file /secure/agent.json \
  --app-token-file /secure/cowork-app-token \
  --client codex
```

## 使用已有凭证文件安装（不自动联网验证）

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
