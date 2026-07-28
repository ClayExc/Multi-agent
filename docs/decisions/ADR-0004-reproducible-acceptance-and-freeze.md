# ADR-0004：可复现验收、稳定冻结证明与审计哈希链

- 状态：Accepted
- 日期：2026-07-28

## 背景

仅保存文件名、自由文本证据或整份可变清单的 SHA-256，无法证明三件事：

1. S2、S3、S4、S5、S6 审查的是同一份不可变契约内容。
2. 120 条功能用例、36 条安全/故障用例及其分母没有被静默删减。
3. Feature 状态、工具写回读和 Audit 完整性对应真实且可复算的证据。

`contract-set.v1.json` 的生命周期字段会在评审后变化。如果评审绑定整文件哈希，写入评审结论会立刻生成一个未被评审的新哈希，形成冻结悖论。

## 决策

### 1. 契约内容摘要与评审证明

`contract-set.v1.json` 使用：

```text
digest_profile = flowpilot.contract-set-content-rfc8785-sha256-v1
content_digest = sha256(RFC8785(P))
```

其中不可变投影 `P` 仅包含：

```text
$schema
contract_set_id
version
digest_profile
owner
published_on
supersedes
required_reviewers
freeze_requirements
schemas
artifacts
release_dependencies
```

明确排除 `content_digest`、`status`、`reviews` 和 `frozen_at`。数组顺序属于内容；重排也会改变摘要。

每条非 `PENDING` Review 必须保存 `reviewed_content_digest`、时间、证据路径和证据哈希。修改投影中的任何字段都必须计算新摘要并把五条 Review 重置为 `PENDING`。只有 S2、S3、S4、S5、S6 对同一摘要全部返回 `ACCEPT`，且所有发布依赖实际为 `frozen`，契约集才能冻结。

五条 Review 对同一 `candidate` 摘要全部 `ACCEPT` 后，该摘要可成为实现基线；S2/S3/S4/S5/S6 可以在独立 Worktree 开始编码。发布级 `frozen` 仍要等待 Registry、Dataset、Fixture 与 Traceability 完成，避免“实现必须等数据集冻结、数据集实现又必须等契约冻结”的循环依赖。

### 2. 可移植字节

所有被原始字节 SHA-256 覆盖的文件必须：

- UTF-8、无 BOM。
- LF 换行。
- JSON 不含重复键。

`.gitattributes` 固定文本 EOL；Conformance Gate 同时检查字节，不能只依赖 Git 配置。

### 3. 评测数据与分母

- `EvaluationDatasetManifest v1` 以文件哈希列出所有 EvaluationCase。
- `EvaluationFixtureManifest v1` 以哈希固定合成租户和主体 Fixture；不得包含真实 PII 或凭据。
- 每个 EvaluationCase 同时绑定 Dataset、Fixture 和 Evaluation Registry 的 ID、版本和 SHA-256。
- Evaluation Registry 的 `suite_policies` 固定类别配额、类别必需确定性断言和分母规则。
- M0 功能集固定 120 条，安全/故障集固定 36 条。
- `passed` 计成功；`failed`、`skipped`、`quarantined` 均计失败并保留在 `all_declared_cases` 分母中。
- 安全类别必须包含对应 tenant、approval、security、tool 或 observability 确定性 Gate；仅配置语义 Judge 或 flow 断言无效。

Dataset 为 `candidate` 时可以没有 Case 文件，表示设计尚未实现；不得因此宣称 120/36 已完成。变为 `frozen` 时，数量、分类、文件、哈希和 Case 内字段必须全部一致。

### 4. Feature 状态证据

`valid_evidence_refs` 使用结构化对象，至少绑定：

- `evidence_id`
- `test_id`
- `artifact_path`
- `artifact_hash`
- `run_id`
- `produced_at`
- `verifier_role`

测试和证据 ID 必须带父 Feature 段；实现责任人与验证责任人必须不同。`VERIFIED`/`RELEASED` 必须有已声明、存在、哈希匹配且由验证责任角色产生的证据。任意字符串、缺失文件或跨 Feature 引用都不能推动状态。

### 5. Audit 哈希链

Audit v1 的前像固定为：

```text
{
  "profile": "flowpilot.audit-chain.v1",
  "event": <AuditEvent 深拷贝后仅删除 integrity.event_hash>
}
```

`event_hash = sha256(RFC8785(preimage))`。`stream_id`、`sequence`、`previous_hash`、`canonicalization` 和存在时的 `signature_ref` 全部进入前像。

Audit Store 必须按可信 Stream 注册表验证：

- 全局 `event_id` 唯一。
- `(stream_id, sequence)` 唯一。
- Stream 与 Tenant 固定绑定。
- 首事件为 `sequence=1` 且 `previous_hash=null`。
- 后续序号连续且 `previous_hash` 等于同流上一条已重算的 `event_hash`。
- 每条事件重新计算哈希。

链头行锁或等价原子机制负责并发追加；数据库设置 `UNIQUE(stream_id, sequence)`。哈希链证明篡改，不单独防止整链重写或截断；生产环境还需受保护的签名或外部链头锚。

## 后果

正面：

- 评审、数据集、Fixture、Feature 和 Audit 都可跨会话、跨平台复算。
- 生命周期字段可变化而不破坏已审查内容身份。
- 跳过、隔离或自由文本证据不能美化指标或伪造状态。

代价：

- 冻结前必须生成更多清单和哈希。
- Judge Prompt、输出 Schema 和校准策略在 Registry 冻结时必须成为可解析的仓库引用。
- 实现阶段需要完整 RFC 8785 库；架构期 Conformance 只接受无浮点的 I-JSON 子集并显式拒绝超范围值。

## 验证

- `FP-EVAL-001`
- `FP-EVAL-002`
- `FP-EVAL-003`
- `FP-EVAL-004`
- `FP-OBS-003`
- `FP-OPS-002`
