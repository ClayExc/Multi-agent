# WP-122-a1-r1 S3-PLATFORM Remediation Handoff

## 基本信息

- Work Package：`WP-122`
- Attempt ID：`WP-122-a1-r1`
- Chain ID：`CHAIN-M11-SHORT-TERM-MEMORY-01`
- Step ID：`M11-01R-S3-MEMORY-SECURITY`
- 责任会话：`S3-PLATFORM`
- 接收会话：`S1-ARCH`
- 交接策略：`S1_GATE`
- 功能 ID：`FP-CTX-002`、`FP-CTX-003`、`FP-SEC-003`、`FP-SEC-005`
- 修复基线：`85909b5971da1f9c42607805d8a2681840fa47c0`
- 分支/最终提交：`codex/s3/wp-122-m11-memory-security` / `<this-handoff-commit>`
- ContractSet 摘要：`sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 原 Handoff：`tests/platform/evidence/WP-122-a1-HANDOFF.md`
- 原 Handoff SHA256：`sha256:72e8e75d1bb95d9f6abadab0261a648b097e5a952a96d6f2eafea34cdd2e659a`
- 状态：修复完成，等待 S1 复核

## S1 审查项处置

1. `analysis`、`thinking` 与权威字段变体：已修复。
   - 不再依赖值中存在 `<thinking>` 等标签；字段名本身经 case-fold、标点归一化和受限
     token-family 匹配。
   - `analysis/thinking/reasoning/role/approval/security_context/scope/capability/`
     `policy_decision/provider_session` 及前后缀变体稳定拒绝。
   - `role_name`、`user.role.name`、`approval_status`、`task-approval-result` 等均覆盖。
   - `roleplay_scenario`、`rethinking_note`、`paralysis_note`、`disapproval_reason`、
     `password_policy_status` 作为相邻合法业务字段继续通过，避免任意子串误报。
   - 全部字段用例与 Turn、Snapshot、Manifest、replay、Context output、error projection、
     log projection 七个生命周期边界交叉。
2. Stateful Mapping 二次读取泄漏：已修复。
   - 不可信 Mapping/Sequence 只读取一次，并复制为仅含内建 `dict/tuple/scalar` 的受信快照。
   - identity memo 保证同一 DAG 节点只读取一次；Mapping `items()` 或 Sequence 迭代异常被
     转换成无原值的 `working_memory_unreadable_container` Finding。
   - 凭据 registry、隐藏推理、Prompt Injection、异常文本、字段策略和深度检查只消费快照，
     不再访问调用方容器。
   - 首次 `items()` 成功、第二次会抛含原文 RuntimeError 的复现现在只调用一次；合法内容
     通过，凭据内容仍由中央 `CREDENTIAL_FAMILIES` 检出并返回 `PLATFORM_DLP_BLOCKED`。
   - 错误 `str/repr/cause/traceback/log` 中原凭据和第二次异常文本均为 0。
3. DAG alias 被误判 cycle：已修复。
   - 循环只按当前递归祖先 identity 判定；祖先回边仍返回 `working_memory_cycle`。
   - 已完成的容器快照按 identity memo 复用，不用全局 `seen` 判错合法 sibling alias。
   - 内建 Mapping alias 与 Stateful Mapping alias 均通过，后者 `items_calls == 1`。
   - 深度与字段策略在受信快照上逐路径重算，因此 memo 不会跳过深路径限制。

## 边界裁决保持

- S3 只提供 universally forbidden 的隐藏推理、权威状态和内容安全规则，不为未知字段复制
  Turn/Snapshot/Manifest Schema allowlist。
- unknown-field allowlist 与 `classification <= trusted ceiling` 仍属于 S2/WP-123 Context
  模型边界。
- 未实现 Context、Persistence、Runtime、API、数据库或公共 Contract 变化。
- 未复制 credential family；全部凭据检测继续使用唯一 `CREDENTIAL_FAMILIES`。

## 修改文件

| 文件 | 变化 | Owner |
|---|---|---|
| `packages/security/src/flowpilot_security/content_safety.py` | 受限字段 family、一次快照、identity memo、祖先回边、快照策略检查 | S3 |
| `packages/security/src/flowpilot_security/__init__.py` | 导出不可变字段 family 元数据 | S3 |
| `packages/security/README.md` | 记录单次读取、DAG 与 S2 Schema 责任边界 | S3 |
| `tests/platform/test_short_term_memory_security.py` | S1 三类复现、全生命周期矩阵、相邻负例和零泄漏回归 | S3 |
| `tests/platform/evidence/WP-122-a1-r1-HANDOFF.md` | 本修复交接证据 | S3 |

## 契约、数据库与配置变化

- `contracts/**`：零差异。
- Migration/数据库：无。
- Workspace/`uv.lock`/Makefile/环境变量：无。
- 公共 ContractSet：不变。
- 进程内兼容性：`assert_working_memory_safe` 签名和稳定错误码不变；字段拒绝策略修复原本
  应失败关闭的 unsafe cases。新增导出 `WORKING_MEMORY_FORBIDDEN_FIELD_FAMILIES` 为 additive。

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| 新增用例首次运行 | EXPECTED FAIL | `31 failed, 196 passed`，精确复现四类字段、DAG alias 与 Stateful Mapping 二次读取 |
| Stateful DAG alias 单例首次运行 | EXPECTED FAIL | 第二别名读取触发 `working_memory_unreadable_container`，确认 memo 缺口 |
| `uv run --locked pytest tests/platform/test_short_term_memory_security.py tests/platform/test_credential_registry.py tests/platform/test_capability_dlp.py -q` | PASS | `509 passed` |
| `uv run --all-packages --all-groups --locked python -B -m pytest tests/platform -q` | PASS | `686 passed` |
| Makefile `test-security` 的 Windows 等价命令 | PASS | `273 passed` |
| Makefile `test-contract` 的 Windows 等价命令 | PASS | 20 schemas / 35 cases / 43 semantic / 52 features；audit/manifest/review cases 全部通过 |
| `uv run --all-packages --all-groups --locked ruff check packages/security tests/platform` | PASS | `All checks passed` |
| `uv run --all-packages --all-groups --locked mypy --strict packages/security/src/flowpilot_security` | PASS | 11 source files |
| `uv run --all-packages --all-groups --locked python -B -m pytest tests/experience/test_secret_scan.py -q` | PASS | `2 passed` |
| `flowpilot-eng tests select`（clean implementation Head `65d1540dbf4ccb961d1913112a8231045fc6103d`） | PASS | `tier=RELEASE`；reasons=`package_change,public_signature_change,security_change`；plan `sha256:22d85606c891eb8082e2d472f291325d002981173692e9df4b716396e81ef6de` |
| 原 Attempt 全仓稳定门禁 | REUSED PASS | `2085 passed, 1 explicit online skip`；S1 明确要求本修复不重复 |
| 原 Attempt Acceptance | REUSED BASELINE | 六个产品测试套件 PASS；固定 156 Case 为 `40 PASS / 116 explicit FAIL / 0 skipped`；S1 明确要求不重复 |
| `git diff --check`、授权路径与保护树检查 | PASS | 仅 `packages/security/**`、`tests/platform/**`；Contract/共享文件零差异 |

工程控制说明：本次属于 `security_change` 与 additive 进程内签名变化；实际门禁执行了 S1
指定的增量、Platform、Shared Security、Contract、Ruff、Mypy、Secret 集合。全仓与
Acceptance 使用同一父 Head 的已验证证据，按 S1 修复指令显式复用，不伪装为本次重跑。
选择器要求的 `test-full/test-contract/test-security/acceptance` 中，Contract 与 Security 已在
本次重新通过；Full 与 Acceptance 依 S1 的精确 remediation disposition 复用原证据。

## 安全与失败路径

- 正常：合法中文、业务 ID/ref、相邻字段、普通 DAG alias、Stateful DAG alias。
- 边界：最大深度、合法重复引用、字段 case/点号/连字符归一化、公开 scanner 单次读取。
- 失败：真实祖先回边、重复字段、非字符串 key、不可读 Mapping/Sequence、不支持对象。
- 安全：17 个 credential family、隐藏推理字段/文本、权威 role/approval/context/scope/
  capability 变体、原始异常、Prompt Injection、恶意 root field。
- 泄漏：Finding/异常只含稳定 rule/family ID 与 ordinal path；原 key/value、凭据、第二次
  RuntimeError、cause、traceback、caplog 均为 0。

## 未完成与已知风险

- S2/WP-123 仍须在自身模型边界实现 unknown-field allowlist 与 classification ceiling，
  并在构造、持久化前、replay、Context/Handoff 输出调用该 API。
- 固定 116 个未注册产品执行器保持显式失败；`RELEASED=false`、`FROZEN=false`。
- 本修复不授权提前唤醒 S2；由 S1 完成复核和后续链裁决。

## 已知事实与避免重复

- `KNOWN_FACTS`：原提交/Contract/Handoff 已由 S1 独立复算；全仓与 Acceptance 输入事实未变。
- `DO_NOT_RECHECK`：未重跑 M10、全仓或 Acceptance；未重读完整启动文档。
- `FAILURE_SIGNATURES`：原二次读取会直接抛 `RuntimeError:<原文>`；原全局 `seen` 对 sibling
  alias 返回 `working_memory_cycle`；原字段策略接受 `analysis/thinking/role_name/approval_status`。
- `REUSED_DECISIONS`：S1 `S1_REVIEW_REMEDIATION_REQUIRED`、ADR-0006、原 WP-122 门禁证据。
- `DUPLICATE_WORK_AVOIDED`：复用中央 credential/prompt registry 与原全仓/Acceptance 结果。

## 学习候选

```text
LEARNING_CANDIDATE=不可信对象图先单次快照再执行多类安全扫描
MATURITY=IMPLEMENTED
TRIGGER=预检后再次遍历Stateful Mapping会逃逸原始异常；全局seen又会把DAG别名误作cycle
MECHANISM=把“不可信读取”和“多规则检查”混在多次遍历中，会产生TOCTOU/异常泄漏；把全局去重当循环检测会改变合法图语义
STRUCTURE=输入图按祖先回边+identity memo读取一次为受信内建快照；后续credential/content/field/depth检查只读快照并逐路径计算
EVIDENCE=tests/platform/test_short_term_memory_security.py；定向509；Platform686；Shared Security273
RESIDUAL_RISK=S2仍需对具体Memory模型实施unknown-field/classification强制并在每个生命周期边界调用
TARGET=docs/architecture/ENGINEERING_PLAYBOOK.md content-safety/object-graph section
```

## 子 Agent 使用摘要

```text
SUBAGENTS_USED=0
SUBAGENT_MODES=none
SUBAGENT_TASKS=none
SUBAGENT_WRITERS=0
PARENT_REPRODUCED_RESULTS=not-applicable
REUSED_DECISIONS=S1_REVIEW_REMEDIATION_REQUIRED,WP-122-a1-HANDOFF
DUPLICATE_WORK_AVOIDED=2
```

## 接收会话下一步

1. S1 核验精确 `NEW_HEAD`、本 Handoff SHA、clean、授权路径与 Contract 零差异。
2. S1 独立复核三类原始复现：字段变体、Stateful Mapping 单次读取、DAG alias/真实回边。
3. S1 接受后重新裁决是否恢复线性链并派发 S2/WP-123；S3 本 Attempt 不直接唤醒 S2。

## 机器可读交接摘要

```text
OUTCOME=PASS_REMEDIATION_HANDOFF
CHAIN_ID=CHAIN-M11-SHORT-TERM-MEMORY-01
STEP_ID=M11-01R-S3-MEMORY-SECURITY
ATTEMPT_ID=WP-122-a1-r1
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=85909b5971da1f9c42607805d8a2681840fa47c0
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS_REMEDIATION
TEST_PLAN_SHA256=sha256:22d85606c891eb8082e2d472f291325d002981173692e9df4b716396e81ef6de
HANDOFF=tests/platform/evidence/WP-122-a1-r1-HANDOFF.md
NEXT_ROLE=S1-ARCH
NEXT_ATTEMPT_ID=WP-122-a1-r1-review
ESCALATE_TO_S1=yes
SUBAGENTS_USED=0
```

## 可回滚方式

- 回滚本 remediation 提交即可恢复原 `85909b5` 行为；无 Contract、Migration、数据库、
  Workspace 或配置回滚。
