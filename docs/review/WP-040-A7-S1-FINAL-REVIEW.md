# WP-040-a7 S1 P2 持久化恢复最终评审

## 裁决

```text
SESSION_ROLE=S1-ARCH
CHAIN_ID=CHAIN-P2-DURABLE-RUNTIME-01
WORK_PACKAGE=WP-040
ATTEMPT_ID=WP-040-a7-S1-FINAL
VERDICT=ACCEPT_P2_DURABLE_CANDIDATE
VALIDATED_S7_HEAD=0b1d6ba3aa31536d9170027f0981c0e626b71f35
TARGET_HEAD=SELF
CONTRACT_CONTENT_DIGEST=sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc
P0_P1_BLOCKERS=none
MERGED_TO_MASTER=no
RELEASED=no
FROZEN=no
USER_GATE_REQUIRED=yes
```

S1 接受 P2 持久化恢复候选进入用户合并门禁。该裁决只覆盖 Flow Lite `g1`；
`g2` Outbox→SSE 与 `g3` 安全 Ticket 写入没有自动获批。

## 输入与证据

| 输入 | Head / Hash |
|---|---|
| S6 Data Handoff | `36e25279d6b4e02e7471c242ed2bd71dfc0a5dbc` |
| S2 Runtime Handoff | `052e61beff5711e3e69dbaf45b792ad8d1a309dc` |
| S7 Integration | `0b1d6ba3aa31536d9170027f0981c0e626b71f35` |
| S7 Handoff SHA-256 | `45fa06e64bb2b12ad7c4af73ed9de5ae6ee204c15404f5e671b2c916b09aa98a` |
| S7 Proof SHA-256 | `25e87ff59df67f3aa05d9a18296d9ef3b836e2728d0e0ac2f4c13f995b2e25e4` |

S1 已独立复算 S7 Worktree/Head、Handoff/Proof 原始字节 Hash、S7 独占路径、
S6/S2 祖先关系和 ContractSet 摘要。P2 激活后的产品改动只在 S6、S2 授权
路径，S7 只增加 Integration 验证与证据。

## S1 FAST final

S1 在独立 `codex/s1/wp-040-a7-final` 分支运行：

```powershell
python scripts/integration/verify_wp040.py --repo . `
  --phase P2_DURABLE_S1_FINAL `
  --s7-head 0b1d6ba3aa31536d9170027f0981c0e626b71f35 `
  --target-head <SELF>
```

结果：

```text
WP040_P2_DURABLE_S1_FINAL_PASS checks=35 failed=0
```

FAST final 证明 S7 Head 是最终 Head 的祖先、S1 增量只有控制面文档、产品树与
S6/S2 Heads 未被改写，Contract/Lock/Migration/Infra 保持相同对象。S7 已对
相同产品候选完成 RELEASE，因此 S1 不重复 Wheel、依赖审计和 Compose。

## 架构与安全结论

- PostgreSQL 是 Task/Checkpoint/Outbox 权威；Redis 丢失后可按可信 tenant 重建。
- 新 Worker generation 1→2，Checkpoint sequence 3→6。
- 旧 Worker 成功写入、陈旧 CAS、终态节点重跑和跨租户读取均为 0。
- Worker 只消费类型化 Persistence Port，没有 PostgreSQL/Redis Driver 旁路。
- `studio-safe` 内存模式与生产持久化恢复模式继续显式分离。

## 项目收口

- 加速规划已并入 final 候选，但未激活后续目标。
- [`PROJECT_HANDOFF.md`](../roadmap/PROJECT_HANDOFF.md) 成为当前项目状态主入口。
- `CODEX_SESSIONS.md` 删除重复逐提交历史和过时固定扩容建议，从 277 行压缩
  到 221 行；审计文件没有删除。
- Handoff/Proof、ADR、Migration、Contract Review 和历史 Chain 继续保留。

## 保留项

| 级别 | 事项 | Owner | 影响 |
|---|---|---|---|
| P2 | `make acceptance` 未实现 | S4/S5 | 阻断发布级一键验收，不阻断 P2 |
| P2 | 全仓 29 个继承 Ruff finding | 对应路径 Owner | P2 影响范围 Ruff 已通过 |
| P2 | 120+36 与正式 Evidence 未冻结 | S4/S1 | Feature 不提升为发布级 VERIFIED |
| P3 | 唤醒别名/Context 字段曾需规范化 | S1 | 协议已固定，后续信封直接使用权威字段 |

## 用户门禁

当前只允许向用户报告并等待。用户明确批准后，S1 才能把精确 final 候选
fast-forward 到 `master`，并在主分支复跑同一 FAST final。不得自动启动
`g2/g3`、推送、发布或连接企业系统。
