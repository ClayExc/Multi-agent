# WP-121：M11 短期记忆门禁

## 元数据

- 状态：DONE
- Attempt：WP-121-a1
- Owner：S1-ARCH
- Reviewer：S2、S3、S4、S5、S6、S7
- 风险：R2
- Feature：FP-CTX-001～005、FP-DATA-001、FP-SEC-003/005、FP-UI-001、FP-EVAL-001/002
- 依赖：WP-120
- 执行：ORDERED

## 目标与输出

固定短期记忆状态权威、摘要事实等级、Token 预算、持久化、恢复、Handoff、隐私清理、Web
投影和验收边界。输出 `SHORT_TERM_MEMORY.md`、ADR-0006、M11 Chain/Registry、WP-122～129
与 S1 Delta Capsule；不修改公共 ContractSet 或产品代码。

激活提交必须是当前 M10 主分支的线性后继，作为所有 M11 Worktree 的相同基线。
