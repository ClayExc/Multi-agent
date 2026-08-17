# WP-122-a1 S3-PLATFORM Handoff

## 基本信息

- Work Package：`WP-122`
- Attempt ID：`WP-122-a1`
- Chain ID：`CHAIN-M11-SHORT-TERM-MEMORY-01`
- Step ID：`M11-01-S3-MEMORY-SECURITY`
- 责任会话：`S3-PLATFORM`
- 接收会话：`S2-RUNTIME`
- 交接策略：`CONSUMER_GATE`
- 功能 ID：`FP-CTX-002`、`FP-CTX-003`、`FP-SEC-003`、`FP-SEC-005`
- 基线提交：`d99c824b08ae78521b9456ea462aea595f37e348`
- 分支/最终提交：`codex/s3/wp-122-m11-memory-security` / `<this-handoff-commit>`
- ContractSet 摘要：`sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- Context Capsule：`.flowpilot-engineering/m11/s1-capsule.json`
- Capsule 逻辑摘要：`sha256:2cf97f6f59efe1380dab9546fcc0cc440216b80084388a6e40227bb2b3d98c79`
- Capsule Blob 摘要：`sha256:c479011ad96fdd4fb9c8408ed7b6fcdb7f3b2b8aaff111d0833413530a4d08b2`
- 状态：完成

## 完成内容

- 在唯一内容安全注册表增加 `ContentSurface.WORKING_MEMORY`；现有三条 Prompt
  Injection 规则显式作用于该 Surface，没有复制第二套凭据或注入注册表。
- 新增 `assert_working_memory_safe` 与 `scan_working_memory_content`，供 Turn 构造、
  Snapshot/Manifest 持久化前、重放、Context 输出及错误/日志投影使用同一入口。
- 凭据检查继续复用全部 `CREDENTIAL_FAMILIES` 并保持 DLP 优先；内容安全注册表版本提升为
  `flowpilot.content-safety.m11.v1`。
- 新增不可变禁止字段集合，阻断 SecurityContext、角色/Scope、Capability、审批/策略、
  Provider Session、Token、完整消息/Prompt/Payload、隐藏推理及原始异常字段。
- 新增隐藏推理和原始异常回显规则；新增 `PLATFORM_WORKING_MEMORY_BLOCKED` 稳定错误码。
- 使用迭代式结构预检实现最大深度 `12`、循环、非字符串 key、不可读容器与非 JSON
  对象失败关闭。预检早于凭据扫描，恶意容器异常不会把原异常或原值带入错误链。
- Finding/异常只携带稳定 rule/family ID 与 ordinal 安全路径。危险调用方 `field` 会降为
  `$`，不会把模型生成字段名或敏感内容写进 `str/repr/traceback/log`。
- 数据驱动测试将全部 17 个凭据 family 与 Turn、Snapshot、Manifest、replay、
  Context output、异常投影、日志投影七个边界交叉；同时覆盖合法中文、业务 ID、短邻接串
  及安全引用。

## 未完成与非目标

- 未实现 Conversation Turn、Snapshot、Manifest、Context Builder、Runtime、Persistence、
  API、Web 或数据库对象；这些分别属于 WP-123～WP-128。
- 未修改公共 ContractSet、Migration、Workspace/Lock、Makefile 或验收注册表。
- 未把 Memory 作为业务、授权、审批、工具账本或 Checkpoint 的权威事实源。
- 固定 156 Case 仍是 `40 PASS / 116 explicit FAIL / 0 skipped`；没有声明
  `RELEASED`、`FROZEN` 或完整 Acceptance PASS。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `packages/security/src/flowpilot_security/content_safety.py` | WORKING_MEMORY Surface、规则、结构预检与统一 API | S3 |
| `packages/security/src/flowpilot_security/errors.py` | 新增稳定 Working Memory 拒绝码 | S3 |
| `packages/security/src/flowpilot_security/__init__.py` | 导出 M11 内容安全 API/元数据并提升 registry version | S3 |
| `packages/security/README.md` | 记录安全边界、调用阶段与非权威范围 | S3 |
| `tests/platform/test_short_term_memory_security.py` | 七边界、17 family、深度/循环/泄漏/合法内容矩阵 | S3 |
| `tests/platform/evidence/WP-122-a1-HANDOFF.md` | 本交接证据 | S3 |

## 契约、数据库与配置变化

- 契约版本：无变化；`contracts/**` 相对基线零差异。
- Migration：无。
- 环境变量：无。
- Workspace/Lock/Makefile：无变化。
- 兼容性：进程内 Python API 为 additive；既有 `assert_content_safe`、
  `assert_safe_projection`、DLP/Prompt 错误码语义保持不变。新增 Surface 行为由
  `flowpilot.content-safety.m11.v1` 精确标识。

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| `uv run --locked pytest tests/platform/test_short_term_memory_security.py tests/platform/test_credential_registry.py tests/platform/test_capability_dlp.py -q` | PASS | `461 passed` |
| `uv run --all-packages --all-groups --locked python -B -m pytest tests/platform -q` | PASS | `638 passed` |
| Makefile `test-security` 的 Windows 等价命令 | PASS | `273 passed` |
| Makefile `test-contract` 的 Windows 等价命令 | PASS | 20 schemas / 35 cases / 43 semantic / 52 features；audit/manifest/review cases 全部通过 |
| `uv run --all-packages --all-groups --locked ruff check packages/security tests/platform` | PASS | `All checks passed` |
| `uv run --all-packages --all-groups --locked mypy --strict packages/security/src/flowpilot_security` | PASS | 11 source files |
| `uv run --all-packages --all-groups --locked python -B -m pytest tests/experience/test_secret_scan.py -q` | PASS | `2 passed` |
| Makefile `test` 的 Windows 等价命令 | PASS | `2085 passed, 1 explicit online skip` |
| `run_acceptance.py`（唯一临时输出目录） | 产品测试套件 PASS；Release gate 保持 FAIL | unit 575、contract 53、integration 168 + 1 explicit online skip、e2e 396、recovery 40、security 37；固定分母 `40 PASS / 116 explicit FAIL / 0 skipped` |
| `git diff --check`、授权路径检查 | PASS | 仅 `packages/security/**`、`tests/platform/**`；越权 0 |

补充说明：Windows 环境未安装 `make`，`make test-security` 与 `make test-contract` 的入口为
`ENV_BLOCKED`，已逐字执行当前 Makefile 中对应的 `uv` 命令。`flowpilot-eng tests select`
在实现已 dirty 后按设计返回 `ENG_DIRTY_WORKTREE`；未伪装为通过。其 `security_change`
确定性策略要求 Release 层门禁，以上已实际执行全仓、Contract、Security 与 Acceptance。
Acceptance 的六个产品测试套件全部通过，整体 `gate=fail` 仅来自项目已声明的 116 个未实现
Case，与本 Attempt 前的可信基线精确一致。

## 安全与失败路径

- 已验证负向路径：全部凭据 family 的 nested key/value/ref/structured offset；隐藏推理 key
  与文本标记；Prompt Injection；SecurityContext/role/scope/capability/provider-session 字段；
  原始 Python/Java 异常标记；最大深度 + 1；循环；非字符串 key；不可读 Mapping；自定义
  对象 `repr`；replay 污染；危险 root field。
- 已验证无泄漏：错误 `str/repr`、格式化 traceback 与 caplog 均不含命中原值、恶意 key、
  ref 或底层异常文本。
- 已验证合法路径：中文业务文本、`TCK-100`、task/turn ID、短 `sk-admin` 邻接串、
  `xoxo-*` 业务 ID、`result://` 与 `knowledge://...#credential-check` 引用。
- Secret/PII 检查：Secret Scan `2 passed`；测试凭据均由字符串片段合成，无真实 Token/PII。

## 已知问题

- `RELEASED=false`、`FROZEN=false`；固定 116 个未注册产品执行器仍按 M11 激活基线显式失败。
- 本安全表面只做内容安全判定。S2 必须在构造、每次重放和每次 Context 输出重新调用，不能
  信任持久化的 safe marker 或摘要 Hash 来跳过扫描。
- S2 应先把内部模型投影成 JSON 兼容树再调用；安全包不会序列化或保留原始对象。

## 已知事实与避免重复

- `KNOWN_FACTS`：M0～M10 工程候选已完成；ContractSet 内容摘要未变；M11 固定分母为
  40 PASS / 116 explicit FAIL。
- `DO_NOT_RECHECK`：无需重跑 M10 Keycloak/RLS/知识链或重读完整 README/STRUCTURE；输入
  Blob、Contract 和 Repository Map 未变。
- `FAILURE_SIGNATURES`：`ENG_DIRTY_WORKTREE` 仅表示 selector 要求 clean；Acceptance
  `gate=fail` 精确绑定 116 个 `EXECUTOR_NOT_REGISTERED` 基线，不是 WP-122 产品测试失败。
- `REUSED_DECISIONS`：ADR-0006、SHORT_TERM_MEMORY、既有 CREDENTIAL_FAMILIES、
  PROMPT_INJECTION_RULES、WP-074 凭据 offset-safe 机理与 M10 稳定门禁。
- `DUPLICATE_WORK_AVOIDED`：未复制凭据/Prompt registry；未复现 M10 不相关链路；两个只读
  子 Agent 分别审查 API 与测试边界，没有重复主线写入。

## 学习候选

```text
LEARNING_CANDIDATE=不可信内容扫描先做无原值结构预检
MATURITY=IMPLEMENTED
TRIGGER=任意 Mapping/Sequence 可能在遍历时抛出携带敏感文本的异常，递归投影还可能因循环或超深结构产生非稳定错误
MECHANISM=凭据或内容规则命中前若直接遍历不可信容器，原始异常可能绕过稳定错误映射；递归实现还会形成资源或 RecursionError 旁路
STRUCTURE=迭代式 ordinal-path 预检先验证深度、循环、key 类型、容器可读性和对象类型；失败只返回 rule ID/安全路径，再执行凭据与内容规则
EVIDENCE=tests/platform/test_short_term_memory_security.py；Platform 638；全仓 2085+1 explicit skip
RESIDUAL_RISK=S2/S6/S4 各消费边界仍须调用该 API，后续组合门禁验证不得以 safe marker 跳过重放扫描
TARGET=docs/architecture/ENGINEERING_PLAYBOOK.md content-safety section
```

## 子 Agent 使用摘要

```text
SUBAGENTS_USED=2
SUBAGENT_MODES=READ_ONLY_PARALLEL
SUBAGENT_TASKS=wp122_security_surface_audit,wp122_test_boundary_audit
SUBAGENT_WRITERS=0
PARENT_REPRODUCED_RESULTS=yes
REUSED_DECISIONS=ADR-0006,SHORT_TERM_MEMORY,M9/M10 central content-safety registry
DUPLICATE_WORK_AVOIDED=2
```

## 接收会话下一步

1. 消费者门禁核验本 Handoff Hash、Contract 摘要、clean 与精确 `NEW_HEAD`，只用
   `--ff-only` 到达该 Head。
2. WP-123 在 `packages/context/**`、`tests/runtime/**` 内实现 Turn/Snapshot/Manifest 与
   Summary/Token 核心；公共 ContextEnvelope v1 不变。
3. 在构造、持久化请求生成前、replay、Context/Handoff 输出及安全错误/日志投影调用
   `assert_working_memory_safe`；不得复制规则或以持久化 Hash/safe marker 跳过重校验。
4. 保持 claimed/verified/inferred 确定性升级、Memory 非权威、无 SecurityContext/角色/
   Scope/Capability/Provider Session 与无原始异常回显。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M11-SHORT-TERM-MEMORY-01
STEP_ID=M11-01-S3-MEMORY-SECURITY
ATTEMPT_ID=WP-122-a1
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=d99c824b08ae78521b9456ea462aea595f37e348
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
RELEASE_GATE=FAIL_EXPECTED_BASELINE_40_PASS_116_EXPLICIT_FAIL
HANDOFF=tests/platform/evidence/WP-122-a1-HANDOFF.md
NEXT_ROLE=S2-RUNTIME
NEXT_ATTEMPT_ID=WP-123-a1
ESCALATE_TO_S1=no
SUBAGENTS_USED=2
```

## 可回滚方式

- 回滚本 Work Package 提交即可移除 M11 Surface、API、错误码、测试与证据；无需 Contract、
  Migration、Workspace 或数据回滚。
