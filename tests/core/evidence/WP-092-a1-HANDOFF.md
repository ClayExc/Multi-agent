# WP-092 S5-CORE 测试选择与 Evidence Cache 交接

## 基本信息

- Work Package：WP-092
- Attempt ID：WP-092-a1
- Chain ID：`CHAIN-M9T-ENGINEERING-CONTROL-01`
- Step ID：`M9T-02-S5-SELECT-CACHE`
- 责任会话：`S5-CORE`
- 接收会话：`S4-QUALITY`
- 交接策略：`CONSUMER_GATE`
- 功能 ID：`FP-OPS-002`
- 基线提交：`22527cab03d77a29e30cbeaf9843ba9ab9079ce2`（WP-091 Handoff Head）
- 原始链基线：`46b98605af898cf0631b4e6dd29b853d6c1d397a`
- 分支/最终提交：`codex/s5/wp-091-engineering-map` / 本文件所在提交
- ContractSet 摘要：
  `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：完成

## 完成内容

- 新增 `flowpilot-eng tests select` 四级确定性选择器：普通包内变化选择定向及传递依赖
  消费者测试；公共入口/Port 升级 SHARED；Contract/Lock/未知路径/依赖图不完整升级
  FULL；Migration、安全/身份/租户和非线性基线升级 RELEASE。
- 无变更证明、缺测试映射或控制面无法证明完整时，返回带明确原因的非空 FULL/RELEASE
  fallback；不会以成功状态返回空测试集。rename/delete 同时使用旧、新包影响面。
- 命令仅保存稳定 `command_id` 和 argv 数组；完整 argv 参与 SHA-256 键，不使用 Shell
  拼接。分号、管道、重定向和 `$()` 作为普通参数往返，NUL/空 executable 稳定拒绝。
- 新增 Evidence Cache：键绑定 command/argv、产品与测试执行树、Contract tree/digest、
  Migration tree、Lock、白名单环境指纹和工具链；记录绑定 producer Head、成功退出码、
  evidence 路径/Hash/字节数及自摘要。
- 失败结果不缓存；在线/付费 Provider、Secret Scan、漏洞查询、真实 Migration、破坏性
  恢复和要求重跑的安全测试默认不可复用。命中前复核 policy、record/evidence 完整性、
  component drift 和 producer Head 祖先关系，并返回具体失效组件。
- Cache 写入使用同卷临时文件、`fsync` 和不覆盖的原子 hard-link；同键同内容幂等，
  同键不同证据拒绝，损坏记录/证据不能命中。Cache 记录不持久化命令参数值。
- 新增 `flowpilot-eng evidence record/check` 与 `attempt report`。Attempt 报告将实际读取
  记录（可空）和按 UTF-8 字节估算 Token 严格分栏，只保存路径/摘要/计数、命令摘要、
  选择/缓存原因和范围扩展计数。
- Makefile 注册 `packages/engineering-control/src` strict Mypy 源，并新增稳定
  `engineering-control-test` / `engineering-control-smoke` 入口。

## 未完成与非目标

- 未替代 Release/Acceptance/真实环境门禁；选择器只能减少开发阶段重复计算。
- 未缓存在线 Provider、Secret、漏洞、真实 Migration、破坏性恢复或显式安全重跑结果。
- 未实现 OS 级读取拦截、远程共享 Cache、签名服务、产品 Runtime Context 或发布提升。
- 未运行全仓 pytest；仅运行一次不含本包定向目录的 Core/Runtime/Data/Platform 共享回归。
- 未唤醒 S7；本提交只交给预授权的 S4 WP-093 黑盒验收。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `packages/engineering-control/src/**/selection.py` | 测试分层、依赖传播、非空 fallback、argv 模型 | S5 |
| `packages/engineering-control/src/**/evidence.py` | Cache key、策略、完整性、原子写与命中解释 | S5 |
| `packages/engineering-control/src/**/report.py` | actual/estimated 分栏 Attempt report | S5 |
| `packages/engineering-control/src/**/cli.py`、`__init__.py`、`errors.py` | 五类 CLI、导出与稳定错误 | S5 |
| `packages/engineering-control/src/**/repository.py`、`capsule.py` | 产品/安全保护树与删除保护标签收口 | S5 |
| `tests/core/engineering_control/**` | 选择、缓存、篡改、漂移、注入、幂等与报告负例 | S5 |
| `Makefile` | 稳定 targeted/smoke 入口和 strict Mypy 包注册 | S5（本 WP 单写授权） |
| `tests/core/evidence/WP-092-a1-HANDOFF.md` | 本交接 | S5 |

## 契约、数据库与配置变化

- 契约版本：无变化；Contract content digest 保持
  `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`。
- Migration / PostgreSQL / Redis：无变化；Migration 变化只触发 RELEASE 与真实门禁计划。
- 环境变量：无新增；环境指纹只记录 OS、架构、Python 实现/版本的摘要，不读取环境
  变量值、Token 或 Secret。
- 依赖：无新增；运行时继续只用 Python 标准库，`uv.lock` 在 WP-092 未变化。
- 兼容性：WP-091 map/capsule schema 保持 v1；新增 test-plan、cache-record 和
  attempt-report v1。公共 ContractSet、产品 API/Runtime 均未变化。

## 验证

| 命令 / 门禁 | 结果 | 证据 |
|---|---|---|
| `uv run --locked pytest -q tests/core/engineering_control` | PASS | 56 passed |
| Core+Runtime+Data+Platform shared（排除已跑 targeted） | PASS | 1058 passed / 1 explicit online-provider skip |
| `python -B contracts/conformance/validate.py` | PASS | 20 schemas / 35 cases / 43 semantic / 52 features |
| Workspace Ruff | PASS | All checks passed |
| Makefile 同源 strict Mypy | PASS | 150 source files |
| `uv lock --check` | PASS | 169 packages resolved；lock unchanged |
| engineering-control wheel | PASS | `flowpilot_engineering_control-0.1.0-py3-none-any.whl` |
| module import / `flowpilot-eng --help` | PASS | map/capsule/tests/evidence/attempt 五类命令可见 |
| Make targets | ENV_BLOCKED | Windows Host 未安装 `make`；已运行其稳定 uv 等价命令 |

共享回归首次误用 `uv run pytest`，在 collection 前因仓库根未进入 `sys.path` 导致既有
`artifacts` / `packages` 两个模块 import error，0 tests executed。随后严格按 Makefile 的
稳定入口 `uv run --all-packages --all-groups --locked python -B -m pytest` 精确重跑同一
集合并通过；没有把错误入口冒充门禁，也没有运行第二次全仓。

## 安全与失败路径

- 已验证负向路径：rename/delete、跨包与传递依赖、公共签名、Contract/Migration/Lock/
  security/unknown/non-linear 升级、无映射/空证明 fallback、Shell 元字符/NUL、失败结果、
  各默认不可复用类别、record/evidence 篡改、环境/工具链/argv/各保护树漂移、不可追溯
  Head、同键污染、重复写幂等和实际读取重复路径。
- Secret/PII：Cache record 和 Attempt report 不保存 argv 值、环境变量、文件正文、Prompt、
  Token、PII 或 Secret；测试以显式 Secret 参数验证输出仅含摘要。
- 残余风险：本地 Cache 自摘要防止非授权漂移和普通篡改，但不是远程敌手签名服务；正式
  Handoff 仍携带外部 SHA-256，由 S4/S7/S1 独立复算。工具故障回退 FULL/RELEASE。
- 在线 Provider smoke 的 1 项 skip 需要显式
  `FLOWPILOT_ENABLE_ONLINE_PROVIDER_SMOKE=1`；按策略不得用 Cache 替代。

## 已知问题

- 无 P0/P1。Host 没有 `make` 是已记录环境限制，稳定目标的等价 uv 命令均已通过。
- `uv run pytest` 与 `python -m pytest` 的根路径语义不同；共享门禁必须复用 Makefile
  规定的后者，错误签名为 collection 阶段 `ModuleNotFoundError: artifacts/packages`。

## 已知事实与避免重复

- `KNOWN_FACTS`：WP-091 Head=`22527cab03d77a29e30cbeaf9843ba9ab9079ce2`；真实 map/
  capsule 已逐字节复算；Contract/Migration/Lock 未变化；WP-092 targeted/shared/static/
  Contract/wheel 均通过。
- `DO_NOT_RECHECK`：S4 复用 56 targeted、1058 shared、Contract/Ruff/Mypy/lock/wheel；只从
  黑盒 CLI、mutation matrix、20% 阈值、Cache policy/integrity 和报告声明边界独立审查。
- `FAILURE_SIGNATURES`：错误 console-script pytest 入口在 collection 前缺根路径；正确
  `python -m pytest` 为 1058 passed / 1 explicit skip。
- `REUSED_DECISIONS`：WP-091 Owner/protected/path/canonical/Git/metadata-only 边界；
  `ENGINEERING_CONTROL_PLANE.md` 的 FULL/RELEASE 和默认不可复用策略。
- `DUPLICATE_WORK_AVOIDED`：共享回归排除 56 targeted；未运行全仓、M7 历史验收、在线
  Provider、真实 Migration 或已知 M8 acceptance 矩阵。

## 学习候选

```text
LEARNING_CANDIDATE=Evidence Cache 必须绑定测试实现与命令入口而不只绑定 argv
MATURITY=VERIFIED
TRIGGER=相同 command_id/argv 下测试文件、Makefile 或执行脚本变化会让旧成功证据语义失效
MECHANISM=只哈希 argv 无法识别命令实现变化，可能产生确定性误命中
STRUCTURE=product execution tree 包含产品源码、测试、Makefile、脚本、CI 与工程控制包；再独立绑定 Contract/Migration/Lock/环境/工具链
EVIDENCE=product/contract/migration/lock/environment/toolchain/argv drift tests；56 targeted passed
RESIDUAL_RISK=远程敌手篡改仍需外部 Handoff Hash/签名与独立复算，本地 Cache 不宣称信任根
TARGET=ENGINEERING_CONTROL_PLANE Evidence Cache section
```

## 子 Agent 使用摘要

```text
SUBAGENTS_USED=2
SUBAGENT_MODES=READ_ONLY_PARALLEL
SUBAGENT_TASKS=WP091/repository-map,WP092/test-selection+evidence-cache
SUBAGENT_WRITERS=0
PARENT_REPRODUCED_RESULTS=yes
REUSED_DECISIONS=WP-091-HANDOFF,ENGINEERING_CONTROL_PLANE,WP-092
DUPLICATE_WORK_AVOIDED=5
```

## 接收会话下一步

1. S4 在精确 S5 Head 上按 WP-093 从 CLI 黑盒复算 map/capsule/plan/cache/report。
2. 以 mutation matrix 独立验证 20% 阈值、零漏选、FULL/RELEASE 升级、默认不可复用与
   actual/estimated 声明；不重复 S5 内部单元实现审查。
3. S4 PASS 后按 Chain 唤醒 S7 WP-094；本 S5 Step 不直接唤醒 S7。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M9T-ENGINEERING-CONTROL-01
STEP_ID=M9T-02-S5-SELECT-CACHE
ATTEMPT_ID=WP-092-a1
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=22527cab03d77a29e30cbeaf9843ba9ab9079ce2
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/core/evidence/WP-092-a1-HANDOFF.md
NEXT_ROLE=S4-QUALITY
NEXT_ATTEMPT_ID=WP-093-a1
ESCALATE_TO_S1=no
SUBAGENTS_USED=2
```

## 可回滚方式

- `git revert` 本 WP-092 提交恢复到 WP-091 map/capsule；禁止 reset、rebase 或 force-push。
  回滚不改变公共 Contract、Migration 或产品 Runtime。
