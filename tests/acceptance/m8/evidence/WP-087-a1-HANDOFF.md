# WP-087-a1 S4 身份租户黑盒验收交接

## 基本信息

- Work Package：WP-087
- Attempt ID：WP-087-a1
- Chain ID：CHAIN-M8-IDENTITY-TENANCY-01
- Step ID：M8-04-S4-ACCEPTANCE
- 责任会话：S4-QUALITY / identity-acceptance-verifier
- 接收会话：S1-ARCH
- 交接策略：S1_GATE
- 功能 ID：FP-SEC-001、FP-SEC-002、FP-SEC-007、FP-EVAL-002
- 基线提交：480391479427c70bc60fb71d281e3bcdab71aa7b
- 分支/实现提交：codex/s4/m8-identity-experience / f3342488a2da04a78cb9cfa4edbbed6d94f3a7a7
- ContractSet 摘要：sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
- 状态：部分完成；离线门禁 PASS，真实 Keycloak/PostgreSQL 两段 ENV_BLOCKED

## 完成内容

- 修复 M7 产品执行器对 S2 mandatory `SecurityContextValidationPort` 的消费：先独立构造并存储完整 issuer、azp、roles、scopes、authentication、期限和 source-token-hash 快照，再注入生产 `RuntimeSecurityContextValidator`；未使用 no-op、当前 Command 回显或不安全默认值。
- 保持 M7 `executor_id=flowpilot.m7.enterprise-knowledge`、`executor_version=1.0.0` 和 24 条精确摘要注册不变。
- 新增独立 `flowpilot.m8.identity-tenancy@1.0.0` 执行器，精确摘要注册 6 条 `tenant_isolation` Case。执行证据来自 API→Worker→LangGraph→GatewayClientPort 的离线真实产品组合；安全 Case 的 Judge 始终为空。
- 按 S1 `OPTION_A` 精确扩权修改官方 `scripts/acceptance/run_acceptance.py`，将 M7 与 M8 执行器注册到唯一固定分母事实源并序列化两份 registration。
- 官方 Runner 逻辑定向实测：固定 156 条，30 PASS、126 明确 FAIL、0 skip、0 quarantine；其中 30 个执行结果为 COMPLETED，126 个为 `EXECUTOR_NOT_REGISTERED`。6 条 `rbac_abac_sod` 因 approval gate 未完成继续明确失败。
- 增加独立黑盒：真实 API OIDC 组合的错 audience、过期、撤销和伪造浏览器 tenant/role；真实 MCP Gateway 的跨租户、错 workload audience、过期/篡改 Context、模型提权/工具越界；重启重放模型/工具增量均为 0。

## 未完成与非目标

- 真实 Keycloak→API 网络段未运行：`ENV_BLOCKED_NOT_RUN`。本 WP 禁止 Compose，未用本地 Fake 冒充真实 Keycloak。
- 真实 PostgreSQL/RLS 连接复用段未运行：`ENV_BLOCKED_NOT_RUN`。未用 `MemoryDatabase` 冒充 PostgreSQL。
- 其余 126 条固定 Case 没有产品执行器，继续明确失败；未补 M9 或业务链执行器。
- 未运行全仓、Compose 或 Release；未校准 Judge；不声明 M8、Feature、RELEASED 或 FROZEN。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `packages/evaluation/m7_product.py` | 完整可信身份快照与生产 Runtime validator 注入 | S4 |
| `packages/evaluation/m8_identity.py` | M8 六 Case 精确执行器与结构化证据 | S4 |
| `scripts/acceptance/run_acceptance.py` | 按 S1 精确扩权接入唯一官方 Runner | S4（本 Attempt 精确授权） |
| `tests/acceptance/evaluation/test_m7_product_executor.py` | M7 validator 实际调用证据 | S4 |
| `tests/acceptance/evaluation/test_m8_identity_executor.py` | 唯一匹配、摘要绑定、固定分母和 approval 未实现门禁 | S4 |
| `tests/acceptance/m8/test_identity_tenancy_composition.py` | OIDC/Gateway/恢复/泄漏独立黑盒 | S4 |
| `tests/acceptance/m8/evidence/WP-087-a1-*` | 本交接与结构化 Proof | S4 |

## 契约、数据库与配置变化

- 契约版本：无变化；Contract content digest 保持 `sha256:1cad07...b42a2`。
- Migration：无。
- 环境变量：无。
- 依赖锁与公共配置：无变化。
- 兼容性：M7 执行器身份、版本、24 条 Case 与唯一精确匹配语义保持不变；固定分母仍为 156。

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| M8 acceptance + evaluation + experience 定向 pytest | PASS：124 passed | `WP-087-a1-PROOF.json` |
| 官方固定分母聚合测试 | PASS：156=30 PASS+126 FAIL；0 skip/quarantine | `test_m8_identity_executor.py` |
| Ruff 授权范围 | PASS | `WP-087-a1-PROOF.json` |
| strict Mypy `packages/evaluation` | PASS：15 source files | `WP-087-a1-PROOF.json` |
| strict Mypy 官方 Runner | PASS：1 source file | `WP-087-a1-PROOF.json` |
| Contract Conformance | PASS：20 schemas / 35 cases / 43 semantic negatives / 52 features | `WP-087-a1-PROOF.json` |
| Experience Secret Scan | PASS：2 passed | `WP-087-a1-PROOF.json` |
| 变更源文件高置信 Secret Scan | PASS：0 | `WP-087-a1-PROOF.json` |
| `git diff --check` | PASS | 终端输出 |
| 真实 Keycloak / PostgreSQL Compose | ENV_BLOCKED_NOT_RUN | 本 WP 明确禁止 Compose |

## 安全与失败路径

- 已验证负向路径：错 audience、身份过期、会话撤销、伪造 tenant/role、跨租户 action、Context hash 篡改、模型提出管理员写工具、未注册工具、重启重放。
- 跨租户成功读和写均为 0；失败在 adapter/ledger/outbox 前关闭，并保留不可采样 Audit/Security pair。
- Token、refresh material、code canary、Provider Session、原始请求正文的证据/响应暴露均为 0。
- Judge 不参与安全、租户、终态、Audit 或工具写入断言。
- 未验证风险：真实 Keycloak 网络行为和 PostgreSQL RLS connection reset/reuse，均已显式标为 `ENV_BLOCKED_NOT_RUN`。

## 已知问题

- 整体 acceptance gate 仍为 FAIL：126 个固定 Case 尚无产品执行器。
- WP-087 Work Package 的 S1-owned 状态字段仍由 S1 在复核后裁决，本 Attempt 未越权更新。

## 已知事实与避免重复

- `KNOWN_FACTS`：WP-081～086 Join 已交付；S2 mandatory runtime identity validation 已进入输入 Head；M7 固定分母基线为 24/132。
- `DO_NOT_RECHECK`：未重跑各 Owner 单测、全仓、Keycloak、RLS、Compose、M7 开发历史或 Release。
- `FAILURE_SIGNATURES`：官方 Runner 曾硬编码单一 M7 executor；已由 S1 `OPTION_A` 精确扩权后改为唯一多执行器注册表。mandatory validator 缺失会令产品执行器在组合时失败。
- `REUSED_DECISIONS`：S1 `OPTION_A`；WP-085 Handoff `sha256:c3b3e9...d862a`；WP-086 Handoff `sha256:cbd1f3...51eb`。
- `DUPLICATE_WORK_AVOIDED`：复用 WP-081～086 的 Owner 证据；S4 只在不同的 API/Gateway/固定分母观察边界验证。

## 学习候选

```text
LEARNING_CANDIDATE=none
MATURITY=VERIFIED
TRIGGER=none
MECHANISM=none
STRUCTURE=none
EVIDENCE=tests/acceptance/m8/evidence/WP-087-a1-PROOF.json
RESIDUAL_RISK=真实 Keycloak 与 PostgreSQL/RLS legs ENV_BLOCKED_NOT_RUN
TARGET=none
```

## 子 Agent 使用摘要

```text
SUBAGENTS_USED=2
SUBAGENT_MODES=READ_ONLY_PARALLEL
SUBAGENT_TASKS=wp087-blackbox-matrix,wp087-executor-map
SUBAGENT_WRITERS=0
PARENT_REPRODUCED_RESULTS=yes
REUSED_DECISIONS=WP-081-through-WP-086,S1-OPTION-A
DUPLICATE_WORK_AVOIDED=6
```

## 接收会话下一步

1. S1 核验最终 Head、Handoff/Proof Hash、ContractSet、输入提交到最终 Head 的线性祖先、授权路径与 clean 状态。
2. S1 复算官方 156 固定分母中的 30/126/0/0，以及 M7 24 与 M8 6 的唯一摘要匹配。
3. 真实 Keycloak 与 PostgreSQL/RLS connection reuse 只能在获准的 Compose/集成门禁中补测；当前不得外推为 PASS。
4. S1 保留 WP 状态、Feature、M8 集成和后续链路裁决；本任务不唤醒 S7。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF_OFFLINE_ENV_BLOCKED_LIVE_LEGS
CHAIN_ID=CHAIN-M8-IDENTITY-TENANCY-01
STEP_ID=M8-04-S4-ACCEPTANCE
ATTEMPT_ID=WP-087-a1
NEW_HEAD=<this-handoff-commit>
IMPLEMENTATION_HEAD=f3342488a2da04a78cb9cfa4edbbed6d94f3a7a7
BASE_COMMIT=480391479427c70bc60fb71d281e3bcdab71aa7b
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=FAIL
OFFLINE_GATE=PASS
LIVE_LEGS_GATE=ENV_BLOCKED
FIXED_DENOMINATOR=156
PASSED=30
FAILED=126
SKIPPED=0
QUARANTINED=0
HANDOFF=tests/acceptance/m8/evidence/WP-087-a1-HANDOFF.md
PROOF=tests/acceptance/m8/evidence/WP-087-a1-PROOF.json
NEXT_ROLE=S1-ARCH
NEXT_ATTEMPT_ID=none
ESCALATE_TO_S1=no
SUBAGENTS_USED=2
```

## 可回滚方式

- 按提交逆序 `git revert` Handoff 提交和实现提交；禁止 reset、rebase 或 force-push。
- 本 Attempt 没有外部系统、数据库、Migration、公共契约、依赖锁或生产数据写入，无数据回滚动作。
