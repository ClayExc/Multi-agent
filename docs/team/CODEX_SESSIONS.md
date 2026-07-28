# FlowPilot 六 Codex 会话协作设计

## 1. 设计目标

FlowPilot 使用六个长期存在、用户可分别继续对话的顶层 Codex 会话。角色负责稳定的能力和路径，实际执行围绕 Work Package、Git Worktree、分支和证据包组织。

这与 OpenAI Symphony 的核心思路一致：从“管理聊天会话”转向“管理待完成工作”。FlowPilot 当前先采用人工控制面，后续可把 GitHub Issues/Projects 接成任务控制面。

```mermaid
flowchart LR
    S1["S1-ARCH<br/>架构/契约/验收/集成"]
    S5["S5-CORE<br/>Domain/Application/API/Workspace"]
    S2["S2-RUNTIME<br/>Graph/Runtime/Context/Worker"]
    S6["S6-DATA<br/>Persistence/Migration/Infra"]
    S3["S3-PLATFORM<br/>MCP/Policy/Security"]
    S4["S4-QUALITY<br/>Experience/Evals/Observability"]

    S1 -->|"公共契约与完成定义"| S2
    S1 -->|"公共契约与完成定义"| S3
    S1 -->|"公共契约与完成定义"| S4
    S1 -->|"公共契约与完成定义"| S5
    S1 -->|"公共契约与完成定义"| S6
    S5 -->|"Application/Execution Port"| S2
    S5 -->|"Repository/UoW Port"| S6
    S2 -->|"ToolRequest"| S3
    S2 -->|"Checkpoint/Lease 需求"| S6
    S3 -->|"Ledger/Idempotency Port"| S6
    S2 -->|"运行 Fixture"| S4
    S3 -->|"安全 Fixture"| S4
    S5 -->|"API/Domain Fixture"| S4
    S6 -->|"RLS/恢复 Fixture"| S4
    S4 -->|"失败证据与回归报告"| S1
```

当前会话是 `S1-ARCH`。所有会话必须先声明 `SESSION_ROLE`，再读取自己的 Session Contract 和 Work Package。

## 2. 六个角色

| 会话 | 定位 | 独占产物 | 当前工作包 |
|---|---|---|---|
| S1-ARCH | 架构、契约、验收与集成 | README、Structure、Schema、ADR、追踪、工作包、发布裁决 | WP-000 |
| S2-RUNTIME | Agent 流程与运行时 | Worker、LangGraph、Agent Runtime、Model Gateway、Context | WP-010 |
| S3-PLATFORM | MCP、安全与策略执行 | MCP Gateway、Tool Contracts、Policy、Security、MCP Servers | WP-020 |
| S4-QUALITY | 产品体验与质量证明 | Web、Retrieval、Observability、Evaluation、Evals、Acceptance | WP-030 |
| S5-CORE | 领域、应用与 API 核心 | API、Domain、Application、Domain Pack、Python Workspace | WP-011 |
| S6-DATA | 数据可靠性与基础设施 | Persistence、Migration、RLS、Inbox/Outbox、Infra | WP-021 |

路径所有权以根目录 `AGENTS.md` 为唯一总规则；Session Contract 和 Work Package 只能进一步收紧。

## 3. 会话与工作的分离

六个会话是能力所有者，不是任务状态机。任务状态属于 Work Package 或 Issue：

```text
BACKLOG
  → READY
  → IN_PROGRESS
  → REVIEW
  → HANDOFF
  → ACCEPTED
  → MERGED
```

异常状态：

```text
BLOCKED  外部依赖或需要新授权
FAILED   自动门禁失败，允许同一工作包修复后重试
CANCELLED 由用户或 S1 明确终止
```

规则：

1. 一个 Work Package 只绑定一个责任会话、一个分支和一个 Worktree。
2. 一个会话同一时间只允许一个写工作包处于 `IN_PROGRESS`。
3. 会话发现范围外问题时提交 RFC/后续 Issue，不顺手扩大当前工作包。
4. `HANDOFF` 不等于完成；只有责任会话自测、跨角色复核和 S1 集成后才可 `ACCEPTED`。
5. 聊天窗口关闭不改变工作状态；状态由仓库工作包、Git 和证据决定。

## 4. 当前激活门禁

仓库已经初始化 Git 并绑定远端。摘要 `sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc` 已取得五角色 `ACCEPT`，Review Evidence、Attestation 和完整门禁均已完成；包含本状态的提交即为 Git 激活提交。

激活进度：

1. `[DONE]` S2、S3、S4、S5、S6 对同一 RC2 `content_digest` 全部返回 `ACCEPT`。
2. `[DONE]` 保存五份 Review Evidence。
3. `[DONE]` 写入 ContractSet Review Attestation。
4. `[DONE]` 运行完整 Contract Conformance Gate。
5. `[ACTIVE_ON_COMMIT]` 创建并推送包含本状态的实现基线激活提交。
6. `[PENDING]` 按依赖从该提交建立对应写 Worktree；首批仅 S5 与 S4。

发布级 `frozen` 仍等待 Registry、Dataset、Fixture 和 Traceability 完成，不前置阻塞实现。

## 5. Worktree 与分支

建议目录和分支：

| 会话 | Worktree | 分支 |
|---|---|---|
| S2 | `E:\workspace\Multi-agent-s2` | `codex/s2/wp-010-runtime-bootstrap` |
| S3 | `E:\workspace\Multi-agent-s3` | `codex/s3/wp-020-platform-bootstrap` |
| S4 | `E:\workspace\Multi-agent-s4` | `codex/s4/wp-030-quality-bootstrap` |
| S5 | `E:\workspace\Multi-agent-s5` | `codex/s5/wp-011-core-bootstrap` |
| S6 | `E:\workspace\Multi-agent-s6` | `codex/s6/wp-021-data-bootstrap` |

S1 留在主 Worktree。禁止两个会话使用同一 Worktree，禁止同一分支同时签出到多个 Worktree。

## 6. 并发容量

六个会话不等于五个实现会话必须同时写代码。人工协调阶段同时写入上限为 3：

1. 第一波：S5/WP-011；S4/WP-030 可并行建设离线评测与证据骨架。
2. S1 接受 `WP-011-H1`（Python Workspace、Application/Repository Port）交接后，启动 S2/WP-010 与 S6/WP-021；若 S4 仍写入，此时正好三个并行写会话。
3. S6 交付执行账本 Port 且 S5 Workspace 可用后启动 S3/WP-020。
4. S4 在前置切片可运行后接入跨组件验收，S1 执行集成裁决。

若某会话等待依赖，它可以只读审查、补测试设计或准备 RFC，不能绕过依赖私自修改共享文件。

## 7. RACI

| 事项 | S1 | S2 | S3 | S4 | S5 | S6 |
|---|---|---|---|---|---|---|
| 公共 Schema/ADR | A/R | C | C | C | C | C |
| Domain/Application/API | A | C | C | C | R | C |
| LangGraph/Runtime/Context | A | R | C | C | C | C |
| MCP Gateway/Policy/Security | A | C | R | C | C | C |
| Persistence/RLS/Migration/Infra | A | C | C | C | C | R |
| Evaluation/Judge/Observability/Web | A | C | C | R | C | C |
| Python Workspace/公共依赖 | A | C | C | C | R | C |
| Compose/环境变量/部署依赖 | A | C | C | C | C | R |
| 功能状态与发布裁决 | A/R | C | C | C | C | C |

`A` 为最终负责，`R` 为实施负责，`C` 为必须咨询。

## 8. 共享文件单写者

| 文件 | 默认写入者 |
|---|---|
| `pyproject.toml`、`uv.lock`、`Makefile` | S5-CORE / WP-011 |
| `.env.example`、根级 Compose/Docker/部署配置 | S6-DATA / WP-021 |
| `scripts/acceptance/**` | S4-QUALITY / WP-030 |
| `contracts/**`、架构/验收/团队文档 | S1-ARCH |

共享文件需要其他角色修改时，先由当前单写者合并或建立独立共享文件工作包。

## 9. 交接与证据

每个 Work Package 的交接必须使用 `docs/team/HANDOFF_TEMPLATE.md`，至少包含：

- Work Package、Feature ID、分支、基线提交与 ContractSet 摘要。
- 完成/未完成内容和修改路径。
- 实际运行命令、退出码及失败项。
- 正常、边界、失败、安全、恢复测试。
- Schema、数据库、依赖和环境变化。
- Evidence 路径与 SHA-256。
- 下一接收会话及其明确动作。

建议 Proof of Work 包含 CI、跨角色 Review、复杂度变化和 UI/多模态功能的可复现演示。

## 10. 审查矩阵

- S2 Graph/State：S1 或 S4 复核；与领域 Port 的绑定由 S5 复核。
- S3 授权/审批/凭据/工具写路径：S1 复核，S4 增加黑盒负向测试，S6 复核账本 Port。
- S4 Judge/指标/报告：S1 复核。
- S5 Domain/Command/API：S1 或 S2 复核，S4 验证外部行为。
- S6 RLS/事务/Inbox/Outbox/Migration：S1 复核，S3 验证安全语义，S4 增加故障测试。
- S1 Schema/ADR：对应实现会话至少一名验证可实现性。

## 11. Symphony 式后续演进

当前先人工执行六会话协议。完成 M0 后可增加 GitHub Issues/Projects 控制面：

1. Issue 字段映射 Work Package、Feature ID、Owner Role、依赖、优先级和状态。
2. 只有 `READY` 且依赖完成的 Issue 才创建隔离 Worktree。
3. Agent 失败或停滞时从 Git/Issue/Evidence 恢复，不依赖聊天上下文。
4. Agent 可以提出后续 Issue，但不能自行扩大当前 Scope 或自动批准安全变更。
5. 自动合并只对低风险、全门禁通过的路径开放；契约、安全、迁移和发布仍需人工批准。

参考：

- [OpenAI：An open-source spec for Codex orchestration: Symphony](https://openai.com/index/open-source-codex-orchestration-symphony/)
- [openai/symphony SPEC](https://github.com/openai/symphony/blob/main/SPEC.md)

## 12. 整体完成定义

- 五个实现会话只在自己的 Worktree、分支和路径内写入。
- 公共契约、依赖、共享配置和数据库变更具有单一权威。
- 正常、边界、失败、安全和恢复证据可由其他会话复现。
- 跨租户成功读写、重复逻辑写入和 Secret 泄漏均为 0。
- S1 根据证据而不是聊天声明更新 `DESIGNED/IMPLEMENTED/VERIFIED/RELEASED`。
