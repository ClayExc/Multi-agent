# CHAIN-P1-VPN-READONLY-01

## 授权

```text
CHAIN_ID=CHAIN-P1-VPN-READONLY-01
STATUS=ACTIVE
AUTHORITY=S1-ARCH
AUTHORITY_REF=docs/team/chain-authorizations/CHAIN-P1-VPN-READONLY-01.md
EXECUTION_MODE=ORDERED
RISK_CLASS=R2
AUTO_WAKE=enabled
MAX_HOPS=6
USER_GATE=FINAL_S1
CONTRACT_CONTENT_DIGEST=sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc
FINAL_GATE=S7-INTEGRATION->S1-ARCH
MAX_LOCAL_REPAIR_ATTEMPTS=1
```

本链交付产品里程碑 P1 的最小可验收垂直切片：合成 VPN 请求经
Command Intake 进入确定性图，缺失环境字段时可中断追问并续跑；字段齐全
后只通过 MCP Gateway 检索租户和 ACL 允许的知识，生成带可回查引用的结果
引用，并以 Task `COMPLETED` 结束。

P1 是产品路线编号，不等于历史工程链 `CHAIN-M1-PLATFORM-01`。本链不修改
公共 ContractSet，也不把候选数据集或功能状态标记为发布级 frozen。

## 功能与完成定义

```text
FEATURE_IDS=FP-FLOW-002,FP-FLOW-003,FP-AGT-001,FP-CTX-001,FP-MCP-001,FP-MCP-002,FP-SEC-003,FP-EVAL-003,FP-OPS-002
```

完成时必须同时满足：

1. `initial_message_ref` 只由受信内部 Port 解析为脱敏请求观察；不得把原始
   消息扩展进公共 `TaskCommand`、Graph State、Trace 或证据。
2. 缺失 `environment` 时 Task 进入 `WAITING_USER`，Interrupt 前无外部
   副作用；恢复后只执行一次知识检索并确定性完成。
3. Knowledge Tool 只经 MCP Gateway 调用。租户、ACL、用途和数据分类过滤
   先于匹配/排序，失败时默认拒绝。
4. 每条答案至少包含文档引用、章节和版本；结果正文经内部结果 Port 保存，
   Task 只暴露 `result_ref`。
5. 20 条固定候选 Case 逐条输出确定性断言结果，覆盖正常、缺字段、无结果、
   错租户/ACL、恶意查询、恢复和重复投递；不得预填成功率。
6. Studio 与 Worker 继续使用同一个 graph factory，安全投影可观察路由、
   Interrupt/Resume、知识调用次数、引用数量和终态，但不暴露原始内容、
   ACL 细节、密钥或隐藏思维链。

## 非目标

- 真实 OpenAI/Claude Provider、LiteLLM 路由或外部账号调用。
- Ticket/Asset/Notification 写工具、审批、工单创建或其他副作用。
- Web 页面、通用向量/混合检索、Rerank、附件或多模态。
- 新数据库表、Migration、RLS、Compose 或 Redis 语义变化。
- 公共 Schema、ContractSet、ADR、Registry 或 Traceability 状态变化。
- 发布级 120/36 数据集、LLM-as-Judge 结论或任何量化提升声明。

## 顺序

```text
S5-CORE
  -> S3-PLATFORM
  -> S2-RUNTIME
  -> S4-QUALITY
  -> S7-INTEGRATION
  -> S1-ARCH(FINAL_GATE)
```

这是严格有序链。S5 先固定内部请求观察、结果引用与 Domain Pack 输入；
S3 再固定知识工具的安全输出；S2 才实现产品图；S4 在完整切片上做独立
黑盒；S7 对精确线性候选执行最终组合复现。后序角色不得提前写入。

## Step 1：S5-CORE 领域与应用边界

```text
STEP_ID=P1-VPN-01-S5
SESSION_ROLE=S5-CORE
WORK_PACKAGE=WP-011
ATTEMPT_ID=WP-011-a6
BASE_COMMIT=WAKE_MESSAGE.ACTIVATION_COMMIT
UPSTREAM_HEADS=none
WORKTREE=E:\workspace\Multi-agent-s5
WRITE_SCOPE=apps/api/**,packages/domain/**,packages/application/**,domain-packs/it-service/**,tests/core/**
MODE=IMPLEMENTATION
UNLOCK_CONDITION=S5 branch and Worktree clean; current S5 Head is ancestor of ACTIVATION_COMMIT; ff-only reaches exact ACTIVATION_COMMIT; ContractSet digest matches
REVIEWER=S3-PLATFORM
NEXT_ROLE=S3-PLATFORM
NEXT_ATTEMPT_ID=WP-020-a2
HANDOFF=tests/core/evidence/WP-011-a6-HANDOFF.md
```

S5 必须：

1. 在 Application 层固定受信的请求引用解析 Port 与结果 Artifact/引用 Port；
   具体命名可调整，但输入输出、租户绑定、稳定错误和幂等语义必须有类型。
2. 保持公共 API 只接收 `TaskCommand`、只查询 Task 投影；不得把原始消息或
   回答正文塞入公共 Task/Command Schema。
3. 完成 `vpn_support` Domain Pack 的环境字段规则、合成知识样本、请求
   Fixture 和引用预期；Domain Pack 仍为 data-only。
4. 覆盖正常解析、缺失环境、未知引用、错租户、引用篡改、结果重复保存和
   稳定错误映射。
5. 不修改 `pyproject.toml`、`uv.lock`、`Makefile`；若需要新依赖或共享文件，
   立即停链上报。

## Step 2：S3-PLATFORM 知识工具安全边界

```text
STEP_ID=P1-VPN-02-S3
SESSION_ROLE=S3-PLATFORM
WORK_PACKAGE=WP-020
ATTEMPT_ID=WP-020-a2
BASE_COMMIT=<Step-1-NEW_HEAD after ff-only>
UPSTREAM_HEADS=S5-CORE:<Step-1-NEW_HEAD>
WORKTREE=E:\workspace\Multi-agent-s3
WRITE_SCOPE=apps/mcp-gateway/**,packages/tool-contracts/**,packages/policy/**,packages/security/**,mcp-servers/knowledge/**,tests/platform/**
MODE=IMPLEMENTATION
UNLOCK_CONDITION=S5 Handoff consumer ACCEPT and S3 ff-only reaches exact S5 Head
REVIEWER=S2-RUNTIME
NEXT_ROLE=S2-RUNTIME
NEXT_ATTEMPT_ID=WP-010-a3
HANDOFF=tests/platform/evidence/WP-020-a2/HANDOFF.md
```

S3 必须：

1. 将 `knowledge.search.v1` 固定为只读工具，输出脱敏摘要与稳定引用元数据：
   `source_ref`、文档版本、章节、内容摘要/哈希和分类，不返回内部 ACL 清单。
2. 在候选进入匹配/排序前验证双主体能力、租户、Purpose、Scope、数据分类
   上限和记录 ACL；未知或缺失属性必须默认拒绝。
3. 更新本地 Tool Schema Pin 与 Schema Hash，并证明旧 Pin 失败关闭；该变化
   不得修改 `contracts/**`，也不使任何旧写审批继续有效。
4. 提供供 Worker 使用的 Gateway 调用边界和确定性 Fake；S2 不得直连
   `KnowledgeMcpAdapter` 或上游 MCP。
5. 覆盖零结果、错租户、越级分类、恶意查询、Schema 漂移、上游错误和
   敏感字段泄漏；逻辑越权读取数必须为 0。

## Step 3：S2-RUNTIME 产品图

```text
STEP_ID=P1-VPN-03-S2
SESSION_ROLE=S2-RUNTIME
WORK_PACKAGE=WP-010
ATTEMPT_ID=WP-010-a3
BASE_COMMIT=<Step-2-NEW_HEAD after ff-only>
UPSTREAM_HEADS=S3-PLATFORM:<Step-2-NEW_HEAD>
WORKTREE=E:\workspace\Multi-agent-s2
WRITE_SCOPE=apps/worker/**,packages/graph/**,packages/agent-runtime/**,packages/context/**,tests/runtime/**,langgraph.json
MODE=IMPLEMENTATION
UNLOCK_CONDITION=S3 Handoff consumer ACCEPT and S2 ff-only reaches exact S3 Head
REVIEWER=S4-QUALITY
NEXT_ROLE=S4-QUALITY
NEXT_ATTEMPT_ID=WP-030-a4
HANDOFF=tests/runtime/evidence/WP-010-a3-HANDOFF.md
```

S2 必须：

1. 用现有同源 graph factory 实现确定性 VPN
   `intake -> clarify/interrupt -> knowledge -> respond` 产品路径；当前
   `service_read` 在该单 Agent 切片中只能确定性跳过，不得产生旁路读取。
2. 只消费 S5 的脱敏 Request Observation 和 S3 的 Gateway 边界；不得直连
   数据库、上游 MCP、企业网络或把 Provider Session 当作状态。
3. 每次调用构建分层 `ContextEnvelope`；知识引用进入最小结果上下文，原始
   文档、内部 ACL、凭据和完整工具 Payload 不进入 Graph State。
4. 缺失环境使用动态 Interrupt；Checkpoint 恢复、重复 Command、Worker
   重启和节点重进不能产生重复知识调用或不同 `result_ref`。
5. Studio 安全投影增加可复核的节点、路由、暂停/恢复、知识调用次数、引用
   数量和终态，不泄漏请求/答案正文或隐藏思维链。
6. 使用确定性 Runtime/Fake 完成本轮；不得加入真实 Provider 或新依赖。

## Step 4：S4-QUALITY 固定用例与黑盒

```text
STEP_ID=P1-VPN-04-S4
SESSION_ROLE=S4-QUALITY
WORK_PACKAGE=WP-030
ATTEMPT_ID=WP-030-a4
BASE_COMMIT=<Step-3-NEW_HEAD after ff-only>
UPSTREAM_HEADS=S2-RUNTIME:<Step-3-NEW_HEAD>
WORKTREE=E:\workspace\Multi-agent-s4
WRITE_SCOPE=packages/evaluation/**,evals/**,tests/acceptance/**,artifacts/acceptance/**的生成器与结构,scripts/acceptance/**
MODE=IMPLEMENTATION
UNLOCK_CONDITION=S2 Handoff consumer ACCEPT and S4 ff-only reaches exact S2 Head
REVIEWER=S7-INTEGRATION
NEXT_ROLE=S7-INTEGRATION
NEXT_ATTEMPT_ID=WP-040-a6
HANDOFF=tests/acceptance/evidence/WP-030-a4-HANDOFF.md
```

S4 必须：

1. 建立恰好 20 条 VPN 功能候选 Case、数据卡和本地哈希清单；它们不进入
   公共 ContractSet Registry，不得宣称 120 条冻结数据集已完成。
2. 从 API/Application/Worker/Gateway 的公开或内部稳定边界黑盒验证字段
   补全、Interrupt/Resume、引用、零结果、错误映射、错租户/ACL、恶意查询、
   重复投递和结果幂等。
3. 确定性规则优先；Judge 不得覆盖租户、ACL、状态、工具调用次数、引用
   完整性或实际成功断言。
4. 输出逐 Case 结果、固定分母、失败保留、证据 Manifest 与 Secret/PII
   扫描；不得手工填写成功率。
5. 本 Attempt 不修改 `web/**`、`packages/retrieval/**` 或共享 Makefile。

## Step 5：S7-INTEGRATION

```text
STEP_ID=P1-VPN-05-S7
SESSION_ROLE=S7-INTEGRATION
WORK_PACKAGE=WP-040
ATTEMPT_ID=WP-040-a6
BASE_COMMIT=<Step-4-NEW_HEAD after ff-only>
UPSTREAM_HEADS=S4-QUALITY:<Step-4-NEW_HEAD>
WORKTREE=E:\workspace\Multi-agent-s7
WRITE_SCOPE=scripts/integration/**,tests/integration/**,artifacts/integration/**的生成器与结构
MODE=IMPLEMENTATION
GATE_LEVEL=RELEASE
UNLOCK_CONDITION=S4 consumer Handoff ACCEPT and S7 ff-only reaches exact S4 Head
REVIEWER=S1-ARCH
NEXT_ROLE=S1-ARCH
HANDOFF=tests/integration/evidence/WP-040-a6-HANDOFF.md
```

本链改变租户/ACL 检索边界，按 `INTEGRATION_GATES.md` 使用 RELEASE，而不是
因无 Migration/Lock 变化降为 STANDARD。S7 必须复算 Head、范围、Handoff
Hash、ContractSet、知识 Tool Schema Hash、20 Case 清单、Workspace/Lock、
产品/安全/Acceptance 测试、Wheel、Secret Scan 和隔离 Compose；证明错租户
成功检索数为 0、Knowledge MCP 不存在旁路、Interrupt 恢复无重复调用，
并输出逐阶段耗时和清理结果。S7 不批准合并。

## 停止条件

除通用协议外，以下情况立即暂停并上报 S1：

1. 需要修改 `contracts/**`、ADR、Traceability、公共 Registry 或现有完成
   定义。
2. 需要真实 Provider、API Key、生产数据、企业网络、外部发布或公网 Tunnel。
3. 需要 Ticket/Asset/Notification 写动作、审批、Migration、S6 路径、
   `pyproject.toml`、`uv.lock`、`Makefile` 或其他共享文件。
4. 原始请求、知识正文、ACL、Secret、PII 或隐藏思维链进入 Graph State、
   Trace、Audit、Security Event、Handoff 或证据。
5. Worker/Agent 绕过 MCP Gateway，或过滤发生在检索候选形成之后。
6. Task/Checkpoint/Provider Session/Studio Thread 的状态权威发生混淆。
7. Head、Handoff、工作树、路径或门禁不一致；`--ff-only` 无法形成单一
   线性候选；同一问题的局部返修次数耗尽。

## 自动唤醒

- 每一步只唤醒上面列出的唯一 `NEXT_ROLE`。
- `DEDUP_KEY=CHAIN_ID/STEP_ID/ATTEMPT_ID/INPUT_HEAD`。
- 正常路径不返回 S1；S7 最终唤醒 S1。
- S1 final gate 必须停在 `USER_GATE_REQUIRED=yes`，不得自动合并或启动
  下一链。
