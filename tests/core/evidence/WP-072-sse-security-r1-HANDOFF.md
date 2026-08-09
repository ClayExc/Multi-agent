# WP-072-sse-r1 S5-CORE SSE/Event 安全返修交接

## 基本信息

- Work Package：WP-072
- Attempt ID：WP-072-sse-r1
- Chain ID：CHAIN-M7-LOCAL-PRODUCT-01
- Step ID：M7-09R-S5-SSE-SECURITY
- DEDUP Key：
  `CHAIN-M7-LOCAL-PRODUCT-01/M7-09R-S5-SSE-SECURITY/WP-072-sse-r1/f1c911c7a8605958947b9f01ad38a86781d89418`
- 风险/严重度：R3 / P0
- 责任会话：S5-CORE
- 接收会话：S2-RUNTIME
- 交接策略：CONSUMER_GATE
- 功能 ID：FP-OBS-001、FP-SEC-002、FP-SEC-006
- 基线提交：`f1c911c7a8605958947b9f01ad38a86781d89418`
- 分支：`codex/s5/m7-core-composition`
- 最终提交：本文件所在提交；精确 SHA 由唤醒信封返回
- ContractSet 摘要：
  `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- Context 模式：DELTA；Context Base
  `726f875ab689eca3627a96af2efe8137fb1756de`
- 状态：S5 P0/P1 返修完成，等待 S2 Studio 权威边界返修

## 完成内容

- `InMemoryEventStream.emit` 在 replay buffer 或 subscriber queue 任一写入前：
  - 校验 stream route tenant 是有界非空字符串；
  - 要求 route `tenant_id` 与 `event.tenant_id` 完全一致；
  - 重新验证完整 `TaskEventEnvelope`。
  错配直接稳定失败关闭，subscriber/replay 写入均为 0。
- 新增 Application 内部 `task_events` 精确验证器，执行现有
  `contracts/jsonschema/task-event.v1.schema.json` 的九个 `oneOf` 分支：
  - event_type 集合；
  - producer 绑定；
  - payload required/optional 白名单；
  - `additionalProperties=false`；
  - 字符串边界、枚举、布尔、数组非空/唯一、标识/Digest/RFC3339 格式。
- 测试从仓库 JSON Schema 动态提取各分支，逐项断言 Application 投影的事件集合、
  producer、required 和 properties 完全相等；每个事件的正例同时通过正式 Schema。
  每种事件的额外字段、缺字段、错 producer 和代表性类型/格式负例同时被正式
  Schema 与 Application 拒绝，未复制更宽松规则。
- 对 payload 的任意嵌套 Mapping/Sequence 递归拒绝敏感键。大小写和分隔符归一化
  后覆盖 `session_ref`、`provider_session`、`reasoning`、`chain_of_thought`、
  credential、secret、token、password、cookie、authorization、API/private key。
- `TaskEventEnvelope` 在构造时先冻结 JSON payload，再验证实际保存值；新增
  `assert_valid()` 供信任边界重验。`to_mapping()` 也重新验证，并把冻结 tuple/
  Mapping 转回真正 JSON array/object，确保输出可直接通过 JSON Schema。
- `_sse_frame` 在生成任何字符串前重新验证 Envelope；构造后被低层篡改的敏感
  payload 在 Stream 入流和 SSE 序列化两处均失败，不产生部分 Frame。
- 对齐现有 Schema：`approval_service` 的 `run_id` 可为 null；其他 producer 仍必须
  使用符合 `run_*` 格式的非空 run_id；trace/causation 字段按现有 Schema 边界执行。

## 未完成与非目标

- 不修改 `contracts/**`；现有 JSON Schema 可确定性实现，无 RFC。
- 不修改 S2 Studio、S4 Web、S3 Policy/MCP/Tool、安全契约或其他角色路径。
- 不实现 Web 页面、真实 Provider、外部网络或付费调用。
- 本 Handoff 只关闭 S5 所有的 SSE route/Event payload P0/P1；S2 Studio 输入、
  visited node、Frame merge/同 ID 指纹问题仍须按下一有序 Step 修复。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `packages/application/src/flowpilot_application/task_events.py` | task-event.v1 精确 payload/producer 与递归敏感键验证 | S5-CORE |
| `packages/application/src/flowpilot_application/models.py` | Envelope 构造、边界重验和 JSON wire 转换 | S5-CORE |
| `apps/api/src/flowpilot_api/stream.py` | route tenant 绑定及写前 Envelope 重验 | S5-CORE |
| `apps/api/src/flowpilot_api/app.py` | SSE Frame 序列化前重验 | S5-CORE |
| `tests/core/test_event_security.py` | 九事件契约矩阵、跨租户/敏感污染直接负例 | S5-CORE |
| `tests/core/evidence/WP-072-sse-security-r1-HANDOFF.md` | 本交接证据 | S5-CORE |

## 契约、数据库与配置变化

- 契约版本：无修改；ContractSet 摘要保持不变。
- Schema 语义：实现开始严格执行既有 `task-event.v1`，没有增加或删除字段。
- 数据库 / Migration / RLS / Redis：无修改。
- 依赖、环境变量、`pyproject.toml`、`uv.lock`、`Makefile`：无变化。
- API 路径/OpenAPI：无变化；非法事件在内存流/SSE 边界提前失败关闭。
- 兼容性：Schema 合法的九种事件保持可构造、可序列化；此前实现错误接受的
  额外字段、错 producer、敏感 payload 和跨租户 route 不再兼容，属于安全修复。

## 验证

环境：Windows、CPython 3.12、uv locked Workspace；在线 Provider Smoke 默认关闭。

| 命令 | 结果 | 证据 |
|---|---|---|
| 修复前公开边界最小复现 | REPRODUCED | CROSS_TENANT_DELIVERED、SENSITIVE_EVENT_CONSTRUCTED、SENSITIVE_SSE 均为 True |
| 修复后相同最小复现 | PASS | 上述三项及 SUBSCRIBER_POLLUTED、REPLAY_POLLUTED 均为 False |
| `pytest tests/core/test_event_security.py -q` | PASS | 33 passed |
| `pytest tests/core -q` | PASS | 121 passed |
| `pytest <test-security + secret targets> -q` | PASS | 117 passed |
| `contracts/conformance/validate.py` | PASS | 20 schemas、43 semantic negatives、52 features |
| 全仓 `pytest -q` | PASS | 883 passed、1 explicit online Provider skip |
| 全仓 Ruff | PASS | 0 errors |
| 全仓 strict Mypy | PASS | 125 source files |
| Application/API wheel 构建 | PASS | 2/2 wheels |
| `git diff --check` 与路径审计 | PASS | 仅 S5 授权路径；无 whitespace error |

Contract Conformance：

```text
CONTRACT_CONFORMANCE_OK schemas=20 cases=35 positive=18 negative=17 mutation_cases=19 mutation_positive=3 mutation_negative=16 semantic_cases=43 semantic_positive=0 semantic_negative=43 audit_chain_cases=5 audit_chain_positive=1 audit_chain_negative=4 manifest_cases=21 manifest_positive=1 manifest_negative=20 review_attestation_cases=10 review_attestation_positive=2 review_attestation_negative=8 retired_review_attestation_cases=5 retired_review_attestation_positive=0 retired_review_attestation_negative=5 features=52
```

## 安全与失败路径

- 跨租户 emit：`tenant-a` route + `tenant-b` Envelope 返回稳定 ValueError；既有
  subscriber queue 为空，随后订阅 replay 仍为空，跨租户成功交付为 0。
- 敏感构造：顶层 `session_ref`、`reasoning` 和嵌套
  `provider_session → credential → access_token` 均在构造阶段拒绝。
- 篡改旁路：使用低层 `object.__setattr__` 模拟构造后 payload 损坏，Stream emit
  与 `_sse_frame` 都重新拒绝；subscriber/replay/SSE 敏感输出均为 0。
- Schema 负例：九种 event_type 均覆盖额外字段、缺字段、错 producer；另逐类覆盖
  const/enum、空数组、日期、ID/Digest、ref、boolean 等类型/格式错误。
- Secret/PII：安全入口含高置信 Secret 扫描并通过；本 Attempt 没有真实凭据、PII、
  Prompt、Trace、隐藏思考过程或外部调用。

## 已知问题

- S2 Studio 仍存在独立 R3 缺口：浏览器可提供服务端派生/权威字段，Frame merge
  未对左右两侧完整复验，同 frame_id 不同内容仍可能 last-write-wins；链路必须继续
  `M7-08R-S2-STUDIO-AUTHORITY`，不能直接恢复 S4 Web。
- `InMemoryEventStream` 仍是进程内传输而非业务事实源；这不改变既有 durable
  Outbox/Consumer Inbox 事实边界。

## 学习候选

```text
LEARNING_CANDIDATE=Fan-out 路由身份必须在任何 buffer/queue 写入前与消息身份绑定
MATURITY=VERIFIED
TRIGGER=emit(route_tenant=a, envelope_tenant=b) 被 a 的 subscriber 与 replay 接收
MECHANISM=传输层按独立 route 参数选择 fan-out 目标，但未把该参数与不可变 Envelope 的 tenant 事实绑定，形成跨租户 confused-deputy 投递
STRUCTURE=构造时执行精确事件契约；每个入流/序列化信任边界重新验证；route tenant 完全一致后才允许任何缓冲或 fan-out 写入
EVIDENCE=tests/core/test_event_security.py; tests/core/evidence/WP-072-sse-security-r1-HANDOFF.md
RESIDUAL_RISK=S2 Studio 权威输入和 Frame merge 尚待下一 Consumer Step 关闭
TARGET=docs/architecture/ENGINEERING_PLAYBOOK.md
```

## 接收会话下一步

1. 核验 S5 `NEW_HEAD`、本 Handoff SHA256、ContractSet、线性祖先、分支、授权
   路径和 clean 状态；只用 `--ff-only` 精确到 S5 Head。
2. 进入 `M7-08R-S2-STUDIO-AUTHORITY` / `WP-072-studio-r1`：新 Studio Thread
   初始输入仅允许注册 `scenario`；profile、visited_nodes、debug_projection 和所有
   服务端派生/权威字段一律拒绝。
3. `assert_studio_input_safe` 使用明确 allowlist 并递归拒绝敏感/权威字段；
   `_append_visits` 校验每个服务端节点；`_merge_frames` 对左右两侧每个 Frame 做
   完整安全验证。
4. 同 `frame_id` 只允许同指纹幂等重放；同 ID 不同内容必须失败关闭，禁止
   last-write-wins。浏览器伪造 frame/tenant/credential/reasoning/node 保留数为 0，
   损坏的持久化左侧 Frame 同样失败关闭。
5. 保持真实 LangGraph Interrupt/Resume 与服务端生成安全投影可用；不修改公共
   Contract、不读取真实凭据、不付费调用。
6. PASS 后直接唤醒 S4 任务
   `019fa699-6ed3-79f3-a2c4-6daea933f4ff`，以新精确 Head 恢复原 WP-072-a1；
   S4 复算跨租户、敏感 SSE、伪造 Studio 全部为 0 后才继续 Web/SSE 实现。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M7-LOCAL-PRODUCT-01
STEP_ID=M7-09R-S5-SSE-SECURITY
ATTEMPT_ID=WP-072-sse-r1
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=f1c911c7a8605958947b9f01ad38a86781d89418
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/core/evidence/WP-072-sse-security-r1-HANDOFF.md
NEXT_ROLE=S2-RUNTIME
NEXT_ATTEMPT_ID=WP-072-studio-r1
WAKE_TARGET_THREAD_ID=019fa697-7be1-7811-8afe-5d8763bbfd9f
NEXT_TASK_THREAD_ID=019fa699-6ed3-79f3-a2c4-6daea933f4ff
ESCALATE_TO_S1=no
```

## 可回滚方式

- Revert 本 Handoff/实现提交；禁止 reset、rebase 或 force-push。本返修没有数据库、
  Migration、共享依赖或外部系统写入，无数据回滚。
