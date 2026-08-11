# WP-085-a1 S2-RUNTIME 身份传播与恢复重验交接

## 基本信息

- Work Package：WP-085
- Attempt ID：WP-085-a1
- Chain ID：CHAIN-M8-IDENTITY-TENANCY-01
- Step ID：M8-03A-S2-RUNTIME
- 责任会话：S2-RUNTIME
- 接收会话：S1-ARCH
- 交接策略：S1_GATE
- 功能 ID：FP-SEC-001、FP-SEC-007、FP-OPS-001
- 基线/输入提交：`e0a929cb15c213d6b65f0d03ba0bbe3742824fbb`
- 分支：`codex/s2/m8-runtime-identity`
- 最终提交：本文件所在提交；精确 SHA 由交接响应返回
- ContractSet 摘要：
  `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：PASS_HANDOFF

## 完成内容

- 新增 `SecurityContextValidationPort` 与生产
  `RuntimeSecurityContextValidator`。生产组合从 PostgreSQL
  `SecurityContextSource` 重新解析可信快照，并用 S3 `SecurityVerifier` 校验活动状态、
  有效期、Issuer/Audience、主体、租户、用途、角色/Scope 与快照 Hash；对外只返回稳定
  `GRAPH_SECURITY_BINDING_MISMATCH`，身份源临时不可用保留可重试语义。
- `RuntimeWorker` 在获取 Lease 和进入 Graph/Checkpoint 恢复前强制重验当前
  `SecurityContext`。撤销或过期 Context 不会获取 Lease，不会读取/推进 Graph，也不会
  写入新 Checkpoint。
- 企业知识问答 Graph 在恢复前、每次 Gateway 调用前、Handoff Context 重建前、模型
  调用前及模型结果/Tool Proposal 接受前重复重验。缓存命中和终态快速返回不能绕过；
  Worker 重启、Interrupt/Resume 与历史命令重投均重新解析当前身份。
- Gateway 调用继续只携带业务请求与 Agent Principal；用户 OIDC Token 不进入
  `GatewayCall`。MCP Transport 的 workload credential 仍由 S3 Gateway 边界独立持有，
  S2 只消费错误映射；错误 workload audience 稳定失败且模型/Artifact 调用为 0。
- Graph State、Context/Handoff、Agent Runtime 深层映射与 Model Gateway wire 统一补齐
  `access_token`、`refresh_token`、`client_secret`、`session_token`、`password`、
  `secret`、`token` 等凭据字段拒绝。State/Context/Checkpoint 仍只保存既有
  SecurityContext ref/hash/purpose 等安全投影，没有新增身份快照、角色或 Token 字段。
- 增加确定性身份 Validator Fake 和覆盖正常、撤销、过期、身份源故障、State/模型
  篡改、Handoff、模型返回、Interrupt/Resume、Worker 重启、终态历史重投、错误
  workload audience 与凭据聚合扫描的 Runtime 测试。

## 未完成与非目标

- 未修改身份签发、API/BFF 会话、Keycloak、RLS、Policy 或 S3 Gateway workload
  credential 实现；这些边界复用 WP-081～084 的已接受结构。
- 未运行 Keycloak、PostgreSQL/RLS、Compose、API、全仓或在线 Provider；在线 Smoke
  保持显式关闭，真实凭据读取和外部/付费调用均为 0。
- 新验证 Port 是必填依赖。范围外的 `packages/evaluation/m7_product.py`（S4）和
  `scripts/integration/verify_durable_recovery.py`（S7）仍需在 WP-087/WP-088 或 Join
  后分别注入当前身份 Validator；本 Attempt 未越权修改。这不会影响本次 Runtime
  门禁，但属于后续组合消费动作。

## 修改文件

| 文件/目录 | 变化 | 所有者 |
|---|---|---|
| `packages/graph/**` | 当前 SecurityContext 验证 Port；Checkpoint 凭据字段门禁 | S2-RUNTIME |
| `apps/worker/**` | 生产 Validator、Worker/Graph 重验、PostgreSQL 产品组合注入 | S2-RUNTIME |
| `packages/context/**` | Handoff 深层凭据字段拒绝 | S2-RUNTIME |
| `packages/agent-runtime/**` | Context、structured output 与 Tool Proposal 深层字段拒绝补齐 | S2-RUNTIME |
| `packages/model-gateway/**` | Provider wire 深层字段拒绝补齐 | S2-RUNTIME |
| `tests/runtime/**` | 身份 Fake、恢复/安全/产品链正负例及既有构造注入 | S2-RUNTIME |
| `tests/runtime/evidence/WP-085-a1-HANDOFF.md` | 本交接证据 | S2-RUNTIME |

## 契约、数据库与配置变化

- 公共 Contract、Schema 与 ContractSet：无变化；Conformance PASS。
- Migration、PostgreSQL/Redis Schema、Checkpoint 格式：无变化。
- `pyproject.toml`、`uv.lock`、`Makefile`、环境变量与依赖：无变化。
- 内部组合兼容性：`RuntimeWorker`、`build_durable_runtime`、
  `compose_local_product_runtime` 新增必填 `security_contexts` Port；S2 调用方已全部迁移，
  上述 S4/S7 范围外消费者留给对应后续步骤显式注入，禁止无验证默认值降级。

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| 新增身份/企业产品链定向测试 | PASS | 23 passed |
| `PYTHONPATH=. pytest -q tests/runtime` | PASS | 263 passed，1 个显式 online Provider skip |
| Ruff：全部 S2 源码与 `tests/runtime` | PASS | All checks passed |
| Mypy `--strict`：Worker、Graph、Context、Agent Runtime、Model Gateway | PASS | 44 source files，0 issues |
| `contracts/conformance/validate.py` | PASS | 20 schemas / 35 cases / 43 semantic cases / 52 features |
| `git diff --check` | PASS | 无 whitespace error |
| 变更路径高置信 Secret Scan | PASS | 0 findings / 24 个实现、测试与证据路径 |
| Contract/Migration/Infra/共享依赖差异 | PASS | 0 changes |

真实 Agent Server authority 在 Runtime 全套中 PASS。首次全套重跑时，前一条被外层
60 秒超时的 pytest 子进程仍短暂持有 `.langgraph_api`，导致并发目录断言失败；确认无
残留进程并串行复跑后，单项 1 passed、全套 263 passed/1 skipped，目录已清理。

## 安全与失败路径

- 撤销、过期、可信快照角色/Hash 不一致：稳定非重试错误，Lease/Graph/Checkpoint
  推进为 0。
- 身份源临时不可用：稳定可重试错误，不泄露底层数据库或身份错误详情。
- Interrupt 后恢复、Worker 重启、终态历史重投：当前身份必重新解析；撤销后持久化
  Checkpoint 集合与模型/Artifact 调用保持不变。
- Handoff 与模型结果边界分别独立重验；边界间撤销时不能继续生成 Context、接受模型
  输出或写 Artifact。
- 模型伪造 tenant/role、Checkpoint 注入 Refresh/Client Secret、错误 workload
  audience 均失败关闭；State/Trace/Checkpoint/Event/Gateway 投影 Secret 扫描为 0。
- Secret/PII 检查：只使用合成标识与 Hash；真实 Token/凭据读取、日志、Checkpoint、
  Trace、模型 Context 与外部调用均为 0。

## 已知问题

- P2（Join 消费动作）：S4 evaluation 与 S7 recovery script 需显式注入新 Port；不得用
  no-op/current-command 回显作为兼容默认值。
- 本地 Studio/Runtime 确定性验证不等同于真实 IdP、生产 HA、网络或 Token 生命周期
  组合验证；这些属于 WP-087/WP-088。

## 已知事实与避免重复

- `KNOWN_FACTS`：WP-081～084 已提供严格身份快照、可信 ContextSource、workload
  identity 与 tenant-bound persistence；本 Attempt 只消费公开 Port。
- `DO_NOT_RECHECK`：未重做 S3 身份正确性、Keycloak、RLS、API、M7 或完整历史证据。
- `FAILURE_SIGNATURES`：`AGENT_SERVER_TEMP_DIR_RACE` 仅在超时残留测试进程与第二次
  Runtime 套件并发时出现；无残留进程的串行复跑稳定 PASS。
- `REUSED_DECISIONS`：ADR-0005、IDENTITY_TENANCY、WP-081～084、M7 Runtime/Studio
  与 P2 恢复证据。
- `DUPLICATE_WORK_AVOIDED`：复用 S3 `SecurityVerifier`/`SecurityContextSource`、S6
  `PostgresSecurityContextSource`、既有 Durable Checkpoint/Lease 和 S5 Application
  Port；未复制身份验证、数据库或策略逻辑。

## 学习候选

```text
LEARNING_CANDIDATE=none
MATURITY=IMPLEMENTED
TRIGGER=none
MECHANISM=none
STRUCTURE=none
EVIDENCE=none
RESIDUAL_RISK=none
TARGET=none
```

## 子 Agent 使用摘要

```text
SUBAGENTS_USED=2
SUBAGENT_MODES=READ_ONLY_PARALLEL
SUBAGENT_TASKS=wp085-runtime-ports,wp085-runtime-tests
SUBAGENT_WRITERS=0
PARENT_REPRODUCED_RESULTS=yes
REUSED_DECISIONS=WP-081..WP-084,M7-runtime,P2-recovery
DUPLICATE_WORK_AVOIDED=2
```

两个子 Agent 分别只读定位生产 Port/组合接点与独立测试矩阵；没有写文件、执行 Git、
唤醒长期任务或作出契约/发布裁决。主 Agent检查全部差异并独立复跑门禁。

## 接收会话下一步

1. S1 核对精确 `NEW_HEAD`、本文件 SHA256、ContractSet、基线祖先、授权路径和 clean
   状态后，在 M8 Join 3 消费 S2 与 S4 两个 Handoff。
2. WP-087 的 S4 evaluation 与 WP-088 的 S7 recovery script 分别注入生产/确定性
   `SecurityContextValidationPort`，不得回退为只相信 Command 内 SecurityContext。
3. 组合验收复算当前身份撤销、Interrupt/Resume、Worker 重启、错误 workload audience
   与 State/Trace/Checkpoint 凭据出现次数 0；普通实现无需回到 S2。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M8-IDENTITY-TENANCY-01
STEP_ID=M8-03A-S2-RUNTIME
ATTEMPT_ID=WP-085-a1
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=e0a929cb15c213d6b65f0d03ba0bbe3742824fbb
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/runtime/evidence/WP-085-a1-HANDOFF.md
NEXT_ROLE=S1-ARCH
NEXT_ATTEMPT_ID=none
ESCALATE_TO_S1=no
SUBAGENTS_USED=2
```

## 可回滚方式

- 仅按正常 Git 流程 revert 本 Attempt 提交；禁止 reset、rebase 或 force-push。
