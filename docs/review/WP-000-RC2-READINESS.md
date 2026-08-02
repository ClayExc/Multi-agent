# WP-000 rc2 集成就绪报告

> 历史报告：本文件记录 `0a82…` 实现基线。当前候选及旧审签失效处置见
> [`WP-000-RC2-REVIEW-1CAD07BD.md`](./WP-000-RC2-REVIEW-1CAD07BD.md)。

## 1. 当前裁决

- 裁决角色：`S1-ARCH`
- 候选：`flowpilot-m0-contracts-v1-rc2`
- 版本：`1.0.0-rc.2`
- 稳定内容摘要：`sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`
- 当前状态：`candidate`
- 五角色 Review Attestation：`5/5 ACCEPT`
- 实现基线状态：`ACTIVE_ON_COMMIT`
- 功能状态：52 项全部保持 `DESIGNED`

S2、S3、S4、S5、S6 已对上述同一内容摘要分别返回 `ACCEPT`，五份 Evidence 已落盘并写入 ContractSet Review Attestation，完整 Conformance Gate 复跑通过。该 candidate 已完成实现基线评审证明；写实现仍须等待包含这些证明的 Git 激活提交及独立 Worktree。发布级 `frozen` 还要等待质量资产完成。

## 2. 正式复审处置

上一摘要 `sha256:babf5689a720b66bb2dfa3f195caf729949f143d830493098446fe9f6c824d94` 的正式结论为：

| 角色 | 结论 | Gate | 处置 |
|---|---|---|---|
| S2-RUNTIME | `ACCEPT` | `PASS` | 结论仅绑定旧摘要，不迁移 |
| S3-PLATFORM | `REJECT` | `PASS` | 接受 `S3-RC2-001`；修正 Approval Tool Schema Hash 与跨对象绑定门禁 |
| S4-QUALITY | `ACCEPT` | `PASS` | 结论仅绑定旧摘要，不迁移 |
| S5-CORE | `ACCEPT` | `PASS` | 结论仅绑定旧摘要，不迁移 |
| S6-DATA | `ACCEPT` | `PASS` | 结论仅绑定旧摘要，不迁移 |

S3 的阻断成立；详细证据见 `docs/review/WP-000-RC2-REVIEW-BABF5689.md`。由于官方 Fixture、语义门禁和 Artifact Hash 已改变，五份旧结论均不能计入当前摘要。ContractSet 的五条 Review Attestation 保持 `PENDING`，五个实现角色必须重新返回绑定当前摘要的结论。

## 3. rc2 阻断处置

### S2-RUNTIME

- Context 各层分类与 Context/Security ceiling 确定性比较。
- `SecurityContextRef.data_classification_ceiling` 现为必填；校验器不再以 `get()` 静默跳过安全分类上限，缺失字段具有独立 Schema 负例。
- Context 估算/实际输入 Token 同时受 Context Policy 和 AgentRunRequest 上限约束。
- TaskCommand 正例使用可重算的 RFC 8785 摘要；错误摘要以及命令与 SecurityContext 的租户、主体 ID、主体类型、创建用途错配均由语义负例拒绝。
- ToolResult 的请求、策略与操作类型回绑原 ToolRequest/PlannedAction。
- 语义负例必须从无错误的合法基线变异，防止“基线已错”的假阴性。

### S3-PLATFORM

- `approved` 同时要求 `approver_id != requester_id`，不能只声明 SoD 布尔值。
- PolicyDecision 显式保存并绑定 `subject_context_hash`。
- 写入 `verified` 必须有非空业务数据、证据引用、观察引用和权威匹配回读。
- Audit 哈希前像、可信 Stream/Tenant、序号连续性和前序哈希成为可执行链门禁。
- Approval 的 Tool Schema Hash 必须等于 PlannedAction Tool Schema Hash；官方正例现已对齐。
- Approval、PlannedAction、PolicyDecision 的策略版本和过期时间必须一致，并具有独立错配负例。

### S4-QUALITY

- EvaluationCase 绑定 Dataset、Fixture、Registry 的 ID/版本/哈希。
- Registry 固定 120/36 类别配额、不可缩减分母和类别必需确定性 Gate。
- 重复 Assertion、终态矛盾、工具允许/禁止交集均有语义负例。
- Feature 证据结构化绑定声明 ID、文件、哈希、Run、时间和独立验证角色。
- ContractSet 使用稳定 `content_digest`；Review 绑定摘要，解决写入评审状态后的哈希悖论。
- Frozen Registry 必须具有可解析且哈希固定的 Judge Prompt；Dataset、Fixture、Traceability 与 ContractSet 同步冻结。

### S5-CORE / S6-DATA 职责拆分

- 新增 S5-CORE，单写 Domain、Application、API、IT Service Domain Pack 与 Python Workspace；S2 仅实现 Execution Port，不复制领域对象。
- 新增 S6-DATA，单写 Persistence、Migration、RLS、Inbox/Outbox、执行账本与 Infra；S3 通过 Persistence Port 使用账本，不自建第二套存储。
- S2 收窄为 Graph、Agent Runtime、Model Gateway、Context 与 Worker；S3 收窄为 MCP Gateway、Tool Contracts、Policy、Security 与 MCP Servers。
- Feature Traceability 的实现责任和测试路径已迁到 `tests/core`、`tests/data`；ContractSet 的必需评审者和 Schema 门禁扩展到 S2～S6。
- `WORKFLOW.md` 把工作项、Git、交接与证据定义为事实源，规定任务状态、最多三个并行写会话、失败恢复和人工集成门禁。

## 4. 可重复性规则

- 被哈希文件为 UTF-8 无 BOM、LF 换行；`.gitattributes` 固定跨平台 EOL。
- JSON 解析拒绝重复键。
- 原始文件 SHA-256 与 ContractSet 内容摘要分别验证。
- ContractSet 摘要投影排除 `status/reviews/frozen_at/content_digest`，生命周期变化不改变已评内容身份。
- RFC 8785 架构期门禁使用无浮点 I-JSON 子集；浮点和超安全范围整数显式拒绝，生产实现必须使用完整合规库。

## 5. 已运行验证

命令：

```text
E:\workspace\personal-kb-qa-system\.venv\Scripts\python.exe -B contracts/conformance/validate.py
```

结果：

```text
CONTRACT_CONFORMANCE_OK schemas=20 cases=35 positive=18 negative=17 mutation_cases=19 mutation_positive=3 mutation_negative=16 semantic_cases=43 semantic_positive=0 semantic_negative=43 audit_chain_cases=5 audit_chain_positive=1 audit_chain_negative=4 manifest_cases=21 manifest_positive=1 manifest_negative=20 features=52
```

覆盖：

- 20 个 Draft 2020-12 Schema 与 `$ref`。
- 清单 SHA-256、稳定内容摘要、发布依赖和便携字节。
- 35 个完整实例、19 个 Schema 变异、43 个跨对象语义负例。
- 两事件 Audit 正链及篡改、缺口、重复序号、跨 Stream 串链。
- 21 个 Registry/Dataset/Fixture/Traceability/ContractSet 清单用例。

`make test-contract` 仍未实现；上述底层命令是 WP-000 契约候选门禁，不冒充实现阶段完整工程测试。

## 6. 未完成条件

1. `[DONE]` S2-RUNTIME 对同一 `content_digest` 返回 `ACCEPT`。
2. `[DONE]` S3-PLATFORM 对同一 `content_digest` 返回 `ACCEPT`。
3. `[DONE]` S4-QUALITY 对同一 `content_digest` 返回 `ACCEPT`。
4. `[DONE]` S5-CORE 对同一 `content_digest` 返回 `ACCEPT`。
5. `[DONE]` S6-DATA 对同一 `content_digest` 返回 `ACCEPT`。
6. `[DONE]` S1 保存五份 Review Evidence、写入 Attestation 并复跑完整门禁。
7. `[ACTIVE_ON_COMMIT]` 包含本报告和 Attestation 的提交是激活提交；推送后从该精确 SHA 创建独立 Worktree。
8. `[PENDING]` 后续发布冻结轮次先把 Registry、Dataset、Fixture、Traceability 本身切换为 `frozen`，重新生成内容摘要并再次进行精确候选评审。

因此，包含本报告的 Git 提交可以使用“rc2 实现基线已激活”，不能使用“契约已冻结”。
