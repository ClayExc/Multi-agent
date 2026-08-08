# WP-071-a1-core S5-CORE API/Application 组合交接

## 基本信息

- Work Package：WP-071
- Attempt ID：WP-071-a1-core
- Chain ID：CHAIN-M7-LOCAL-PRODUCT-01
- Step ID：M7-05-S5-CORE-COMPOSITION
- DEDUP Key：
  `CHAIN-M7-LOCAL-PRODUCT-01/M7-05-S5-CORE-COMPOSITION/WP-071-a1-core/2a923b8a61896bc747d4a745f3418ed39569df2a`
- 责任会话：S5-CORE
- 接收会话：S6-DATA
- 交接策略：CONSUMER_GATE
- 功能 ID：FP-FLOW-001、FP-FLOW-005、FP-OBS-001、FP-OPS-001
- 基线提交：`2a923b8a61896bc747d4a745f3418ed39569df2a`
- 实现提交：`7dad744aaf726f2a07908d78f43870db5d139bb2`
- 分支：`codex/s5/m7-core-composition`
- 最终提交：本文件所在提交；精确 SHA 由唤醒信封返回
- ContractSet 摘要：
  `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- Context 模式：DELTA；Context Base
  `0fb5f78f5fe876f6323a5d8afb12623b395ff974`
- 状态：当前 S5 Step 完成，等待 S6 消费门禁

## 完成内容

- 完成 S4 Provider 黑盒消费门禁：精确核验 S4 Head、Handoff/Proof Hash、
  ContractSet、线性祖先、授权路径与 clean 状态，并用 `--ff-only` 到达
  `2a923b8a61896bc747d4a745f3418ed39569df2a`。
- 新增框架无关 `compose_core_application`，显式接收：
  - Command `UnitOfWorkFactory`；
  - 只读 `TaskQueryUnitOfWorkFactory`；
  - S2 实现的幂等 `ExecutionPort`。
  返回 `CoreApplicationServices`，统一提供 `CommandIntakeService` 与
  `TaskQueryService`，不导入 S2/S6 具体 Adapter。
- 新增 `create_product_app` FastAPI 组合根，要求调用方显式提供：
  - Command、Task Query、Task Event 三类 Unit of Work；
  - S2 `ExecutionPort`；
  - 可信 `RequestSecurityPort`。
  组合根装配命令接入、只读 Task 查询、事务 Outbox 消费与租户隔离 SSE；可选
  接收 Approval Decision、Event Stream 配置和 UTC Clock。
- 模块级 `flowpilot_api.main:app` 继续保持未配置且失败关闭；只有显式调用
  `create_product_app` 并提供全部端口才形成产品组合。API 不直接连接 Provider、
  Worker、数据库、Redis、MCP、企业网络或凭据。
- 新增正常、边界、失败、安全和幂等测试：
  - 企业知识问答使用不透明 `initial_message_ref` 接入，原始中文正文不跨 API；
  - 相同命令重放只调用一次 Execution Port，并保留原始接收时间；
  - Provider/Runtime 异常映射为稳定、可重试且脱敏的 503；
  - 错配 Runtime Receipt 失败关闭为稳定 502；
  - 伪造浏览器 `X-Tenant-ID` 不能覆盖可信身份，持久化与 Runtime 调用均为 0；
  - API/Application 组合模块不导入 Provider SDK、Worker 或 Persistence 具体类。
- 保持在线 Provider Smoke 默认关闭；本 Attempt 没有读取真实凭据、没有启动
  Claude CLI、没有 Provider 或付费调用。

## 未完成与非目标

- 本 Step 只完成 S5 所有的 API/Application 组合入口，不表示 WP-071 后端链、
  M7 固定分母或发布门禁已经完成。
- 未实现 PostgreSQL/Redis、Compose、RLS、Checkpoint、Inbox/Outbox 具体 Adapter、
  恢复或迁移；这些是紧随其后的 S6 Step。
- 未实现 Worker/LangGraph 产品路由、正式企业知识库执行、Provider 调用、只读 MCP
  调用或 run/thread/checkpoint/trace ID 分配；这些是后续 S2 Step。
- 未实现 OIDC 或信任浏览器 Header；`RequestSecurityPort` 必须由受信适配器提供，
  请求正文与 Header 只能参与绑定校验，不能创建可信 `SecurityContext`。
- 未硬编码 VPN 路由、意图或页面。VPN 仍只是历史回归 Fixture。
- 未运行真实在线 Provider Smoke 或发布级 `make acceptance`；后者在链路后续
  WP-073/S7 才具备产品 executor 与发布语义。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `packages/application/src/flowpilot_application/composition.py` | 框架无关 Core Application 服务组合 | S5-CORE |
| `packages/application/src/flowpilot_application/__init__.py` | 导出组合 API | S5-CORE |
| `packages/application/README.md` | 记录三方端口和组合边界 | S5-CORE |
| `apps/api/src/flowpilot_api/composition.py` | 完整端口注入的本地产品 FastAPI 组合根 | S5-CORE |
| `apps/api/src/flowpilot_api/__init__.py` | 导出 `create_product_app` | S5-CORE |
| `apps/api/README.md` | 记录产品组合、可信身份与最小权限 | S5-CORE |
| `tests/core/test_product_composition.py` | 正常、重放、失败、协议与租户安全测试 | S5-CORE |
| `tests/core/evidence/WP-071-a1-core-HANDOFF.md` | 本交接 | S5-CORE |

## 契约、数据库与配置变化

- 契约版本：无修改；ContractSet 摘要保持不变。
- Migration / 数据库 / RLS：无。
- 环境变量：无新增或修改；没有读取真实值。
- `pyproject.toml` / `uv.lock` / `Makefile`：无变化；`uv lock --locked`
  仍为 168 packages。
- 兼容性：现有 `create_app` 与模块级未配置 ASGI 应用保持不变；新增组合 API 为
  内部 Python 加法，不扩宽公共 `TaskCommand`、Task、TaskEvent 或 OpenAPI 字段。

### S6 必须实现/提供的端口

- `UnitOfWorkFactory`：Command Inbox、Task Version 和 Version Slot 的事务边界。
- `TaskQueryUnitOfWorkFactory`：受租户约束的只读 Task 投影事务。
- `TaskEventUnitOfWorkFactory`：Task Query、Outbox 和 Consumer Inbox 的同租户
  事务边界。
- 同一个 S6 工厂可以结构化实现三种协议，但 Application 层不会假设它们共享
  事务实例，也不会在请求之间复用 Unit of Work。

## 验证

环境：Windows、CPython 3.12.11、uv 0.12.1；在线 Provider Smoke 默认关闭。

| 命令 | 结果 | 证据 |
|---|---|---|
| `uv ... pytest tests/core/test_product_composition.py -q` | PASS | 5 passed |
| `uv ... pytest tests/core -q` | PASS | 82 passed |
| `.\\scripts\\quality.ps1 test-all` | PASS | 820 passed、1 explicit online skip；Contract Conformance PASS |
| `.\\scripts\\quality.ps1 lint` | PASS | Ruff；strict Mypy 121 source files |
| `.\\scripts\\quality.ps1 test-security` | PASS | 114 passed |
| `.\\scripts\\quality.ps1 audit` | PASS | 0 known vulnerabilities；15 个本地 editable FlowPilot 包按入口定义跳过 |
| `uv lock --locked` | PASS | 168 packages |
| `uv build --all-packages --wheel` | PASS | 15/15 Workspace wheels |
| 全新 venv 安装与组合导出导入 | PASS | 15 个内部 wheel + 3 个精确 SDK；4 个组合导出可用；Provider 调用 0 |
| 高置信 Secret 扫描、范围审计、`git diff --check` | PASS | 0 matches；仅 S5 授权路径 |
| `make acceptance` | NOT_RUN | M7 产品 executor 与固定分母发布门禁属于 WP-073/S7，不是当前 S5 Step |

Contract Conformance：

```text
CONTRACT_CONFORMANCE_OK schemas=20 cases=35 positive=18 negative=17 mutation_cases=19 mutation_positive=3 mutation_negative=16 semantic_cases=43 semantic_positive=0 semantic_negative=43 audit_chain_cases=5 audit_chain_positive=1 audit_chain_negative=4 manifest_cases=21 manifest_positive=1 manifest_negative=20 review_attestation_cases=10 review_attestation_positive=2 review_attestation_negative=8 retired_review_attestation_cases=5 retired_review_attestation_positive=0 retired_review_attestation_negative=5 features=52
```

## 安全与失败路径

- 可信 tenant、subject、purpose、Security Context ID/ref/hash 只来自
  `RequestSecurityPort`，并在授权和 Application 持久化前与 `TaskCommand` 做完整
  绑定。浏览器 tenant Header 不能升级为可信事实。
- 跨租户伪造负例返回 403；Command Store、Execution Port 和授权调用均为 0。
- Runtime 原始异常不进入 API；测试使用包含 `api_key` 的合成异常，响应只暴露
  `CORE_EXECUTION_UNAVAILABLE` 与安全消息。
- Runtime Receipt 的 command/tenant/task/ref 任一绑定异常均映射为
  `CORE_EXECUTION_PROTOCOL_ERROR`，不会被记录为成功执行。
- Application/API 组合代码只依赖协议与服务，不导入三方 Provider SDK、S2 Worker
  或 S6 Persistence 实现；在线开关与凭据仍停留在 S2 Adapter 后方。
- Secret/PII 检查：安全入口 114 passed；变更高置信扫描 0 matches；无真实 PII、
  密钥、Prompt、Trace 或隐藏思考过程。

## 已知问题

- P2：`InMemoryEventStream` 的连接队列与短期 replay buffer 是进程内传输，不是
  业务事实源。Durable Outbox/Consumer Inbox、重投与 Redis 丢失恢复必须由 S6
  数据 Step 保持；SSE 客户端重连语义由后续 S4 Step 黑盒复核。
- P2：真实身份适配、OIDC 与浏览器登录属于 M8；M7 必须继续显式注入受信
  `RequestSecurityPort`，不得临时相信 Header。
- P2：真实在线 Provider Smoke 仍未授权；本组合仅证明端口接通与错误/安全语义，
  不证明真实模型质量、Endpoint 可用性或发布成功率。
- P2：run/thread/checkpoint/trace/event 标识的跨组件组合需要 S6/S2 后续 Step 才能
  完整复现，本 S5 Step 只保持已有不透明 `execution_ref` 与公共 ID 不变。

## 学习候选

```text
LEARNING_CANDIDATE=none
MATURITY=VERIFIED
TRIGGER=none
MECHANISM=none
STRUCTURE=none
EVIDENCE=7dad744aaf726f2a07908d78f43870db5d139bb2
RESIDUAL_RISK=none
TARGET=none
```

## 接收会话下一步

1. 核验 S5 `NEW_HEAD`、本 Handoff SHA256、ContractSet、线性祖先、分支、授权
   路径和 clean 状态；只用 `--ff-only` 精确到达 S5 Head。
2. 进入 `M7-06-S6-DATA-COMPOSITION` / `WP-071-a1-data`，实现或装配上文三类
   UoW 协议；PostgreSQL/RLS、Outbox/Inbox、Checkpoint、Redis 与 Compose 必须
   保持现有 S6 权威语义。
3. 复验跨租户成功数 0、Redis 清空、Worker 重启、旧 generation fencing、事件
   重投和真实凭据不进入环境模板。不要修改 S5/S2/S3 路径或公共 Contract。
4. 正常完成后只唤醒链路唯一下一 S2 Runtime Step；P0/P1、Contract/S3 边界、
   越权、破坏性迁移、门禁失败或未授权付费调用立即停链上报 S1。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M7-LOCAL-PRODUCT-01
STEP_ID=M7-05-S5-CORE-COMPOSITION
ATTEMPT_ID=WP-071-a1-core
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=2a923b8a61896bc747d4a745f3418ed39569df2a
IMPLEMENTATION_HEAD=7dad744aaf726f2a07908d78f43870db5d139bb2
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/core/evidence/WP-071-a1-core-HANDOFF.md
NEXT_ROLE=S6-DATA
NEXT_ATTEMPT_ID=WP-071-a1-data
ESCALATE_TO_S1=no
```

## 可回滚方式

- 按逆序 revert 本 Handoff 提交和实现提交
  `7dad744aaf726f2a07908d78f43870db5d139bb2`；禁止 reset、rebase 或
  force-push。本 Step 没有数据库、外部系统或生产数据写入，无数据回滚。
