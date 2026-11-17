# Relax 记忆中心：完整 Demo 操作手册

配套：[产品方案](./memory-center-product.md)、[技术设计](./memory-center-design.md)。本手册对应仓库实际代码；Demo 不需要 Docker、GPU、模型服务或新增 Python 依赖。

## 1. 后台启动并打开浏览器

在 Relax 仓库根目录执行：

```bash
python examples/memory/center_demo.py up
```

默认监听 `127.0.0.1:8766`，状态目录为 `~/.local/state/relax-memory-center`。命令启动后台 Python 进程后退出，并输出 JSON，其中 `url` 是可以直接打开的完整访问链接。无需保留前台终端。

链接带临时页面访问 fragment，打开后页面将其移除并把密钥仅保存在页面内存中。不要把此完整链接放入公开文档或提交仓库；它代表此单管理员 Demo 的全部权限。重新加载后可再次使用启动器输出的完整链接，或手工输入状态目录 `center-key` 中的密钥。

查看状态和重新取得链接：

```bash
python examples/memory/center_demo.py status
```

停止自身服务，保留所有词条和历史：

```bash
python examples/memory/center_demo.py down
```

启动器基于 Linux `/proc` 验证进程命令与状态目录，避免向无关 PID 发送停止信号。这是后台进程启动器，不是自动拉起、开机启动或生产级进程监控。

### 在现有容器中使用

将状态目录放到容器已有的持久化挂载中。默认端口可在 IDE 转发后用本机浏览器访问。若要在可达内网中直接访问，显式配置监听地址和浏览器使用的主机名：

```bash
MEMORY_CENTER_STATE=/your/persistent/path/relax-memory-center
python examples/memory/center_demo.py up \
  --state-dir "$MEMORY_CENTER_STATE" \
  --host 0.0.0.0 --port 8766 --public-host your-reachable-host
```

替换示例路径和主机名，不能直接复制占位符运行。`--public-host` 只改变链接，不创建网络路由；容器端口映射、IDE 转发或网络可达性仍由运行环境提供。`--port 0` 可选择空闲端口，实际值在输出链接中。

已有服务运行时再次 up 复用该实例，不悄悄切换监听配置。修改 host/port 前先对相同 state-dir 执行 down，再 up。不同实例使用不同目录与端口。

需要前台调试时使用底层入口：

```bash
python -m relax.memory.center \
  --state-dir /your/persistent/path/relax-memory-center \
  --host 127.0.0.1 --port 8766 --seed-demo
```

## 2. 初次打开看到什么

空库首次启动时导入六条演示内容：三条已生效、一条待审批、一条已失效、一条已驳回；生效内容中有一条到达复核日期。真实仓库来源与演示假设在来源、证据等级和审核说明中分别标明。

页面布局：

- 左侧：词条库、审批工作台、待复核与老化、操作记录。
- 顶部：总数、生效、待审批、待复核/已失效统计。
- 中间：搜索、类型/状态筛选和词条列表。
- 右侧详情：正文、适用条件、来源、有效期和可展开的历史内容。
- 顶部按钮：提交记忆、刷新、Agent 读取预览。

界面使用仓库自带 HTML/CSS/JavaScript，不从外网下载字体、脚本或组件。页面每 15 秒刷新；正在编辑和确认操作时暂停自动刷新。

## 3. 实际走一遍提交与审批

1. 点击“提交记忆”，填写标题、摘要、正文、负责人和来源。
2. 示例可写“区分首步编译耗时与稳态吞吐”，选择性能优化方向，记录适用条件。
3. 证据等级选择“有文档来源，未重新实测”，不要把未执行实验标为已测试。
4. 选择未来的复核时间和更晚的到期时间，或留空不设时间。
5. 提交后在“审批工作台”查看。此时用 Agent 读取预览搜索标题，不应出现该候选。
6. 打开详情，点击“审批通过”，填写实际核对的依据。再次预览，该词条可以进入新快照。
7. 在详情历史中查看提交人、审核人、时间、原因及当时内容。

审批不运行测试；“通过”表示操作人确认了填写的依据。操作人名称为自填，Demo 不证明操作者真实身份，也未要求提交与审核由不同人完成。

## 4. 驳回、修订与重新提交

提交另一条缺少对照证据的候选，点击“驳回”，填写“缺少同条件基线与测量范围”。它保留为已驳回，不进入 Agent 读取结果。

点击“修订 / 调整有效期”补充内容，再提交审批。对于已生效条目的修订，Demo 会先撤下旧版本，再等待新版审批。过去任务的物化快照不改变，新的任务暂不读取这条记忆。

两个页面同时操作同一词条，后提交的旧工作流版本会被拒绝，提示刷新，避免静默覆盖。

## 5. 复核、到期与主动失效

- **待复核**：把复核时间设到过去、到期时间设到未来并批准，词条显示待复核，但仍可进入新快照。
- **自动到期**：提交一条有效期约一分钟后的演示词条并批准。到时后台扫描会生成老化事件；创建新快照立即按 TTL 排除，不依赖扫描完成。日期精度为分钟，操作时留足审批时间。
- **主动失效**：在已生效详情点击“主动失效”，填写不适用原因，之后的新任务不再读取。
- **恢复使用**：修订内容和有效期，重新批准。不会抹掉之前的失效记录。

到期扫描间隔 10 秒，页面刷新间隔 15 秒，因此列表视觉状态可能稍后更新；点击刷新会立即检查。长期不设到期的词条仍可设置复核日，避免永久无人维护。

## 6. Agent 读取与版本预览

在搜索框输入主题，点击“Agent 读取预览”。后台创建当前空间的只读快照，再通过任务凭证实际检索。返回包含 read_receipt、条目 ID/revision、来源、审核声明和内容。

最多返回 20 条、65536 字节；超预算时可能省略条目。它是当前 Memory 的实际字节预算，不等于 token 数。旧快照保存历史内容，普通到期只影响新任务。

中心 Demo 的预览不是向已安装 Codex/Claude Code 自动推送上下文。真实客户端接入还需配置 MCP 与任务凭证，见 [Memory skill](../../skills/memory/SKILL.md)。

## 7. 性能诊断闭环 Demo

另一个可运行演示覆盖“真实脚本 → 历史案例 → 诊断建议 → 候选审核 → 选择发布 → 远端读取 → 本地离线缓存”：

```bash
PYTHONPATH=. python examples/memory/performance_demo.py \
  --output /tmp/relax-performance-walkthrough
```

输出目录必须未存在；重复演示换一个目录，避免覆盖回执。结果包括：

| 文件 | 用途 |
| --- | --- |
| `diagnosis/report.html` | 可筛选的诊断审阅页面 |
| `diagnosis/report.json` | 当前输入观察、引用案例和建议依据 |
| `diagnosis/candidate.json` | 本次候选计划 |
| `mcp-response.json` | 实际本地 MCP 子进程返回 |
| `sync-receipt.json` | 选择发布、远端读取和缓存来源 |
| `offline-diagnosis/report.html` | 远端停止后使用本地缓存的结果 |
| `walkthrough.json` | 本次运行结果与限制 |

这个流程会临时启动本机 HTTP 服务模拟远端，结束后自动关闭；不是部署到真实云服务。历史源为仓库 Kimi K3 文档和脚本，不重新执行 GPU 实验。

自己的输入可通过以下命令诊断：

```bash
PYTHONPATH=. python examples/memory/performance.py \
  --db /tmp/relax-performance-local/memory.sqlite seed
PYTHONPATH=. python examples/memory/performance.py \
  --db /tmp/relax-performance-local/memory.sqlite diagnose \
  --script examples/models/kimi-k3/scripts/run-kimi-k3-pokemon-lora-64xblackwell.sh \
  --query 'Kimi K3 MLA 编译缓存' --output /tmp/relax-performance-task-1
```

可追加 `--log` 或 `--trace`，详情见 [性能原型说明](../../skills/memory/references/performance-prototype.md)。当前中心与性能演示使用独立实例；不要把它们描述为已自动共享刚提交的知识。

## 8. 验证命令

在无 GPU 环境执行行为回归：

```bash
CUDA_VISIBLE_DEVICES='' PYTHONPATH=. python -m pytest -q tests/cpu/memory
```

测试覆盖真实 HTTP、本地 MCP、权限、候选与快照隔离、生命周期及页面 API；日志/trace 解析使用明确标注的合成样例。没有真实 GPU、外部 MemOS、生产 SSO 或浏览器自动化环境时，不将这些项目描述为已验证。

## 9. 常见问题

**打不开链接**：先检查 `status`，再确认浏览器能访问输出主机与端口；容器无法直达时使用 IDE 端口转发。默认绑定 loopback 不提供远端直达。

**页面提示密钥**：从 status 输出取得新的完整链接，或输入 `center-key` 内容。密钥不保存在浏览器 localStorage/cookie，刷新可能需要重新授权。

**修改没立即出现在 Agent 预览**：新内容需要审批；当前任务快照不会自动更新。预览按钮创建新快照；实际客户端需要新任务绑定。

**某条经验看起来有效却搜不到**：检查审核状态、有效期、搜索关键词和返回字节预算。复核提醒不等同于失效。

**提交失败**：检查必填项、日期顺序、带时区的 API 日期和字段长度。出现版本冲突先刷新，不重复覆盖。

**服务启动失败**：检查状态目录中的 server.log，端口占用时选择其他端口；不要停止不属于本 Demo 的监听进程。

**重启数据还在吗**：相同状态目录会保留 SQLite、事件和密钥。容器删除是否保留取决于该目录是否位于持久化挂载；停止服务不会删除数据。

## 10. Demo 的明确限制

这是可信内网的单管理员原型，不是公开 SaaS。真实生产还需 TLS、SSO、业务隔离、审批分权、幂等操作、跨服务恢复、分页和容量管理、备份及审计策略。

当前老化按固定日期执行，不根据访问次数自动降低可信度或删除内容。没有自动语义合并、自动共享、跨库撤回、平台文档连接器或训练奖励门控。MemOS 仍是可选适配，非此 Demo 运行依赖。
