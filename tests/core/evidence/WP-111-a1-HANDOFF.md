# WP-111 / S5-CORE Handoff

## 基本信息

- Work Package：WP-111
- Attempt ID：WP-111-a1（工程控制面修复：WP-111-a1-r1）
- Chain ID：CHAIN-M10-KNOWLEDGE-01
- Step ID：M10-01-S5-KNOWLEDGE-CORE / M10-01R-S5-ENGINEERING-CONTROL
- 责任会话：S5-CORE
- 接收会话：S6-DATA
- 交接策略：CONSUMER_GATE
- 功能 ID：FP-FLOW-003、FP-DATA-001、FP-SEC-003、FP-UI-001；工程控制面修复复用 FP-OPS-002
- 基线提交：`4c32c4d7f4095e5c93e8d2a017bcd099bbdb05e4`
- 产品实现提交：`52ad1ef91c615265396215eb1187a4c7b6790b27`
- 工程控制面修复提交：`71ed366fdf5c085d107338766c9fb14ebef2232e`
- 分支：`codex/s5/wp-111-m10-knowledge-core`
- ContractSet 摘要：`sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：完成

## 完成内容

- 新增纯 Python 知识领域模型：文档聚合、不可变内容版本、ACL、用途、分级、来源、有效/过期窗口、正文哈希与稳定引用。
- 文档并发修订 `revision` 与内容版本 `current_version` 分离，均从 0 开始。更新同时推进两者；撤销/删除只推进聚合修订，不伪造内容版本。
- 正文在进入 Port 前规范化为 NFC 和 LF，并校验 UTF-8 SHA-256；正文及来源引用使用 `repr=False`，不进入请求摘要、事件、索引任务、收据或稳定错误。
- 新增 import/update/retire/delete/rebuild/query/diagnostic Application 模型、Port 与服务，以及稳定的 `CORE_KNOWLEDGE_*` 错误族。
- 新增精确绑定的授权边界：策略决策必须绑定租户、可信 SecurityContext、subject、purpose、操作、文档、当前修订、当前/目标 ACL 摘要、目标分级与正文哈希。
- 新增集中内容安全 Port；S5 不复制 S3 的 DLP/Prompt 规则。
- 新增 Repository/UoW/Idempotency Inbox/Outbox/Index Job/Diagnostic Port，S6 可直接实现。
- 稳定引用严格查询指定版本并校验哈希；旧引用可解析到原版本，但永远不会重定向到最新版本。文档撤销、删除、未生效或过期时失败关闭。
- 修复工程控制选择器：TARGETED、SHARED、migration-real 统一使用 Workspace 全包/全组的 `python -B -m pytest` 入口；FULL/RELEASE 的既有 `make` 入口保持不变。

## S6 必须保持的事务与持久化语义

1. `KnowledgeUnitOfWork` 的 `documents`、`inbox`、`outbox`、`index_jobs` 必须绑定同一 PostgreSQL 事务及同一受信 tenant；事务内不得切换 tenant。
2. import 必须原子写入 `KnowledgeDocument(revision=0,current_version=0)`、`DocumentVersion(version=0)`、正文、Inbox 完成记录、元数据 Outbox 和 UPSERT Index Job。
3. update 必须按 `expected_revision` 做数据库 CAS，追加唯一且不可变的 `current_version + 1`，不能覆盖旧版本。CAS 失败返回 `CONFLICT`，不得产生部分正文、Inbox、Outbox 或 Index Job。
4. retire/delete 按 `expected_revision` 做 CAS。retire 保留版本事实但投递 REMOVE；delete 在同一事务写 tombstone、删除所有正文载荷并投递 REMOVE，仅保留拒绝旧引用所需的安全元数据。
5. Inbox `claim` 和 `complete` 必须在同一 UoW：同 tenant/key/摘要返回原收据；同 key 异摘要返回 `CONFLICT`；未提交 claim 在回滚后不可见。
6. Outbox payload 只能使用 `KnowledgeOutboxEvent.safe_payload()` 的闭集元数据，不得加入正文、source_ref、ACL principal、SecurityContext、Token、Secret 或任意原异常。
7. Index Job 由稳定 `job_id` 幂等；消费方必须校验 tenant/document/version/revision/content_hash 全绑定，索引不是事实源。
8. Repository 的所有读取必须 tenant-bound。返回错 tenant、错 document、错 version 或诊断漂移时，Application 会以 `CORE_KNOWLEDGE_REPOSITORY_PROTOCOL_ERROR` 失败关闭。
9. 查询 exact version 后仍须应用当前文档 lifecycle，以及该版本 ACL、purpose、classification、effective/expiry；不能先召回再过滤。
10. 策略拒绝的不可采样 Audit/Security Event 仍由可信 Policy/Security 边界产生；S6 不应从失败请求或自报 tenant 合成安全事实。

## 未完成与非目标

- 未实现数据库、Migration、RLS、Redis、向量/关键词索引或 Outbox 消费者；这些属于 WP-112/WP-113。
- 未实现 Retrieval、MCP、Runtime、Web 或知识 API composition。
- 未修改 `knowledge.search.v1`、schema pin、公共 Contract、根 Workspace、依赖锁或 Makefile。
- 未实现跨实例缓存或索引协调；PostgreSQL 仍是唯一业务事实源。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `packages/domain/src/flowpilot_domain/knowledge.py` | 知识聚合、版本、ACL、内容、来源和稳定引用 | S5 |
| `packages/domain/src/flowpilot_domain/{__init__,errors}.py` | 公开导出与稳定 Domain 错误 | S5 |
| `packages/application/src/flowpilot_application/knowledge_models.py` | 请求、授权、事件、索引、诊断与收据模型 | S5 |
| `packages/application/src/flowpilot_application/knowledge_ports.py` | Repository/UoW/Inbox/Outbox/Index/Query Port | S5 |
| `packages/application/src/flowpilot_application/knowledge_services.py` | 生命周期命令和精确版本查询服务 | S5 |
| `packages/application/src/flowpilot_application/{__init__,errors}.py` | 公开导出与稳定 Application 错误 | S5 |
| `tests/core/test_knowledge_core.py` | 正常、边界、失败、安全、幂等、并发与回滚回归 | S5 |
| `packages/engineering-control/src/flowpilot_engineering_control/selection.py` | 统一直接 pytest Workspace argv | S5（S1 Scope Expansion） |
| `tests/core/engineering_control/test_{selection,cli,evidence_cache}.py` | argv、CLI、Plan/Cache 漂移回归 | S5（S1 Scope Expansion） |

## 契约、数据库与配置变化

- 契约版本：无变化；`knowledge.search.v1` 与 schema pin `sha256:b7679fde5be1187e8a36b4cd4dd95a95b63a50dc56532294174b0088f0e6600b` 未改。
- Migration：无。
- 环境变量：无。
- 依赖/锁：无；`pyproject.toml`、`uv.lock` 未改。
- 兼容性：新增内部 Python Port 版本 `flowpilot.knowledge-ports.m10.v1`；既有 Port/Contract 未放宽。

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| `uv run --locked pytest -q tests/core/test_domain.py tests/core/test_application.py tests/core/test_knowledge_core.py` | PASS | 43 passed；产品提交后未再修改 Domain/Application |
| `uv run --locked pytest -q tests/core/engineering_control` | PASS | 58 passed |
| `uv run --locked ruff check packages/domain/src packages/application/src tests/core/test_knowledge_core.py` | PASS | 产品实现提交前 PASS |
| `uv run --locked mypy --strict packages/domain/src packages/application/src tests/core/test_knowledge_core.py` | PASS | 25 source files；产品实现提交前 PASS |
| `uv run --locked ruff check packages/engineering-control/src/flowpilot_engineering_control tests/core/engineering_control` | PASS | 工程控制面修复 PASS |
| `uv run --locked mypy --strict packages/engineering-control/src` | PASS | 13 source files |
| `uv lock --check` | PASS | 169 packages；后续未改 Workspace/Lock，selector lock tree signature=`3b2f66bc665bf7c2a1b39c8283f95888e1d82c77c253e9154222b88840e9a665` |
| `flowpilot-eng tests select ...` | PASS | SHARED；complete=true；fallback=false；Plan=`sha256:5fe8b67018490c65762f44212cefee45cf8c16444bfd32e0591df68dc5a19ad4`；argv hash=`sha256:6fcdbcd3fc7f46d1ccb629ace28d715d5a2de41a6f4bdc9aa76c646ddd899b2f` |
| `uv run --all-packages --all-groups --locked python -B -m pytest -q tests/core tests/runtime tests/data tests/platform` | PASS | 1226 passed，1 explicit online-provider skip |
| `uv build --wheel --package flowpilot-domain` | PASS | `flowpilot_domain-0.1.0-py3-none-any.whl` |
| `uv build --wheel --package flowpilot-application` | PASS | `flowpilot_application-0.1.0-py3-none-any.whl` |
| `uv build --wheel --package flowpilot-engineering-control` | PASS | `flowpilot_engineering_control-0.1.0-py3-none-any.whl` |
| `uv run --all-packages --all-groups --locked python -B -m pytest -q tests/experience/test_secret_scan.py` | PASS | 2 passed |

旧选择计划 `sha256:a6843e8085d29b703826f684a5d5ced1d2c3e1e93c0562054e3bfd96e8aa057b` 及旧 argv 不得复用；新 argv 改变了 `argv_sha256` 和 Plan Hash，Evidence Cache 会自然返回 `COMMAND_DRIFT`。

## 安全与失败路径

- 已验证负向路径：正文哈希篡改、同键异摘要、过期/伪造 SecurityContext、错 tenant、错 purpose、超 classification ceiling、策略拒绝/不可用/错绑定、版本漂移、重复撤销、未生效/撤销引用、Repository 跨租户投影、Outbox 失败全事务回滚。
- 未验证风险：生产数据库锁、RLS、Migration、索引消费者恢复与真实删除清理由 S6 后续验证。
- Secret/PII 检查：Secret Scan 2 passed；正文/source_ref 不进入 repr、事件、索引任务、收据或错误；测试故意将正文放入下游异常，Application 丢弃异常链。

## 已知问题

- 无 P0/P1。
- P2：失败后的不可采样安全事件依赖既有 Policy/Security 可信边界；本 WP 不新增重复安全事实源。

## 已知事实与避免重复

- `KNOWN_FACTS`：Contract content digest、knowledge.search.v1/schema pin、Lock/Migration/Environment tree signatures均未变化。
- `DO_NOT_RECHECK`：S6 不需重跑 S5 的纯领域哈希/生命周期测试；应聚焦事务、RLS、CAS、删除与恢复。
- `FAILURE_SIGNATURES`：旧 selector argv 在 Runtime collection 报 `ModuleNotFoundError: artifacts/packages`；新 argv 已通过 1226-test SHARED gate。
- `REUSED_DECISIONS`：复用 S3 集中内容安全与可信 SecurityContext，不复制 DLP、身份、策略或 Contract。
- `DUPLICATE_WORK_AVOIDED`：未重跑 Keycloak、M9 历史、Contract Conformance 或 Acceptance；选择器只要求 SHARED。

## 学习候选

```text
LEARNING_CANDIDATE=测试选择器必须生成仓库标准 Workspace Python 入口
MATURITY=VERIFIED
TRIGGER=选择器直接调用 console-script pytest，Runtime 测试 collection 无法导入根级 artifacts/packages
MECHANISM=uv 未启用 all-packages/all-groups，且 console script 启动语义未保持仓库根模块路径
STRUCTURE=所有直接 pytest 计划共享不可变 argv 前缀：uv run --all-packages --all-groups --locked python -B -m pytest -q；FULL/RELEASE 继续使用 Make 稳定入口
EVIDENCE=71ed366；engineering-control 58 passed；SHARED 1226 passed/1 skip；Plan/argv/Cache 漂移回归
RESIDUAL_RISK=新测试层级若新增直接 runner，必须复用同一前缀或稳定 Make 入口
TARGET=docs/architecture/ENGINEERING_CONTROL_PLANE.md
```

## 子 Agent 使用摘要

```text
SUBAGENTS_USED=0
SUBAGENT_MODES=none
SUBAGENT_TASKS=none
SUBAGENT_WRITERS=0
PARENT_REPRODUCED_RESULTS=not-applicable
REUSED_DECISIONS=Capsule initial set; S1 authorized owner scope expansion
DUPLICATE_WORK_AVOIDED=4
```

## 接收会话下一步

1. S6 只用 `--ff-only` 到唤醒信封中的精确 S5 最终 Head，并复核本 Handoff Hash 与 Contract digest。
2. 按上述事务语义实现 WP-112 的 PostgreSQL Repository/UoW/Inbox/Outbox、Migration、RLS、删除正文与恢复测试。
3. 成功后按链授权 HOT_CONTINUE WP-113；不得修改 S5 Port 语义或公共 Contract，确需变化时 P1 回 S1。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M10-KNOWLEDGE-01
STEP_ID=M10-01-S5-KNOWLEDGE-CORE
ATTEMPT_ID=WP-111-a1-r1
NEW_HEAD=71ed366fdf5c085d107338766c9fb14ebef2232e
BASE_COMMIT=4c32c4d7f4095e5c93e8d2a017bcd099bbdb05e4
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/core/evidence/WP-111-a1-HANDOFF.md
NEXT_ROLE=S6-DATA
NEXT_ATTEMPT_ID=WP-112-a1
ESCALATE_TO_S1=no
SUBAGENTS_USED=0
```

`NEW_HEAD` 是经验证的实现/控制面 Head；包含本 Handoff 的最终证据提交由下游唤醒信封中的 `INPUT_HEAD` 精确指定。

## 可回滚方式

- 回滚工程控制面修复提交 `71ed366` 可恢复旧 selector 行为，但会重新引入已验证的 collection 阻断，不建议单独回滚。
- 产品实现为独立祖先提交 `52ad1ef`；任何回滚由 S1 以新增反向提交裁决，禁止 reset/rebase。
