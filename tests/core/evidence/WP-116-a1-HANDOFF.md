# WP-116 / S5-CORE Final Handoff

## 基本信息

- Work Package：WP-116
- Attempt ID：WP-116-a1
- Chain ID：CHAIN-M10-KNOWLEDGE-01
- Step ID：M10-06E-S5-WP116-FINAL
- 责任会话：S5-CORE
- 接收会话：S1-ARCH
- 交接策略：S1_GATE
- 功能 ID：FP-KNOW-010、FP-UI-001、FP-DATA-001、FP-SEC-003
- 最终门禁输入提交：`88101155f52405e9f528171c1407c38edb406fdb`
- WP-116 产品提交：`c2c916d0f653d063dffb7d902d2e29cfbba942af`
- 分支：`codex/s5/wp-111-m10-knowledge-core`
- ContractSet 摘要：`sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：完成；等待 S1 最终复核与 WP-117 解锁裁决

## 完成内容

- 交付本地 Knowledge 管理/诊断 API：import、update、retire、delete、rebuild、document read 与 diagnostic read。
- 写操作重验可信 Cookie 身份、SecurityContext、用途、职责和服务端 ACL，并绑定严格 `Idempotency-Key`；拒绝客户端自报 tenant、ACL、classification authority 或其他授权事实。
- 公开查询仅返回安全文档/诊断投影，不返回正文；错误使用稳定安全映射，响应禁止缓存并绑定 Cookie 变体。
- 增加 PostgreSQL Knowledge service factory、Retrieval/Knowledge MCP 生产组合边界和 dependency all-or-none 防误配。
- 完成根 Workspace/Lock 闭包：注册既有 Retrieval member/source，声明 API 对 MCP Gateway、Knowledge MCP、Persistence、Retrieval 的直接依赖。
- 根静态检查与 Coverage 源集合加入 Retrieval；稳定 `test`/`test-coverage` 使用 pytest importlib 收集模式，不排除目录或 Case。
- 消费并验证 S2/S4/S7 三个线性修复 Head；最终唯一全仓、Contract、Security 门禁全部通过。

## 三类修复闭合

### S2 Runtime import fixture

- Head：`75902004e339d05eeca3a9e6a376427fa12f0fad`
- Handoff：`tests/runtime/evidence/WP-116-a1-RUNTIME-IMPORT-HANDOFF.md`
- SHA256：`sha256:2d65031ea707256430ce3e39adc1022ebb96e18907e54686588558d80406241d`
- 12 个 Runtime 模块改为仓库根明确 helper 包导入；不使用临时 `PYTHONPATH`、`sys.path` 注入、目录排除或 prepend 回退。
- 原 collection blocker 已闭合；最终全仓稳定收集 1856 items。

### S4 Acceptance fixture

- Head：`d57782c3cf08fc52ee4a89dd5410ef0bb4f34ae4`
- Handoff：`tests/acceptance/evidence/WP-116-a1-ACCEPTANCE-FIXTURE-HANDOFF.md`
- SHA256：`sha256:1efc7a07166b32268aa49c001006a30ab6aa82d1a0448c46db92077009e18de4`
- 集中 DLP 期望迁移到稳定 `CONTENT_BLOCKED`；28 个旧 CapabilityHandle fixture 改为绑定真实 SecurityContext/Action/Resource/Policy/Execution/Use 的当前模型。
- 原 29/29 S4 fixture failures 已闭合；没有恢复 legacy Handle、放宽 Capability 或修改公共 Contract。

### S7 Historical verifier isolation

- Head：`88101155f52405e9f528171c1407c38edb406fdb`
- Handoff：`tests/integration/evidence/WP-116-a1-HISTORICAL-VERIFIER-HANDOFF.md`
- SHA256：`sha256:a200ee3618ebec816144c8279ad0ac7449cbf4bf28b2663500e0d7c240686432`
- WP-094/WP-109 验证记录的候选提交；WP-040 在临时 detached historical checkout 中验证，不再把当前 M10 checkout 当作历史事实。
- 原 10/10 S7 historical verifier failures 已闭合；未更新历史 Hash、放宽 ancestry/protected tree/migration 检查或把 M10 当作旧候选。

## 未完成与非目标

- WP-117 Runtime citation 尚未开始；S5 未唤醒 S2。
- 固定 Acceptance 156 当前仍为 39 PASS / 117 `EXECUTOR_NOT_REGISTERED`。这是 WP-119 前的已知非发布基线，不是 WP-116 回归，也不表示 Release。
- 本步骤未再次生成 Acceptance Artifact，未改变固定分母、Dataset、Feature 状态、`RELEASED=false` 或 `FROZEN=false`。
- 未实现 Web、Runtime citation、数据库/Migration、MCP Tool Schema 或公共 Contract 变更。
- 未重复运行 full Ruff、strict Mypy、lock 或 API wheel；按 S1 指令复用此前 PASS，且从产品提交到最终门禁输入，相应产品/Workspace 文件无漂移。

## 修改文件

### WP-116 产品提交

| 文件/目录 | 变化 | 所有者 |
|---|---|---|
| `apps/api/src/flowpilot_api/app.py` | Knowledge 管理/查询路由、稳定错误与安全响应 | S5 |
| `apps/api/src/flowpilot_api/knowledge.py` | Knowledge Port 适配、访问策略与生产组合 | S5 |
| `apps/api/src/flowpilot_api/models.py` | 严格请求与安全响应模型 | S5 |
| `apps/api/src/flowpilot_api/security.py` | Knowledge 请求身份重验与授权 | S5 |
| `apps/api/src/flowpilot_api/composition.py` | Product composition 注入 | S5 |
| `apps/api/src/flowpilot_api/testing.py` | Core Fake 的 Knowledge 授权行为 | S5 |
| `apps/api/src/flowpilot_api/__init__.py` | Knowledge API/composition 导出 | S5 |
| `apps/api/pyproject.toml` | API 直接 Workspace 依赖 | S5 / Workspace writer |
| `pyproject.toml` | Retrieval Workspace member/source/root dependency 与工具源集合 | S5 / Workspace writer |
| `uv.lock` | Workspace lock 闭包 | S5 / Workspace writer |
| `Makefile` | Retrieval 检查集合与 importlib 稳定测试入口 | S5 / Workspace writer |
| `tests/core/test_knowledge_api.py` | Knowledge API 正常、边界、失败、安全与幂等测试 | S5 |

### 最终步骤新增

| 文件 | 变化 | 所有者 |
|---|---|---|
| `tests/core/evidence/WP-116-a1-HANDOFF.md` | 正式最终交接证据 | S5 |

S2/S4/S7 修复路径与各自所有权已在对应 Handoff 中完整记录；三个 Head 均为精确单父线性链。

## 契约、数据库与配置变化

- 公共 Contract / Tool Schema：无变化；ContractSet digest 精确匹配。
- Application/Domain Port：未放宽既有 Knowledge Port、分类、稳定引用或安全不变量。
- Migration / RLS / 数据库 Schema：无变化。
- 环境变量：无新增；Knowledge 组合由显式依赖注入构造。
- Workspace / Lock：新增既有 Retrieval workspace closure 与 API 直接依赖；`uv.lock` 已同步并复用 PASS lock 证据。
- 兼容性：消费者 fixture 已迁移到当前 DLP/Capability 接口；产品没有为旧 fixture 增加兼容回退。

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| `uv run --all-packages --all-groups --locked python -B -m pytest --import-mode=importlib` | PASS | 1855 passed、1 explicit online Provider skip；1856 collected；395.52s；仅运行一次 |
| `uv run --all-packages --all-groups --locked python -B contracts/conformance/validate.py` | PASS | 20 schemas / 35 cases / 43 semantic / 52 features；全部 mutation/audit/manifest/review cases 通过 |
| Makefile `test-security` 精确等价命令 | PASS | 273 passed in 7.52s |
| `ruff check`：`a773d53..8810115` 新增的 21 个测试/脚本 | PASS | All checks passed |
| `git diff --check a773d53..8810115` | PASS | 无 whitespace error |
| 三份 Handoff Hash / 单父提交 / Owner 范围 | PASS | Hash 精确匹配；`a773d53 -> 7590200 -> d57782c -> 8810115` |
| full Ruff / strict Mypy / API wheel | REUSED PASS | S1 明确授权复用；产品提交 `c2c916d` 至最终输入 `8810115` 的 `apps/api` 与静态检查输入无漂移 |
| `uv lock --check` | REUSED PASS | WP-116 producer checkpoint 已通过；后续三个修复范围未修改 root Workspace/Lock |
| Acceptance 固定 156 | REUSED NON-RELEASE BASELINE | 39 PASS / 117 `EXECUTOR_NOT_REGISTERED`；本步骤未重跑或生成 Artifact |

Windows 环境无 `make`，上述 test、test-contract、test-security 均执行 Makefile 中的精确等价 `uv --all-packages --all-groups --locked` 命令。

## 安全与失败路径

- Knowledge 写入只接受可信 Cookie Identity 与复验 SecurityContext；客户端自报 authority 字段在调用服务前失败。
- ACL、purpose、classification、tenant、职责与 idempotency 均保持失败关闭；查询响应不包含正文。
- S4 Capability fixture 仍执行全字段强绑定自检；Invoke/Readback 使用隔离 Token Hash，未降低 replay/UNKNOWN/readback 断言。
- S7 historical fixture 使用固定 recorded revision；非祖先、未授权路径、protected drift、Migration missing/tamper/extra-head 负例继续通过。
- Security gate 273 PASS，包含 Secret Scan 2 PASS；无 Token、Secret、PII、正文或隐藏思维链进入响应、错误或证据。

## 已知问题

- 无新增 P0/P1，WP-116 产品与三类跨 Owner 修复均已闭合。
- P2 / 非发布状态：Acceptance 固定 156 仍有 117 个 executor 尚未注册，按 M10 顺序由 WP-117～119 处理；不能提升为 RELEASED/FROZEN。
- Online Provider Smoke 保持显式关闭并产生唯一 skip；未使用生产凭据或公网 Provider。

## 已知事实与避免重复

- `KNOWN_FACTS`：三份 Handoff Hash、线性父提交、Owner 范围、Contract digest、全仓/Contract/Security 最终门禁均已精确复算。
- `DO_NOT_RECHECK`：S1 不需重复运行本次 6 分 35 秒全仓；复核 Head、Handoff Hash、clean、Contract 与门禁输出后再决定 WP-117 解锁。Acceptance Artifact 等到 WP-119 再生成。
- `FAILURE_SIGNATURES`：原 S2 12 collection、S4 29 fixture、S7 10 historical failures 在唯一最终全仓中均未重现。
- `REUSED_DECISIONS`：此前 full Ruff、strict Mypy、lock、API wheel PASS；固定 156 的 39/117 非发布基线。
- `DUPLICATE_WORK_AVOIDED`：未重跑 full static/wheel/lock、未重跑 Acceptance 生成、未第二次运行全仓。

## 学习候选

```text
LEARNING_CANDIDATE=none
MATURITY=VERIFIED
TRIGGER=none
MECHANISM=none
STRUCTURE=none
EVIDENCE=三份 repair Handoff 已分别记录可复用机理
RESIDUAL_RISK=Acceptance executor registration remains for WP-117 through WP-119
TARGET=none
```

## 子 Agent 使用摘要

```text
SUBAGENTS_USED=0
SUBAGENT_MODES=none
SUBAGENT_TASKS=none
SUBAGENT_WRITERS=0
PARENT_REPRODUCED_RESULTS=yes
REUSED_DECISIONS=full Ruff/strict Mypy/lock/API wheel and fixed-156 acceptance baseline
DUPLICATE_WORK_AVOIDED=4
```

## 接收会话下一步

1. S1 复核本正式 Handoff Hash、最终 evidence Head、Contract digest、clean 与唯一最终门禁输出。
2. WP-117 只有在 S1 明确授权其以 `--ff-only` 精确消费包含本 Handoff 的最终 S5 Head 后解锁；S5 本步骤不自行唤醒 S2。
3. WP-117 不得把 39/117 Acceptance 非发布基线误解释为 WP-116 失败或 Release；后续只按 M10 线性链注册 Runtime/Web/Acceptance executor。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M10-KNOWLEDGE-01
STEP_ID=M10-06E-S5-WP116-FINAL
ATTEMPT_ID=WP-116-a1
NEW_HEAD=88101155f52405e9f528171c1407c38edb406fdb
BASE_COMMIT=88101155f52405e9f528171c1407c38edb406fdb
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/core/evidence/WP-116-a1-HANDOFF.md
NEXT_ROLE=S1-ARCH
NEXT_ATTEMPT_ID=none
ESCALATE_TO_S1=no
SUBAGENTS_USED=0
```

`NEW_HEAD` 是最终门禁验证的精确产品/修复 Join Head；包含本 Handoff 的最终证据提交由返回 S1 的外部交接信封精确指定。

## 可回滚方式

- 仅由 S1 通过新增反向提交按线性顺序回滚对应产品或修复提交；禁止 reset/rebase/force-push。
- 不得以排除测试、回退 pytest prepend 模式、临时 `PYTHONPATH`、恢复旧 Capability/DLP 接口或修改历史 Hash 的方式回滚。
