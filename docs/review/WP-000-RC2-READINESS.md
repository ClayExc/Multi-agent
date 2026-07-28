# WP-000 rc2 集成就绪报告

## 1. 当前裁决

- 裁决角色：`S1-ARCH`
- 候选：`flowpilot-m0-contracts-v1-rc2`
- 版本：`1.0.0-rc.2`
- 稳定内容摘要：`sha256:a8de1d2bd74d7bd507f766829c0e31e2d60f29d1904aabb502a47bcbd505f8ec`
- 当前状态：`candidate`
- 三方 Review Attestation：全部 `PENDING`
- 功能状态：52 项全部保持 `DESIGNED`

底层契约和语义门禁已达到“可提交三会话实现基线复审”的条件，但尚未达到发布级 `frozen`。S2、S3、S4 对上述同一内容摘要分别返回 `ACCEPT` 并完成 Review Attestation 后，该 candidate 可启动实现；发布冻结还要等待质量资产完成。

## 2. rc2 二轮阻断处置

### S2-RUNTIME

- Context 各层分类与 Context/Security ceiling 确定性比较。
- Context 估算/实际输入 Token 同时受 Context Policy 和 AgentRunRequest 上限约束。
- TaskCommand 正例使用可重算的 RFC 8785 摘要；错误摘要以及命令与 SecurityContext 的租户、主体 ID、主体类型、创建用途错配均由语义负例拒绝。
- ToolResult 的请求、策略与操作类型回绑原 ToolRequest/PlannedAction。
- 语义负例必须从无错误的合法基线变异，防止“基线已错”的假阴性。

### S3-PLATFORM

- `approved` 同时要求 `approver_id != requester_id`，不能只声明 SoD 布尔值。
- PolicyDecision 显式保存并绑定 `subject_context_hash`。
- 写入 `verified` 必须有非空业务数据、证据引用、观察引用和权威匹配回读。
- Audit 哈希前像、可信 Stream/Tenant、序号连续性和前序哈希成为可执行链门禁。

### S4-QUALITY

- EvaluationCase 绑定 Dataset、Fixture、Registry 的 ID/版本/哈希。
- Registry 固定 120/36 类别配额、不可缩减分母和类别必需确定性 Gate。
- 重复 Assertion、终态矛盾、工具允许/禁止交集均有语义负例。
- Feature 证据结构化绑定声明 ID、文件、哈希、Run、时间和独立验证角色。
- ContractSet 使用稳定 `content_digest`；Review 绑定摘要，解决写入评审状态后的哈希悖论。
- Frozen Registry 必须具有可解析且哈希固定的 Judge Prompt；Dataset、Fixture、Traceability 与 ContractSet 同步冻结。

## 3. 可重复性规则

- 被哈希文件为 UTF-8 无 BOM、LF 换行；`.gitattributes` 固定跨平台 EOL。
- JSON 解析拒绝重复键。
- 原始文件 SHA-256 与 ContractSet 内容摘要分别验证。
- ContractSet 摘要投影排除 `status/reviews/frozen_at/content_digest`，生命周期变化不改变已评内容身份。
- RFC 8785 架构期门禁使用无浮点 I-JSON 子集；浮点和超安全范围整数显式拒绝，生产实现必须使用完整合规库。

## 4. 已运行验证

命令：

```text
python -B -c "<加载临时 jsonschema 4.25.1 并运行 contracts/conformance/validate.py>"
```

结果：

```text
CONTRACT_CONFORMANCE_OK schemas=20 cases=35 positive=18 negative=17 mutation_cases=18 mutation_positive=3 mutation_negative=15 semantic_cases=36 semantic_positive=0 semantic_negative=36 audit_chain_cases=5 audit_chain_positive=1 audit_chain_negative=4 manifest_cases=20 manifest_positive=1 manifest_negative=19 features=52
```

覆盖：

- 20 个 Draft 2020-12 Schema 与 `$ref`。
- 清单 SHA-256、稳定内容摘要、发布依赖和便携字节。
- 35 个完整实例、18 个 Schema 变异、36 个跨对象语义负例。
- 两事件 Audit 正链及篡改、缺口、重复序号、跨 Stream 串链。
- 20 个 Registry/Dataset/Fixture/Traceability/ContractSet 清单用例。

`make test-contract` 仍未实现；上述底层命令是 WP-000 契约候选门禁，不冒充实现阶段完整工程测试。

## 5. 未完成条件

1. S2-RUNTIME 对同一 `content_digest` 返回 `ACCEPT`。
2. S3-PLATFORM 对同一 `content_digest` 返回 `ACCEPT`。
3. S4-QUALITY 对同一 `content_digest` 返回 `ACCEPT`。
4. S1 保存三份 Review Evidence 并写入 Attestation；至此形成可实现基线。
5. 后续发布冻结轮次先把 Registry、Dataset、Fixture、Traceability 本身切换为 `frozen`，重新生成内容摘要并再次进行精确候选评审。

因此，本报告只能使用“rc2 集成候选已通过底层门禁、待三方最终复审”，不能使用“契约已冻结”。
