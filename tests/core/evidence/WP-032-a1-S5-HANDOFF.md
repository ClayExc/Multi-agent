# WP-032-a1-S5 Core/API strict type hardening 交接

## 基本信息

- Work Package：WP-032
- Attempt ID：WP-032-a1-S5
- Chain ID：CHAIN-M6-ACCEPTANCE-REMEDIATION-01
- Step ID：M6-REM-02-TYPES
- Agent ID：core-type-hardener
- 责任会话：S5-CORE
- 接收会话：S1-ARCH
- 交接策略：`S1_GATE`
- 功能 ID：FP-OPS-002
- 基线提交：`71afa72a4975a506796e1e02d8d475d142616652`
- 激活提交：`f8dff51df0998d826ffc51ecf8cce0dd50bf7c02`
- 分支：`codex/s5/wp-032-type-hardening`
- 最终提交：本文件所在提交；精确 SHA 由交接消息返回
- ContractSet 摘要：`sha256:f3c2dd6eb7d398d9a0a0891110cbc913bb998ed72208ea179a644c97af655e56`
- 状态：完成

## 上下文启动

- 使用 `DELTA`；Activation/Product Base 均为当前输入 Head 的祖先。
- `71afa72a..f8dff51d` 间 `README.md`、`STRUCTURE.md`、`AGENTS.md`、
  `docs/acceptance/**`、`docs/architecture/**`、`docs/decisions/**`、
  `docs/team/session-contracts/**` 与 `contracts/**` 无变化。
- 读取当前 Chain Authorization、WP-032、对应 Agent Registration、直接上游
  WP-031 Handoff、交接模板以及直接相关源码/测试；`FULL` 读取次数为 0，重复读取
  次数为 0。
- Contract conformance 独立复跑通过，声明摘要与 Chain 摘要一致。

## 完成内容

- 为持久化 Outbox delivery 的事件投影增加局部、只读结构化 Protocol，在
  delivery/view 归一化边界完成显式收窄，消除 9 个 `object` 属性错误；未引入
  `Any`、忽略或跨层依赖。
- 将领域 `ApprovalStatus` 明确收窄为 API 响应允许的
  `approved | rejected | revoked` 三个 Literal，消除 1 个参数类型错误；有效响应
  值保持不变，非决策状态继续失败关闭。
- S5 分片 strict Mypy 从 10 errors / 2 files 修复为 0 errors。

## 未完成与非目标

- 未处理 S2、S4 分片剩余 strict Mypy 错误；由各自路径 Owner 并行交付。
- 未运行 116-source 最终组合门禁；需 S1 消费三个互斥 Head 后统一复跑。
- 未修改公共契约、领域状态转换、API Schema/错误码、依赖、锁文件或其他角色路径。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `packages/application/src/flowpilot_application/services.py` | Outbox delivery/view 事件结构类型收窄 | S5-CORE |
| `apps/api/src/flowpilot_api/app.py` | Approval 决策终态到响应 Literal 的显式收窄 | S5-CORE |
| `tests/core/evidence/WP-032-a1-S5-HANDOFF.md` | 本交接证据 | S5-CORE |

## 契约、数据库与配置变化

- 契约版本：无变化；ContractSet content digest 保持不变。
- Migration：无。
- 环境变量：无。
- 兼容性：领域状态、成功响应字段和值、API 错误码及 Outbox 运行时归一化行为不变。

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| `uv run --all-packages --all-groups --locked mypy --strict packages/application/src apps/api/src` | PASS：16 source files，0 issues | 当前分支控制台结果 |
| `uv run --all-packages --all-groups --locked python -B -m pytest tests/core -q` | PASS：77 passed | 当前分支控制台结果 |
| `uv run --all-packages --all-groups --locked ruff check packages/application apps/api tests/core` | PASS | 当前分支控制台结果 |
| `uv run --all-packages --all-groups --locked python -B contracts/conformance/validate.py` | PASS：`CONTRACT_CONFORMANCE_OK`，20 schemas / 35 cases | 当前分支控制台结果 |
| `git diff --check` | PASS | 当前分支控制台结果 |

## 安全与失败路径

- 已验证负向路径：完整 Core 套件覆盖租户隔离、命令安全绑定、Outbox 重投/提交故障、
  缺口与敏感字段等既有负例；本次收窄未改变这些路径。
- 未验证风险：三个分片尚未组合，116-source 最终 strict Mypy 由 S1 汇合后验证。
- Secret/PII 检查：变更仅含类型结构、固定安全错误文本与合成交接数据；没有密钥、
  真实 PII、Prompt、Trace 或原始附件。

## 已知问题

- Application Outbox Port 使用归一化 `OutboxEventView`，现有 Persistence adapter 在
  运行时返回包含同构事件的 `OutboxDelivery`；本包仅在既有适配边界准确描述结构，
  未变更跨角色 Port。若未来统一 Port，须另开跨角色工作包并由 S1 裁决。

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

## 接收会话下一步

1. S1 校验本 Head 与其他 S2/S4 Head 同源、范围互斥、工作树干净。
2. S1 逐分片复跑验收后组合三个 Head，并执行 WP-032 的 canonical 116-source strict
   Mypy 与责任范围回归门禁。
3. 组合门禁通过后，按 Chain Authorization 解锁 `M6-REM-03-S1-CONTRACT`。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M6-ACCEPTANCE-REMEDIATION-01
STEP_ID=M6-REM-02-TYPES
ATTEMPT_ID=WP-032-a1-S5
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=71afa72a4975a506796e1e02d8d475d142616652
CONTRACT_CONTENT_DIGEST=sha256:f3c2dd6eb7d398d9a0a0891110cbc913bb998ed72208ea179a644c97af655e56
GATE=PASS
HANDOFF=tests/core/evidence/WP-032-a1-S5-HANDOFF.md
NEXT_ROLE=S1-ARCH
NEXT_ATTEMPT_ID=none
ESCALATE_TO_S1=yes
```

## 可回滚方式

- 回滚本 Attempt 在激活提交 `f8dff51d` 之后的提交；不需要数据库、契约、配置或
  外部资源回滚。
