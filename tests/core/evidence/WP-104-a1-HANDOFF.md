# WP-104 / S5-CORE Handoff

## 基本信息

- Work Package：WP-104
- Attempt ID：WP-104-a1
- Chain ID：CHAIN-M9-GOVERNANCE-01
- Step ID：M9-04-S5-GOVERNANCE-API
- 责任会话：S5-CORE / governance-api-builder
- 接收会话：S6-DATA / audit-data-builder
- 交接策略：`CONSUMER_GATE`
- 功能 ID：FP-SEC-004、FP-OBS-002、FP-OBS-003
- 基线提交：`400d70b75400640e57a8cd901469f7ea7a028cf2`
- 分支/最终提交：`codex/s5/wp-104-m9-governance-api` / 本文件所在提交
- ContractSet 摘要：`sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：完成

## 完成内容

- 消费者门禁接受 WP-103：Context、Agent Runtime、Model Gateway 和 Worker 直接复用
  S3 `flowpilot_security` 集中内容安全能力，未复制 DLP/Prompt-Injection 规则；Core
  362 与 Contract Conformance 在实现前独立复算通过。
- 新增 `flowpilot.governance-query.m9.v1` Application Port：
  - `GovernanceQueryContext` 只由可信 Cookie 身份派生；包含 Tenant、Subject、Purpose
    和 SecurityContext Ref/Hash，不接收浏览器自报身份。
  - `GovernanceQueryUnitOfWorkFactory(context)` 在事务建立前传入可信上下文，供 S6
    在同一事务中设置 RLS，查询过程不能切换 Tenant。
  - Policy Version、Policy Decision、Audit、Security Event 和 Correlation Chain 使用
    封闭 DTO；不暴露 Rego module/data、Policy input preimage、Prompt、原始参数/结果、
    资源/证据正文、凭据或隐藏推理。
  - Service 二次验证 Tenant、关联 ID、页大小、唯一 ID、游标形状和集中
    `assert_safe_projection`；跨租户、超页、重复、危险投影稳定失败关闭。
- 新增五个受控 FastAPI 只读接口：
  - `GET /v1/governance/policy-versions`
  - `GET /v1/governance/policy-decisions`
  - `GET /v1/governance/audit-events`
  - `GET /v1/governance/security-events`
  - `GET /v1/governance/correlations/{correlation_id}`
- 治理请求沿用生产 `OidcRequestSecurity` Cookie-only 边界，并新增显式
  `GovernanceAccessPolicy`。每次请求重新解析 Session、resolve/verify 当前
  SecurityContext，再以 composition 注入的 Role/Purpose allowlist 授权；缺策略、缺
  Port、普通用户、Bearer 和身份覆盖 Header 均失败关闭。
- Query 只接受路由级闭集字段；未知、重复、Tenant/Role/Purpose/Prompt 等敏感查询
  字段、坏时间窗和畸形游标在 Repository 调用前拒绝。成功响应固定
  `Cache-Control: no-store`、`Vary: Cookie`。
- `create_product_app` 原子接收治理 Query UoW 与 Access Policy，禁止只装配其中一侧。
- M9 Workspace/Lock 无新依赖：`uv.lock`、根 `pyproject.toml` 和 `Makefile` 保持不变；
  169 个锁条目可解析，16 个 Workspace wheel 全部构建并在全新 Python 3.12 环境中
  安装、导入通过。

## 未完成与非目标

- 未实现 PostgreSQL Repository、RLS、签名游标、Audit/Security append、Migration、
  OPA Infra、Secret Infra、Web 或产品执行器；上述数据库范围交给 WP-105。
- Application 只规定游标必须是有界 opaque `gcur_...`；S6 必须验证签名，并将游标
  绑定 Tenant、资源类型、规范化过滤器、排序位置和版本。不得把形状校验当作真实性
  校验。
- 不修改公共 `contracts/**`，不把 S3 `PolicyBundleRelease` 或
  `ResolvedPolicyDecision` 直接序列化到 API。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `packages/application/src/flowpilot_application/governance.py` | 治理安全 DTO、Query Port/UoW、Service、稳定版本 | S5 |
| `packages/application/src/flowpilot_application/errors.py` | Cursor/Not Found/Repository/Unsafe Projection 稳定错误码 | S5 |
| `packages/application/src/flowpilot_application/__init__.py` | 导出治理 Application API | S5 |
| `apps/api/src/flowpilot_api/security.py` | 显式 GovernanceAccessPolicy 与每请求重验授权 | S5 |
| `apps/api/src/flowpilot_api/app.py` | 五个受控治理查询路由、严格 query 解析与错误映射 | S5 |
| `apps/api/src/flowpilot_api/models.py` | 封闭 Pydantic 响应模型 | S5 |
| `apps/api/src/flowpilot_api/composition.py` | Query UoW 与 Access Policy 原子组合 | S5 |
| `apps/api/src/flowpilot_api/errors.py` | 稳定治理 query 错误码 | S5 |
| `apps/api/src/flowpilot_api/testing.py` | Static RequestSecurity 治理授权 Fake | S5 |
| `apps/api/src/flowpilot_api/__init__.py` | 导出 GovernanceAccessPolicy | S5 |
| `tests/core/test_governance_api.py` | 正常、边界、失败、安全、分页与投影回归 | S5 |
| `tests/core/test_product_composition.py` | 治理 Port/Policy 原子组合负例 | S5 |
| `tests/core/evidence/WP-104-a1-HANDOFF.md` | 本交接证据 | S5 |

## 契约、数据库与配置变化

- 契约版本：公共 Contract 无变化；新增内部 Port 版本
  `flowpilot.governance-query.m9.v1`。
- Migration：无。
- 环境变量：无。
- 依赖/Lock：无新增生产或开发依赖；`pyproject.toml`、`uv.lock`、`Makefile` 未变化。
- 兼容性：仓库内 `OidcRequestSecurity` 与 `StaticRequestSecurity` 已实现新增治理授权方法；
  S6 只需实现新 Query UoW/Port，不得依赖 S3 私有模型或放宽公共 Contract。

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| WP-103 consumer review | PASS | 直接复用 S3 Content Safety；无规则复制、无 Contract/S5 路径变化 |
| `uv run --all-packages --all-groups --locked python -B -m pytest tests/core/test_governance_api.py tests/core/test_product_composition.py -q` | PASS | 32 passed |
| `uv run --all-packages --all-groups --locked python -B -m pytest tests/core -q` | PASS | 389 passed / 82.95s |
| `uv run --all-packages --all-groups --locked ruff check apps packages mcp-servers domain-packs scripts tests web` | PASS | All checks passed |
| `uv run --all-packages --all-groups --locked mypy --strict ...` | PASS | 154 source files |
| `uv run --all-packages --all-groups --locked python -B contracts/conformance/validate.py` | PASS | 20 schemas / 35 cases / 43 semantic / 52 features |
| `uv run --all-packages --all-groups --locked python -B -m pytest tests/experience/test_secret_scan.py -q` | PASS | 2 passed |
| `uv lock --check` | PASS | 169 packages resolved；lock unchanged |
| `uv build --all-packages --wheel --out-dir <temp>` | PASS | 16/16 Workspace wheels built |
| 全新 Python 3.12 venv 安装 16 wheel 并导入 16 模块 | PASS | 59 resolved；`ISOLATED_WHEEL_IMPORTS=16_PASS` |
| `git diff --check` / Scope 检查 / commit 后 clean | PASS | 无空白错误；差异仅在 WP-104 S5 授权路径 |

## 安全与失败路径

- 已验证负向路径：无 Cookie、浏览器 Bearer、`X-Tenant-Id`、`X-Role`、`X-Purpose`、
  普通用户、错误 Purpose、过期/撤销 Context、未知/重复/敏感 query、畸形/伪造游标、
  反向时间窗、跨 Tenant 投影、重复记录、危险 DLP 投影、Repository 异常、缺组合依赖。
- 身份失败在 Query Port 前发生；跨 Tenant 成功读取为 0。Repository 原异常、DSN、
  Token、Tenant 细节不进入 API 错误。
- Secret/PII 检查：Secret Scan 2 passed；响应不包含 `tenant_id`/`subject_id` 字段、
  Context、Rego input、Prompt、参数/结果正文、Resource/Evidence Ref 或凭据。
- 游标真实性由 S6 Repository 负责；Application/API 已定义稳定
  `CORE_GOVERNANCE_CURSOR_INVALID` 400 映射并测试 Port 拒绝路径。

## 已知问题

- P2 / 上游包元数据：WP-103 的 `flowpilot-context`、`flowpilot-model-gateway`、
  `flowpilot-agent-runtime`、`flowpilot-worker` 存在直接导入与各自 package metadata 声明
  不完全一致。它们位于 S2 独占路径且不在 WP-104 Write Scope，本步骤未越权修改。
  完整 16-wheel Workspace 集的构建、安装和导入已通过；若未来要求逐个独立发布这些
  S2 wheel，应由 S2/S1 单独补齐直接依赖元数据。该 P2 不影响 S6 实现治理 Query Port。

## 已知事实与避免重复

- `KNOWN_FACTS`：WP-103 Handoff
  `sha256:9287df80bf20faba68e0aa86477f11abdaa8805d2271940dde7b5970dc5b498f`；
  S2 Head `400d70b75400640e57a8cd901469f7ea7a028cf2`；Contract Digest 与授权一致。
- `DO_NOT_RECHECK`：S6 不重复 WP-103 DLP 接线审查、不重跑 S2 Runtime 278、不重读 S3
  私有规则；只消费本 Port 与本 Handoff。
- `FAILURE_SIGNATURES`：`CORE_GOVERNANCE_CURSOR_INVALID`=不可信/错绑定游标；
  `CORE_GOVERNANCE_REPOSITORY_PROTOCOL_ERROR`=跨租户、超页、重复或结构违约；
  `CORE_GOVERNANCE_UNSAFE_PROJECTION`=集中安全投影拒绝。
- `REUSED_DECISIONS`：复用 S3 `assert_safe_projection` 和 OIDC Cookie-only
  RequestSecurity，不复制 DLP 或身份实现。
- `DUPLICATE_WORK_AVOIDED`：复用 WP-103 生产者证据；消费者只换观察边界复核
  Content Safety 调用位置与错误映射。

## 学习候选

```text
LEARNING_CANDIDATE=tenant-bound-query-uow-with-closed-projection
MATURITY=VERIFIED
TRIGGER=治理读同时需要RLS绑定、游标真实性和防止高敏事实模型被直接序列化
MECHANISM=若Repository接收浏览器Tenant或API直接返回内部Policy/Audit模型，RLS与DLP任一层失误都会形成跨租户或敏感数据泄漏
STRUCTURE=可信Cookie身份派生QueryContext，在UoW创建时绑定Tenant/Context；Repository签名游标；Application用封闭DTO再验Tenant/页协议/集中安全投影
EVIDENCE=tests/core/test_governance_api.py；Core 389；Secret Scan 2
RESIDUAL_RISK=签名游标、PostgreSQL RLS和append完整性仍待WP-105实库验证
TARGET=docs/architecture/ENGINEERING_PLAYBOOK.md governance query boundary
```

## 子 Agent 使用摘要

```text
SUBAGENTS_USED=2
SUBAGENT_MODES=READ_ONLY_PARALLEL
SUBAGENT_TASKS=wp104-consumer-review,wp104-api-model
SUBAGENT_WRITERS=0
PARENT_REPRODUCED_RESULTS=yes
REUSED_DECISIONS=WP-103-Handoff,S3-central-content-safety,existing-OIDC-request-security
DUPLICATE_WORK_AVOIDED=2
```

## 接收会话下一步

1. S6 先验证本 Handoff Hash、精确 Head、Contract Digest、范围与 clean，再以
   `--ff-only` 进入 WP-105。
2. 实现 `GovernanceQueryUnitOfWorkFactory(context)`；同一事务使用可信 Tenant/Context
   设置 RLS，连接池复用前后都不能残留或切换 Tenant。
3. 实现五个 Query Port 方法，只构造本 Port 的封闭 DTO。签名游标必须绑定 Tenant、
   资源类型、规范化过滤器、排序位置和版本；伪造/跨租户/跨过滤器复用抛出
   `ApplicationError(ErrorCode.GOVERNANCE_CURSOR_INVALID, ...)`。
4. 将 Append-only Audit/Security Store、可信 sequence、完整性链、双向关联和 Migration
   与 Query UoW 一并验证；不得把原始 arguments/result/evidence 或内部 Policy input
   填入安全 DTO。
5. WP-105 PASS 后按链授权热继续 WP-106；P0/P1、Contract 变化、越权或门禁失败停链回
   S1。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M9-GOVERNANCE-01
STEP_ID=M9-04-S5-GOVERNANCE-API
ATTEMPT_ID=WP-104-a1
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=400d70b75400640e57a8cd901469f7ea7a028cf2
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/core/evidence/WP-104-a1-HANDOFF.md
NEXT_ROLE=S6-DATA
NEXT_ATTEMPT_ID=WP-105-a1
ESCALATE_TO_S1=no
SUBAGENTS_USED=2
```

## 可回滚方式

- 回滚本文件所在提交；不需要 Contract、Migration、数据或环境回滚。
