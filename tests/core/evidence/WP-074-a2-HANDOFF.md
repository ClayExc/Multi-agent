# WP-074-a2 S5-CORE 凭据消费者收敛交接

## 基本信息

- Work Package：WP-074
- Attempt ID：WP-074-a2
- Chain ID：CHAIN-M7-LOCAL-PRODUCT-01
- Step ID：M7-SEC-02-S5-CREDENTIAL-CONSUMERS
- Agent ID：core-composer
- 责任会话：S5-CORE
- 接收会话：S4-QUALITY
- 交接策略：CONSUMER_GATE
- 风险与严重度：R3 / P0；S1 人工架构修复链
- 功能 ID：FP-SEC-002、FP-SEC-006
- 基线提交：`9e042227b6ce13964631381c19ee69002ee23dbf`
- 上游 S3 Handoff：`tests/platform/evidence/WP-074-a1-HANDOFF.md`
- 上游 Handoff SHA256：
  `sha256:a5ac784a66ab2cf99135d9675ad0247d5458e60d05c617ca5381e65516a34436`
- 分支：`codex/s5/m7-core-composition`
- 最终提交：本文件所在提交；精确 SHA 由消费者唤醒信封返回
- ContractSet 摘要：
  `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：完成
- 消费者裁决：`CONSUMER_VERDICT=ACCEPT`

## 完成内容

- 核验 S3 精确 Head、Handoff Hash、ContractSet、线性祖先、授权范围和 clean 后，
  只使用 `--ff-only` 到达输入提交。
- Application 显式依赖内部 Workspace 包 `flowpilot-security`；锁文件同步记录该
  单向依赖，未复制或扩展凭据 family 注册表。
- TaskEvent 构造和重新验证统一调用 S3 的 `assert_no_secret_material`，同时保留：
  - event type 对应 payload 的精确 Schema、producer 绑定和额外字段拒绝；
  - session/reasoning 等隐藏投影字段拒绝；
  - opaque ref、tenant、producer principal 和全部 Envelope 字段校验。
- 集中凭据扫描先于本地隐藏投影检查，防止恶意 Mapping key 被拼入后续错误路径。
- `InMemoryEventStream.subscribe` 在建立 subscriber 或写入 replay queue 前重新验证
  所有缓冲事件；`emit` 与 SSE frame 继续在任一输出前验证完整 Envelope。
- ASIA、OpenAI admin、Slack xapp、ENCRYPTED PRIVATE KEY 在构造、emit、subscriber、
  replay 和 SSE 边界均失败关闭；异常、repr 和捕获日志不包含原始值。

## 未完成与非目标

- 未修改 `contracts/**`、公共 TaskEvent Schema、ADR 或架构文档。
- 未迁移 Persistence 或 Evaluation 的消费者；未修改 S6/S4 所有权路径。
- 未启用真实 Provider、外部网络或付费调用；在线 Provider Smoke 仍按既有策略显式关闭。
- S4 独立黑盒复核尚未执行，是本 Handoff 的下一消费者步骤。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `packages/application/pyproject.toml` | 显式声明 `flowpilot-security` Workspace 依赖 | S5 |
| `uv.lock` | 固定 Application 到 Security 的内部依赖闭包 | S5 shared-writer |
| `packages/application/src/flowpilot_application/task_events.py` | 删除本地凭据正则副本并接入集中扫描 | S5 |
| `apps/api/src/flowpilot_api/stream.py` | replay/subscriber 写入前统一重验 route 与 Envelope | S5 |
| `tests/core/test_event_security.py` | family、污染为零、错误/日志脱敏与 replay 篡改回归 | S5 |
| `tests/core/evidence/WP-074-a2-HANDOFF.md` | 本交接证据 | S5 |

## 契约、数据库与配置变化

- 契约版本：无变化；ContractSet 摘要不变。
- Migration / 数据库 / Redis：无变化。
- 环境变量：无变化。
- 新第三方依赖：无；`flowpilot-security` 是仓库内部 Workspace 包，沿用项目许可。
- 依赖用途：消费唯一的凭据 family 注册表与失败关闭扫描 API。
- 替代方案：继续维护 Application 本地正则；因会造成 family 漂移和等价绕过而拒绝。
- 攻击面：新增依赖为纯本地、确定性、无网络/文件/数据库/Provider I/O 的扫描内核；
  依赖方向为 Application -> Security，未形成依赖环。
- 兼容性：合法 opaque URI、Schema payload、普通带连字符业务 ID 与原有 SSE 输出保持兼容。

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| `uv lock` | PASS；168 packages resolved，仅增加内部 Application -> Security 依赖 | `uv.lock` |
| `uv run --all-packages --all-groups --locked python -B -m pytest tests/core/test_event_security.py -q` | PASS；166 passed | 本地命令输出 |
| `uv run --all-packages --all-groups --locked python -B -m pytest --ignore=tests/acceptance/studio -q` | PASS；1115 passed / 1 explicit online skip | 本地命令输出 |
| `.\\scripts\\quality.ps1 test-contract` | PASS；20 schemas / 35 cases / 43 semantic cases / 52 features | 本地命令输出 |
| `.\\scripts\\quality.ps1 test-security` | PASS；160 passed | 本地命令输出 |
| `.\\scripts\\quality.ps1 lint` | PASS；Ruff + strict Mypy 126 source files | 本地命令输出 |
| `.\\scripts\\quality.ps1 audit` | PASS；0 known vulnerabilities | 本地命令输出 |
| `uv build --package flowpilot-security/application/api --wheel` | PASS；三个 wheel 构建成功，Application METADATA 含 `Requires-Dist: flowpilot-security` | 本地命令输出 |
| `git diff --check`、授权路径核对 | PASS | 本地命令输出 |

全仓稳定套件继续忽略 S4 所有权下的 `tests/acceptance/studio` 旧 oracle；这与上游
授权闭包一致，不把该排除项描述为通过。唯一 skip 是必须显式授权的在线 Provider Smoke。

## 安全与失败路径

- P0 family 的确定性复现结果：
  - `ASIA_*`：constructed/delivered/subscriber/replay/tampered-replay/SSE 全部为 false。
  - `OPENAI_ADMIN_*`：上述全部为 false。
  - `SLACK_XAPP_*`：上述全部为 false。
  - `ENCRYPTED_PRIVATE_KEY_*`：上述全部为 false。
- 对每个 P0 family 验证异常、`repr` 和捕获日志均不含原始值。
- 对凭据作为 Mapping key 且嵌套本地敏感字段的组合路径，集中扫描先失败关闭，
  错误路径不复制原始 key。
- replay 缓冲被对象篡改时，`subscribe` 在创建或注册 queue 前失败；subscriber 污染为 0。
- 高置信仓库差异 Secret 扫描：0 matches。

## 已知问题

- S4 仍需以消费者身份独立黑盒复算构造、stream、replay/subscriber、SSE 和日志泄漏
  均为 0，当前 Handoff 不替代其验收。
- Persistence/Evaluation 的扫描器迁移不属于本 Attempt，不得据此宣告它们已收敛。

## 学习候选

```text
LEARNING_CANDIDATE=集中凭据扫描必须先于会拼接诊断路径的消费者校验
MATURITY=VERIFIED
TRIGGER=消费者本地递归校验先运行时，恶意 Mapping key 可能进入后续异常路径
MECHANISM=即使集中扫描器自身不复制原始 key，消费者若先以业务 key 构造 path，仍可能形成二次泄漏通道
STRUCTURE=单一 family registry + 消费边界首先执行安全扫描 + 后续规则仅处理非凭据投影 + 异常/repr/log 负例
EVIDENCE=packages/application/src/flowpilot_application/task_events.py；tests/core/test_event_security.py；166 passed
RESIDUAL_RISK=其他消费者迁移时若把集中扫描放在会记录原对象的逻辑之后，仍可能重现同类问题
TARGET=ENGINEERING_PLAYBOOK 安全投影与凭据扫描候选
```

## 接收会话下一步

1. S4 核验精确 S5 Head、本 Handoff Hash、ContractSet、线性祖先、路径范围和 clean，
   仅用 `--ff-only` 到达唤醒信封的 INPUT_HEAD。
2. 独立黑盒复算 ASIA、OpenAI admin、Slack xapp、ENCRYPTED PRIVATE KEY 在 TaskEvent
   构造、emit、subscriber、replay 与 SSE 的成功污染数为 0，并验证异常/日志无原值。
3. 复核合法 opaque ref、普通业务 ID、Schema/producer/tenant 门禁无回归；发现新 P0/P1
   或公共契约需求时停止链路并上报 S1。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M7-LOCAL-PRODUCT-01
STEP_ID=M7-SEC-02-S5-CREDENTIAL-CONSUMERS
ATTEMPT_ID=WP-074-a2
AGENT_ID=core-composer
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=9e042227b6ce13964631381c19ee69002ee23dbf
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/core/evidence/WP-074-a2-HANDOFF.md
NEXT_ROLE=S4-QUALITY
NEXT_ATTEMPT_ID=WP-074-q1
ESCALATE_TO_S1=no
```

## 可回滚方式

- revert 本 Attempt 的单一 S5 提交；禁止 reset、rebase 或 force-push。回滚后 P0 消费者
  重新暴露于本地 family 漂移，必须同时停止 TaskEvent/SSE 相关交付。
