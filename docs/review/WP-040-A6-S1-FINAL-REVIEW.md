# WP-040-a6 S1 P1 VPN 最终集成评审

## 裁决

```text
SESSION_ROLE=S1-ARCH
CHAIN_ID=CHAIN-P1-VPN-READONLY-01
WORK_PACKAGE=WP-040
ATTEMPT_ID=WP-040-a6-S1-FINAL
VERDICT=ACCEPT_P1_VPN_CANDIDATE
VALIDATED_S7_HEAD=0da13854beafd0e82f5f6151cc9f78ef1e090fc9
CONTRACT_CONTENT_DIGEST=sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc
P0_P1_BLOCKERS=none
MERGED_TO_MASTER=no
RELEASED=no
FROZEN=no
USER_GATE_REQUIRED=yes
```

S1 接受 P1 VPN 只读知识闭环候选进入用户合并门禁。候选可以从受信请求引用
解析脱敏观察，在缺少环境字段时 Interrupt/Resume，只经 MCP Gateway 执行
租户与 ACL 过滤的知识检索，保存带版本和章节引用的结果，并以 Task
`COMPLETED` 结束。该裁决不代表真实企业 Knowledge、Provider、工单写入、
120/36 数据集或发布环境已经完成。

## 输入与线性候选

| 输入 | Head |
|---|---|
| P1 激活主分支 | `3256f064423f4b80a610b7efeefbdc5584e9e236` |
| S5 Core | `1d6870764464cd4762351e7cf278bacd8e4fbced` |
| S3 Platform | `d360f0351520790c86b9c2cc9a7e8c08222a38f9` |
| S2 Runtime | `c5c118d808931492d7ee44455b1c2a9360625675` |
| S4 Quality | `4792098ecfe3d4723c04ece8cf9c8d62fcf02d0e` |
| S7 Integration | `0da13854beafd0e82f5f6151cc9f78ef1e090fc9` |

上述 Heads 构成单父线性链。S7 Worktree 洁净；Handoff 与 Proof 原始字节
Hash、ContractSet 摘要和 Knowledge Schema Pin 与唤醒信封一致。S4→S7
增量只有 S7 独占路径，公共契约、Workspace/Lock、Migration 和 Infra 未变。

## S1 独立复现

S1 在独立 `codex/s1/wp-040-final-gate` 分支执行 FAST final gate：

```text
WP040_P1_VPN_S1_FINAL_PASS checks=49 failed=0
```

该门禁重新证明 S7 Head 祖先关系、S1/S7 路径范围、产品树与四个输入 Head
未被改写、Contract/Lock/Migration Hash 稳定、Knowledge Schema Pin 与 20
条 Case/Proof 闭合。S7 已对同一候选完成 RELEASE：253 项产品、68 项安全、
89 项 Acceptance、44 项 Integration、14 Wheel、依赖/Secret 扫描和隔离
Compose/RLS/恢复均通过，因此 S1 不重复完整 RELEASE。

## 架构与安全结论

- Knowledge 调用只经 Gateway Port；Worker 对上游 MCP/Adapter 的旁路为 0。
- 租户、ACL、Purpose、Scope、分类和有效期在匹配前失败关闭；跨租户成功
  检索数为 0。
- 缺字段 Interrupt、跨 Worker 恢复、Artifact retry 与重复投递保持一次
  逻辑检索和稳定 `result_ref`。
- Graph State、Studio 投影与证据只保存最小脱敏元数据，不包含原始请求、
  文档正文、ACL、凭据、PII 或隐藏思维链。
- 20 条 Case 使用固定分母和确定性断言，Judge 不能覆盖安全、调用次数、
  引用完整性或 Task 终态。

## 保留项

| 级别 | 事项 | Owner | 影响 |
|---|---|---|---|
| P2 | `make acceptance` 尚未实现 | S4/S5 | 阻断发布级一键验收，不阻断 P1 候选 |
| P2 | 继承 4 个 Acceptance Ruff I001 | S4 | 不在 P1 变更范围 |
| P2 | `apps/worker/.../vpn.py` 已超过 1,000 行 | S2 | 行为已验证；下一 Runtime 重构应拆分图、节点和恢复适配 |
| P2 | 20 条 Case 仍是 candidate-only | S4/S1 | 不代表 120/36 或发布级 frozen |
| P2 | 注册制与事件驱动仍处渐进迁移 | S1 | 下一链开始度量消息和重复读取量 |

## 用户门禁

主分支仍停留在 P1 激活提交。链路状态为
`PAUSED / USER_GATE_REQUIRED`；用户明确批准后，S1 才能将精确候选
fast-forward 到主分支，并在主分支复跑同一 FAST final gate。当前不自动
合并、不推送，也不启动下一条开发链。

## 用户门禁结果

```text
USER_DECISION=APPROVED
MERGED_TO_MASTER=yes
MERGED_CANDIDATE_HEAD=25a1dcd02e20230718f15da591682a931e0cf8b5
MERGE_MODE=FAST_FORWARD_ONLY
POST_MERGE_FAST_GATE=49/49_PASS
RELEASED=no
FROZEN=no
NEXT_SCHEDULER=AGENT_REGISTRY_WITH_FLOW_LITE
```

该记录只确认候选已进入主分支。真实 Provider、工单写入、120/36 数据集和
发布冻结的状态仍未提升；下一链必须重新建立工作包、注册选择和用户批准。
