# WP-020-a1 S3-PLATFORM 交接

## 基本信息

- Work Package：WP-020
- Attempt ID：WP-020-a1
- Chain ID：CHAIN-M1-PLATFORM-01
- Step ID：M1-PLATFORM-01-S3
- 风险等级：R2
- 执行模式：ORDERED
- 责任会话：S3-PLATFORM
- 接收会话：S6-DATA（REVIEW_ONLY）
- 交接策略：CONSUMER_GATE
- 功能 ID：FP-MCP-001、FP-MCP-002、FP-SEC-001、FP-SEC-004
- 分支：`codex/s3/wp-020-platform-bootstrap`
- 基线提交：`c4062b2ac6a81aba4e3e1ac63cc01f54efecfed0`
- NEW_HEAD：本文件所在提交；精确 SHA 由唤醒信封返回
- ContractSet 摘要：
  `sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`
- 状态：S3 范围实现和自测完成，等待 S6 消费侧只读复核

## 完成内容

- 建立 `flowpilot.mcp-gateway.m0.v1` 入口，固定执行
  Ingress、身份、Registry/Schema、Policy、Approval、Ledger、Upstream、
  Readback、Result、Audit/Security 与 Reconciliation 生命周期。
- Tool Registry 默认拒绝，工具输入/输出采用闭合 JSON Schema 白名单；
  未知 Schema keyword、非闭合嵌套对象、Schema Hash 漂移和额外字段失败关闭。
- 同时绑定可信用户 `SecurityContextRef` 与服务端认证的 Agent 工作负载，
  检查 Context 引用/哈希、Tenant、Purpose、Audience、Agent 版本、工具
  scope、有效期和数据分类上限。
- Policy PEP 只接受公共 `PolicyDecision v1`，重算 RFC 8785 输入摘要，
  `deny` 优先；六种强类型 Obligation 均有确定性实现或失败关闭。
- 单审批完整绑定 requester、approver 职责分离、Tenant、Action Digest、
  Tool Schema Hash、PolicyDecision、policy_version 及 Action/Policy/Approval
  三侧 `expires_at`；执行和对账都会重新校验当前角色与有效期。
- 写路径只消费 S6 `DataUnitOfWork` 的 Execution Ledger 与 Outbox Port。
  `PREPARED/RUNNING/VERIFIED/FAILED_RETRYABLE/FAILED_FINAL/UNKNOWN` 行为与
  S6 v2 状态转换一致；终态 Ledger 与脱敏 Audit 草稿在同一 UoW 提交。
- 重复已验证请求不再调用上游；`UNKNOWN` 不盲重试。只有权威
  `confirmed_not_executed` 负向证明可解锁新 Attempt；对账请求还会再次
  比对原 Ledger Intent，禁止用同一幂等键切换参数。
- 写成功必须经过权威回读并携带 evidence/observed reference；回读不可用、
  结果不匹配、恶意输出或持久化提交不确定时保持 `UNKNOWN`。
- 凭据只通过短期 opaque capability handle 代理，TTL 被 Action、Policy、
  SecurityContext 与工作负载最早过期时间截断；长期 Secret 不进入请求、
  Ledger、Outbox、Trace、Audit、Security 或 debug projection。
- Trace 可采样；Audit/Security 不可采样并分流。白名单
  `debug_projection` 不含原始 Context、完整 Payload、Prompt、Secret 或
  隐藏思维链。拒绝事件只用已验证 Context 标记 Tenant/Actor；验证前失败
  进入 `unresolved` 隔离归属，不能由请求方伪造审计租户。
- 提供只读 `knowledge.search.v1` 模拟 MCP，固定 Schema、按 capability
  中可信 Tenant 过滤，无写 API、生产凭据、真实网络或持久事实源。

## 未完成与非目标

- 未修改公共 `contracts/**`、Persistence Port、Migration、RLS、Infra、
  Redis、领域终态、根 Workspace、`uv.lock` 或 `Makefile`。
- 未接入真实 OIDC/Workload Identity Provider、生产凭据或企业网络。
- 根 Workspace 对五个 S3 包的注册、锁文件和稳定 `make test-security`
  入口属于链路后续 S5-CORE Step；本 Attempt 未越权修改共享文件。
- S4 独立安全黑盒、S7 组合证据和 S1 最终接受尚未执行；本交接不声明
  ACCEPTED、VERIFIED、MERGED 或 RELEASED。

## 修改文件

| 路径 | 变化 | 所有者 |
|---|---|---|
| `apps/mcp-gateway/**` | Gateway、Registry、生命周期、Ledger/Outbox 接入、信号草稿 | S3 |
| `packages/tool-contracts/**` | 严格 ToolRequest/Result 与 Tool Schema Hash adapter | S3 |
| `packages/policy/**` | PolicyDecision、Obligation、PEP、Approval verifier | S3 |
| `packages/security/**` | Context/Workload 校验、capability Port、安全投影 | S3 |
| `mcp-servers/knowledge/**` | 只读、租户过滤模拟 MCP | S3 |
| `tests/platform/**` | 正常、边界、失败、安全、恢复和公共契约测试 | S3 |

最终候选差异只包含授权的 S3 WRITE_SCOPE。

## 契约、数据库与配置变化

- 公共契约：无变化；只消费冻结的 rc2 v1 ContractSet。
- 内部 Port：
  - `flowpilot.mcp-gateway.m0.v1`
  - `flowpilot.policy-adapter.m0.v1`
  - `flowpilot.security-adapter.m0.v1`
  - `flowpilot.tool-contracts.m0.v1`
  - `flowpilot.knowledge-mcp.m0.v1`
- Persistence：消费 `flowpilot.persistence-ports.m0.v2`；未修改 S6 Port。
- Migration / RLS / 数据库：无变化。
- Redis：无使用，不作为事实源。
- 生产环境变量：无新增。
- 外部生产依赖：无新增；仅新增五个内部 Python 包，等待 S5 注册 Workspace。

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| `python -B -m pytest -q tests/platform` | PASS：51 passed | `tests/platform/**` |
| `python -B -m pytest -q tests/core tests/runtime tests/data tests/platform` | PASS：194 passed | 四角色本地回归 |
| `python -B contracts/conformance/validate.py` | PASS：20 schemas、35 cases、52 features | `contracts/conformance/**` |
| Ruff 检查全部 S3 源码与平台测试 | PASS：All checks passed | S3 WRITE_SCOPE |
| Mypy `--strict` 检查五个 S3 包源码 | PASS：24 source files | 各包 `src/**` |
| 五个 S3 Python package wheel build | PASS：5 wheels | Windows Temp，未提交 |
| 高置信生产 Secret pattern scan | PASS：0 matches | S3 WRITE_SCOPE |
| Git 路径范围扫描 | PASS：无授权范围外变化 | `git status --short` |
| `make test` / `make test-contract` / `make test-security` | ENV_BLOCKED | 当前 Windows 无 `make`；`test-security` 入口也等待 S5 Step |

契约门禁完整摘要：

```text
CONTRACT_CONFORMANCE_OK schemas=20 cases=35 positive=18 negative=17 mutation_cases=19 mutation_positive=3 mutation_negative=16 semantic_cases=43 semantic_positive=0 semantic_negative=43 audit_chain_cases=5 audit_chain_positive=1 audit_chain_negative=4 manifest_cases=21 manifest_positive=1 manifest_negative=20 features=52
```

## 安全与失败路径

- 正常：只读租户过滤、写入回读验证、Policy Obligation、Approval、Audit。
- 身份：Context 过期/伪造、跨租户、错 Audience、Agent/角色伪造、分类越界。
- 契约：Action Digest、Schema Hash、输入/输出 Schema、公共 v1 对象复验。
- 审批：参数重放、Schema/Policy/主体/Tenant/expiry 绑定和角色撤销。
- 依赖：PDP、MCP、Credential Broker、Ledger、Reconciliation 不可用。
- 恢复：重复请求、`NOT_SENT`、`UNKNOWN`、权威未执行证明、对账确认、
  参数切换拒绝、回读不可用和重复逻辑写入计数。
- 可观察性：稳定原因码、阶段顺序、debug 白名单、Trace 采样不影响
  Audit、Audit/Security 双向关联和可信 Tenant stamping。
- 结果：测试夹具中的跨租户成功、重复逻辑写入和真实 Secret 泄漏均为 0。

## 已知问题

- Windows 环境没有 `make`，不能把等价底层命令冒充稳定入口通过。
- 根 Workspace 尚未注册 S3 新包；这是授权链 Step 3 的 S5 交付，不是
  S3 缺失的私有依赖实现。
- Audit/Security 草稿的可信 Stream、sequence 与 integrity hash 由下游
  不可采样 Sink/Store 分配；S6 本轮需确认 Outbox 消费不会信任调用方
  自报 Stream/Tenant，也不会把草稿当成已完成公共 AuditEvent。

## 学习候选

```text
LEARNING_CANDIDATE=拒绝事件不能回退使用未验证请求的租户归属
MATURITY=IMPLEMENTED
TRIGGER=SecurityContextRef 精确匹配失败时，请求仍携带格式合法但可伪造的 tenant_id 和主体
MECHANISM=若拒绝 Audit/Security 直接复制请求字段，攻击者虽无法越权执行，仍可向其他租户的审计流注入伪造归属
STRUCTURE=只用已验证 Context stamp Tenant/Actor；验证前失败进入 unresolved 隔离分区，并由可信 Sink/Store 分配最终 Stream
EVIDENCE=tests/platform/test_gateway_security.py::test_forged_context_tenant_cannot_stamp_security_event_tenant
RESIDUAL_RISK=下游 Audit Store 必须继续从可信租户注册表分配 Stream 并重算完整性
TARGET=docs/architecture/ENGINEERING_PLAYBOOK.md 4.9
```

## 接收会话下一步

1. S6-DATA 在原 S3 NEW_HEAD 上只读复核：没有私有账本、Redis 事实源、
   越权事务语义或未绑定 Tenant。
2. 重点复算 Ledger key/状态转换、终态与 Outbox 同事务、拒绝零写、
   `UNKNOWN`/confirmed-not-executed 和 Audit 草稿的可信 Sink 边界。
3. 若 `CONSUMER_VERDICT=ACCEPT`，按链路把原 S3 Head/Handoff 直接唤醒
   S5-CORE；S6 不创建提交。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M1-PLATFORM-01
STEP_ID=M1-PLATFORM-01-S3
ATTEMPT_ID=WP-020-a1
NEW_HEAD=<this-commit>
BASE_COMMIT=c4062b2ac6a81aba4e3e1ac63cc01f54efecfed0
CONTRACT_CONTENT_DIGEST=sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc
GATE=PASS
HANDOFF=tests/platform/evidence/WP-020-a1/HANDOFF.md
NEXT_ROLE=S6-DATA
NEXT_ATTEMPT_ID=WP-020-r1-s6
ESCALATE_TO_S1=no
```

## 可回滚方式

- 由链路 Owner 对本 Attempt 最终提交执行 `git revert <NEW_HEAD>`。
- 不需要数据库回滚、Migration、Secret 撤销或外部系统补偿。
