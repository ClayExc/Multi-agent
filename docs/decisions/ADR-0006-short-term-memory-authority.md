# ADR-0006：短期记忆是任务内可重建派生状态

- 状态：Accepted
- 日期：2026-08-16
- 决策者：S1-ARCH
- 影响 Feature：FP-CTX-001～FP-CTX-005、FP-DATA-001、FP-SEC-003、FP-UI-001

## 背景

FlowPilot 已有 LangGraph Checkpoint、Task Facts、ContextEnvelope、分层摘要和 Token Ledger。
如果再增加一个可以自行演进的 Memory Store，会形成第二业务状态源：摘要可能覆盖 Task Facts，
旧 Snapshot 可能在恢复时覆盖新 Checkpoint，权限或审批也可能被错误地“记住”。

## 决策

1. 短期记忆限定在 `tenant + task + thread`，是可从可见消息和权威 Task Facts 重建的派生状态。
2. LangGraph/Task/Checkpoint、审批、策略和工具账本保持各自权威；Memory 只能保存引用和安全投影。
3. SecurityContext、角色、Scope、Capability、凭据、Provider Session 和隐藏推理禁止进入 Memory。
4. Snapshot 使用版本、消息高水位、source hash 与 CAS；Checkpoint 只保存最新 Snapshot 引用和 Hash。
5. 模型只生成摘要候选。claimed、verified、inferred 的写入和升级由确定性代码验证。
6. Context Manifest 必须在 Provider 调用前持久化；Manifest 失败则不调用模型。
7. Redis 不是 Memory 事实源；终态/TTL/用户清除可以删除可删除内容，但不能伪造完成审计。
8. M11 不修改公共 ContextEnvelope v1；跨进程契约需求出现时另走 Contract RFC。

## 结果

- Worker 可以在重启后恢复任务内上下文，而不会引入第二编排中心。
- 摘要错误或丢失只影响上下文质量，不会改变业务状态、授权、审批或工具执行事实。
- 需要新增 PostgreSQL 派生状态表、RLS、CAS、清理和对账测试。
- M12/M13 必须建立独立的长期记忆和画像契约，不能直接扩大 M11 Snapshot 的范围。

## 被拒绝方案

- 把完整 Transcript 塞进 Checkpoint：体积、隐私和恢复冲突不可控。
- 只存在 Redis：清空或故障后无法恢复与审计。
- 让模型直接更新“已确认事实”：会把推断升级为业务事实。
- 把短期、长期记忆和用户画像放在同一表：保留、授权和更正语义无法隔离。
