# evals/runners — 评测运行器

## calibrate_judge.py（FP-EVAL-004：Judge 盲测校准）

离线、确定性的 Judge 校准流水线（对应 `docs/acceptance/ACCEPTANCE.md` §12.3）：

```bash
# 1) 构建盲测集：从 M6 语料分层抽样 >= 30 条并匿名化（隐藏 case_id/hash/真实标签）
python evals/runners/calibrate_judge.py build-blind-set --size 30

# 2) 人工评审（两轮盲审，ACCEPTANCE.md §12.3）：
#    评审表  evals/runners/review-sheet.v1.md
#    判定模板 evals/runners/verdicts.template.v1.json（填 verdict 0/1 + score 0.0-1.0）
#    填写后另存为 verdicts.v1.json

# 3) 计算校准指标并输出 calibration.json（metrics + 阈值建议 + 置信区间）
python evals/runners/calibrate_judge.py calibrate \
    --labels evals/runners/blind-set-labels.v1.json \
    --verdicts evals/runners/verdicts.v1.json

#    流水线冒烟（无人工判定时，明确标记 placeholder_proxy，不算通过门槛）：
python evals/runners/calibrate_judge.py calibrate \
    --labels evals/runners/blind-set-labels.v1.json --proxy

# 4) M6 Hash 冻结：数据集文件哈希 + 校准基线 + 执行者注册制身份 → 冻结清单
python evals/runners/calibrate_judge.py freeze-hashes \
    --calibration evals/runners/calibration.json

# 5) 验证：冻结哈希一致性 + 盲测集可复现性 + 校准文件未漂移
python evals/runners/calibrate_judge.py verify \
    --freeze evals/runners/m6-hash-freeze.v1.json \
    --labels evals/runners/blind-set-labels.v1.json \
    --calibration evals/runners/calibration.json
```

### 产物

| 文件 | 说明 |
|---|---|
| `blind-set.v1.json` | 匿名盲测集（Judge 可见，无任何真实标签） |
| `blind-set-labels.v1.json` | 内部标签表（盲测 ID ↔ 真实 case、参考标签），勿泄露给 Judge |
| `review-sheet.v1.md` / `verdicts.template.v1.json` | 人工两轮盲审的评审表与判定模板 |
| `calibration.json` | 校准输出：混淆矩阵/准确率/kappa/误判漏判率、阈值建议（Youden J）、Wilson 95% 置信区间 |
| `m6-hash-freeze.v1.json` | M6 数据集全量文件哈希 + 校准基线 + 执行者身份（g2/S4-QUALITY eval-freezer）留痕 |

### 门槛语义

- 样本数 < 30 拒绝校准（§12.3）。
- kappa 建议门槛 0.75；未达门槛（或 placeholder 代理判定）时
  `gate.gate_met = false`，与 registry 的
  `aggregation_rules.uncalibrated_judge_effect = "no_effect"` 一致：
  未校准 Judge 对任何汇总无影响。
- Judge/Prompt 变化后必须重新校准（§12.3），旧 calibration.json 保留原版本。
