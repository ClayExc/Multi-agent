# WP-091 S5-CORE 仓库地图与 Context Capsule 交接

## 基本信息

- Work Package：WP-091
- Attempt ID：WP-091-a1
- Chain ID：`CHAIN-M9T-ENGINEERING-CONTROL-01`
- Step ID：`M9T-01-S5-MAP-CAPSULE`
- 责任会话：`S5-CORE`
- 接收会话：`S5-CORE`（HOT_CONTINUE WP-092）
- 交接策略：`CONSUMER_GATE`
- 功能 ID：`FP-OPS-002`
- 基线提交：`46b98605af898cf0631b4e6dd29b853d6c1d397a`
- 分支/最终提交：`codex/s5/wp-091-engineering-map` / 本文件所在提交
- ContractSet 摘要：
  `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：完成

## 完成内容

- 新增标准库优先的 `flowpilot-engineering-control` Workspace 包及
  `flowpilot-eng map build`、`flowpilot-eng capsule build` CLI。
- 仓库地图确定性记录 clean HEAD、Workspace 成员/内部依赖边、Owner/共享单写者规则、
  定向测试映射、保护树、文件路径/字节数/SHA-256 和公共入口签名摘要；不保存文件正文。
- 路径策略统一 Windows/POSIX 分隔符与 Unicode NFC，拒绝绝对路径、drive、遍历、NUL、
  大小写折叠冲突、未知 Owner 和重叠 Owner；排除 Git、虚拟环境、IDE、缓存、coverage、
  测试 evidence 与生成验收 artifacts。
- Delta Capsule 使用 Base/Target Git 差异处理 add/modify/delete/rename，记录受影响包、直接
  依赖/消费者、公共签名、必读集合、授权范围和枚举化范围扩展；脏树、非祖先 Base、
  Target 非 clean HEAD、越权或跨 Owner 未授权变化稳定失败关闭。
- Git 与 CLI 只使用 argv 数组和 `shell=False`；Git stderr、文件正文和任意事实文本不进入
  输出。`KNOWN_FACTS` / `DO_NOT_RECHECK` 仅接受 ID、repo-relative evidence 路径和摘要。
- `.flowpilot-engineering/` 作为本地原子输出目录加入忽略；根 dev group 和 lock 注册新包。

## 未完成与非目标

- 测试选择、Evidence Cache 和 Attempt 报告由紧接的 WP-092 HOT_CONTINUE 实现。
- 未实现 OS 级终端读取拦截、产品 Runtime Context、发布门禁替代或公共 Contract 变化。
- 未唤醒 S1/S4/S7；本 Handoff 只解锁同一 S5 Worktree 的 WP-092。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `packages/engineering-control/**` | 新包、map/capsule/CLI、稳定错误与路径/Owner/Git 边界 | S5 |
| `tests/core/engineering_control/**` | 确定性、rename/delete、Owner、dirty/non-linear、Secret 与注入负例 | S5 |
| `pyproject.toml`、`uv.lock` | Workspace/dev dependency 与锁闭包 | S5（本 WP 单写） |
| `.gitignore` | 忽略 `.flowpilot-engineering/` 本地结果 | S5（本 WP 单写） |
| `tests/core/evidence/WP-091-a1-HANDOFF.md` | 本交接 | S5 |

## 契约、数据库与配置变化

- 契约版本：无变化；Contract content digest 保持不变。
- Migration / 数据库 / Redis：无变化。
- 环境变量：无新增；输出不读取或保存环境变量值。
- 依赖：新包运行时仅 Python 标准库；构建继续复用 Hatchling。无新增第三方生产依赖、
  许可证或供应链攻击面。主要攻击面是恶意路径/Git ref/CLI 参数、符号链接和错误正文
  泄漏，已通过路径验证、clean HEAD、完整 commit 解析、argv-only 调用、symlink 仅哈希目标
  字节及脱敏稳定错误收口。
- 兼容性：新增工程控制面，不被 API/Worker/Graph/MCP Gateway 产品 Runtime 导入。

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| `uv run --locked pytest -q tests/core/engineering_control` | PASS | 27 passed |
| `uv run --locked ruff check packages/engineering-control tests/core/engineering_control` | PASS | All checks passed |
| `uv run --locked mypy --strict packages/engineering-control/src` | PASS | 10 source files |
| `uv lock --check` | PASS | 169 packages resolved；lock unchanged |
| `uv build --wheel --package flowpilot-engineering-control` | PASS | `flowpilot_engineering_control-0.1.0-py3-none-any.whl` |
| `uv run --locked python -c ...` / `flowpilot-eng --help` | PASS | package import 与 CLI entrypoint 正常 |

## 安全与失败路径

- 已验证负向路径：路径遍历/drive/NUL、未知路径、Owner 冲突、大小写冲突、缺失成员、
  未注册内部依赖、tracked/untracked dirty、非祖先 Base、跨 Owner rename 未扩展、恶意
  revision、输出越界、正文/Secret/IDE/evidence/coverage 泄漏。
- 未验证风险：当前客户端仍不能从 OS 层阻止任意手工读取；按架构设计由生成范围、Git
  差异、Handoff 和审查约束，工具故障时必须回退 FULL。
- Secret/PII 检查：Fixture 中显式 Secret/本地 IDE/evidence 字节均不出现在 map/capsule；
  生产输出只含路径、Hash、签名、计数和授权元数据。

## 已知问题

- 无 P0/P1。WP-092 尚未实现，因此本提交不能宣称测试漏选或 Evidence Cache 门禁通过。

## 已知事实与避免重复

- `KNOWN_FACTS`：BASE/branch/clean 已精确核对；控制面只管理工程上下文；Contract、
  Migration 和产品 Runtime 未变化。
- `DO_NOT_RECHECK`：WP-092 复用本包 map/capsule、Owner policy、路径规范化、canonical JSON
  和 argv-only Git 结论，不重新读取仓库总览或重跑 WP-091 全部负例。
- `FAILURE_SIGNATURES`：`ENG_DIRTY_WORKTREE`、`ENG_NON_LINEAR_BASE`、
  `ENG_UNKNOWN_PATH`、`ENG_OWNER_CONFLICT`、`ENG_SCOPE_VIOLATION`。
- `REUSED_DECISIONS`：`ENGINEERING_CONTROL_PLANE.md`、WP-091、当前 Chain、S5 Contract。
- `DUPLICATE_WORK_AVOIDED`：复用现有 Workspace/Hatch/uv 门禁；子 Agent 分离审查 WP-091
  map/capsule 与 WP-092 cache/select，未重复跑全仓或历史产品门禁。

## 学习候选

```text
LEARNING_CANDIDATE=工程上下文中的事实和扩展理由也必须元数据化
MATURITY=IMPLEMENTED
TRIGGER=Context Capsule 需要携带 KNOWN_FACTS、DO_NOT_RECHECK 和范围扩展，但任意自由文本可能混入 Prompt、Token、PII 或 Secret
MECHANISM=仅禁止文件正文不足以保证工程证据安全；自由文本字段同样形成旁路
STRUCTURE=事实引用采用稳定 ID+repo-relative evidence path+SHA-256；扩展理由采用枚举 reason_code+authority+path
EVIDENCE=tests/core/engineering_control metadata-only、Secret、scope expansion 与 deterministic tests；27 passed
RESIDUAL_RISK=OS 级手工读取仍由客户端与审查约束，当前工具不宣称实现读取沙箱
TARGET=ENGINEERING_CONTROL_PLANE Delta Context Capsule section
```

## 子 Agent 使用摘要

```text
SUBAGENTS_USED=2
SUBAGENT_MODES=READ_ONLY_PARALLEL
SUBAGENT_TASKS=WP091/repository-map,WP092/test-selection+evidence-cache
SUBAGENT_WRITERS=0
PARENT_REPRODUCED_RESULTS=yes
REUSED_DECISIONS=ENGINEERING_CONTROL_PLANE,WP-091,WP-092
DUPLICATE_WORK_AVOIDED=2
```

## 接收会话下一步

1. 同一 S5 会话 HOT_CONTINUE WP-092；复用本提交的 map/capsule、Owner、保护树和摘要。
2. 实现测试选择升级、Evidence Cache 完整性/复用策略和 Attempt report。
3. 仅在 WP-092 最终执行一次授权共享门禁，再提交 WP-092 Handoff 并唤醒唯一 S4。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M9T-ENGINEERING-CONTROL-01
STEP_ID=M9T-01-S5-MAP-CAPSULE
ATTEMPT_ID=WP-091-a1
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=46b98605af898cf0631b4e6dd29b853d6c1d397a
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/core/evidence/WP-091-a1-HANDOFF.md
NEXT_ROLE=S5-CORE
NEXT_ATTEMPT_ID=WP-092-a1
ESCALATE_TO_S1=no
SUBAGENTS_USED=2
```

## 可回滚方式

- `git revert` 本 WP-091 提交；禁止 reset、rebase 或 force-push。回滚只移除工程控制面，
  不改变产品 Runtime、Contract 或 Migration。
