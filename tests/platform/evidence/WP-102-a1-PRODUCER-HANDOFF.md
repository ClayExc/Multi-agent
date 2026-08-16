# WP-102-a1 S3-PLATFORM Producer Checkpoint

## 基本信息

- Work Package：WP-102
- Attempt ID：WP-102-a1
- Chain ID：CHAIN-M9-GOVERNANCE-01
- Step ID：M9-02A-S3-WP102-PRODUCER-CHECKPOINT
- 责任会话：S3-PLATFORM
- 接收会话：S1-ARCH
- 交接策略：REMEDIATION_HANDOFF
- 功能 ID：FP-MCP-006、FP-SEC-005、FP-SEC-006、FP-SEC-007
- 基线提交：`46576b345d0f6c54b70af218009e311ac260a7db`
- 分支/检查点提交：`codex/s3/wp-101-m9-policy` / `<this-handoff-commit>`
- ContractSet 摘要：`sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：生产者检查点；WP-102 未通过共享门禁

## 生产者检查点内容

- 新增短时 Capability 的受信绑定与原子消费语义：tenant、Security Context、tool、
  resource、action digest、policy version、execution、audience、scope、use 和 TTL 均由
  Gateway 校验；invoke/readback 使用不同 Handle，重放失败关闭。
- 新增开发态 `SecretProviderPort`。明文 Secret 只在 Gateway 上游调用栈的受限 Lease
  内可见；Lease 不可 JSON 序列化，退出时清零，异常和表示不携带原值。
- 新增集中式 Credential/DLP/Prompt-Injection 注册表，并接入工具参数、MCP 内容、
  ToolResult、readback/reconciliation 和 Audit/Security/Debug 投影。
- 所有参数、Capability 和 Secret 授权拒绝均发生在 ledger 占位及上游调用前；危险写
  响应或回读保持 `UNKNOWN`，不伪造成功终态。
- 保持 Capability 必填绑定、原子 `consume`、集中 DLP 和稳定错误码；未为旧消费者
  Fixture 增加兼容降级。

## 门禁状态

```text
GATE=FAIL_CROSS_OWNER_FIXTURE
WP102_STATUS=PRODUCER_CHECKPOINT_ONLY
RELEASE_CLAIM=no
PASS_HANDOFF=no
S2_WAKE=no
```

| 检查 | 结果 | 证据 |
|---|---|---|
| WP-102 定向组合 | PASS | 86 passed |
| `tests/platform` | PASS | 424 passed |
| 影响范围 Ruff | PASS | All checks passed |
| strict Mypy | PASS | security/gateway/tool-contracts，25 source files |
| Contract Conformance | PASS | ContractSet v1 conformance passed |
| Secret Scan | PASS | 2 passed；检查点收口再次定向复核 |
| 共享 Security | FAIL | 242 passed / 10 failed；仅 S4-owned Fixture 未迁移 |
| diff/scope | PASS | 仅 S3 授权路径；无 staged/out-of-scope/shared-root/contracts 差异 |

本检查点复用此前完成的 86/424、Ruff、Mypy、Contract 和共享 Security 证据；依据
S1 裁决未重复运行全量或共享 Security。收口阶段仅执行 Head、diff、scope、
`git diff --check` 和定向 Secret Scan。

## 跨 Owner 阻断

共享 Security 的 10 个失败全部位于 S4 所有的
`tests/acceptance/platform_security/**`：

- `test_authorization_blackbox.py`：2 个参数化 Case。
- `test_recovery_blackbox.py`：6 个 Case。
- `test_timeline_evidence.py`：2 个 Case。

根因是 `tests/acceptance/platform_security/blackbox.py` 的 `CapabilityIssuer` 仍实现旧
`issue` 签名，未提供新增受信绑定和原子 `consume`，并用旧参数构造
`CapabilityHandle`。Gateway 按失败关闭返回 `PLATFORM_CREDENTIAL_UNAVAILABLE`。
相同 Fixture 仍期望旧投影错误码 `PLATFORM_UNSAFE_PROJECTION`，而集中 DLP 的稳定码为
`PLATFORM_DLP_BLOCKED`。

S3 未修改 S4 路径。若为兼容旧 Fixture 将新字段设为可选、接受 legacy broker、取消
原子消费或恢复旧 DLP 错误码，会削弱 R3 的资源/用途绑定和重放防护，因此不采用。

## 修改范围

- `apps/mcp-gateway/**`：Gateway 执行顺序、Capability/Secret/DLP 接入、Port、信号和
  生命周期安全投影。
- `packages/security/**`：Capability 模型、SecretProvider、集中内容安全注册表与稳定
  错误码。
- `tests/platform/**`：Capability、DLP、Secret 和 Gateway 安全回归，以及本证据。
- `packages/tool-contracts/**`：本检查点无实际差异。
- `contracts/**`、S4 路径、根共享文件、依赖锁、数据库和 Migration：无变化。

## 风险与下一动作

- 当前风险：共享 Security 门禁仍为 FAIL，WP-102 不得标记完成或交给 S2 消费。
- 下一动作：S1 派发 S4 迁移 `tests/acceptance/platform_security/**` 的 Capability
  Fixture 与 DLP 稳定码期望；Join 后由 S3 复跑共享门禁并生成正式 WP-102 Handoff。
- 本检查点后不唤醒 S2，不开始 WP-103。

## 子 Agent 使用摘要

```text
SUBAGENTS_USED=1
SUBAGENT_MODES=READ_ONLY_PARALLEL
SUBAGENT_TASKS=wp102_security_audit
SUBAGENT_WRITERS=0
PARENT_REPRODUCED_RESULTS=yes
LEARNING_CANDIDATE=Capability consumer fixtures must migrate atomically with required binding and consume semantics
```

## 机器可读摘要

```text
OUTCOME=REMEDIATION_HANDOFF
CHAIN_ID=CHAIN-M9-GOVERNANCE-01
STEP_ID=M9-02A-S3-WP102-PRODUCER-CHECKPOINT
ATTEMPT_ID=WP-102-a1
BASE_HEAD=46576b345d0f6c54b70af218009e311ac260a7db
NEW_HEAD=<this-handoff-commit>
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=FAIL_CROSS_OWNER_FIXTURE
SHARED_SECURITY=242_passed_10_failed
HANDOFF=tests/platform/evidence/WP-102-a1-PRODUCER-HANDOFF.md
NEXT_ROLE=S1-ARCH
S2_WAKE=no
```

## 可回滚方式

- revert 本生产者检查点提交；不要 reset、rebase 或 force-push。回滚不会改变公共契约。
