# WP-115-r2-platform S3-PLATFORM Handoff

## 基本信息

- Chain / Step：`CHAIN-M10-KNOWLEDGE-01` / `M10-05R4-S3-KNOWLEDGE-MCP-RESUME`
- Work Package / Attempt：`WP-115-R2` / `WP-115-r2-platform`
- 角色 / 下一角色：`S3-PLATFORM` / `S5-CORE`
- 执行：`ORDERED / RESUME_AFTER_CONSUMER_ACCEPT`，风险 `R2`
- 输入 Head：`7422e8f831f5488f6fb1e25ef2f4b7011e5c116f`
- ContractSet：`sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 上游 Handoff：`tests/acceptance/m10/evidence/WP-115-r2-quality-HANDOFF.md`
- 上游 Handoff SHA-256：
  `sha256:f3185d6444868a92e39e51f1469da6f834998a1869ec2fbc8d726d5f52f6eb9b`
- 结果：`PASS_HANDOFF`；不代表 M10、Feature、`RELEASED` 或 `FROZEN`

## 消费者门禁与 P1 修复复用

- S3 恢复前 Head 为 `629571c97631e31cab0c5a1eed241ce4f51ab3e0`，分支与角色
  匹配、工作树 clean，且是输入 Head 的祖先。
- 对输入 Head 中 Handoff 原始 Git Blob 复算 SHA-256，ContractSet digest 匹配；
  `629571c..7422e8f` 的 `contracts/**` 差异为 0。
- 只执行 `git merge --ff-only 7422e8f831f5488f6fb1e25ef2f4b7011e5c116f`，精确消费
  S5/S6/S4 线性修复。
- 复用 S5 的 Application Port v2、S6 exact-version/RLS Projection、S4 强制 Action
  ceiling 与 51 条 Retrieval 证据；未重复运行 PostgreSQL、Migration、Compose 或 Owner
  全套测试。

## 完成内容

- 新增 `RetrievalKnowledgeMcpAdapter`，以 `HybridRetrievalEngine` 为唯一排序、阈值、
  去重与引用复验实现；Knowledge MCP 不复制排序逻辑，也不直连数据库或正文存储。
- 新增兼容的内部 `TrustedContextToolAdapter`。Gateway 仅在完成 SecurityContext Source
  resolve、完整性验证、Tool Registry、双主体、Policy 与 Capability 绑定后，将可信
  `SecurityContextRef` 传入实现该 Port 的 Adapter；现有 ToolAdapter/SecretAdapter 行为不变。
- M10 Adapter 的普通 `invoke` 永远失败关闭，禁止调用方只凭 Capability 绕过可信 Context。
- 在 Retrieval 前精确复验 capability use、audience、tool、scope、tenant、subject、purpose、
  context hash、Context/Capability 有效期与 Action classification ceiling；Action ceiling
  作为 `RetrievalRequest` 强制字段在候选形成前传入。
- 将可信 subject、group、role ACL 映射为强类型 `AclPrincipal`。额外 subject、未知前缀、
  空主体或伪造 ACL 均失败关闭；工作负载主体继续由 Gateway Tool Registry/身份门禁独立验证。
- 只消费 Retrieval v2 授权后 exact-version `content_excerpt`；逐项复核 tenant、Citation、
  opaque content_ref、Hash、classification、数量与重复项，再运行集中 Secret/DLP/
  Prompt-Injection 检查。
- 通过安全检查后才将 excerpt 映射为固定 Tool Schema 的 `redacted_summary`。输出不包含
  internal content_ref、ACL、分数、候选、向量或 Retrieval diagnostics。
- 新增稳定错误码：
  `PLATFORM_KNOWLEDGE_CONTENT_REJECTED`、
  `PLATFORM_KNOWLEDGE_REFERENCE_REJECTED`、
  `PLATFORM_KNOWLEDGE_RETRIEVAL_UNAVAILABLE`；错误、事件与调试投影不复制正文或原异常。
- `knowledge.search.v1` 输入/输出 Schema 与
  `KNOWLEDGE_SCHEMA_PIN=sha256:b7679fde5be1187e8a36b4cd4dd95a95b63a50dc56532294174b0088f0e6600b`
  保持不变。

## 兼容与迁移边界

- 旧 `KnowledgeMcpAdapter` / `KnowledgeRecord` 仅为 M7～M9 已冻结的离线 Fixture 保留；
  M10 生产组合必须使用 `RetrievalKnowledgeMcpAdapter`。
- `flowpilot-mcp-knowledge` 新增 Application/Domain/Retrieval 包依赖；
  `packages/retrieval` 尚未注册根 Workspace/Lock，按单写者约束由 S5 WP-116 处理。
- 未添加 fallback、兼容默认 ceiling、降级 SecurityContext、伪造摘要或事后候选过滤。
- 公共 Contract、Tool Schema、数据库、Migration、环境变量、根 Workspace、`uv.lock`、
  Makefile 均未修改。

## 修改范围

| 路径 | 变化 | Owner |
|---|---|---|
| `apps/mcp-gateway/**` | 可信 Context Adapter 分派和 Knowledge 稳定错误映射 | S3 |
| `mcp-servers/knowledge/**` | Retrieval-backed M10 Adapter、依赖声明、版本与边界说明 | S3 |
| `tests/platform/**` | Source root、正常/边界/失败/安全测试与本证据 | S3 |

`packages/security/**`、`packages/tool-contracts/**` 无实际差异；S5/S6/S4 输入提交保持独立
祖先，S3 未修改其路径。

## 验证

| 检查 | 结果 |
|---|---|
| Knowledge MCP 定向 | PASS：`35 passed` |
| 完整 Platform | PASS：`442 passed` |
| 共享 Security | PASS：`273 passed` |
| 影响范围 Ruff | PASS：All checks passed |
| strict Mypy | PASS：Gateway + Knowledge MCP，`12 source files` |
| Contract Conformance | PASS：20 schemas / 35 cases / 43 semantic / 52 features |
| Secret Scan | PASS：`2 passed` |
| `uv build --no-sources mcp-servers/knowledge` | PASS：sdist + wheel |
| `git diff --check` | PASS |
| 根 `uv run --all-packages --all-groups --locked ...` | `DEPENDENCY_LOCK_PENDING_WP116` |

共享 Security 使用当前 M10 Worktree 的显式 Source roots，执行原权威测试集合并通过；首次
入口因主 Worktree 的旧 Domain Source 被优先导入而在收集前失败，修正 Source root 后同一
命令 `273 passed`，没有产品 Case 失败。

根 locked 入口在测试执行前拒绝：`flowpilot-retrieval` 声明为 workspace source 但尚非根
workspace member。这正是 WP-116 的既定单写者任务；S3 未修改根 `pyproject.toml` 或
`uv.lock`。独立 Source-root Platform/Security、Contract、Mypy、Ruff 和无 Source 解析的
sdist/wheel 构建均已真实通过。

构建产生的根 `dist/` 仅包含 gitignored 可重建产物；客户端策略拒绝本会话删除该目录，
它不在 Git 差异或提交范围内。S5 执行 Workspace 闭包时可在其授权流程中清理或复用。

## 安全负例

- 可信 Context 缺失、错 tenant/purpose/context hash、过期 Context/Capability、超 Context
  ceiling、错 audience/tool/use/scope：Retrieval 调用为 0。
- 额外 subject 与未知 ACL 类型：候选调用为 0。
- Secret/Prompt-Injection 查询：候选调用为 0。
- 跨租户或超分级候选、候选协议错误：引用/正文读取为 0。
- Citation version/hash/content_ref/classification 漂移：无 Tool data 输出，稳定引用拒绝。
- Secret 或 Prompt-Injection excerpt：在 MCP 输出构造前拒绝，原文不进入 ToolResult、
  Audit、Security Event 或 debug projection。
- Retrieval/数据库异常：稳定不可用码，不泄漏内部主机、SQL、正文或原异常。
- 零结果：显式返回空 records 与 `returned_count=0`，不伪造模型证据。
- 旧 Schema Pin：Gateway Registry 在 Adapter 调用前失败关闭。

## Context、复用与避免重复

- DELTA 读取当前 Chain、WP-115、Session Contract、M10 Architecture、WP-114 与 P1 修复
  Handoff，以及直接相关 Gateway/MCP/Retrieval/Application/Persistence Port。
- `KNOWN_FACTS`：WP-114 排序与引用验证、S5 v2 授权顺序、S6 RLS exact-version read、
  S4 51 条 ceiling/excerpt 测试和 Contract digest 均未变化，直接复用。
- `DO_NOT_RECHECK`：未重跑 M7～M9、真实 PostgreSQL、Migration、Compose、完整仓库、
  在线 Provider 或 S4 51 条目标套件。
- `DUPLICATE_WORK_AVOIDED`：未复制 Retrieval 排序、未复制 DLP registry、未新增正文 Port、
  未修改公共 Tool Schema。

## 学习候选

```text
LEARNING_CANDIDATE=安全衰减值和正文必须沿不同阶段的强类型链传递
MATURITY=VERIFIED
TRIGGER=Gateway Action ceiling 比 SecurityContext 更严格，且 Tool Schema 需要授权后摘要
MECHANISM=复用原 Context 会扩大候选 ceiling；伪造降级 Context 会破坏 context_hash；Citation 元数据不能证明随后正文仍是同一版本
STRUCTURE=独立 mandatory action ceiling 在候选前传递；authorization 后 exact-version Projection 全字段复验；excerpt repr=False；最终由 S3 集中内容安全后映射公开摘要
EVIDENCE=S5/S6/S4 remediation Handoffs + S3 Platform 442 passed / shared Security 273 passed
RESIDUAL_RISK=根 Workspace/Lock 尚待 WP-116 注册并复算 locked 门禁
TARGET=ENGINEERING_PLAYBOOK trusted retrieval boundary candidate
```

## 子 Agent 使用摘要

```text
SUBAGENTS_USED=0
SUBAGENT_MODES=none
SUBAGENT_TASKS=none
SUBAGENT_WRITERS=0
PARENT_REPRODUCED_RESULTS=not-applicable
REUSED_DECISIONS=S5-v2-ceiling;S6-exact-projection;S4-retrieval-hit
DUPLICATE_WORK_AVOIDED=4
```

## 接收会话下一步

1. S5 WP-116 消费本精确 Head 与 Handoff，按 DELTA 读取 WP-116，不重跑 S3/S4/S6 Owner
   套件。
2. 由 S5 单写根 Workspace/Lock/Makefile，注册 `flowpilot-retrieval` 并更新
   `flowpilot-mcp-knowledge` 依赖闭包；不得删除安全 Port 或改回兼容默认 ceiling。
3. 在 API/composition 层装配真实 QueryService、PostgreSQL Candidate/Projection、
   HybridRetrievalEngine、RetrievalKnowledgeMcpAdapter 与 Gateway，不让 API/模型直传
   SecurityContext、Capability、ACL 或 content_ref。
4. locked 闭包与组合门禁 PASS 后按链唤醒 S2 WP-117；P0/P1、Contract、跨 Owner 或门禁
   失败才回报 S1。

## 机器可读摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M10-KNOWLEDGE-01
STEP_ID=M10-05R4-S3-KNOWLEDGE-MCP-RESUME
WORK_PACKAGE=WP-115-R2
ATTEMPT_ID=WP-115-r2-platform
INPUT_HEAD=7422e8f831f5488f6fb1e25ef2f4b7011e5c116f
NEW_HEAD=<this-handoff-commit>
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
KNOWLEDGE_SCHEMA_PIN=sha256:b7679fde5be1187e8a36b4cd4dd95a95b63a50dc56532294174b0088f0e6600b
GATE=PASS_WITH_DEPENDENCY_LOCK_PENDING_WP116
ROOT_LOCK_STATUS=DEPENDENCY_LOCK_PENDING_WP116
HANDOFF=tests/platform/evidence/WP-115-r2-platform-HANDOFF.md
NEXT_ROLE=S5-CORE
NEXT_ATTEMPT_ID=WP-116-a1
ESCALATE_TO_S1=no
SUBAGENTS_USED=0
USER_INPUT_REQUIRED=none
```

## 可回滚方式

- 由 S1 以新增反向提交回滚本 S3 提交；禁止 reset/rebase/force-push。回滚不会改变公共
  Contract，但会移除 M10 Retrieval-backed MCP/Gateway 可信 Context 组合。
