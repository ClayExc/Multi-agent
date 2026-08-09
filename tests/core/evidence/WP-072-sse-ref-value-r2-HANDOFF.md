# WP-072-sse-r2 S5-CORE Task Event 引用和值安全交接

## 基本信息

- Work Package：WP-072
- Attempt ID：WP-072-sse-r2
- Chain ID：CHAIN-M7-LOCAL-PRODUCT-01
- Step ID：M7-09R2-S5-SSE-REF-VALUE
- 责任会话：S5-CORE
- 接收会话：S4-QUALITY
- 交接策略：CONSUMER_GATE
- 功能 ID：FP-SEC-002、FP-OBS-001
- 输入提交：`de6c5b3252785742e50ff48025038ae18af364fd`
- 分支：`codex/s5/m7-core-composition`
- 最终提交：本文件所在提交；精确 SHA 由唤醒信封返回
- ContractSet 摘要：
  `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 上游 Handoff：`tests/runtime/evidence/WP-072-studio-security-r2-HANDOFF.md`
- 上游 Handoff SHA256：
  `sha256:62e720a9f02d3e3c77f5ba51e514b44b580ac9e8a9e8a12db34ebdf3292730d6`
- 状态：PASS_HANDOFF

## 完成内容

- 所有合法 Task Event payload `*_ref` 非空值统一要求为 opaque URI：
  `scheme://` 后必须有非空 ASCII 不透明路径；拒绝 userinfo、query、fragment、
  空路径、空白、控制字符、百分号编码和明文引用。
- 顶层 `producer_principal_ref` 使用相同 opaque URI 边界；保留
  `workload://` 正例。
- 保持现有 `task://`、`prompt://`、`display://`、`proposal://`、
  `result://`、`runtime-result://` 正例；现有 Schema 允许的可选空
  `detail_ref`/`handoff_ref` 保持兼容。
- 对 Envelope 顶层可输出字符串与 payload 任意嵌套 Mapping/Sequence 字符串
  执行统一高置信扫描：Bearer/Basic、凭据赋值、Provider/GitHub/Slack/AWS
  token、JWT、私钥和带 userinfo 的凭据 URI 均失败关闭。
- 保留并扩展递归敏感键拒绝，覆盖 `session_ref`、`provider_session`、
  `reasoning`、`chain_of_thought`、`credential`、`secret`、`token`、
  `password`、`cookie` 与 `authorization`。
- `TaskEventEnvelope.assert_valid()` 是构造和重验证共同边界；既有
  `InMemoryEventStream.emit()` 在任何 replay/subscriber 写入前调用它，既有
  `_sse_frame()` 在 JSON/SSE 生成前调用它。篡改后的对象不能绕过三层。

## 未完成与非目标

- 不修改 `contracts/**`；task-event.v1 的字段、类型、生产者矩阵和公共版本均
  无变化。
- 不修改 S2 Runtime/Graph、S4 Web/acceptance、S3 Policy 或 S6 Persistence。
- 不更新 `tests/acceptance/studio` 的旧 oracle；上游 S2 Handoff 已将其明确交给
  下一 S4 步骤更新并执行组合复算。
- 未执行在线 Provider、真实凭据、网络或付费调用。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `packages/application/src/flowpilot_application/task_events.py` | opaque ref 与递归高置信敏感值安全边界 | S5-CORE |
| `packages/application/src/flowpilot_application/models.py` | Envelope 顶层字符串与 principal ref 重验证 | S5-CORE |
| `tests/core/test_event_security.py` | 引用矩阵、敏感值、构造/stream/SSE 零写入测试 | S5-CORE |
| `tests/core/evidence/WP-072-sse-ref-value-r2-HANDOFF.md` | 本交接证据 | S5-CORE |

## 契约、数据库、依赖与配置变化

- ContractSet、JSON Schema、OpenAPI：无变化；Conformance PASS。
- Migration、PostgreSQL、Redis：无变化。
- `pyproject.toml`、`uv.lock`、`Makefile`、环境变量：无变化。
- 新生产依赖：无。
- API 公共形状：无变化；仅将原本会泄漏的非法引用和值收窄为失败关闭。

## 复现与修复证据

修复前独立复现：

```text
PLAINTEXT_REF_CONSTRUCTED=True
QUERY_REF_CONSTRUCTED=True
TOP_LEVEL_SECRET_CONSTRUCTED=True
NESTED_SECRET_CONSTRUCTED=True
INVALID_REF_DELIVERED=True
SUBSCRIBER_POLLUTED=True
REPLAY_POLLUTED=True
INVALID_REF_SSE=True
```

修复后相同复现：

```text
PLAINTEXT_REF_CONSTRUCTED=False
QUERY_REF_CONSTRUCTED=False
TOP_LEVEL_SECRET_CONSTRUCTED=False
NESTED_SECRET_CONSTRUCTED=False
INVALID_REF_DELIVERED=False
SUBSCRIBER_POLLUTED=False
REPLAY_POLLUTED=False
INVALID_REF_SSE=False
```

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| Task Event 定向安全矩阵 | PASS；77 passed | 所有合法 ref 正例、非法 URI、敏感值和三层零写入 |
| Core | PASS；156 passed | 领域/Application/API 回归 |
| `.\scripts\quality.ps1 lint` | PASS | Ruff；strict Mypy 125 source files |
| `.\scripts\quality.ps1 test-contract` | PASS | 20 schemas / 35 cases / 43 semantic cases / 52 features |
| `.\scripts\quality.ps1 test-security` | PASS；156 passed | 配置的跨角色安全集合与 Web Secret 扫描 |
| S5 变化文件高置信 Secret 扫描 | PASS；0 matches | 私钥、AWS/OpenAI 类 key 与 Bearer token 模式 |
| `.\scripts\quality.ps1 audit` | PASS | 0 known vulnerabilities；editable Workspace 包按入口定义跳过 |
| 全仓稳定闭包（`--ignore=tests/acceptance/studio`） | PASS；963 passed、1 explicit online skip | 保留 Runtime 真实安全/集成测试，仅排除上游声明待更新的 S4 oracle |
| 原始全仓 `pytest -q` | NOT PASS；963 passed、1 skip、4 errors | 四项均为同一旧 S4 Studio oracle 前置验证；上游 Handoff 已声明并交由 S4 更新 |
| Application/API wheel | PASS；2/2 | `flowpilot_application-0.1.0`、`flowpilot_api-0.1.0` |
| `git diff --check`、路径范围 | PASS | 仅 S5 授权路径 |

## 安全与失败路径

- 构造负例：明文 ref、空 opaque path、userinfo、query、fragment、控制字符、
  空白、Bearer/Basic、敏感赋值、Provider/AWS/JWT、私钥和凭据 URI。
- 入流负例：篡改 ref 或顶层敏感值后，subscriber queue=0、replay=0。
- SSE 负例：篡改 ref、敏感键或敏感值后，partial frame=0。
- 正例：九类 task-event.v1 分支继续精确匹配现有 Schema/producer；六类既有
  产品 ref scheme 与可选空 ref 保持兼容。
- 跨租户：前一 S5 修复继续保持跨租户 emit 的 queue/replay 成功写入为 0。

## 已知问题

- S4 现有 `tests/acceptance/studio` oracle 尚按修复前的 Studio 拒绝状态形状判断，
  原始全仓命令产生 4 个 fixture setup errors。该事实已由 S2 上游 Handoff 明确
  声明为下一 S4 范围；S5 没有越权修改。稳定闭包除该目录外 963 passed。
- 在线 Provider Smoke 未授权，保持显式 skip。

## 学习候选

```text
LEARNING_CANDIDATE=事件字段 allowlist 不能替代引用值和字符串内容安全
MATURITY=VERIFIED
TRIGGER=task-event payload 字段/producer 已精确校验，但合法 *_ref 可承载明文、query 凭据，合法字符串字段可承载 secret-like 内容
MECHANISM=只验证 JSON Schema 形状会让敏感内容借合法 string/ref 字段通过构造、replay buffer 和 SSE
STRUCTURE=统一 opaque ref 校验 + 顶层/嵌套高置信值扫描 + 构造/emit/serialize 三次同一 Envelope 重验证 + 零写入断言
EVIDENCE=tests/core/test_event_security.py；WP-072-sse-r2 提交
RESIDUAL_RISK=新增 task-event *_ref 字段或新凭据格式时必须扩展同一中央校验与黑盒扫描矩阵
TARGET=ENGINEERING_PLAYBOOK Event/SSE 数据最小化候选
```

## 接收会话下一步

1. 核验 S5 精确 `NEW_HEAD`、本文件 SHA256、ContractSet、线性祖先、范围与 clean，
   只用 `--ff-only` 到达精确 Head。
2. 恢复原 `WP-072-a1`，更新 S4 Studio oracle 以匹配 S2 修复后的失败关闭状态，
   不放宽 Runtime 权威边界。
3. 组合复算：Studio Command/update_state 绕过=0、跨租户 SSE=0、敏感 ref/value
   SSE=0、subscriber/replay/frame 污染=0，并继续 Web/SSE 验收。
4. P0/P1、Contract 变化、路径越权、新门禁失败或必须改变公共 task-event.v1 时
   停链上报 S1。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M7-LOCAL-PRODUCT-01
STEP_ID=M7-09R2-S5-SSE-REF-VALUE
ATTEMPT_ID=WP-072-sse-r2
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=de6c5b3252785742e50ff48025038ae18af364fd
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/core/evidence/WP-072-sse-ref-value-r2-HANDOFF.md
NEXT_ROLE=S4-QUALITY
NEXT_ATTEMPT_ID=WP-072-a1
ESCALATE_TO_S1=no
```

## 可回滚方式

- Revert 本 Handoff 所在提交；禁止 reset、rebase 或 force-push。
