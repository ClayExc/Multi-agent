# WP-FL-04-S1-FINAL-REVIEW — M4-2 重开发合并审查（g2 全新开发）

## 审查结论

```text
SNAPSHOT=M4_2_REDEVELOPED_MERGED
STATUS=APPROVED_FOR_MASTER
REVIEWER=S1-ARCH（人类门禁授权）
REVIEW_DATE=2026-08-01
CANDIDATE_HEAD=2543524
CANDIDATE_BASE=f69a608（回滚后基线）
```

## 1. 背景

g2（M4-2 Context 预算与受限 Handoff）首轮开发因 agent 越权自合并 + 9 个测试
失败被用户裁决**全部回滚重开发**（见 WP-FL-03-S1-REVIEW）。本文件审查全新
开发的 g2 分支（2543524，单提交，基于回滚后基线 f69a608）。

## 2. 门禁检查项（全部通过）

| 检查 | 结果 |
|---|---|
| master HEAD 未被移动（越权检查） | ✅ 2d65716 保持不变（加固 prompt 生效） |
| 全量测试 | ✅ 362 passed |
| 契约一致性 | ✅ CONTRACT_CONFORMANCE_OK（20 schemas / 52 features） |
| S1 独占路径 | ✅ 仅 TRACEABILITY 路径引用修正（evals/runners→packages/evaluation），状态保持 DESIGNED，无越权升级 |
| 凭据/密钥 | ✅ 无 |
| 调试残留 | ✅ 无（17 文件均为实现+测试+产物） |
| 单提交可审查 | ✅ 2543524（4066 行插入，9 删除） |

## 3. 合入内容（M4-2 完整垂直切片）

- `packages/context`：ContextBuilder 接线、BudgetLedger（50 轮硬预算）、
  models 扩展（FP-CTX-001~004）
- `packages/graph`：engine/state/errors 接线，每次模型调用 ContextEnvelope
  （FP-CTX-001）
- `packages/evaluation`：context_ablation.py 确定性报告 + artifacts 产物
  （FP-CTX-005）
- `tests/runtime`：contract/e2e/integration/unit 四层测试（handoff 过滤与
  边界、预算上限、消融、摘要分层）

## 4. 遗留

- FP-CTX-001~005、FP-AGT-004 保持 DESIGNED，升级需独立验证者证据。
- 越权自合并加固（prompt 禁 merge）首次实测有效；机制级改造（run 前后
  master HEAD 校验等）仍按 INCIDENT-2026-08-01 记录待实施。

## 5. 裁决

S1-ARCH 审查通过，批准合入 master。RELEASED=false、FROZEN=false 保持不变。
