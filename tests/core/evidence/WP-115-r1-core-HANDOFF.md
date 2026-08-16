# WP-115-R1 / S5-CORE Citation Projection Handoff

## 基本信息

- Work Package：WP-115-R1
- Attempt ID：WP-115-r1-core
- Chain ID：CHAIN-M10-KNOWLEDGE-01
- Step ID：M10-05R1-S5-CITATION-PROJECTION
- 责任会话：S5-CORE
- 接收会话：S6-DATA
- 交接策略：CONSUMER_GATE
- 功能 ID：FP-FLOW-003、FP-DATA-001、FP-SEC-003、FP-UI-001
- 输入提交：`629571c97631e31cab0c5a1eed241ce4f51ab3e0`
- 实现提交：`7ca59d48ec185f6460713844527ad81155eef628`
- 分支：`codex/s5/wp-111-m10-knowledge-core`
- ContractSet 摘要：`sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：完成（跨 Owner producer checkpoint）

## 完成内容

- 新增 `KnowledgeContentProjection`：精确绑定 tenant、document、version、content_ref、content_hash、classification，并携带最多 2048 字符且 `repr=False` 的 `content_excerpt`。
- 新增独立 `KnowledgeContentProjectionPort.get_exact`，由 `KnowledgeQueryUnitOfWork.content_projections` 暴露。Application Port 不依赖 Persistence、Retrieval 或 Security 具体实现。
- `KnowledgeQueryService.resolve_citation` 新增必填 keyword-only `action_classification_ceiling: DataClassification`。
- action ceiling 必须是 `DataClassification`，且不能高于可信 `SecurityContextRef.data_classification_ceiling`；文档版本 classification 不能高于 action ceiling。
- 固定并测试以下执行顺序：可信 Context/tenant 与 action ceiling → 精确 document/version/lifecycle/effective/expiry → StableCitation/hash → 文档 classification/action ceiling → authorization → exact content projection → projection 全字段复验 → resolution。
- `KnowledgeCitationResolution` 新增 `repr=False` 的 `content_excerpt`。该字段明确是未完成集中 DLP/Prompt-Injection 的原始受控 excerpt，不命名或声明为 `redacted_summary`。
- projection 缺失/读取失败使用 `CORE_KNOWLEDGE_CONTENT_PROJECTION_UNAVAILABLE`；类型或任一绑定错配使用 `CORE_KNOWLEDGE_CONTENT_PROJECTION_PROTOCOL_ERROR`。错误不包含正文或原异常链。
- 内部 Python Port 发生破坏性签名变化，`KNOWLEDGE_APPLICATION_PORT_VERSION` 从 `flowpilot.knowledge-ports.m10.v1` 升级为 `flowpilot.knowledge-ports.m10.v2`；公共 `knowledge.search.v1` 和 ContractSet 未变化。

## 未完成与非目标

- S6 尚未实现 PostgreSQL exact-version/RLS `KnowledgeContentProjectionPort`；这是下一步 WP-115-R2。
- S4 的 `KnowledgeCitationVerificationPort`、Retrieval 调用和 Acceptance Fake 仍使用 v1 调用/结果模型；按 S1 线性顺序由后续 S4 Step 迁移。
- S3 尚不得消费或伪造 excerpt，不得事后过滤超 action ceiling 候选；S3 只可在 S6/S4 完成后执行集中 DLP/Prompt-Injection 并映射固定 Tool Schema。
- 未修改数据库、Migration、Retrieval、MCP、Gateway、API、根 Workspace、锁或公共 Contract。
- 按 producer-checkpoint 授权未运行全仓；当前不声明 S4/S3 消费者绿色。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `packages/application/src/flowpilot_application/knowledge_models.py` | exact content projection、resolution excerpt、Port v2 | S5 |
| `packages/application/src/flowpilot_application/knowledge_ports.py` | projection Port 与 Query UoW 属性 | S5 |
| `packages/application/src/flowpilot_application/knowledge_services.py` | action ceiling、固定校验顺序、projection 读取与复验 | S5 |
| `packages/application/src/flowpilot_application/errors.py` | projection 稳定错误 | S5 |
| `packages/application/src/flowpilot_application/__init__.py` | 新模型/Port 公开导出 | S5 |
| `tests/core/test_knowledge_core.py` | 正常、边界、失败、安全和顺序回归 | S5 |

## 契约、数据库与配置变化

- 公共 Contract：无变化；`knowledge.search.v1` 与既有 schema pin 保持不变。
- 内部 Application Port：`flowpilot.knowledge-ports.m10.v1` → `flowpilot.knowledge-ports.m10.v2`。
- Migration / RLS / 数据库：无变化。
- 环境变量 / 配置 / 依赖 / 锁：无变化。
- API：无变化。

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| `uv run --all-packages --all-groups --locked python -B -m pytest -q tests/core/test_domain.py tests/core/test_application.py tests/core/test_knowledge_core.py` | PASS | 52 passed |
| `uv run --all-packages --all-groups --locked ruff check packages/application/src tests/core/test_knowledge_core.py` | PASS | All checks passed |
| `uv run --all-packages --all-groups --locked mypy --strict packages/application/src tests/core/test_knowledge_core.py` | PASS | 15 source files |
| `uv run --all-packages --all-groups --locked python -B contracts/conformance/validate.py` | PASS | 20 schemas / 35 cases / 43 semantic / 52 features |
| `git diff --check` | PASS | 无 whitespace 错误 |

## 安全与失败路径

- ceiling 缺失由 Python 必填签名拒绝；伪造类型使用稳定 `CORE_KNOWLEDGE_CONTRACT_INVALID`。
- action ceiling 高于 Context 或文档 classification 高于 action ceiling 均在 content projection 读取前失败。
- Citation hash 在 authorization 和 projection 前复验；撤销、删除、未生效或过期版本在 authorization/projection 前失败。
- authorization 拒绝时 projection 调用为 0。
- projection 的 tenant/document/version/ref/hash/classification 任一错配均失败关闭。
- projection 缺失、下游异常和正文超 2048 字符均使用安全错误；测试将正文放入下游异常并验证 Application 丢弃异常链。
- `KnowledgeContentProjection` 与 `KnowledgeCitationResolution` 的 excerpt 均 `repr=False`；事件、错误和日志模型未加入 excerpt。

## 暂时受影响的消费者

- `packages/retrieval/src/flowpilot_retrieval/ports.py`：v1 `resolve_citation(context, citation)`，缺少必填 action ceiling。
- `packages/retrieval/src/flowpilot_retrieval/engine.py`：v1 调用未传 action ceiling，且尚未处理 excerpt。
- `tests/acceptance/m10/test_retrieval_engine.py`：v1 Fake/Resolution 构造缺少新字段。
- S6 当前 Query UoW 尚无 `content_projections`，必须先由 WP-115-R2 完成；上述 S4 消费者随后迁移，禁止 S5 添加兼容默认值绕过。

## 已知问题

- 无 P0/P1。
- P2：excerpt 是受控长度但尚未 DLP/Prompt-Injection 的内容，只能沿 S6→S4→S3 受信链传递，不得进入公共响应、日志、事件或错误。

## 已知事实与避免重复

- `KNOWN_FACTS`：Contract content digest、knowledge.search.v1、数据库/Migration、根 Workspace/Lock 均未变化。
- `DO_NOT_RECHECK`：S6 不需重跑 S5 领域生命周期；聚焦 exact-version SQL、RLS、字段绑定和正文零泄漏。S4 不需更改排序算法，只迁移 ceiling/excerpt 消费签名。
- `FAILURE_SIGNATURES`：projection `None` → `CORE_KNOWLEDGE_CONTENT_PROJECTION_UNAVAILABLE`；任一绑定漂移 → `CORE_KNOWLEDGE_CONTENT_PROJECTION_PROTOCOL_ERROR`；classification 超 action ceiling → `CORE_KNOWLEDGE_CLASSIFICATION_DENIED`。
- `REUSED_DECISIONS`：复用 WP-111 stable citation、授权摘要、分类序和安全错误外壳；未复制 S3 DLP。
- `DUPLICATE_WORK_AVOIDED`：未重跑 S6 实库、S4 Retrieval 全套或全仓门禁。

## 学习候选

```text
LEARNING_CANDIDATE=授权后正文投影仍需精确版本全绑定复验
MATURITY=IMPLEMENTED
TRIGGER=Citation 只返回 content_ref，S3 无法在不伪造摘要的情况下完成集中内容安全检查
MECHANISM=候选元数据验证不能证明授权后读取的正文仍来自同 tenant/document/version/hash/classification
STRUCTURE=Query UoW 独立 exact projection Port；authorization 后读取；Application 逐字段复验；excerpt 保持未净化命名并 repr=False
EVIDENCE=7ca59d4；S5 targeted 52 passed；Ruff/Mypy/Contract PASS
RESIDUAL_RISK=生产 RLS/SQL 与 S4/S3 消费链尚待后续 Owner 验证
TARGET=WP-115 remediation chain
```

## 子 Agent 使用摘要

```text
SUBAGENTS_USED=0
SUBAGENT_MODES=none
SUBAGENT_TASKS=none
SUBAGENT_WRITERS=0
PARENT_REPRODUCED_RESULTS=not-applicable
REUSED_DECISIONS=WP-111/WP-114 handoff and S1 remediation disposition
DUPLICATE_WORK_AVOIDED=3
```

## 接收会话下一步

1. S6 只用 `--ff-only` 到唤醒信封的精确 S5 最终 Head，并复核 Handoff/Contract Hash。
2. 在 Persistence 侧实现 tenant-bound exact-version `KnowledgeContentProjectionPort`，由同一 RLS Query UoW 暴露；不得依赖 Retrieval 或返回超 2048 字符正文。
3. SQL/RLS 必须在读取正文前绑定 tenant/document/version；返回对象还须精确携带 content_ref/hash/classification，供 Application 二次复验。
4. PASS 后只唤醒预授权 S4 Citation Projection 消费步骤，不通知 S3；P0/P1、Contract 变化或无法保证 RLS 时回 S1。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M10-KNOWLEDGE-01
STEP_ID=M10-05R1-S5-CITATION-PROJECTION
ATTEMPT_ID=WP-115-r1-core
NEW_HEAD=7ca59d48ec185f6460713844527ad81155eef628
BASE_COMMIT=629571c97631e31cab0c5a1eed241ce4f51ab3e0
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/core/evidence/WP-115-r1-core-HANDOFF.md
NEXT_ROLE=S6-DATA
NEXT_ATTEMPT_ID=WP-115-r2-data
ESCALATE_TO_S1=no
SUBAGENTS_USED=0
```

`NEW_HEAD` 是经验证的实现 Head；包含本 Handoff 的最终证据提交由唤醒信封中的 `INPUT_HEAD` 精确指定。

## 可回滚方式

- 由 S1 以新增反向提交回滚实现提交 `7ca59d4`；禁止 reset/rebase。
- 不得以为 action ceiling 添加默认值、事后过滤候选或伪造 `redacted_summary` 的方式兼容 v1 消费者。
