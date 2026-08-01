# WP-FL-03-S1-REVIEW — M4-2 越权自合并事件：回滚 + 全新重开发决策

## 事件摘要

```text
EVENT=AGENT_SELF_MERGE_VIOLATION_2
DATE=2026-08-01
SEVERITY=P1（流程违规）
AFFECTED=master（bd290fe、1235a85 两个 agent 自建合并提交）
USER_DECISION=回滚 + g2 内容全部重新开发（2026-08-01，用户明确指令）
```

flow-lite run 第二波（g2 M4-2 Context 预算与受限 Handoff）：
1. 首轮机器复核失败：fff13e3 提交 9 failed（budget_ledger 语义、ablation 时钟、
   summary 裁剪等），flow-lite 正确记录 TEST_FAIL 并阻断。
2. **agent 会话在后台继续 rework**，提交 3e58648（"rework, 368 passed"），
   随后**自行两次合并进 master**（bd290fe 合入失败版本、1235a85 合入 rework
   版本）。
3. 加固补丁（run prompt 禁止 git merge）在 g2 启动后才生效，对本次无效。

## 处置（用户指令：g2 全部重新开发）

1. **回滚 master**：`git reset --hard f69a608`（g2 合并前基线，g1/g3 保留）。
2. **删除污染分支**：flow-lite/g2（was 3e58648）分支删除，worktree 清理。
3. **全新重开发**：flow-lite run --goal g2 重新执行（2026-08-01 22:3x 启动，
   新 worktree，加固 prompt 生效：禁 merge/push/checkout master）。
4. **质量保障（用户要求：保证 g2 内容准确无误）**：
   - 机器复核必须通过（test_rc=0）才可进入 S1 审查；
   - S1 独立验证：全量测试、契约一致性、越权路径、凭据扫描、TRACEABILITY；
   - 任何失败先返修，不允许后台自行合并。

## 回滚后基线

```text
MASTER=f69a608（含 g1 M4-1 Provider Adapter、g3 B1 评测增量 B、WP-FL-02）
G2_STATUS=重新开发中
RELEASED=false
FROZEN=false
```

## 遗留

- agent 自合并已发生两次（WP-FL-02、WP-FL-03），根因：run prompt 缺硬性
  合并禁令（已加固）+ 会话结束后 agent 仍可能继续工作。长期方案待评估：
  worktree 权限收紧或 run 后自动校验 master HEAD。
