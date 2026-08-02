# WP-032-a1 S4-QUALITY 交接

## 基本信息

- Work Package：WP-032
- Attempt ID：WP-032-a1-S4
- Chain ID：CHAIN-M6-ACCEPTANCE-REMEDIATION-01
- Step ID：M6-REM-02-TYPES
- 责任会话：S4-QUALITY（临时 Agent `experience-type-hardener`）
- 接收会话：S1-ARCH
- 交接策略：`S1_GATE`
- 功能 ID：FP-OPS-002
- 产品基线提交：`71afa72a4975a506796e1e02d8d475d142616652`
- 激活输入 Head：`f8dff51df0998d826ffc51ecf8cce0dd50bf7c02`
- 分支/实现提交：`codex/s4/wp-032-type-hardening` / `18d71d904939c2cfaeaa63f7c2de958f9fd0ff2c`
- ContractSet 摘要：`sha256:f3c2dd6eb7d398d9a0a0891110cbc913bb998ed72208ea179a644c97af655e56`
- 状态：完成

## 上下文加载

- `CONTEXT_MODE=DELTA`
- 祖先校验：产品基线 `71afa72a...` 是激活输入 `f8dff51d...` 的祖先。
- 强制基线增量：`README.md`、`STRUCTURE.md`、`AGENTS.md`、`docs/acceptance/**`、`docs/architecture/**`、`docs/decisions/**`、`docs/team/session-contracts/**` 在该区间无变化，因此未全文重读。
- 实际读取：当前 Chain Authorization、WP-032、对应 Agent Registration、直接上游 `WP-031-a1-HANDOFF.md`、Web Shell 两份目标源码及直接相关体验测试。
- `FULL` 触发：否；重复全量读取：0。

## 完成内容

- 为 `_parse_dt` 增加基于 `nullable` Literal 的重载，使必填时间字段静态收窄为 `datetime`，Optional 字段仍保持 `datetime | None`，运行时解析语义不变。
- 将字符串、标识、摘要、整数、布尔和时间验证器的输入边界从 `Any` 收紧为 `object`，仅在运行时校验成功后返回具体类型。
- 将 JSON 解码结果约束为 `object`，并在 Task 投影、命令接收响应和错误信封边界显式验证 string-keyed JSON object。
- 错误信封的 `code`、`message`、`retryable` 仅接受契约类型；畸形嵌套 object、`null` 或字符串 truthiness 不再扩散到页面错误模型，统一失败关闭。
- 消除 Web Shell 基线的 12 个 strict Mypy 错误，未使用 `cast`、`type: ignore`、全局忽略或放宽 strict。

## 未完成与非目标

- 本分片不处理 S2/S5 的并行类型错误；116 源码组合门禁由 S1 在三个分片汇合后复跑。
- 未修改公共 Schema、API payload、页面正常行为、依赖、Workspace 配置或非 S4 路径。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `web/src/flowpilot_shell/models.py` | Optional 时间重载与运行时验证器类型收窄 | S4-QUALITY |
| `web/src/flowpilot_shell/api_client.py` | JSON object/错误信封失败关闭边界 | S4-QUALITY |
| `tests/experience/test_adapter_boundary.py` | 必填时间 null、2xx 非 object、畸形 error 类型负例 | S4-QUALITY |
| `tests/experience/evidence/WP-032-a1-S4-HANDOFF.md` | 本交接证据 | S4-QUALITY |

## 契约、数据库与配置变化

- 契约版本：无变化；Conformance 复算/校验通过，摘要保持 `f3c2dd6e...55e56`。
- Migration：无。
- 环境变量：无。
- 兼容性：合法 API payload 与页面行为不变；仅畸形成功体或错误信封改为确定性 `ShellContractError`。

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| `uv run --all-packages --all-groups --locked mypy --strict web/src` | PASS：17 source files，0 errors | 当前分支控制台结果 |
| `uv run --all-packages --all-groups --locked python -B -m pytest tests/experience -q` | PASS：63 passed | 当前分支控制台结果 |
| `uv run --all-packages --all-groups --locked ruff check web/src tests/experience` | PASS | 当前分支控制台结果 |
| `uv run --all-packages --all-groups --locked python -B contracts/conformance/validate.py` | PASS：`CONTRACT_CONFORMANCE_OK` | 当前分支控制台结果 |
| `git diff --check` | PASS | 当前分支控制台结果 |

## 安全与失败路径

- 已验证负向路径：非 Optional 时间字段为 `null`、2xx 命令响应为 list、错误信封 `error` 为 list/null、`retryable` 为字符串时均失败关闭。
- 未验证风险：无本分片新增风险；最终 116-source 结果依赖 S2/S5 分片汇合。
- Secret/PII 检查：修改仅含合成测试 payload 与类型边界，无密钥、令牌、真实 PII、Prompt 或 Trace。

## 已知问题

- 无本分片阻断问题。

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

1. S1 复核实现提交 `18d71d904939c2cfaeaa63f7c2de958f9fd0ff2c` 的行为兼容性、失败关闭边界和 S4 门禁。
2. 与 S2/S5 互斥分片汇合后复跑 canonical 116-source strict Mypy、责任范围 Ruff 与相关回归测试。
3. 三个分片全部通过后，按 Chain Authorization 解锁 `M6-REM-03-S1-CONTRACT`。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M6-ACCEPTANCE-REMEDIATION-01
STEP_ID=M6-REM-02-TYPES
ATTEMPT_ID=WP-032-a1-S4
NEW_HEAD=18d71d904939c2cfaeaa63f7c2de958f9fd0ff2c
BASE_COMMIT=f8dff51df0998d826ffc51ecf8cce0dd50bf7c02
CONTRACT_CONTENT_DIGEST=sha256:f3c2dd6eb7d398d9a0a0891110cbc913bb998ed72208ea179a644c97af655e56
GATE=PASS
HANDOFF=tests/experience/evidence/WP-032-a1-S4-HANDOFF.md
NEXT_ROLE=S1-ARCH
NEXT_ATTEMPT_ID=none
ESCALATE_TO_S1=yes
```

## 可回滚方式

- 回滚实现提交 `18d71d904939c2cfaeaa63f7c2de958f9fd0ff2c` 及其后的本交接证据提交；不需数据库、契约或外部资源回滚。
