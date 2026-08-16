# WP-116-a1 Runtime Import Fixture 迁移交接

## 基本信息

- Work Package：WP-116-R1
- Attempt ID：WP-116-a1-runtime-fixture
- Chain ID：CHAIN-M10-KNOWLEDGE-01
- Step ID：M10-06B-S2-RUNTIME-IMPORT-MIGRATION
- 责任会话：S2-RUNTIME
- 接收会话：S1-ARCH
- 交接策略：S1_GATE
- 功能 ID：FP-KNOW-010
- 基线提交：`a773d53d32e74b4aee6540c3b986a3025a153dd1`
- 分支：`codex/s2/wp-117-m10-knowledge-runtime`
- 最终提交：本文件所在提交；精确 SHA 由交接响应返回
- ContractSet 摘要：
  `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：PASS_HANDOFF

## 完成内容

- 将 10 个 Runtime 测试模块的顶层 `identity_helpers` 引用迁移为明确的
  `tests.runtime.identity_helpers`。
- 将 3 个 Recovery 测试模块中对 `onboarding_harness` 的顶层及函数内延迟引用迁移为
  `tests.runtime.recovery.onboarding_harness`；其中组合模块同时迁移两类 Fixture。
- 12 个受影响模块在 pytest `--import-mode=importlib` 下可独立收集和执行，不依赖临时
  `PYTHONPATH`、新增 `sys.path`、目录排除或 prepend 模式。
- 只修改测试导入与本 Handoff，没有改变 Fixture 行为、产品代码、公共 Contract 或测试
  断言。

## 未完成与非目标

- 未运行全仓、Contract、Security、Acceptance、Compose 或在线 Provider；本修复仅针对
  importlib 收集暴露的 12 个 S2 Runtime Fixture 模块。
- 未修改现存测试基础设施中的历史路径引导代码；本 Attempt 没有新增或依赖任何
  `sys.path`/`PYTHONPATH` 方案。
- 未修改产品代码、根 pytest 配置、共享文件或其他 Owner 路径。

## 修改文件

| 文件/目录 | 变化 | 所有者 |
|---|---|---|
| `tests/runtime/integration/test_execution_adapter.py` | 稳定 identity Fixture 导入 | S2-RUNTIME |
| `tests/runtime/test_task_event_publisher.py` | 稳定 identity Fixture 导入 | S2-RUNTIME |
| `tests/runtime/security/test_m8_runtime_identity.py` | 稳定 identity Fixture 导入 | S2-RUNTIME |
| `tests/runtime/integration/test_langgraph_runtime.py` | 稳定 identity Fixture 导入 | S2-RUNTIME |
| `tests/runtime/recovery/test_composite_restart.py` | 稳定 identity/onboarding Fixture 导入 | S2-RUNTIME |
| `tests/runtime/integration/test_m7_product_runtime.py` | 稳定 identity Fixture 导入 | S2-RUNTIME |
| `tests/runtime/integration/test_persistence_adapter.py` | 稳定 identity Fixture 导入 | S2-RUNTIME |
| `tests/runtime/recovery/test_durable_runtime.py` | 稳定 identity Fixture 导入 | S2-RUNTIME |
| `tests/runtime/recovery/test_worker_restart.py` | 稳定 identity Fixture 导入 | S2-RUNTIME |
| `tests/runtime/integration/test_vpn_readonly_graph.py` | 稳定 identity Fixture 导入 | S2-RUNTIME |
| `tests/runtime/recovery/test_composite_checkpoint_no_rerun.py` | 稳定 onboarding Fixture 导入 | S2-RUNTIME |
| `tests/runtime/recovery/test_composite_reauthorize_resume.py` | 稳定 onboarding Fixture 导入 | S2-RUNTIME |
| `tests/runtime/evidence/WP-116-a1-RUNTIME-IMPORT-HANDOFF.md` | 本交接证据 | S2-RUNTIME |

## 契约、数据库与配置变化

- 公共 Contract、Schema 与 ContractSet：无变化。
- Migration、数据库、Checkpoint、环境变量与依赖：无变化。
- `pyproject.toml`、`uv.lock`、`Makefile` 与 pytest 配置：无变化。
- 兼容性：importlib 模式获得稳定仓库根模块路径；Fixture API 与测试行为不变。

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| 12 模块 `pytest --import-mode=importlib --collect-only -q` | PASS | 65 tests collected |
| 12 模块 `pytest --import-mode=importlib -q` | PASS | 65 passed |
| 12 模块 `ruff check` | PASS | All checks passed |
| `git diff --check` | PASS | 无 whitespace error |

## 安全与失败路径

- Import 收集不依赖外部路径注入、环境变量、网络或动态模块别名。
- Recovery、身份重验、租户隔离、Checkpoint、Capability 与 Worker 幂等测试在定向
  65 项中保持通过。
- Secret/PII：没有引入测试数据、凭据、日志或外部调用；仅调整静态导入路径。

## 已知问题

- 无阻断问题。
- 本 Handoff 不宣称全仓门禁；全仓 importlib 组合复算由 WP-116 的主 Join/S1 按原计划
  完成。

## 已知事实与避免重复

- `KNOWN_FACTS`：BASE_COMMIT 已包含 M10 WP-111～115 生产者输入；ContractSet 摘要未变。
- `DO_NOT_RECHECK`：未重跑 M10 产品实现、全仓、数据库、MCP、Web、Acceptance 或历史
  Runtime 全套。
- `FAILURE_SIGNATURES`：`IMPORTLIB_RUNTIME_FIXTURE_TOP_LEVEL_IMPORT`——旧的裸模块名仅在
  目录被注入搜索路径时可见，importlib 全仓收集失败。
- `REUSED_DECISIONS`：pytest importlib 全仓收集策略、现有 Runtime Fixture API 与目录
  所有权。
- `DUPLICATE_WORK_AVOIDED`：只处理检索确认的 12 个模块和 4 处函数内延迟导入，没有
  扩大到无关 Runtime 测试或产品代码。

## 学习候选

```text
LEARNING_CANDIDATE=Test fixture imports must be repository-root explicit under importlib
MATURITY=VERIFIED
TRIGGER=pytest importlib 全仓收集不注入测试文件所在目录，裸 helper 模块名不可见
MECHANISM=测试共享模块使用仓库根明确路径；禁止依赖 sys.path/PYTHONPATH 或收集模式副作用
STRUCTURE=tests.runtime.<fixture> and tests.runtime.recovery.<fixture>
EVIDENCE=12 modules collected / 65 tests passed under --import-mode=importlib
RESIDUAL_RISK=新增测试共享 Fixture 仍需遵循相同绝对路径约定
TARGET=ENGINEERING_PLAYBOOK test-import candidate
```

## 子 Agent 使用摘要

```text
SUBAGENTS_USED=0
SUBAGENT_MODES=none
SUBAGENT_TASKS=none
SUBAGENT_WRITERS=0
PARENT_REPRODUCED_RESULTS=yes
REUSED_DECISIONS=importlib-collection,runtime-fixture-apis
DUPLICATE_WORK_AVOIDED=12
```

## 接收会话下一步

1. S1 核对精确 `NEW_HEAD`、本 Handoff SHA256、基线父提交、ContractSet、授权路径与
   clean 状态。
2. 在 WP-116 主 Join 中用既定 importlib 收集命令复算全仓；不得添加临时路径、排除
   Runtime 目录或回退 prepend 模式。
3. 本子步骤不唤醒 S4/S5/S7；后续链路由 S1 裁决。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M10-KNOWLEDGE-01
STEP_ID=M10-06B-S2-RUNTIME-IMPORT-MIGRATION
ATTEMPT_ID=WP-116-a1-runtime-fixture
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=a773d53d32e74b4aee6540c3b986a3025a153dd1
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/runtime/evidence/WP-116-a1-RUNTIME-IMPORT-HANDOFF.md
NEXT_ROLE=S1-ARCH
NEXT_ATTEMPT_ID=none
ESCALATE_TO_S1=no
SUBAGENTS_USED=0
```

## 可回滚方式

- 仅按正常 Git 流程 revert 本 Attempt 提交；禁止 reset、rebase 或 force-push。
