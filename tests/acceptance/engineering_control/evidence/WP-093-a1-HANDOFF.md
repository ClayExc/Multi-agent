# WP-093 S4-QUALITY 工程控制面黑盒验收交接

## 基本信息

- Work Package：WP-093
- Attempt ID：WP-093-a1
- Chain ID：`CHAIN-M9T-ENGINEERING-CONTROL-01`
- Step ID：`M9T-03-S4-ACCEPTANCE`
- 责任会话：S4-QUALITY
- 接收会话：S7-INTEGRATION
- 交接策略：`CONSUMER_GATE`
- 功能 ID：FP-OPS-002
- 基线提交：`fbee7919c4c8bd9d1318d65cc4ce8bb5361a5c9b`
- 分支/最终提交：`codex/s4/wp-093-engineering-acceptance` / 本文件所在提交
- ContractSet 摘要：
  `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：完成

## 完成内容

- 从 `python -m flowpilot_engineering_control` 公开 CLI 子进程建立独立黑盒，不导入生产
  选择器、Cache 或报告实现。每个 Case 使用隔离、固定提交时间、clean 的临时 Git
  多包仓库。
- 固定 Mutation Matrix 覆盖包内、跨包、公共签名、Contract、Migration、Lock、安全、
  未知路径、依赖图异常、非线性异常和无变更证明；所有计划均非空，预期测试前缀漏选
  数为 0，未知已跟踪路径稳定 `ENG_UNKNOWN_PATH` 失败关闭。
- Map/Capsule 输出逐字节确定；Windows 分隔符归一化，UTF-8 路径保留，LF/无 BOM；超大
  生成 Artifact 与 coverage 噪音不进入源码计数。包内 Fixture 初始读取为 6/88 文件、
  307/67820 字节，比例 45 basis points（0.45%），低于 20%。
- Cache 黑盒覆盖精确命中、Evidence/Record 篡改、环境/工具链漂移、同键污染、失败结果、
  argv 注入，以及六类默认不可复用证据；成功污染和命令执行数均为 0。
- Attempt Report 将实测 8 bytes 与估算 304 bytes 严格分栏；缺少 actual 记录为 `null`，
  重复路径失败关闭；人工范围扩展保留且不改变原 TARGETED 计划。
- 正式 Proof 完全由 28 条唯一逐 Case 原始结果生成：28 PASS、0 FAIL、0 skip，Proof 内部
  摘要为 `66a06074e062bc421797030bbdff44556f80761175fb98444b63369e57730cdd`。

## 未完成与非目标

- 未运行全仓 pytest、Compose、在线 Provider、真实 Migration、破坏性恢复、漏洞查询或
  Release 门禁；这些证据按 WP-092 策略不可复用，留给相应 Owner/S7。
- 未修改生产实现、公共 Contract、Migration、Lock、Makefile 或 Feature 状态。
- 本交接不宣称 FP-OPS-002、M9T、产品 Feature 为 `RELEASED` 或 `FROZEN`。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `tests/acceptance/engineering_control/blackbox.py` | 临时 Git Fixture、公开 CLI Mutation/Cache/Report 黑盒 | S4 |
| `tests/acceptance/engineering_control/test_engineering_control_blackbox.py` | 六组独立验收入口 | S4 |
| `tests/acceptance/engineering_control/generate_proof.py` | 从逐 Case 结果原子生成 Proof | S4 |
| `tests/acceptance/engineering_control/__init__.py` | 测试包标记 | S4 |
| `artifacts/acceptance/engineering-control/WP-093-a1-PROOF.json` | 28 条 Case 正式 Proof | S4 |
| `tests/acceptance/engineering_control/evidence/WP-093-a1-HANDOFF.md` | 本交接 | S4 |

## 契约、数据库与配置变化

- 契约版本：无变化；Contract content digest 保持不变。
- Migration / PostgreSQL / Redis：无变化；仅在临时 Fixture 中验证 Migration 选择升级。
- 环境变量：无新增、无读取或保存环境变量值。
- 依赖 / Lock / Makefile：无变化。
- 兼容性：新增内容仅位于 S4 验收与生成 Artifact 路径，不被产品 Runtime 导入。

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| `uv run --locked python -B -m pytest -q tests/acceptance/engineering_control/test_engineering_control_blackbox.py` | PASS | 6 passed；28/28 原始 Case |
| `uv run --locked ruff check tests/acceptance/engineering_control` | PASS | All checks passed |
| `uv run --all-packages --all-groups --locked mypy --strict --explicit-package-bases tests/acceptance/engineering_control` | PASS | 4 source files |
| `uv run --all-packages --all-groups --locked python -B contracts/conformance/validate.py` | PASS | 20 schemas / 35 cases / 43 semantic / 52 features |
| `flowpilot_security.scan_secret_material` 扫描本 WP 源码与 Proof | PASS | 0 findings |
| `git diff --check` | PASS | 无空白错误 |

## 安全与失败路径

- 已验证负向路径：未知 Owner 路径、无变更证明、依赖图/非线性故障、Contract/Migration/
  Lock/安全升级、Cache Record/Evidence 篡改、环境/工具链漂移、失败结果、同键污染、六类
  policy deny、Shell 元字符、重复 actual read、Secret/正文泄漏、生成/coverage 噪音。
- 未验证风险：本地 Cache 仍不是远程签名信任根；OS 级手工读取拦截、真实外部环境和最终
  Release 组合门禁不属于本 WP。
- Secret/PII：高置信扫描 0；Proof、Map、Capsule、Cache/Report 输出不含 Fixture 正文、
  argv 值、Token、Secret 或 PII。

## 已知问题

- 无新增 P0/P1。
- 首次 Mypy 命令未进入类型检查，因为 tests namespace 被解析成两个模块名；按仓库既有
  稳定入口增加 `--explicit-package-bases` 后严格检查通过。该失败未冒充门禁通过。

## 已知事实与避免重复

- `KNOWN_FACTS`：S5 Head/Handoff/Contract 已精确核对；WP-091/092 定向、共享、Lock、Wheel
  证据保持可复用；S4 Proof SHA-256 为
  `d512cffd08bf6d6bd3f94028e23694e2a08fcbf00e684c847c3a337f827a150c`。
- `DO_NOT_RECHECK`：S7 不重跑 S5 56 targeted、1058 shared 或 S4 开发过程；从 Proof Hash、
  独立 CLI 抽样、保护树和组合入口换观察边界复算。
- `FAILURE_SIGNATURES`：Mypy tests namespace 需 `--explicit-package-bases`；未知路径为
  `ENG_UNKNOWN_PATH`；失败证据为 `ENG_CACHE_FAILED_RESULT`；同键污染为
  `ENG_CACHE_KEY_CONFLICT`。
- `REUSED_DECISIONS`：WP-091 Owner/path/metadata-only；WP-092 FULL/RELEASE 与不可复用策略；
  `ENGINEERING_CONTROL_PLANE.md`。
- `DUPLICATE_WORK_AVOIDED`：未重复 S5 白盒、共享回归、全仓、在线/付费/真实 Migration。

## 学习候选

```text
LEARNING_CANDIDATE=none
MATURITY=VERIFIED
TRIGGER=none
MECHANISM=none
STRUCTURE=none
EVIDENCE=WP-093 复用 WP-091/092 已记录机理，无新增独立通用机制
RESIDUAL_RISK=none
TARGET=none
```

## 子 Agent 使用摘要

```text
SUBAGENTS_USED=0
SUBAGENT_MODES=none
SUBAGENT_TASKS=none
SUBAGENT_WRITERS=0
PARENT_REPRODUCED_RESULTS=not-applicable
REUSED_DECISIONS=WP-091-HANDOFF,WP-092-HANDOFF,WP-093
DUPLICATE_WORK_AVOIDED=5
```

## 接收会话下一步

1. S7 仅以 `--ff-only` 精确消费本提交，独立复算 Handoff/Proof Hash、28/28 分母、0.45%
   阈值、选择零漏项、Cache/Report 声明和产品/Contract/Migration/Lock 保护树。
2. S7 执行 WP-094 组合门禁并交回 S1；S7 不批准自身结果，不自动提升 Feature 状态。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M9T-ENGINEERING-CONTROL-01
STEP_ID=M9T-03-S4-ACCEPTANCE
ATTEMPT_ID=WP-093-a1
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=fbee7919c4c8bd9d1318d65cc4ce8bb5361a5c9b
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/acceptance/engineering_control/evidence/WP-093-a1-HANDOFF.md
NEXT_ROLE=S7-INTEGRATION
NEXT_ATTEMPT_ID=WP-094-a1
ESCALATE_TO_S1=no
SUBAGENTS_USED=0
```

## 可回滚方式

- `git revert` 本 WP-093 提交；禁止 reset、rebase 或 force-push。回滚只移除 S4 黑盒和
  Proof，不改变工程控制生产包、公共 Contract、Migration 或产品 Runtime。
