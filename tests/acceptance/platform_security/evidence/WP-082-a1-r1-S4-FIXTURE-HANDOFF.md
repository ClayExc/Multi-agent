# WP-082-a1-r1 S4 acceptance fixture handoff

## 基本信息

- Work Package：`WP-082`
- Attempt ID：`WP-082-a1-r1-s4-fixture`
- Chain ID：`CHAIN-M8-IDENTITY-TENANCY-01`
- Step ID：`M8-01C1-S4-ACCEPTANCE-FIXTURE`
- 责任会话：`S4-QUALITY`
- 接收会话：`S1-ARCH`
- 交接策略：`S1_GATE`
- 功能 ID：`FP-SEC-001`、`FP-SEC-007`
- 基线提交：`532e86b2e8dd2c68a70966afb8b13eff9da1e0b5`
- 分支/最终提交：`codex/s4/wp-082-acceptance-fixture`；本文件所在提交，精确 SHA 由交接信封提供
- 实现提交：`a3985a066c82492e10666ca4b2b203b2c62147f1`
- ContractSet 摘要：`sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：完成

## 完成内容

- 将 `platform_security` 的可信用户 Context Fixture 迁移到完整授权快照：issuer、authorized party、subject、roles、scopes、认证信息、有效期和 source-token hash 共同参与 `context_hash`。
- `ContextSource` 返回与快照一致的 `TrustedSecurityContext` 身份证据。
- 将 Gateway Workload Fixture 迁移为带完整 issuer、authorized party、subject 和 credential hash 的 server-attested OIDC workload。
- 保留过期 Context 负例的原断言；负例变更有效期后重新绑定完整快照，使其继续到期检查而不是被快照完整性检查提前拦截。
- checkpoint 标出的 25 个旧 Fixture 阻断 Case 均包含在通过的 33 项定向测试中；没有放宽生产验证器或安全断言。

## 未完成与非目标

- 未修改 S3 身份实现、公共契约、生产代码或共享文件。
- S2 Runtime Fixture 迁移属于并行步骤 `M8-01C2-S2-RUNTIME-FIXTURE`，不在本 Attempt 范围。
- 本交接不声明 WP-082、M8、Feature 状态或 Release 状态。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `tests/acceptance/platform_security/blackbox.py` | 完整可信 Context 快照与 attested OIDC Workload Fixture | S4-QUALITY |
| `tests/acceptance/platform_security/test_authorization_blackbox.py` | 过期 Context 负例在变更有效期后重算可信快照 | S4-QUALITY |
| `tests/acceptance/platform_security/evidence/WP-082-a1-r1-S4-FIXTURE-HANDOFF.md` | 本交接证据 | S4-QUALITY |

## 契约、数据库与配置变化

- 契约版本：无变化。
- Migration：无。
- 环境变量：无。
- 兼容性：仅测试 Fixture 消费现有严格公开构造接口；未扩宽任何接口或断言。

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| `uv run --frozen python -m pytest tests/acceptance/platform_security -q` | PASS：`33 passed`，包括 checkpoint 标出的原 25 个失败 Case | 终端输出 |
| `uv run --frozen ruff check tests/acceptance/platform_security` | PASS：`All checks passed!` | 终端输出 |
| `uv run --frozen python -m pytest tests/experience/test_secret_scan.py -q` | PASS：`2 passed` | 终端输出 |
| `python -m pytest tests/acceptance/platform_security -q` | `ENV_BLOCKED`：宿主 Hermes Python 未安装 pytest；随后改用仓库锁定 `uv --frozen` 环境并 PASS | 终端输出 |
| `uv run --frozen ruff format --check tests/acceptance/platform_security` | 非门禁诊断：3 个既有文件仍有 formatter 建议；本次新增行已按建议对齐，未越权批量格式化旧代码 | 终端输出与基线差异 |
| `git diff --check` | PASS | 终端输出 |

## 安全与失败路径

- 已验证负向路径：跨租户、双主体伪造、purpose/audience 错配、过期 Context、未注册工具、审批绑定与恢复等原安全断言全部保持通过。
- 未验证风险：S2 并行 Runtime Fixture 不属于本路径，须由 Join 门禁独立确认。
- Secret/PII 检查：Secret Scan `2 passed`；Fixture 只使用合成摘要和本地域名，不含真实凭据或 PII。

## 已知问题

- 无本 Attempt 阻断问题。
- 非门禁 formatter 诊断仍会建议格式化三个既有测试文件；未扩大当前安全 Fixture 迁移范围处理。

## 已知事实与避免重复

- `KNOWN_FACTS`：S3 严格身份实现已 checkpoint；25 个共享安全失败来自 S4 旧 Fixture。
- `DO_NOT_RECHECK`：未重复审查 S3 身份实现正确性、M7、README/STRUCTURE 或全仓历史 Handoff。
- `FAILURE_SIGNATURES`：旧 Context 三字段摘要触发 `PLATFORM_SECURITY_CONTEXT_UNTRUSTED`；未 attested workload 触发 `PLATFORM_WORKLOAD_UNTRUSTED`。
- `REUSED_DECISIONS`：复用 `tests/platform/evidence/WP-082-a1-r1-CHECKPOINT.md` 及现有严格公开身份构造接口。
- `DUPLICATE_WORK_AVOIDED`：未重跑 S3 白盒门禁、M7 或全仓测试。

## 学习候选

```text
LEARNING_CANDIDATE=none
MATURITY=VERIFIED
TRIGGER=none
MECHANISM=none
STRUCTURE=none
EVIDENCE=none
RESIDUAL_RISK=none
TARGET=none
```

## 子 Agent 使用摘要

```text
SUBAGENTS_USED=0
SUBAGENT_MODES=none
SUBAGENT_TASKS=none
SUBAGENT_WRITERS=0
PARENT_REPRODUCED_RESULTS=not-applicable
REUSED_DECISIONS=tests/platform/evidence/WP-082-a1-r1-CHECKPOINT.md
DUPLICATE_WORK_AVOIDED=3
```

## 接收会话下一步

1. S1 核验最终 Head、Handoff SHA-256、ContractSet、范围和 clean 状态。
2. 与并行 S2 Fixture 结果汇合后重跑 WP-082 指定共享门禁；本 S4 任务不直接唤醒 S3 或其他角色。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M8-IDENTITY-TENANCY-01
STEP_ID=M8-01C1-S4-ACCEPTANCE-FIXTURE
ATTEMPT_ID=WP-082-a1-r1-s4-fixture
NEW_HEAD=<this-handoff-commit>
IMPLEMENTATION_HEAD=a3985a066c82492e10666ca4b2b203b2c62147f1
BASE_COMMIT=532e86b2e8dd2c68a70966afb8b13eff9da1e0b5
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/acceptance/platform_security/evidence/WP-082-a1-r1-S4-FIXTURE-HANDOFF.md
NEXT_ROLE=S1-ARCH
NEXT_ATTEMPT_ID=none
ESCALATE_TO_S1=no
SUBAGENTS_USED=0
```

## 可回滚方式

- 按提交逆序回滚本分支的交接证据、格式对齐与 Fixture 迁移提交；无需契约、数据库或配置回滚。
