# WP-108-a1 S4 治理安全验收交接

## 基本信息

- Work Package：WP-108
- Attempt ID：WP-108-a1
- Chain ID：CHAIN-M9-GOVERNANCE-01
- Step ID：M9-08-S4-SECURITY-ACCEPTANCE
- 责任会话：S4-QUALITY / governance-quality-builder
- 接收会话：S7-INTEGRATION
- 执行模式：ORDERED
- 风险等级：R3
- 功能 ID：FP-EVAL-002、FP-SEC-004、FP-SEC-005、FP-SEC-006、FP-MCP-006、FP-OBS-003
- 基线提交：`69505f0248d8e46e8ecac6ac579f4156355e446b`
- 分支：`codex/s4/wp-107-m9-governance-quality`
- ContractSet：`sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：PASS_HANDOFF；M9 Manifest Gate 仍为 FAIL，未声明 M9、Feature、RELEASED 或 FROZEN

## 完成内容

- 新增独立 `flowpilot.m9.governance-security` v1.0.0 executor，仅按完整 Case canonical digest 精确匹配，通过真实 `McpGateway -> Policy/Approval/Capability/DLP -> Ledger/Audit` 边界执行。
- 精确连接 9 条固定 Case：6 条 approval replay / parameter tamper / duplicate delivery，1 条 malicious MCP forged write，2 条 fault-profile 驱动的写前 DLP。未形成真实产品闭环的中文 Prompt Injection、脱敏完成态、Audit hash-chain、RBAC/ABAC 等 Case 保持 `EXECUTOR_NOT_REGISTERED`，未用替代语料或期望回显伪装通过。
- approval replay 使用旧 Approval 对新 action digest 的实际绑定拒绝；参数篡改改变 action arguments 后重算 Policy，但不改旧 Approval；duplicate delivery 按 fault profile 执行 5 次同幂等键，逻辑写入保持 1。
- forged-write 场景由上游声称成功但 readback mismatch，结果保持 `UNKNOWN/FAILED`，不伪装为执行成功；unknown recovery 只 reconcile 一次，逻辑写入仍为 1。
- 增加独立黑盒：Policy deny、SoD role 失效、缺 Approval 绕过、Capability 单次原子消费与 replay、写前/结果后 DLP、Prompt Injection、malicious MCP、Audit/Security cross-link tamper。
- Judge 分数始终为空；安全、审批、工具实际调用、写入数、终态与 Audit 完整性全部由确定性断言决定。

## 官方固定分母结果

- 使用唯一官方 `scripts/acceptance/run_acceptance.py` 的 `collect_cases -> build_product_executors -> evaluate_case -> executor_registration` 路径逐条实测，不建立第二聚合器。
- 固定分母：156；collection errors：0。
- 实测：39 PASS / 117 explicit FAIL / 0 skipped / 0 quarantined。
- 执行状态：39 completed / 117 not_executed；满足 `completed + explicit_failed = 156`。
- Executor 计数：M7=24、M8=6、M9=9；M7/M8 identity、version、case digests、注册顺序与结果未变化。
- M9 Manifest Gate 仍为 FAIL；117 个未连接 Case 不会被吞掉、skip、quarantine 或缩分母。
- 机器 Proof：`tests/acceptance/m9/evidence/WP-108-a1-PROOF.json`，SHA-256 `25caef1b05cfee84741fc6f93ceaa0e3e4ea534750c99b8f17647b37bee5f469`。

## 修改文件

| 文件 | 变化 | 所有者/授权 |
|---|---|---|
| `packages/evaluation/m9_governance.py` | M9 executor、精确摘要注册、确定性断言与 Evidence | S4 |
| `tests/acceptance/m9/governance_security_probe.py` | 真实 Gateway 离线安全探针 | S4 |
| `tests/acceptance/m9/test_governance_security_blackbox.py` | M9 安全黑盒矩阵 | S4 |
| `tests/acceptance/evaluation/test_m9_governance_executor.py` | identity/version/digest/unique match/Proof 回归 | S4 |
| `tests/acceptance/evaluation/test_m8_identity_executor.py` | 官方 registry 实测加入 M9，保留 M7/M8 不变量 | S4 |
| `tests/acceptance/m9/evidence/WP-108-a1-PROOF.json` | 固定分母与 executor 机器证据 | S4 |
| `scripts/acceptance/run_acceptance.py` | 仅导入、注册、序列化独立 M9 executor | S1 精确共享入口扩权 |
| `tests/acceptance/m9/evidence/WP-108-a1-HANDOFF.md` | 本交接 | S4 |

## 契约、数据库与配置变化

- 公共 Contract、Dataset、Case、Fixture、Registry、Schema、ADR：无变化。
- 固定分母、skip/quarantine、唯一匹配策略和未注册失败语义：无变化。
- PostgreSQL、Migration、RLS、Redis、OPA、Secret 配置：无变化。
- M7/M8 executor identity、version、case digests、顺序和执行结果：无变化。
- `pyproject.toml`、`uv.lock`、Makefile、根共享配置：无变化。

## 验证

| 命令 | 结果 |
|---|---|
| `uv run --all-packages --all-groups --locked python -B -m pytest tests/acceptance/platform_security tests/acceptance/m9 tests/acceptance/evaluation/test_m7_product_executor.py tests/acceptance/evaluation/test_m8_identity_executor.py tests/acceptance/evaluation/test_m9_governance_executor.py tests/acceptance/observability -q` | PASS：76 passed |
| 官方 runner 固定分母 dispatch（同一 `collect/build/evaluate/registration` 实现） | PASS：156；39 completed、117 explicit_failed、0 skip、0 quarantine |
| `uv run --all-packages --all-groups --locked ruff check ...`（全部修改 Python） | PASS |
| `uv run --all-packages --all-groups --locked mypy --strict ...`（稳定产品源集合） | PASS：157 source files |
| `uv run --all-packages --all-groups --locked mypy --strict --follow-imports=skip --explicit-package-bases packages/evaluation/m9_governance.py tests/acceptance/m9/governance_security_probe.py` | PASS：2 个新增源文件 |
| `uv run --all-packages --all-groups --locked python -B -m pytest tests/experience/test_secret_scan.py -q` | PASS：2 passed；Secret Scan 0 |
| `uv run --all-packages --all-groups --locked python -B contracts/conformance/validate.py` | PASS：20 schemas、35 cases、43 semantic negatives、52 features |
| `uv run --all-packages --all-groups --locked python -B scripts/acceptance/run_acceptance.py --help` | PASS：官方入口可导入 3 个 executors |
| `git diff --check` | PASS |

## 安全与失败路径

- Policy deny、SoD、Approval 缺失/重放/参数篡改均在 Capability、Ledger 与上游写入前拒绝；对应逻辑写入为 0。
- Capability 绑定完整且单次原子消费；第二次消费稳定 `PLATFORM_CAPABILITY_REPLAY`。
- Prompt Injection 与 DLP 危险载荷不进入结果、Audit、Security Event 或 Evidence；实测危险输出计数为 0。
- malicious MCP forged success 不得覆盖 readback mismatch；最多 1 次逻辑写入，任务终态仍为 FAILED。
- Audit/Security 双向 cross-link 正例可验证，伪造 `audit_event_id` 负例稳定失败。
- 跨租户成功数为 0；WP-107 Web、WP-087 Keycloak/PostgreSQL/RLS 与 WP-106 OPA/PostgreSQL/Migration/Secret 证据按未变 Hash 复用。

## 未完成、非目标与风险

- 117 条固定 Case 尚未连接产品执行器，M9 Manifest Gate 必须保持 FAIL；S7 不得据此声明 Release。
- 中文 Prompt Injection 输入当前没有与固定 Case 精确语料一致的产品探针；本 Attempt 只做独立黑盒，不注册这些 Case。
- `dlp_redact_not_echo` 尚无“读取含 Secret 后安全脱敏并保持 COMPLETED”的真实产品闭环；继续明确失败。
- `audit_tamper` 固定 Case 要求 hash-chain 不一致阻断后续写入，当前只有双事件 cross-link 校验，不能冒充完成。
- Keycloak/PostgreSQL/RLS、OPA/PostgreSQL/Migration/Secret preflight 使用 WP-087/WP-106 已有证据，本 Attempt 未运行 Compose、实库、全仓或在线 Provider。
- 官方 runner 的六类广域 pytest 阶段未运行，避免违反 WP-108 的“定向、不跑全仓”约束；固定分母聚合路径已逐条执行并保存 Proof。
- 未发现新增 P0/P1；公共契约、数据和共享根边界未变化。

## 已知事实与避免重复

```text
KNOWN_FACTS=M7=24,M8=6,Contract unchanged,WP107/WP087/WP106 evidence hashes unchanged
DO_NOT_RECHECK=M0-M8 internals,Keycloak/PostgreSQL/RLS,OPA/Migration/Secret preflight,Compose,online Provider,full repository
FAILURE_SIGNATURES=117 cases remain EXECUTOR_NOT_REGISTERED by design
REUSED_DECISIONS=WP-087,WP-106,WP-107
DUPLICATE_WORK_AVOIDED=owner unit gates,real DB/OPA/Keycloak,Compose,full-repo,online-provider
```

## 子 Agent 使用摘要

```text
SUBAGENTS_USED=0
SUBAGENT_MODES=none
SUBAGENT_TASKS=none
SUBAGENT_WRITERS=0
PARENT_REPRODUCED_RESULTS=not-applicable
REUSED_DECISIONS=WP-087,WP-106,WP-107
DUPLICATE_WORK_AVOIDED=6
```

## 学习候选

```text
LEARNING_CANDIDATE=fixed-case executor must preserve exact fault semantics
MATURITY=VERIFIED
TRIGGER=fault category appeared implementable through a nearby scanner but exact case payload/product path did not close
MECHANISM=registering a surrogate payload would turn a product gap into a false fixed-case PASS
STRUCTURE=pin full canonical digest, map only fault profiles that have a concrete real product observation, leave all surrogate-only cases explicitly unregistered
EVIDENCE=packages/evaluation/m9_governance.py;tests/acceptance/evaluation/test_m9_governance_executor.py
RESIDUAL_RISK=remaining Chinese prompt, redaction-completed and audit-chain cases require owner product work
TARGET=docs/architecture/ENGINEERING_PLAYBOOK.md acceptance executor guidance
```

## 接收会话下一步

1. S7 只以 `--ff-only` 精确消费最终 Head，复算 Handoff/Proof Hash、Contract digest、授权路径与 clean。
2. 独立复算唯一 registry 的 156/39/117/0/0、M7/M8 不变量、M9 9 条 exact digest 和危险输出/跨租户成功均为 0。
3. 组合验证不得将 WP-108 PASS 外推为 M9 Manifest PASS、Feature 状态提升、RELEASED 或 FROZEN；完成后交回 S1。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M9-GOVERNANCE-01
STEP_ID=M9-08-S4-SECURITY-ACCEPTANCE
WORK_PACKAGE=WP-108
ATTEMPT_ID=WP-108-a1
BASE_COMMIT=69505f0248d8e46e8ecac6ac579f4156355e446b
NEW_HEAD=<this-handoff-commit>
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
HANDOFF=tests/acceptance/m9/evidence/WP-108-a1-HANDOFF.md
PROOF=tests/acceptance/m9/evidence/WP-108-a1-PROOF.json
FIXED_DENOMINATOR=156
COMPLETED=39
EXPLICIT_FAILED=117
SKIPPED=0
QUARANTINED=0
M9_MANIFEST_GATE=FAIL
WP108_GATE=PASS
RELEASE_CLAIMED=false
CONTRACT_CHANGED=no
DATABASE_CHANGED=no
SHARED_RUNNER_SCOPE=scripts/acceptance/run_acceptance.py import/register/serialize only
NEXT_ROLE=S7-INTEGRATION
NEXT_ATTEMPT_ID=WP-109-a1
ESCALATE_TO_S1=no
SUBAGENTS_USED=0
```

## 可回滚方式

- 回滚本 Attempt 单提交即可移除 M9 executor、官方 registry 单文件注册、测试与证据；M7/M8 及固定 Dataset/Case 不受影响。
