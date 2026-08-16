# WP-102-a1 S4-QUALITY Fixture Migration Handoff

## 基本信息

- Work Package：WP-102-R1
- Attempt ID：WP-102-a1-fixture
- Chain ID：`CHAIN-M9-GOVERNANCE-01`
- Step ID：`M9-02B-S4-WP102-FIXTURE-MIGRATION`
- 责任会话：S4-QUALITY
- 接收会话：S1-ARCH
- 交接策略：`S1_GATE`
- 功能 ID：FP-MCP-006、FP-SEC-005、FP-SEC-006、FP-SEC-007
- 基线提交：`c1db8f744199b4baf1683c0d6e45667137563c3e`
- 分支/最终提交：`codex/s4/wp-107-m9-governance-quality` / 本文件所在提交
- ContractSet 摘要：
  `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 生产者 Handoff SHA-256：
  `63b8670386e81703e847a5784badc9b2919dafd94943e056e260982fa8e1514c`
- 状态：完成

## 完成内容

- 机械迁移 S4 `CapabilityIssuer` 到 WP-102 的完整边界：tenant、Security Context、tool、
  resource、action digest、policy version、execution、audience、scope、use 和 TTL 均写入
  `CapabilityHandle`，没有 legacy 兼容入口或可选弱绑定。
- Capability token ID 绑定关键执行字段；issue/consume 共享 `asyncio.Lock`，issued/consumed
  状态在同一临界区更新。未知、篡改、过期或重复 Handle 统一以
  `PLATFORM_CAPABILITY_REPLAY` 失败关闭，成功 consume 严格单次计数。
- 将 secret-output 的期望稳定码从旧 `PLATFORM_UNSAFE_PROJECTION` 迁移为集中 DLP 的
  `PLATFORM_DLP_BLOCKED`；malicious extra-field 仍为 `PLATFORM_TOOL_OUTPUT_INVALID`。
- 原 10 个失败全部恢复；malicious/secret output 零投影、Gateway restart replay、UNKNOWN
  reconcile、authoritative not-sent retry、readback mismatch、idempotency conflict 和 timeline
  evidence 断言均保持通过。

## 未完成与非目标

- 未修改 S3 产品代码、公共 Contract、Migration、根共享文件或依赖锁。
- 未运行全仓、S3 的 86/424、Contract、Mypy、Compose、在线 Provider 或 M8 历史门禁。
- 本交接不宣称 WP-102 完成；S1 Join 后仍需由 S3 复跑共享门禁并生成正式 Handoff。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `tests/acceptance/platform_security/blackbox.py` | 完整 Capability issue 绑定及原子单次 consume | S4 |
| `tests/acceptance/platform_security/test_authorization_blackbox.py` | 集中 DLP 稳定码期望 | S4 |
| `tests/acceptance/platform_security/evidence/WP-102-a1-FIXTURE-HANDOFF.md` | 本交接 | S4 |

## 契约、数据库与配置变化

- 契约版本：无变化；Contract content digest 保持不变。
- Migration / PostgreSQL / Redis：无变化。
- 环境变量：无新增。
- 依赖 / Lock / 根共享文件：无变化。
- 兼容性：只迁移测试 Fixture 到现行安全边界，不增加旧接口适配层。

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| `uv run --locked python -B -m pytest -q tests/acceptance/platform_security/test_authorization_blackbox.py tests/acceptance/platform_security/test_recovery_blackbox.py tests/acceptance/platform_security/test_timeline_evidence.py` | PASS | 33 passed；原 10 failures 全部恢复 |
| `uv run --locked ruff check tests/acceptance/platform_security` | PASS | All checks passed |
| `git diff --check` | PASS | 无空白错误 |
| `flowpilot_security.scan_secret_material` 基线/当前差分扫描 | PASS | 0 new findings；3 个既有合成负例保持不变 |

## 安全与失败路径

- 已验证负向路径：Capability 重放/过期/篡改拒绝机理、malicious/secret output 零投影、
  UNKNOWN 不盲重试、readback mismatch 保持 UNKNOWN、幂等冲突、not-sent 安全重试、恢复后
  不重复逻辑写及 timeline 非发布证据。
- 未验证风险：S3 共享 Security 组合门禁由 Join 后 Owner 复跑；本 S4 Attempt 不重复生产者
  86/424 或内部实现验证。
- Secret/PII：集中扫描器在基线和当前文件中均识别相同的 2 个
  `credential_assignment` 与 1 个 `authorization_bearer` 合成攻击 Fixture；新增 Finding=0，
  未删除合成 canary 来规避扫描。

## 已知问题

- 无新增产品 P0/P1，无范围外修复需求。
- 首次目标 pytest 在创建隔离 `.venv` 时达到命令等待上限，未形成测试终态；环境就绪后
  同一三个文件完整重跑并得到 33 passed，该启动超时未冒充门禁结果。

## 已知事实与避免重复

- `KNOWN_FACTS`：生产者 Head、Handoff Hash 与 Contract Digest 已精确核对；生产者
  86/424/Contract/Mypy 证据保持可复用；原 10 failures 仅来自 S4 stale Fixture/code。
- `DO_NOT_RECHECK`：WP-101 policy internals、M8 Keycloak/RLS/recovery、全仓、Compose、在线
  Provider 和 S3 产品内部实现。
- `FAILURE_SIGNATURES`：旧 `issue` 签名导致 `PLATFORM_CREDENTIAL_UNAVAILABLE`；旧 DLP
  期望为 `PLATFORM_UNSAFE_PROJECTION`，现稳定码为 `PLATFORM_DLP_BLOCKED`。
- `REUSED_DECISIONS`：WP-102 Producer Handoff；Capability 必填绑定、单次 consume 和集中 DLP。
- `DUPLICATE_WORK_AVOIDED`：未重复 S3 86/424、Contract、Mypy 或历史 M8 门禁。

## 学习候选

```text
LEARNING_CANDIDATE=Capability consumer fixtures must migrate atomically with required binding and consume semantics
MATURITY=VERIFIED
TRIGGER=生产者收紧 Capability 必填绑定后，旧跨 Owner Fixture 全部在 credential 阶段失败
MECHANISM=只迁移 Handle 构造而不同时迁移原子 consume，会把恢复/重放测试变成弱认证假阳性
STRUCTURE=Fixture issuer 与 consumer 在同一变更中补齐完整绑定、唯一 token ID 和锁内单次消费
EVIDENCE=WP-102-a1-fixture；三个目标文件 33 passed
RESIDUAL_RISK=共享 Security 组合仍需 S3 在 Join Head 复跑
TARGET=PRINCIPAL_SUBAGENT_PROTOCOL / cross-owner fixture migration guidance
```

## 子 Agent 使用摘要

```text
SUBAGENTS_USED=0
SUBAGENT_MODES=none
SUBAGENT_TASKS=none
SUBAGENT_WRITERS=0
PARENT_REPRODUCED_RESULTS=not-applicable
REUSED_DECISIONS=WP-102-a1-PRODUCER-HANDOFF
DUPLICATE_WORK_AVOIDED=5
```

## 接收会话下一步

1. S1 仅以 `--ff-only` 精确消费本提交，复算 Handoff Hash、授权路径和 clean 状态。
2. S1 Join 后交回 S3 复跑共享 Security 并生成正式 WP-102 Handoff；本会话不唤醒 S3/S2。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M9-GOVERNANCE-01
STEP_ID=M9-02B-S4-WP102-FIXTURE-MIGRATION
ATTEMPT_ID=WP-102-a1-fixture
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=c1db8f744199b4baf1683c0d6e45667137563c3e
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/acceptance/platform_security/evidence/WP-102-a1-FIXTURE-HANDOFF.md
NEXT_ROLE=S1-ARCH
NEXT_ATTEMPT_ID=WP-102-a1-join
ESCALATE_TO_S1=no
SUBAGENTS_USED=0
```

## 可回滚方式

- `git revert` 本 Fixture 迁移提交；禁止 reset、rebase 或 force-push。回滚只恢复旧 S4
  Fixture，不改变 S3 产品、公共 Contract、Migration 或共享配置。
