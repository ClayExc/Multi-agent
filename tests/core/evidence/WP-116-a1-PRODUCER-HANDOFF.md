# WP-116 / S5-CORE Producer Checkpoint Handoff

## 基本信息

- Work Package：WP-116
- Attempt ID：WP-116-a1
- Chain ID：CHAIN-M10-KNOWLEDGE-01
- Step ID：M10-06A-S5-WP116-PRODUCER-CHECKPOINT
- 责任会话：S5-CORE
- 接收会话：S1-ARCH
- 交接策略：S1_GATE
- 功能 ID：FP-KNOW-010、FP-UI-001、FP-DATA-001、FP-SEC-003
- 基线提交：`de03beba1a7ef82b97f88b9bf54d0f66092d9a7b`
- 实现提交：`c2c916d0f653d063dffb7d902d2e29cfbba942af`
- 分支：`codex/s5/wp-111-m10-knowledge-core`
- ContractSet 摘要：`sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：部分完成；生产者实现已提交，跨 Owner 测试迁移阻塞
- Gate：`FAIL_CROSS_OWNER_TEST_MIGRATION`

## 完成内容

- 增加本地知识管理 API：import、update、retire、delete、rebuild、document read 与 diagnostic read。
- 写操作绑定可信 Cookie 身份、SecurityContext、用途/职责、服务端 ACL 与 `Idempotency-Key`；拒绝客户端自报 tenant、ACL、classification authority 或其他授权事实。
- 增加 PostgreSQL knowledge service factory 与本地 Knowledge MCP/检索组合边界；公开响应只返回安全文档/诊断投影，不返回正文。
- 根 Workspace 注册 Retrieval，并补齐 API 对 MCP Gateway、Knowledge MCP、Persistence、Retrieval 的直接依赖及 `uv.lock` 闭包。
- 根 Mypy/Coverage 源集合加入 Retrieval。
- `make test` 与 `make test-coverage` 的 pytest 命令显式加入 `--import-mode=importlib`；没有排除目录、Case，也没有改变断言失败语义。
- 新增 20 个 Core API 用例，覆盖正常、边界、失败、安全、幂等、组合与依赖全有或全无。

## 未完成与非目标

- 本检查点不是 WP-116 PASS，不得作为 WP-117 输入，也不得唤醒 S2/S4/S7。
- S1 已独立复现的 39 个失败仍需对应测试 Owner 迁移：S4 29 个，S7 10 个；S5 不添加兼容回退。
- importlib collection smoke 另发现 12 个 S2-owned Runtime 测试仍依赖 pytest prepend 模式提供同目录顶层 helper 导入；本步骤未越权修改这些测试。
- 不修改公共 Contract、数据库、Migration、Web、Runtime、Acceptance 或 Integration 测试。
- 未再次运行全仓测试；遵守 S1 的 `NO_RETEST`/必要复核约束。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `apps/api/src/flowpilot_api/app.py` | Knowledge 管理/查询路由、稳定错误与安全响应 | S5 |
| `apps/api/src/flowpilot_api/knowledge.py` | Knowledge Port 适配、访问策略与生产组合 | S5 |
| `apps/api/src/flowpilot_api/models.py` | Knowledge 严格请求/安全响应模型 | S5 |
| `apps/api/src/flowpilot_api/security.py` | Knowledge 请求重验与授权边界 | S5 |
| `apps/api/src/flowpilot_api/composition.py` | Knowledge product composition 注入 | S5 |
| `apps/api/src/flowpilot_api/testing.py` | Core Fake 的 Knowledge 授权行为 | S5 |
| `apps/api/src/flowpilot_api/__init__.py` | Knowledge API/composition 公开导出 | S5 |
| `apps/api/pyproject.toml` | API 直接 Workspace 依赖闭包 | S5（WP-116 Workspace writer） |
| `pyproject.toml` | Retrieval member/source/root dependency 与工具源集合 | S5（WP-116 Workspace writer） |
| `uv.lock` | Workspace lock 闭包 | S5（WP-116 Workspace writer） |
| `Makefile` | Retrieval 静态检查/覆盖集合；test/test-coverage importlib 收集模式 | S5（WP-116 Workspace writer） |
| `tests/core/test_knowledge_api.py` | Knowledge API 正常、边界、失败、安全与幂等测试 | S5 |
| `tests/core/evidence/WP-116-a1-PRODUCER-HANDOFF.md` | 本生产者阻塞交接 | S5 |

## 契约、数据库与配置变化

- 公共 Contract：无变化；ContractSet digest 保持不变。
- Application/Domain Port：本检查点未放宽既有 Knowledge Port 与安全不变量。
- Migration / RLS / 数据库 Schema：无变化。
- 环境变量：无新增；组合由显式依赖注入构造。
- Workspace：根 Workspace 新增既有 `packages/retrieval` member/source，API 声明其实际直接依赖；lock 已同步。
- 兼容性：S4/S7 旧测试 fixture 必须迁移到当前 API/仓库事实；禁止在产品层恢复旧 DLP 错误码、旧 CapabilityHandle 形状或历史仓库快照假设。

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| `git diff --check` / `git diff --cached --check` | PASS | 无 whitespace 错误 |
| `uv lock --check` | PASS | `Resolved 170 packages`，lock 无漂移 |
| `uv run --all-packages --all-groups --locked python -B -m pytest -q tests/core/test_knowledge_api.py` | PASS | 20 passed in 2.60s |
| `uv run --all-packages --all-groups --locked python -B -m pytest --import-mode=importlib --collect-only -qq` | FAIL | 12 个 S2 Runtime collection errors；未执行测试 Case |
| S1 对全仓失败的独立定向复现 | FAIL（复用） | 共 39 failures：S4 29、S7 10；S1 裁决未发现 WP-116 产品回归 |
| 全仓 `make test` | 未运行 | 按 S1 指令禁止重复全仓；当前 collection smoke 已确定会在执行 Case 前失败 |

## 39 个既有跨 Owner 失败分类

- S4-owned `tests/acceptance/**`：29 个。
  - 1 个集中 DLP 稳定错误码仍断言旧期望。
  - 28 个仍构造旧 `CapabilityHandle` fixture。
- S7-owned `tests/integration/**`：10 个。
  - 历史候选/迁移验证器读取当前仓库事实，因仓库演进产生确定性漂移。
- 以上均由 S1 独立定向复现；未发现 WP-116 产品行为回归。生产代码不得为了这些 fixture 恢复旧契约或放宽安全门禁。

## 新发现的 collection 阻断

- importlib 模式消除了全仓同名测试模块的 collection collision，但不会把测试目录隐式加入 `sys.path`。
- 10 个 S2 Runtime 测试以顶层 `identity_helpers` 导入 `tests/runtime/identity_helpers.py`；2 个以顶层 `onboarding_harness` 导入 `tests/runtime/recovery/onboarding_harness.py`，共 12 个 collection errors。
- 该问题属于 S2 测试 fixture/import 迁移；S5 未添加临时 `PYTHONPATH`、未修改 S2 路径、未排除测试目录。
- 因 collection 尚未通过，39 个执行期失败与这 12 个收集错误不能合并为一次可比较的全仓失败计数。

## 安全与失败路径

- 定向测试验证可信 Context/服务端 ACL、错误职责、缺失依赖、客户端 authority 字段拒绝、稳定错误映射和幂等回放。
- 响应设置 `Cache-Control: no-store` 与 `Vary: Cookie`；正文不进入 document/diagnostic 投影。
- 未修改集中 DLP、安全策略、Contract 或跨租户规则；未以兼容代码绕过 S4 fixture。
- Secret/PII 检查：本检查点未按 `NO_RETEST` 重跑独立全仓扫描；定向测试未输出正文或授权材料，diff-check 通过。

## 已知问题

- P1 / Gate blocker：稳定 `make test` 使用 importlib 后，12 个 S2-owned 顶层 helper 导入必须迁移，当前全仓不能完成 collection。
- Gate blocker：S1 已确认的 39 个 S4/S7 fixture/历史验证失败尚未迁移。
- 该生产者提交只保存已验证 S5 差异；不得向 WP-117 线性传播。

## 已知事实与避免重复

- `KNOWN_FACTS`：S1 已独立复现 39 个执行期失败并裁决无 WP-116 产品回归；公共 Contract 未变化；S5 定向 20 PASS；lock check PASS。
- `DO_NOT_RECHECK`：不得再次运行全仓以重复 39 个失败；S4 迁移旧错误码/CapabilityHandle，S7 修复读取当前仓库的历史验证器，S2 迁移顶层 helper import 后再恢复一次稳定全仓门禁。
- `FAILURE_SIGNATURES`：`ModuleNotFoundError: identity_helpers`（10 collection files）；`ModuleNotFoundError: onboarding_harness`（2 collection files）；S4 29/S7 10 分类见上。
- `REUSED_DECISIONS`：复用 S1 `COMMIT_PRODUCER_BEFORE_CROSS_OWNER_TEST_MIGRATION` 裁决与 39 failures 独立复现，不重复运行全仓。
- `DUPLICATE_WORK_AVOIDED`：1 次全仓重跑及 39 个跨 Owner 逐项复现。

## 学习候选

```text
LEARNING_CANDIDATE=importlib 收集模式要求测试 helper 可包导入
MATURITY=VERIFIED
TRIGGER=同名测试模块碰撞通过 --import-mode=importlib 修复后，Runtime 顶层 helper 导入在 collection 阶段失败
MECHANISM=prepend 模式隐式把测试目录加入 sys.path；importlib 模式不提供该偶然依赖
STRUCTURE=测试 helper 使用明确包路径或受控 fixture 包；稳定根入口保持 importlib，禁止临时 PYTHONPATH 和目录排除
EVIDENCE=WP-116 collection-only：12 deterministic collection errors
RESIDUAL_RISK=S2 fixture 迁移完成前稳定 make test 无法执行用例
TARGET=engineering playbook / S2 cross-owner test migration
```

## 子 Agent 使用摘要

```text
SUBAGENTS_USED=0
SUBAGENT_MODES=none
SUBAGENT_TASKS=none
SUBAGENT_WRITERS=0
PARENT_REPRODUCED_RESULTS=yes
REUSED_DECISIONS=S1 independent 39-failure classification
DUPLICATE_WORK_AVOIDED=1
```

## 接收会话下一步

1. S1 将本提交保持为 producer checkpoint，不将其授权为 WP-117 输入。
2. 按 Owner 迁移 S2 的 12 个 helper import collection failures、S4 的 29 个 fixture failures 与 S7 的 10 个历史验证器 failures。
3. 消费者迁移完成后仅运行一次稳定全仓门禁；不得通过排除目录、回退 pytest 模式、临时 `PYTHONPATH` 或放宽产品安全语义获得绿色。

## 机器可读交接摘要

```text
OUTCOME=BLOCKED
CHAIN_ID=CHAIN-M10-KNOWLEDGE-01
STEP_ID=M10-06A-S5-WP116-PRODUCER-CHECKPOINT
ATTEMPT_ID=WP-116-a1
NEW_HEAD=c2c916d0f653d063dffb7d902d2e29cfbba942af
BASE_COMMIT=de03beba1a7ef82b97f88b9bf54d0f66092d9a7b
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=FAIL_CROSS_OWNER_TEST_MIGRATION
HANDOFF=tests/core/evidence/WP-116-a1-PRODUCER-HANDOFF.md
NEXT_ROLE=S1-ARCH
NEXT_ATTEMPT_ID=none
ESCALATE_TO_S1=yes
SUBAGENTS_USED=0
```

`NEW_HEAD` 是已提交的生产者实现 Head；包含本 Handoff 的最终证据提交由外部交接信封精确指定。

## 可回滚方式

- 仅由 S1 通过新增反向提交回滚 `c2c916d0f653d063dffb7d902d2e29cfbba942af`；禁止 reset/rebase。
- 不得以恢复旧 CapabilityHandle、旧 DLP 码、prepend 收集模式、临时 `PYTHONPATH` 或排除测试的方式回滚失败语义。
