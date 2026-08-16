# WP-102-a1 S3-PLATFORM Handoff

## 基本信息

- Work Package：WP-102
- Attempt ID：WP-102-a1-final
- Chain ID：CHAIN-M9-GOVERNANCE-01
- Step ID：M9-02C-S3-WP102-FINAL
- 责任会话：S3-PLATFORM
- 接收会话：S2-RUNTIME
- 交接策略：CONSUMER_GATE
- 功能 ID：FP-MCP-006、FP-SEC-005、FP-SEC-006、FP-SEC-007
- WP-102 基线：`46576b345d0f6c54b70af218009e311ac260a7db`
- S3 生产者检查点：`c1db8f744199b4baf1683c0d6e45667137563c3e`
- S4 Fixture Join：`0fd2a098d9d6914a96a31fe8e5b0fc2cf77236a9`
- 分支/最终提交：`codex/s3/wp-101-m9-policy` / `<this-handoff-commit>`
- ContractSet 摘要：`sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：PASS_HANDOFF；不代表 Release

## 完成内容

- Capability Handle 精确绑定 tenant、Security Context、tool、resource、action digest、
  policy version、execution、audience、scope、use 和 TTL；Gateway 对每次使用执行原子
  `consume`，invoke/readback 使用独立 Handle，重放失败关闭。
- 新增开发态 `SecretProviderPort`。Secret 明文只在 Gateway 上游调用栈的受限 Lease
  内可见；Lease 不可 JSON 序列化，退出时清零，异常、日志和对象表示不携带原值。
- 集中 Credential/DLP/Prompt-Injection 注册表覆盖工具参数、MCP 内容、ToolResult、
  readback/reconciliation 和 Audit/Security/Debug 投影；Finding 只携带稳定规则、路径和
  surface，不复制危险原值。
- 参数、Capability 和 Secret 授权拒绝均发生在 ledger 占位及上游调用前；逻辑写入和
  上游调用为 0。危险写响应或回读保持 `UNKNOWN`，不伪造成功终态。
- S4 消费者 Fixture 已迁移必填 Capability 绑定和原子消费，并更新集中 DLP 稳定码
  `PLATFORM_DLP_BLOCKED`；原共享门禁 10 个失败全部恢复。

## 修改范围

| 路径 | 内容 | Owner |
|---|---|---|
| `apps/mcp-gateway/**` | Gateway 顺序、Capability/Secret/DLP 接入、Port、信号和生命周期投影 | S3 |
| `packages/security/**` | Capability 模型、SecretProvider、内容安全注册表和稳定错误码 | S3 |
| `tests/platform/**` | Capability、DLP、Secret、Gateway 安全回归和证据 | S3 |
| `tests/acceptance/platform_security/**` | S4 消费者 Fixture 迁移及独立证据 | S4，经 S1 线性 Join |
| `packages/tool-contracts/**` | 无实际差异 | S3 |

- `contracts/**`、Runtime、Data、API、Web、Infra、根共享文件和依赖锁：无变化。
- 数据库、Migration、环境变量和公共 Contract：无变化。

## 验证

| 门禁 | 结果 | 来源 |
|---|---|---|
| WP-102 定向 Capability/DLP/Gateway 组合 | PASS，86 passed | S3 Producer Handoff 复用 |
| `tests/platform` | PASS，424 passed | S3 Producer Handoff 复用 |
| 影响范围 Ruff | PASS | S3 Producer Handoff 复用 |
| strict Mypy | PASS，25 source files | S3 Producer Handoff 复用 |
| Contract Conformance | PASS | S3 Producer Handoff 复用 |
| Secret Scan | PASS，2 passed | S3 Producer Handoff 复用 |
| S4 目标 Fixture | PASS，33 passed | S4 Fixture Handoff 复用 |
| 共享 Security | PASS，252 passed | S3 在 Join Head 精确复跑 |

最终共享门禁命令：

```text
uv run --all-packages --all-groups --locked python -B -m pytest tests/core/test_security.py tests/core/test_oidc_api.py tests/runtime/security tests/data/security tests/platform/security tests/platform/test_gateway_security.py tests/platform/test_identity_boundary.py tests/acceptance/platform_security tests/experience/test_secret_scan.py -q
```

结果：`252 passed in 10.10s`。本步骤按 S1 指令未重复 86/424、Ruff、Mypy、Contract
或 Secret Scan；上述结果由未变化的 S3 Producer Handoff 精确复用。

## 证据与工程控制面

- WP-101 Handoff：`tests/platform/evidence/WP-101-a1-HANDOFF.md`，
  `sha256:3b169079b636d199a39921e918b00083cfab4c77e24c3c504caa9e60f60358e3`。
- WP-102 Producer Handoff：`tests/platform/evidence/WP-102-a1-PRODUCER-HANDOFF.md`，
  `sha256:63b8670386e81703e847a5784badc9b2919dafd94943e056e260982fa8e1514c`。
- S4 Fixture Handoff：
  `tests/acceptance/platform_security/evidence/WP-102-a1-FIXTURE-HANDOFF.md`，
  `sha256:6d8b8c1111049d7c63342289bea9f2963bb025d4101b16d5b38e1a6aedf31b38`。
- 初始 Context Capsule：`.flowpilot-engineering/m9/wp101-capsule.json`；声明的规范化摘要
  `sha256:227fe5666fa0e1a0d714bb0abc57502169346d1b8f75651e63c330a58a71dec3`，
  当前物理文件摘要
  `sha256:c83b3dffc7a1ebd7fbc520e0b1861a5b694c24413b3c716162da23a9fa818eb5`。
- 最终 Join 的 no-change 测试选择：
  `.flowpilot-engineering/m9/wp102-test-selection.json`，
  `sha256:432e2f49d18d92e13ad3c7caa9ff27fa4848816fee5cabd414f114dc056e5431`。
- 最终 Join Attempt Report：`.flowpilot-engineering/m9/wp102-attempt-report.json`，
  `sha256:a3c08e3ca4972d12b41d0f971bf3d109735149932850b630f4fb89fb2f2617ea`；
  报告内 `capsule_sha256=02a0291a1f3c05a3084026bb454cce356a0952d44285f29edfa5d982b2339cac`。

最终工程控制面报告以相同 Base/Target `0fd2a09` 表达 S1 已批准 Join 后的 no-change
消费复核；S3 生产者变化由 Producer Handoff 表达，S4 变化由 Fixture Handoff 表达。
选择器保守返回 `tier=FULL`、`fallback_required=true`。本步骤显式授权只复跑共享
Security 并复用未变化的产品、类型、Contract 与 Secret 门禁，因此未把未执行的
full/contract 计划伪报为本步骤新 PASS。

## 安全与失败路径

- 已覆盖 Capability 字段篡改、错 tenant/resource/audience/use、过期、重复消费、
  invoke/readback 复用、Broker/SecretProvider 不可用和上游异常零泄漏。
- 已覆盖工具参数、MCP 内容、写响应、readback/reconciliation 引用与数据、完整
  ToolResult、Audit/Security/Debug 投影中的凭据与高置信 Prompt Injection。
- 拒绝发生在 ledger 与上游调用前；危险写结果维持 `UNKNOWN`，不会通过 DLP 失败
  伪造 `VERIFIED`。
- 未通过降级可选字段、legacy broker、非原子消费或旧错误码兼容旧 Fixture。

## 已知风险与非目标

- 当前 SecretProvider 是开发态内存实现，不冒充 Vault/KMS 或多实例生产存储；生产
  Secret 后端和持久 Capability 消费由后续工作包提供。
- 本 WP 不修改公共 Contract，不让 OPA/模型拥有 Task、审批、执行或租户状态。
- 本 Handoff 只允许 S2 消费 M9 内部安全 Port，不代表 Feature 已 RELEASED。

## Capsule 扩展与复用

- `unresolved_dependency`：读取 WP-102、现有 Gateway/Security/Tool Port 和相关测试。
- `security_boundary_change`：复核 Capability、Secret 明文生命周期、DLP 和拒绝顺序。
- `public_signature_change`：复核 Gateway 内部 Port/Fake 的生产者与消费者一致性。
- `test_failure`：定位 S4 旧 Capability Fixture，并由 S1 派发 S4 独立迁移后消费。
- `reviewer_request`：读取 Producer/S4 Handoff 和 Handoff 模板完成最终证据。
- 复用 M9T、WP-101、M8 既有证据；未重跑 M8、WP-094、全仓、Compose 或在线 Provider。

## 子 Agent 使用摘要

```text
SUBAGENTS_USED=1
SUBAGENT_MODES=READ_ONLY_PARALLEL
SUBAGENT_TASKS=wp102_security_audit
SUBAGENT_WRITERS=0
PARENT_REPRODUCED_RESULTS=yes
DUPLICATE_WORK_AVOIDED=producer_gates;s4_fixture_33;m8;m9t
```

## 学习候选

```text
LEARNING_CANDIDATE=Capability consumer fixtures must migrate atomically with required binding and consume semantics
MATURITY=VERIFIED
TRIGGER=Capability Port 新增资源、用途和单次消费约束后，旧消费者 Fixture 在共享门禁失败
MECHANISM=保持 fail closed 并由消费者 Owner 同步迁移，不能由生产者添加 legacy 降级
EVIDENCE=shared Security recovered from 242 passed/10 failed to 252 passed after S4 fixture migration
RESIDUAL_RISK=future external consumers require the same versioned migration discipline
TARGET=ENGINEERING_PLAYBOOK capability-port migration candidate
```

## 接收会话下一步

1. S2 读取 `docs/team/work-packages/WP-103-m9-runtime-dlp.md` 并按 DELTA 热启动。
2. 以 WP-101/WP-102 Handoff 和本 Contract 摘要为输入，将集中 DLP 接入 Context、
   Agent Runtime、Model Gateway 与 Worker；不得复制第二套策略或安全注册表。
3. PASS 后直接唤醒 S5 WP-104；只有 P0/P1、Contract、跨 Owner 或门禁失败回报 S1。

## 机器可读摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M9-GOVERNANCE-01
STEP_ID=M9-02C-S3-WP102-FINAL
WORK_PACKAGE=WP-102
ATTEMPT_ID=WP-102-a1-final
BASE_COMMIT=46576b345d0f6c54b70af218009e311ac260a7db
PRODUCER_HEAD=c1db8f744199b4baf1683c0d6e45667137563c3e
S4_JOIN_HEAD=0fd2a098d9d6914a96a31fe8e5b0fc2cf77236a9
NEW_HEAD=<this-handoff-commit>
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
SHARED_SECURITY=252_passed
HANDOFF=tests/platform/evidence/WP-102-a1-HANDOFF.md
NEXT_ROLE=S2-RUNTIME
NEXT_WORK_PACKAGE=WP-103
S2_WAKE=pending
```

## 可回滚方式

- revert S4 Fixture Join、S3 Producer 检查点及本 Handoff 提交；不要 reset、rebase 或
  force-push。回滚不改变公共 Contract。
