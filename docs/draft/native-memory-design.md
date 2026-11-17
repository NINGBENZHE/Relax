# Relax 原生 Memory：模块设计与产品形态

最新整合交付（2026-11-10）：[记忆中心产品方案](./memory-center-product.md)、[技术设计](./memory-center-design.md)、[完整 Demo 操作手册](./memory-center-demo.md)。本文保留原始训练侧目标设计；当前项目知识中心的实际边界以整合文档为准。

状态：设计草案。第 1–16 节描述目标设计；其中本地基础知识／经验记忆与 MemOS 适配已交付初版，实现范围及验证限制见第 17 节。其余接口、配置与产品能力仍为拟议契约，不能作为已实现功能使用。首期目标为一个双月；实施优先级以 Memory 为主，新模型与卡型优化作为配套验收工作流。

## 1. 产品定位与范围

提供独立于业务模型的经验记忆层：单业务在本地使用，多业务通过私域服务复用能力；Relax 训练通过同一协议读取、验证和沉淀经验。不要求部署 MemT，不要求更换业务模型，也不要求为了保存经验训练一个专用记忆模型。

首期存储三类内容：任务经历、经验证的成功策略、带失败证据和适用边界的失败教训。原始轨迹作为证据引用保存，不能把所有对话无差别变成长期记忆。优先使用结构化模板、规则检索和规则校验；摘要可调用已有私域模型，但摘要结果仍是候选经验，必须保留证据。

记忆服务负责经验生命周期和访问边界，Runtime 负责训练一致性，agent 负责消费经验及提出候选。模型仍通过原来的模型接口执行任务。首期不包含可训练记忆策略、自动跨业务共享、跨地域多主写入或专用向量数据库的强制依赖。

## 2. 两种产品形态

| 维度 | Local：本地／单业务私域部署 | Shared：云端／多业务私域共享服务 |
| --- | --- | --- |
| 用户 | 开发者、单个 AIO 业务、离线环境 | 多业务团队、平台管理员、训练平台 |
| 交付 | 直接运行的 Python 服务、Python SDK、MCP 适配器 | 同一服务的集中部署包、HTTP/MCP 入口、管理界面 |
| 数据落点 | 用户指定目录，SQLite 与本地证据文件；单写进程 | PostgreSQL 与私域对象存储；多个无状态 API 实例 |
| 连接 | stdio MCP 启动本地适配器；多个 agent 可连同一个本地服务 | Streamable HTTP MCP 或 SDK HTTP；通过组织身份认证 |
| 隔离 | 工作区／业务／环境命名空间，文件权限；训练 Session 凭证 | tenant → business → environment → namespace；授权绑定身份 |
| 共享 | 默认不上传；显式导出经过筛选的经验包 | 默认业务私有；显式发布后进入授权共享库 |
| 运维 | 初始化、备份、恢复、检查状态、查看经验 | 配额、审计、发布审批、版本回滚、备份恢复、容量监控 |
| 断网 | 核心读写可离线；摘要能力取决于本地模型 | 可选预先授权的只读快照缓存；离线候选恢复后重新校验 |

Local 与 Shared 是同一产品的两个部署配置，不维护两套读写语义。导入导出保留条目 ID、版本、来源和 schema 版本；导入时重新校验目标空间权限，不能携带原租户权限进入新空间。首期不做自动双向同步。

云端共享指共享服务能力，不代表公开业务数据。服务可部署在客户 VPC 或内网，出站模型调用默认关闭。远程 agent 必须有到服务的网络路径，本机 stdio 配置不能直接当作云端可达性保证。

### 用户可见界面

agent 内以工具结果卡片为主，展示「经验摘要、适用条件、来源、验证状态、版本、有效期」；必要时展开完整证据。候选写入后明确展示「暂存，尚未发布」，不能把候选回执描述为已经被其他任务学会。

Local 提供 CLI 完成空间初始化、检索、查看、候选管理、失效、快照和备份。Shared 增加轻量管理页，首期只做四个视图：业务空间、候选审核、经验版本／发布、运行与成本。每条经验可回答“从哪次任务来、谁验证、哪些任务读过、何时失效”。

拟议自然语言交互：

- “开始前查一下本项目相关经验，最多使用 800 token。”→ 受限检索，返回适用经验及来源。
- “把刚才通过测试的解决办法记下来。”→ 创建候选，关联测试证据；由验证方决定能否进入私有库。
- “这条经验已经不适用于新版本。”→ 提交纠正候选；有权限的管理者创建新版本或执行失效。
- “把这条通用方法共享给其他业务。”→ 生成脱敏后的发布预览，由授权发布者批准。

## 3. 与 Codex／Claude Code 等 agent 的交互契约

主入口选择 MCP，SDK/HTTP 供 Relax 与自有 agent 使用。Codex 与 Claude Code 的官方文档均列出本地 stdio 与远程 HTTP 接入方式，因此可以共用工具 schema；客户端配置与授权细节分别适配。[Codex MCP](https://developers.openai.com/codex/mcp)、[Claude Code MCP](https://code.claude.com/docs/en/mcp)。

普通 agent 只暴露四个工具，减少工具选择和上下文开销：

| 拟议工具 | 输入 | 输出与边界 |
| --- | --- | --- |
| `memory_search` | query、task_context、token_budget、可选类型过滤 | 命中摘要、版本、来源、read_receipt；服务端限制预算上限 |
| `memory_get` | memory_id、revision、read_receipt、token_budget | 同一授权快照内的详情；不能借详情接口读取最新版本 |
| `memory_propose` | kind、content、conditions、evidence_refs、idempotency_key | 私有 candidate_id；不能自行声明验证通过 |
| `memory_feedback` | read_receipt、helpful／outdated／incorrect、evidence_refs | 使用反馈；不直接覆盖经验或等价于可信奖励 |

`verify`、`commit`、`publish`、`expire`、`snapshot` 属于可信运行器或管理面，不能授予普通模型工具凭证。业务空间、Session、snapshot 和读写权限从服务端授权上下文推导，不接受模型通过参数切换租户。

拟议工具返回示例：

```json
{
  "snapshot_id": "snap-42",
  "read_receipt": "read-17",
  "items": [{
    "memory_id": "mem-9",
    "revision": 3,
    "kind": "strategy",
    "content": "先验证输入约束，再执行修复，并运行对应回归。",
    "conditions": {"task_family": "repair"},
    "source": {"business": "aio-a", "evidence_id": "evidence-8"},
    "verification": "verified"
  }],
  "truncated": false
}
```

技能／项目指令负责教 agent 在何时查询和何时提候选，MCP 负责执行接口。建议规则为：任务开始一次；进入关键工具执行或连续失败后的策略切换前按剩余预算补查；结束后有证据再提候选。无需把整个经验库写进 `AGENTS.md`／`CLAUDE.md`。这些说明只能引导模型，不能保证执行，训练所需的强制检索由 harness 适配器执行。

普通 Codex／Claude Code 使用可以保持原模型端点；接入 Memory 不等于已经接入 Relax 训练。训练还必须满足 Relax 的模型请求、完整历史、奖励与导出契约。不同客户端 hook 不作为首期共同依赖，先以 MCP 工具和薄 harness 适配器实现相同行为。

## 4. 模块边界与持久化契约

```text
Codex / Claude Code / Business Agent     Relax Agentic Runtime
                  | MCP / SDK                    | SDK
                  +------------------------------+
                                  |
                     Memory API + Authorization
                                  |
                  Retrieval / Validation / Versioning
                                  |
                  Records + Staging + Snapshot + Audit
                                  |
                     Local Store / Shared Store
```

拟新增 `relax/memory/`，拆分协议与类型、服务端、存储适配、检索策略、验证策略、MCP 适配和 Runtime 适配。服务进程不依赖 Ray/GPU，可独立运行；Runtime 只依赖客户端协议。SQLite/PostgreSQL 等为拟议存储选型，本次不新增依赖。

统一 `MemoryStore` 协议包含：`search`、`get`、`stage`、`validate`、`commit`、`update`、`expire`、`create_snapshot`、`publish`、`feedback`。SDK、HTTP 与 MCP 复用服务逻辑，不能分别实现权限和去重规则。

| 对象 | 必需字段与语义 |
| --- | --- |
| MemoryRecord | id、revision、scope、kind、content、适用条件、反例／禁用条件、来源、证据、验证器版本、创建时间、有效期、状态、内容 hash |
| Candidate | candidate_id、Session/Group/run、私有 staging scope、候选内容、证据、幂等键、校验状态；自身不属于可检索长期库 |
| SnapshotManifest | 私有库与共享库版本、条目 revision 清单、索引版本、检索策略版本、cutoff、有效性判定时间、hash；不可变 |
| ReadReceipt | 实际返回字节与 hash、排序、条目版本、snapshot、query hash、截断信息、来源、授权 scope；可对应到模型消息 |
| CommitReceipt | 幂等键、候选 hash、验证结果、目标 revision、提交序号；供恢复与对账使用 |

`stage` 重试同一幂等键与内容返回同一候选；同键异内容报冲突。`commit` 以业务空间和幂等键唯一约束保证重试不重复写。`update` 必须携带 expected_revision，冲突交回调用方重新审阅，不静默覆盖。错误区分 `forbidden`、`revision_conflict`、`snapshot_unavailable`、`budget_exceeded` 和可重试服务故障。

检索先做授权、快照可见性、有效性和适用条件过滤，再做关键词与结构化标签匹配，按相关性、证据质量和适用版本排序。首期没有 embedding 模型也可运行；语义检索作为可替换插件，索引必须按版本和空间过滤，缓存键必须包含授权空间与快照。

去重分两层：规范化内容 hash 做精确去重；同任务类型与条件下做近似候选匹配。近似结果不直接覆盖已有结论；合并须保留来源。相互矛盾的经验保留适用条件与冲突关系，不能以“较新”自动认定正确。

## 5. 原生训练集成：快照与写入隔离

现有代码中，`relax/agentic/pipeline/prepare.py` 准备 Group，`runtime.py` 管理 Session 执行，`reward.py` 提供 Session／Group 奖励和最终过滤，`transfer.py` 管理训练分区与批次；`relax/agentic/session/state.py` 保存上下文与训练导出。这些是接入位置，不是已有 Memory 能力。

关键不变量：同一逻辑采样批次读取同一个只读 Memory manifest；同一 Group 的兄弟 Session 不可读彼此候选；任务奖励不能回流到该任务已经发生的模型输入。

1. **分配读取代次。** 在本批次第一个 Session 开始执行前创建 `memory_epoch`，绑定不可变快照。预启动任务也必须先获得代次；禁止运行时隐式取 latest。
2. **开始与决策点检索。** Runtime 策略经 harness 适配器生成查询，控制次数、字节、token 和延迟预算。只从绑定快照读取，默认不从 staging 读取；同任务工作笔记保留在自身对话中。
3. **形成真实模型上下文。** 初始经验放入有来源标记的上下文消息；中途检索通过实际工具调用及对应结果追加。保留客户端原有角色语义，不能伪造不存在的 tool call，也不能在模型生成后才补写记忆到训练轨迹。
4. **暂存候选。** 任务执行中或完成时可提出候选，但只写 Session 私有 staging。不存在同批次 read-your-writes 的长期记忆视图。
5. **奖励与验证。** 任务完成后读取可信奖励、执行器证据与最终 Group 接纳状态，再校验候选。首期只提交被接纳 Group 的经验；失败教训也必须有已完成且可归因的失败证据，超时／基础设施故障不能直接变成业务教训。
6. **提交与可见性。** 用持久化 outbox 记录待提交候选，幂等提交新 revision。它们只能进入后续采样代次的快照，不改变任何在途批次。提交失败重试，不重复产生训练样本。
7. **批次与恢复。** 转交训练时保存样本到 memory_epoch 的映射、快照 manifest 和提交水位。恢复沿用原 manifest 与实际读回执，不重新检索最新库。

Fully Async 与 partial rollout 不能直接用 optimizer step 号定义快照边界。应在采样准入时分配 cohort／memory_epoch，并让 Transfer 按 epoch 分桶；为首期验收，物理训练批次也保持单一 epoch。在途旧任务继续使用旧快照，不能迁入新代次凑批。动态过滤补样从原代次补齐，避免凑批时改变对照条件。该分桶可能降低吞吐，需纳入成本测量。

流程存在两个不同的持久化边界：经验提交和训练 checkpoint。首期以“最终接纳且奖励可信的任务”作为经验提交条件，不声称模型更新与记忆提交跨系统原子一致。恢复使用 checkpoint 中记录的快照；已经提交但尚未被 checkpoint 覆盖的经验仍在历史库中，通过提交回执对账，在显式开启新代次前不可自动读入。outbox 与接纳决策需要持久保存，不能仅保存在 Python 内存中。

### 轨迹、token 与 loss mask

ReadReceipt 保存最终裁剪后的实际内容，不只保存文档 ID。模型请求保存对应 messages／tools／template 参数，导出关联消息位置、token 区间、tokenizer/template 版本、snapshot 和来源。预算以目标模型 tokenizer 对最终渲染后的内容计数，覆盖工具包装开销；服务端估算仅供预筛，最终以 Runtime/适配器的裁剪结果为准。

沿用 SessionForest 当前语义：初始记忆属于 prompt；后续外部记忆 observation 的 continuation token 不参与 loss；模型自己生成的检索调用及回答保留原 assistant 训练语义。不能将“模型复述的记忆”一律设为零，也不能把外部经验文本当作模型生成 token。

每次请求提交前确认上下文中的经验与 read receipt 一致。压缩历史属于显式上下文变更，应记录压缩输入与结果及新的 lineage；有分支或非线性历史时遵守现有显式导出契约。进程崩溃恢复还需要持久化 harness checkpoint；现有 partial resume 不能被描述为任意进程崩溃后的完整恢复。

## 6. 版本、过期与共享治理

候选生命周期为 `staged → validated → committed`，失败进入 `rejected`；已提交内容通过新 revision 更新，过期／撤销使用状态事件。高奖励不等于通用策略正确：验证器同时检查任务结果、证据可读性、适用条件、是否包含样本答案／秘密、与已有经验的冲突。

TTL 和适用软件版本共同约束检索。快照按创建时的有效性判定时间固定内容，普通 TTL 到期只影响新快照，保证长任务和恢复可复现。安全撤销或强制删除优先于复现：拒绝继续读取受影响快照，明确标记相关运行无法完整复现，不能偷偷换成最新版。快照有引用计数／保留期限，GC 不删除仍被活跃运行或保留 checkpoint 引用的版本。

训练与评测使用不同环境空间。评测可从指定训练快照显式复制一份冻结基线，但不能自动读取训练新写入，也不把评测答案写回训练库。持续更新评测是单独实验模式：按预先固定的时间窗口更新，窗口内同样隔离并发任务，不能与冻结基准混报。

跨业务共享通过授权发布者执行：生成脱敏派生条目 → 预览内容和受众 → 校验 → 发布到共享库。保留私有来源的受控关联，其他业务不能由共享条目反查私有原文。共享条目的后续更新也需重新发布；撤销从新快照移除，旧快照遵循上述撤销规则。

服务端从凭证推导 scope，数据库行策略与查询谓词双重限制；对象证据访问同样鉴权。检索缓存、去重索引、日志、指标和错误返回都不能绕开边界。经验内容始终作为不可信数据消费，不能升级为系统指令。权限不能仅依赖 agent 遵守提示词。

## 7. 配置与故障行为

以下是待实现配置草案，不是当前 Relax 参数；具体配置加载方式在实施阶段确定。

```yaml
memory:
  mode: local                  # local | shared | disabled
  endpoint_env: RELAX_MEMORY_ENDPOINT
  credential_env: RELAX_MEMORY_CREDENTIAL
  namespace: aio-a/train       # 服务端仍需校验授权
  read:
    snapshot_policy: cohort
    max_calls_per_task: 3
    max_tokens_per_task: 1600
    max_tokens_per_call: 800
    timeout_ms: 500
  write:
    staging_scope: session
    require_verification: true
    visibility: next_cohort
  sharing:
    publish: explicit
  evaluation:
    namespace: aio-a/eval
    writes: disabled
```

数值是起始实验预算，不是性能承诺。Shared 模式从环境／凭证系统读取 endpoint 和短期凭证；Local 的数据目录由部署者指定。两种模式共用 schema，`disabled` 作为无记忆对照。

交互式工具超时可以返回清晰的“记忆不可用”结果，agent 继续原任务并记入降级指标。训练／评测默认不静默降级：缺失绑定快照或必需读回执则停止该任务并按既有 Group 规则处理，避免“无记忆样本”混进记忆组。预算耗尽返回空结果和原因；空命中与故障在指标中区分。写入失败留在 outbox，配额超限限制候选增长并保留状态。

## 8. 一个双月的交付安排

| 时间 | 交付 | 可评审证据 |
| --- | --- | --- |
| 第 1–2 周 | 协议、存储 schema、Local 读写／去重／版本／TTL／快照、MCP 最小工具 | 同一场景由 SDK 和 MCP 得到相同权限与版本结果；备份恢复可读 |
| 第 3–4 周 | Runtime 快照绑定、私有 staging、奖励后验证、outbox、轨迹关联；首个 AIO 配方 | 双 Session 无交叉读取；真实模型请求与导出内容一致；完成优化器更新 |
| 第 5–6 周 | Shared 部署、租户权限、共享发布与审计；第二个业务接入 | 两业务使用同一协议；跨业务检索、详情、证据、缓存访问均不能越权 |
| 第 7–8 周 | 三组对照、过期与恢复实验、管理页、部署包、运行手册与成本报告 | 可复现的效果—成本表、故障恢复记录、接口复用结果与遗留项 |

拟议新增 AIO Memory 配方应包括 agent 适配器、任务数据 schema、可信 verifier、三种 memory profile、启动脚本和评测汇总。AIO 的具体业务任务、奖励定义、数据来源与可用资源尚待业务确定，不用虚构业务数据替代验收。实施前若涉及参数解析、Controller／Service／Launcher 或新增依赖，按仓库约定单独评审具体变更。

## 9. 评测与验收口径

三组对照保持模型 checkpoint、任务集合、采样参数、任务顺序及计算预算可比，并报告多个随机种子的波动：A 无记忆；B 固定经验库；C 从与 B 相同的初始库持续更新。冻结模型的在线任务实验测量记忆本身收益；RL 实验另行运行三个独立训练分支，不能把模型训练进步全部归因为记忆。

数据按任务族／近重复簇划分，阻止同题答案进入检索。成功经验是否跨任务泛化、失败教训是否误导正常任务、版本变更后是否仍命中过期策略，均需独立切片。持续更新实验按时间先后执行，只允许过去窗口的合格经验进入后续窗口。

| 类别 | 度量 |
| --- | --- |
| 效果 | 业务成功率、奖励、完成步数、重复错误率；按任务族给出样本量和置信区间 |
| 遗忘与过期 | 历史能力回归、过期命中率、撤销生效情况、错误经验传播率、新版本适应情况 |
| 资源 | 记忆输入 token、总输入／输出 token、检索 p50/p95、摘要调用、索引与证据存储 |
| 端到端成本 | 每成功任务成本、每任务时延、训练吞吐；包含 GPU、CPU、数据库、摘要与运维分摊 |
| 一致性 | 快照混用、兄弟 Session 泄漏、重复提交、恢复后内容／版本／mask 漂移 |
| 隔离 | 跨业务、跨环境、共享来源反查、对象证据、缓存与去重侧信道的越权检查 |

一致性和隔离是硬门槛，验收用例中不得出现违规；效果提升与成本上限由业务基线设定，不预先宣称收益。CPU 层覆盖存储契约、鉴权、幂等、快照与过期边界；进程层覆盖崩溃恢复和 outbox 重试；训练层覆盖真实轨迹导出、mask、异步分批与优化器更新。优先扩展既有测试，不用只检查 mock 调用或源码字符串的测试代替行为验证。

## 10. 与新模型接入和新卡型优化的关系

Memory 不绑定模型架构，但 tokenizer、chat template、工具协议／parser、上下文长度会影响预算与训练正确性。每次模型切换重新跑 Memory 读写轨迹和 mask 验收，不能只验证能生成文字。

新模型快速接入清单分三道门：

1. **推理可用：** 官方权重、许可和依赖版本确认；真实消息／工具调用／reasoning parser、模板、长上下文与模型特有输入通过验证。
2. **权重映射与训练正确：** HF 与训练后端的映射／分片、权重往返、数值与梯度、训练后权重同步通过验证；以结构实际需求覆盖 Dense/MoE/注意力变体。
3. **业务训练与导出验收：** AIO 配方达到约定业务指标，checkpoint 恢复和导出可重新推理，记录模型版本、配置、硬件和首个可用配方。

Qwen4 相关工作以官方发布且所需权重可获取为触发条件；本文不假设其发布状态或架构。交付周期从“官方权重与必要材料均可获取”到“首个配方通过上述验收”计时，同时记录外部依赖阻塞时间。未满足条件时用已获批准的现有模型验证流程，不宣称已经交付 Qwen4 配方。

Blackwell 等卡型以业务实际使用的 Dense、MoE、稀疏／线性注意力模型建立矩阵，记录卡型、互联、软件版本、并行布局、batch、序列长度与精度。先测基线，再分别验证算子、通信、显存、并行布局瓶颈；低精度、融合算子和计算通信重叠仅在实现与硬件支持且正确性通过时进入实验。

报告必须给出同等业务质量下的端到端吞吐、延迟、峰值显存、每成功任务成本和可复用配置。分别记录无记忆与有记忆的 prompt 长度／缓存变化，避免把 Memory 带来的负载变化误判成卡型优化收益。国产化成果统一回到 Top 1 的 AIO 业务验收；本文不提供尚未实测的硬件提升数字。

## 11. 当前实现依据与待交付边界

已检查的现有实现：

- [Agentic 用户契约](../zh/guide/agentic-rollout.md)：agent process、模型接口、完整上下文与显式导出。
- [Prepare](../../relax/agentic/pipeline/prepare.py)、[Runtime](../../relax/agentic/pipeline/runtime.py)：Group 准备与 Session 执行。
- [Reward](../../relax/agentic/pipeline/reward.py)、[Transfer](../../relax/agentic/pipeline/transfer.py)：奖励、过滤与训练分区。
- [SessionForest](../../relax/agentic/session/state.py)：上下文、metadata 和 token/mask 导出。

本草案定义产品形态、接口边界和实施验收方案。Memory 服务与 MCP 工具的初版范围见第 17 节；Runtime 自动集成、AIO 配方和优化报告仍待交付。目标设计示例不能直接当作可执行功能。

## 12. Coding Memory：记什么、何时用、怎样验证

Coding Memory 的最小单元是一条有条件、有来源、可验证的工程经验，而不是一次对话摘要。经验应回答“在什么代码与环境下，遇到什么问题，采用什么办法，如何确认有效，以及何时不能使用”。代码与测试仍是事实来源；记忆负责缩短定位过程，不能替代读取当前代码。

保留顶层 `kind = episode | strategy | lesson`，用 `domain = coding` 和 `subtype` 区分工程用途，避免为每个业务建立不兼容的分类：

| subtype | 内容 | 最低证据与有效性条件 |
| --- | --- | --- |
| `code_map` | 模块职责、入口、符号关系与定位线索 | 引用代码及 blob hash；相关符号变化后重新确认 |
| `project_convention` | 已存在的项目约定及其适用目录 | 当前规范文件位置及 hash；规范原文优先 |
| `workflow` | 构建、测试、调试、发布的可复用流程 | 实际执行记录、环境与结果；涉及发布仍遵守用户授权 |
| `bug_fix` | 症状、触发条件、根因、修复步骤与回归方法 | 可复现失败、修复后验证、对应代码状态 |
| `pitfall` | 无效方案、失败原因、不要使用的条件与替代路径 | 明确失败证据；根因不确定时标为未知 |
| `design_decision` | 采用某种实现的背景、约束与取舍 | 维护者批准的 ADR／评审记录；模型推测不能成为团队决策 |

`episode` 保存某次实际任务经历；`strategy` 抽取经验证可重复使用的方法；`lesson` 保存受条件限制的失败教训。同一次经历可派生多个条目，通过 `derived_from` 关联，避免直接把全部日志塞进策略。

### Coding 任务闭环

1. **进入项目：** 确认项目身份、当前 worktree、HEAD、dirty diff、语言／依赖清单及有效项目指令；只收集与任务有关的文件摘要，不默认上传整个代码库。
2. **定位任务：** 用任务描述、错误特征、文件路径、符号、依赖版本生成查询，先查项目空间，再查显式订阅的通用经验包。开始时返回少量摘要，决定是否展开。
3. **修改前：** 对命中经验涉及的路径与关键符号读取当前代码；路径不存在、blob 不匹配或规范已变化时降低为定位线索，不能直接照搬旧补丁。
4. **执行中：** 首次出现新错误或准备切换修复策略时补查。相同错误与相同代码状态命中本任务查询缓存，不因每次工具调用重复检索。
5. **验证后：** 根据实际 diff、执行记录和用户反馈提出候选。成功策略要区分“测试通过”“CI 通过”“人工接受”“业务训练验收”，不能用一个成功布尔值代替。
6. **任务结束：** 写入私有候选并返回状态。可信本地验证器可按配置自动提交符合规则的项目私有经验；团队规范变更和共享发布仍由授权维护者决定。下一任务打开新快照才能读到新经验。

本地开发不要求 RL reward：可信执行器的测试／构建证据、已有 CI 结果或明确的人审可以作为验证来源。接入 Relax 训练时额外要求第 5 节中的奖励、Group 接纳与快照契约，普通 agent 不能自行伪造这些信号。

### 证据等级与写入门槛

`observed` 表示有任务或代码证据，`reproduced` 表示问题已被复现，`tested` 表示指定验证项通过，`accepted` 表示有授权审核记录。这些标签描述不同证据，不承诺全局正确；条目另存已覆盖与未覆盖的范围。

成功修复至少保存验证项、退出码、执行时的 HEAD 与 diff hash、依赖环境、结果摘要和证据引用。测试在修复前执行、仅收集到零用例、全部 skip 或仅静态检查通过，不能证明修复行为正确。涉及硬件的方案没有相应硬件实测，只能保留为带限制的经历，不能标记为已验证硬件策略。

失败教训区分“方案不适用”“实现有缺陷”“环境不可用”“尚未定位”。例如依赖缺失导致测试无法启动，应记为环境阻塞，不能沉淀成“该算法不可用”。重复失败没有新证据时更新支持次数，不无限新增条目。

## 13. 项目本地使用策略

### 文件与服务分工

建议项目内只版本控制可审阅配置和人工发布的经验包；数据库、执行轨迹、候选和凭证放在用户指定的私有数据目录。本节目录均为拟议布局，本次不创建运行目录或修改项目指令。

```text
<repository>/
  .relax-memory/
    project.yaml                 # 项目身份、读取预算、验证策略；可提交
    packs/                       # 人工审阅的可移植经验包；可选择提交
      coding-baseline.jsonl

<private-data-dir>/<project-id>/
  memory.sqlite                  # 服务持有；agent 不直接编辑
  artifacts/                     # 证据与实际读取内容
  snapshots/                     # 不可变 manifest
  staging/<workspace-id>/<session-id>/
  backups/
```

数据库是运行时唯一写入入口；JSONL 是导入导出格式，Markdown 是阅读视图。agent 不同时修改三种表示。项目经验包通过导入校验变成服务端版本，后续修改包文件不会偷偷改变已绑定快照；包删除也不直接等价于安全撤销。

本地服务使用单写进程与事务管理多个客户端，不让每个 MCP 子进程独立写同一个文件。stdio 适配器连接服务或使用互斥机制启动服务；数据库文件优先放在本机磁盘。共享文件系统上的工作目录不意味着应该把数据库放在该目录；跨机器访问改用 Shared 服务协议。

### 项目、分支与 worktree 身份

`project_id` 是初始化时分配的稳定标识；仓库 remote URL 仅作辅助识别，需去除凭证，不能直接当作权限或唯一身份。新 clone 是否继承已有项目空间由用户选择；fork 默认新项目，只有显式导入的经验可迁移。即使项目配置被复制，服务仍须鉴权，不能凭 `project_id` 访问数据。

同仓库 worktree 共用已提交的项目经验库，具有不同 `workspace_id`、Session 和 staging。branch 名只是来源线索，不是有效性判断依据：rebase、cherry-pick、同名分支都可能对应不同代码。具体修复通过 commit、路径、符号和 blob/diff 指纹判断；未提交改动产生的经验默认限制在原 workspace，直到验证其适用范围。

普通 coding 会话在任务开始固定快照。其他 agent 的新经验在下一任务可见；长任务如需刷新，必须显式创建新读取阶段并保留阶段前后的 read receipt，不能重写旧上下文。训练和冻结评测不允许这种会话中刷新。

### 项目指令与经验的优先关系

用户当前要求与有效项目规范决定如何工作。Memory 中的 `project_convention` 只是带来源的索引，不能覆盖当前 `AGENTS.md`／`CLAUDE.md`、制造新的审批要求或把过期约定升级为指令。发现冲突时读取源文件、记录冲突并提出纠正候选。

建议向项目指令提供以下可审阅片段；安装工具应先展示 diff，不自动改写用户文件：

```text
任务开始时按项目 Memory 配置检索相关经验，返回来源与适用条件。
修改代码前检查相关经验是否匹配当前代码和环境；以当前代码和有效项目指令为准。
仅在出现新问题或切换策略时补查；遵守任务检索预算。
完成验证后提出有证据的候选，明确验证范围和未验证项。
不要把候选当作已提交经验，不要自动跨项目或跨业务发布。
Memory 不可用时说明降级状态，继续遵守原有项目工作流。
```

建议首期本地策略配置如下，字段为待实现设计：

```yaml
schema_version: "1.0"
project_id: "project-example"
profile: coding
storage:
  private_data_dir_env: RELAX_MEMORY_DATA_DIR
read:
  snapshot: task_start
  max_calls: 3
  max_tokens_total: 1600
  max_tokens_per_call: 800
  max_items_per_call: 5
  order: [project, subscribed_packs]
write:
  destination: session_staging
  private_commit: verified_only
  dirty_tree_scope: workspace
  shared_publish: explicit
verification:
  policy_id: project-coding-v1
  accept_agent_claim_as_evidence: false
retention:
  uncommitted_candidates_days: 7
  episodes_days: 30
  strategy_review_after_days: 90
```

预算是初始实验值；retention 是待验证的默认策略，项目可以调整。`review_after` 表示需要重新检查，不等价于硬删除；`expires_at` 才限定新快照的可检索截止时间。任何清理都必须尊重活跃快照和 checkpoint 引用。无新增代码／依赖变化时不重复验证全库；相关文件、依赖锁文件或规范变化时，仅标记相关条目需要复核。

## 14. 标准化格式：Memory Record v1

采用“JSON 规范记录 + JSONL 交换包 + Markdown 阅读卡片”。YAML 可用于人工展示或配置，但不作为另一套存储协议。一次记录表示一个独立结论；长日志和补丁保存在受控证据对象中，通过 ID 引用。任务续接笔记是 Session 状态，不自动成为长期经验。

### 字段定义与所有权

| 字段 | 类型／必需性 | 含义与写入方 |
| --- | --- | --- |
| `schema_version` | string，必需 | 格式版本；v1 为 `1.0` |
| `id`, `revision` | string、正整数，提交后必需 | 服务分配稳定 ID 和递增 revision；候选不能指定已提交版本 |
| `scope` | object，必需 | tenant、business、environment、namespace、project_id、visibility；服务注入 |
| `kind`, `domain`, `subtype` | enum/string，必需 | 三类经验、领域和用途；coding 子类型见第 12 节 |
| `title`, `summary` | string，必需 | 独立可理解的标题与简要结论，禁止仅写“已解决” |
| `content` | object，必需 | problem、conditions、actions、expected_result、avoid、unknowns |
| `applicability` | object，必需 | 文件／符号／代码状态／依赖范围、scope_level、失效条件 |
| `evidence` | array，必需且非空 | 受控 evidence_id、类型、支持哪条结论；可信执行器核验 |
| `verification` | object，必需 | state、claims、limitations、verifier_id/version、verified_at；可信验证方写入 |
| `provenance` | object，必需 | task/session、workspace、agent 标识、观察时间、来源代码状态；服务与执行器核验 |
| `lifecycle` | object，必需 | status、created_at、updated_at、review_after、expires_at |
| `relations` | object，必需 | derived_from、supersedes、conflicts_with，空数组明确表示无关系 |
| `integrity` | object，提交后必需 | canonicalization、content_sha256、record_sha256；服务生成 |
| `extensions` | object，可选 | 按命名空间存放扩展；不能用于隐藏权限、状态或有效性条件 |

时间统一为 UTC RFC 3339；未知值不能伪造。允许为空的 expires_at、review_after 使用 `null`，列表无元素使用 `[]`。路径采用仓库相对路径，拒绝绝对路径、`..` 穿越及越界符号链接；符号和 blob 指纹用于消除仅凭行号定位的不稳定性。

`content.actions` 是经验数据，不是自动执行授权；涉及命令时使用 argv 数组与相对 cwd，执行方仍要按当前任务权限判断，不能把记忆内容直接交给 shell。隐藏测试答案、密钥、凭证、完整私有请求等不应进入可复用内容；必要的原始证据使用独立权限与保留策略。

`applicability.scope_level` 取 `workspace | project | general`；它描述适用范围，不改变访问权限。首期代码条件支持 `exact_tree`、`referenced_blobs` 或 `manual_review` 三种匹配模式：无法自动证明匹配时返回需复核，不假装适用。依赖条件指定生态、包名与版本表达式，不能混用不同生态的版本比较规则。

`verification.state` 取 `unverified | verified | rejected`，证据等级存于 claims；`verified` 只表示声明的 claims 被验证，不表示全部任务或硬件通过。生命周期状态与校验状态分开：被验证的候选仍可能未提交，已提交的版本也可能已过期。

### 示例 A：成功修复候选（完整可解析 JSON）

以下是虚构的通用 Python 项目示例，用于说明格式，不是本仓库的实际修复记录。候选只携带 agent 可提交的字段，scope、验证结论、时间、hash 和最终版本由服务补齐；证据 ID 必须由执行器预先登记。

```json
{
  "schema_version": "1.0",
  "idempotency_key": "session-example:proposal:1",
  "kind": "strategy",
  "domain": "coding",
  "subtype": "bug_fix",
  "title": "分页读取不能把空页等同于结束",
  "summary": "当接口以 next_cursor 表示结束时，空 items 仍可能有后续页。",
  "content": {
    "problem": "读取中间空页后提前结束，遗漏后续结果。",
    "conditions": ["接口契约明确以 next_cursor=null 标记结束"],
    "actions": [
      {"description": "依据 next_cursor 判断终止，并保留循环游标保护。"},
      {"description": "验证空中间页、正常结束和重复游标场景。"}
    ],
    "expected_result": "空中间页不会造成结果遗漏，异常游标不会导致无限循环。",
    "avoid": ["不能套用于明确以空 items 为终止条件的其他接口"],
    "unknowns": ["未验证真实服务的速率限制行为"]
  },
  "applicability": {
    "scope_level": "workspace",
    "match_mode": "manual_review",
    "paths": ["src/client/pagination.py"],
    "symbols": ["iterate_pages"],
    "dependencies": [],
    "invalidate_when": ["分页 API 终止契约变化"]
  },
  "evidence": [
    {"evidence_id": "ev-before-01", "type": "test_run", "supports": "problem"},
    {"evidence_id": "ev-after-01", "type": "test_run", "supports": "expected_result"}
  ],
  "relations": {"derived_from": [], "supersedes": [], "conflicts_with": []}
}
```

候选 API 另外通过调用上下文获得 project/workspace/Session；不接受模型自行传入 `verified=true` 或其他租户 scope。验证器检查上述证据对应的测试与代码状态，若只验证空中间页而未验证重复游标，则必须缩小 expected_result 或保留为未验证，不能全量批准。

### 提交后的标准信封

最终记录包含候选中的领域内容，并增加以下服务端信封；下面的尖括号是展示占位符，不是可导入值。

```yaml
schema_version: "1.0"
id: "<service-assigned-id>"
revision: 1
scope:
  tenant: "<authorized-tenant>"
  business: "<authorized-business>"
  environment: dev
  namespace: coding
  project_id: "<bound-project-id>"
  visibility: private
verification:
  state: verified
  claims:
    - level: reproduced
      evidence_ids: [ev-before-01]
    - level: tested
      evidence_ids: [ev-after-01]
  limitations: ["未验证真实服务的速率限制行为"]
  verifier_id: coding-verifier
  verifier_version: "1"
  verified_at: "<UTC timestamp>"
provenance:
  task_id: "<task-id>"
  session_id: "<session-id>"
  workspace_id: "<workspace-id>"
  agent: "<client-name-and-version>"
  observed_at: "<UTC timestamp>"
  code_state:
    head: "<git-object-id>"
    diff_sha256: "<64-lowercase-hex>"
    untracked_manifest_sha256: "<64-lowercase-hex>"
    environment_fingerprint: "<64-lowercase-hex>"
lifecycle:
  status: committed
  created_at: "<UTC timestamp>"
  updated_at: "<UTC timestamp>"
  review_after: null
  expires_at: null
integrity:
  canonicalization: relax-json-v1
  content_sha256: "<64-lowercase-hex>"
  record_sha256: "<64-lowercase-hex>"
```

`code_state` 不仅保存 HEAD，还记录修改和任务相关未跟踪文件；fingerprint 的覆盖清单由执行器保存，不能只存一个无法解释的 hash。证据对象至少含 argv、cwd、开始／结束时间、退出码、测试收集／通过／失败／跳过数量（非测试命令可为空）、代码状态、环境摘要和受控输出引用；含敏感环境变量的完整 env 不入库。

`relax-json-v1` 定义为 UTF-8、对象键递归排序、无多余空白、数组保持顺序；拒绝重复键、NaN/Infinity 和浮点数，需小数的扩展值用十进制字符串表达。字符串保留原始 Unicode 内容，不自动改写代码或换行。`content_sha256` 计算 kind/domain/subtype/title/summary/content/applicability，去重另加授权 scope；`record_sha256` 计算除 integrity 本身外的完整记录。hash 用于完整性与去重，不替代来源认证或证据验证。

导入时严格校验必需字段、枚举、长度和 schema；未知 major 版本拒绝，未知普通字段拒绝，扩展只进 `extensions`。导入的验证声明视为外部声明，目标空间的验证器或授权审核者重新建立信任。后续应交付对应 JSON Schema、标准编码样例与跨存储契约测试；本草案尚未提供可执行 schema 校验器。

### 示例 B：失败教训

同样使用 v1 字段，`kind=lesson`、`subtype=pitfall`。例如“只提高超时没有解决请求积压”：problem 写观察到的队列增长，conditions 写负载和并发条件，actions 写已尝试的超时调整，expected_result 写“不能据此认为容量提升”，avoid 写适用范围。若无调用栈或容量证据，unknowns 必须保留“尚未定位根因”，不能编造为死锁。证据记录实际前后指标；这是一次受限失败经历，只有补齐可归因证据后才可提升为可复用教训。

### 示例 C：项目约定

使用 `kind=strategy`、`subtype=project_convention`，内容只摘录与任务相关的约定，evidence 指向规范文件、内容 hash 与适用目录；验证 claim 为“来源一致”。规范更新时索引失效，不自动把旧约定重新发布成新规范。比如当前项目的版权头与日志接口约定应链接到有效项目指令，并在使用前核对，不能仅依据某次 agent 的口头总结。

### 给模型看的紧凑卡片

模型默认读摘要卡片，不读整条存储信封；展开和再次检索共同计入任务 token 预算。卡片由确定性 renderer 从已授权版本生成，其实际字节进入 read receipt。

```text
[Memory mem-example@1 | snapshot snap-example | strategy/bug_fix]
结论：分页接口以 next_cursor=null 结束时，不能因中间页为空而终止。
适用：src/client/pagination.py::iterate_pages；当前代码需要复核。
行动：核对终止契约；检查游标循环保护；执行相关回归。
证据：问题已复现，指定回归通过；未验证真实服务限流。
来源：本项目私有经验；详情使用 memory_get，保持当前快照。
```

## 15. Coding 首期验收增量

在第 9 节通用验收上增加以下场景，优先用临时 Git 仓库和轻量进程完成，只有训练导出验证需要真实训练环境：

- 两个 worktree 同时修复相似问题，候选互不可见；提交后下一任务按权限读取，不混用 dirty diff。
- 切换分支、rebase、修改相关符号或规范文件后，旧经验被标记需要复核；无关文件变化不使全库失效。
- 修复前通过的测试、全 skip、零用例与伪造 evidence_id 不能把修复候选提升为成功策略。
- JSONL 导出再导入后内容和关系保持一致；未知 schema、重复键、越界路径、跨 scope 证据被拒绝。
- 压缩上下文／续接会话仍保留实际读内容和版本；记忆不可用的普通 coding 降级与训练失败策略分别生效。
- 用相同任务比较无记忆、固定项目包、持续更新三组，测定位工具调用数、首次有效修复时间、回归通过率、重复错误率及总 token；同时检查是否错误复用过期补丁。

## 16. MemOS 复用评估与接入决策

评估日期：2026-11-06。源码检查基于 MemTensor/MemOS 提交 `d326a6419467c2205041b58533b0ebfdf4f38173`，Python 包声明版本为 2.0.33；仅检查源码与文档，未安装、部署或完成兼容性实测。以下判断不能替代集成验收。

**建议：把 MemOS 作为可选的检索／经验处理后端；Relax 保留标准记录、验证提交、隔离与训练快照的所有权。** 可直接复用现有能力缩短工程周期，但现有公开接口不足以证明可直接满足全部训练一致性契约。

### 能复用什么，仍需补什么

| Relax 需求 | MemOS 已检查的能力 | 接入决策 |
| --- | --- | --- |
| 独立私域服务 | Python REST 服务，示例部署使用 Neo4j 与 Qdrant | 可作为独立服务候选；与训练 Python 环境分开 |
| 检索、写入、反馈、删除 | product API、读写 cube 参数、附加 metadata、异步写入 | 封装 adapter；异步入队回执不能视为提交完成 |
| 记忆历史 | `TextualMemoryMetadata.version/history` 与 archived memory | 可用于来源映射；不能等价于整个训练批次的不可变快照 |
| 项目本地经验 | TypeScript Local Plugin，SQLite、本地检索与 Viewer | 参考其产品与检索实现；作为独立候选后端验证，不当作 Python 服务的 SQLite 模式 |
| Agent 工具 | Python MCP server 已有 search/add/update/delete 等工具 | 复用协议经验，向 agent 暴露 Relax 限权后的四个工具 |
| 多业务隔离 | cube 路由、用户字段；仓库另有鉴权相关实现 | 必须补充身份到 cube 的服务端映射和越权测试，参数名字不是授权证明 |
| 规则优先与私域模型 | 可配置模型／embedding；示例环境含外部模型端点 | 核验所选路径是否依赖模型；全部替换为私域端点或禁用，不默认认为完全离线 |
| 快照／staging／奖励门控 | 所检查公开请求模型没有我们的 snapshot/cohort/奖励提交协议 | 由 Relax 实现，不把普通 Session ID 或历史版本误作隔离边界 |
| token/mask 与恢复 | 未验证存在 Relax SessionForest 对应契约 | 由 Runtime 与 read receipt 实现，后端不能代替 |

Python 服务、本地插件、托管 Cloud API 是不同产品路径，部署、模型依赖和接口不能混为一谈。当前 Local Plugin 文档列出 OpenClaw、Hermes、DeepSeek Harness 适配，不能据此声称 Codex／Claude Code 已经开箱即用。它们可经 Relax MCP 适配使用，但需要实际客户端验证。

### 推荐结构

```text
Coding Agent / Relax Runtime
            |
Relax Memory Gateway (MCP / HTTP)
            |
Authorization + Staging + Verification + Immutable Records + Read Receipts
            |
MemoryBackend Adapter
    |                    |
Local baseline       MemOS self-hosted
                     (retrieval / extraction / indexing)
```

Memory Record v1 保持权威记录，MemOS metadata 保存 `relax_memory_id`、`relax_revision`、`content_hash` 与索引代次；维护一条规范记录与多个抽取片段的映射。检索结果必须能映射回已授权、已提交的规范版本。MemOS 自动摘要或演化得到的新结论属于新候选，不能无校验覆盖 v1 内容。

首期优先采用“冻结经验包 → 冻结检索索引 → 采样 cohort”的路径。只有索引构建完成、条目映射和校验和一致、且能够阻止后台改写后，才发布 manifest。若所选 MemOS 路径无法可靠关闭读时写入、后台演化或跨 cube 检索，则将该快照物化到独立只读检索实例，或用 Relax 的本地基线索引执行训练检索；MemOS 继续承担离线候选加工。不能仅为 cube 加上 snapshot 名字就认定它不可变。

仅从实时库取 top-k 后再按旧版本过滤不够：新条目可能挤掉旧快照中的合法命中，导致召回与排序发生变化。因此快照约束必须作用于候选检索阶段，不能只做返回结果过滤。已发生的读取仍保存最终内容与排序，恢复直接复用回执。

默认通过 HTTP 接入 MemOS 独立进程／容器，避免直接将其完整依赖安装进 Relax 训练环境。当前 Python 包声明 Python >=3.10，并对 OpenAI SDK、Transformers 等依赖设有版本范围；实际是否冲突需对照选定训练镜像验证。仓库根许可证标记 Apache-2.0；正式打包时保留适用声明，并核对实际纳入的子包与依赖许可。

### PoC 准入门槛

先选择固定 commit 的 Python 自部署服务完成以下验证，再决定是否进入首期生产交付；Local Plugin 的接入单独评估，避免同时维护两套适配造成失焦：

1. 全部服务与辅助模型只使用私域资源；执行离线／出站受限实验并记录实际模型调用成本。
2. v1 写入、检索、去重与更新后能回溯原始记录；异步重试不产生重复的已提交经验。
3. 两业务相同 query 无交叉命中；伪造 user/cube、直接详情读取与证据下载均不可越权。
4. 同一 cohort 的两个 Session 不读彼此候选；后台更新和服务重启不改变旧快照的候选集合与内容。
5. 对接一个 coding harness，证明实际模型输入、导出与读取回执一致；后续再验证真实优化器更新。
6. 与轻量本地基线比较检索质量、端到端延迟、辅助模型 token、运维与存储成本，收益不足时保留为可选后端。

MemOS 的公开 benchmark 结果不直接作为 Relax/AIO 的效果预期；三组对照仍按第 9 节执行。此路线允许借鉴或接入 MemOS，同时维持“无需指定外部产品即可运行”的框架能力边界。

检查依据（固定源码版本）：[Python 依赖](https://github.com/MemTensor/MemOS/blob/d326a6419467c2205041b58533b0ebfdf4f38173/pyproject.toml)、[请求模型](https://github.com/MemTensor/MemOS/blob/d326a6419467c2205041b58533b0ebfdf4f38173/src/memos/api/product_models.py)、[记忆历史](https://github.com/MemTensor/MemOS/blob/d326a6419467c2205041b58533b0ebfdf4f38173/src/memos/memories/textual/item.py)、[MCP 工具](https://github.com/MemTensor/MemOS/blob/d326a6419467c2205041b58533b0ebfdf4f38173/src/memos/api/mcp_serve.py)、[Local Plugin](https://github.com/MemTensor/MemOS/blob/d326a6419467c2205041b58533b0ebfdf4f38173/apps/memos-local-plugin/README.md)、[部署环境示例](https://github.com/MemTensor/MemOS/blob/d326a6419467c2205041b58533b0ebfdf4f38173/docker/.env.example)。


## 17. 已实现的首个可运行切片

本轮按基础知识／经验记忆需求实现，不需要 GPU，也不修改训练参数、Controller、Service 或 Launcher。

- `relax/memory/`：标准库 SQLite/HTTP 服务、管理员与任务绑定凭证、不可变历史记录、私有候选、人工审核／可信验证方提交、精确去重、修订冲突检测、手动过期、物化快照、读取回执与重放。
- MCP stdio：search/get/propose/feedback 四个工具；生成项目／任务凭证和客户端配置片段。模型工具不能指定 namespace 或提交审核结论。
- MemOS 自部署 API 适配：显式绑定 user/cube，解析嵌套返回结构，跨 cube 结果拒绝；导入只产生待审候选，导出是管理员显式复制，未提供跨系统 exactly-once 保证。
- `scripts/tools/memory.sh`：`up`／`local` 直接前台启动 Python 服务，`status` 检查接口，`verify` 验证本地闭环；通过显式 `MEMOS_ENDPOINT` 执行 `verify-memos`。无需 Dockerfile 或额外容器，Ctrl-C 停止后保留数据。
- [操作 skill](../../skills/memory/SKILL.md) 与[操作手册](../../skills/memory/references/operations.md)：本地启动、项目接入、候选审核、MemOS 部署和排障。

入口命令：

```bash
bash scripts/tools/memory.sh up
# 在另一终端验证已经运行的本地服务
bash scripts/tools/memory.sh verify
```

本地启动只需要 Python 3.10+、可写持久化目录和可用端口，不需要额外 Python 依赖或模型服务。MemOS 是外部可选接口：由服务提供方维护其部署，Relax 配置 endpoint、user/cube 和鉴权后导入／导出。启动脚本不再管理 MemOS、Neo4j、Qdrant 或模型部署。

本地服务已完成实际 HTTP 与独立 MCP 子进程闭环；CPU 回归覆盖隔离、幂等、修订、快照恢复和 MemOS 协议返回。当前没有可用的外部 MemOS endpoint，因此真实 MemOS 接口检索仍未验证；`verify-memos` 用于已有服务的接入验证，Docker 不属于本模块的运行或验证前提。

初版限制：v1 采用核心字段子集；当前检索为关键词与 byte 预算，不声称精确 token 计数。审核接口记录可信方决定，不自行验证测试证据。独立中心 Demo 已提供 TTL 调度与单管理员管理页；凭证轮换、通用共享发布 UI、Runtime 奖励门控／cohort 自动绑定和 HA 尚未实现。新任务需要重新创建快照绑定以读取更新。MemOS 导入是检索结果的审核后物化，不是整个上游 cube 的原子快照。
