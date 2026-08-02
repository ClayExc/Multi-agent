# Judge 校准运行器（FP-EVAL-004）

v2 运行器只接受真实的 Acceptance Observation Bundle。每条符合条件的功能样本
必须包含语义 Judge rubric、非空的产品观测输出及其 SHA-256 摘要、已经通过的
确定性断言，以及哈希可复算的证据文件。Case input 和 `expected` 数据绝不作为
候选输出或参考标签。安全/故障 Case 和未通过确定性门禁的 Case 均不纳入校准。

```powershell
python evals/runners/calibrate_judge.py build-blind-set `
  --observations artifacts/acceptance/<run>/judge-observations.v1.json `
  --evidence-root artifacts/acceptance/<run> `
  --out-dir artifacts/acceptance/<run>/judge-calibration

python evals/runners/calibrate_judge.py calibrate `
  --blind artifacts/acceptance/<run>/judge-calibration/blind-set.v2.json `
  --bindings artifacts/acceptance/<run>/judge-calibration/blind-set-bindings.v2.json `
  --human-round-1 human-round-1.json --human-round-2 human-round-2.json `
  --adjudication adjudication.json --judge-predictions judge-predictions.json `
  --out calibration.v2.json
```

两轮人工评审必须使用不同且非空的 reviewer identity，并且精确覆盖 Blind Set。
每项分歧都需要显式 adjudication。Judge prediction 使用单独文件，并且必须绑定
model ID 和 Prompt SHA-256。输入缺失、可信样本少于 30 条、人工或 Judge kappa
低于 0.75，或者使用任意 proxy backend，都会产生 `USER_GATE_REQUIRED`，同时
设置 `aggregation_effect=no_effect`。指标通过时也只得到 `status=candidate`，
同样不会影响聚合结果。若要用于发布，必须具有
`flowpilot.judge-calibration-freeze.v2` 记录，其中包含 S1 approval identity，
并精确绑定每项校准输入和输出的哈希。合成 Fixture 本身绝不具有发布效力。

仓库中已有的 `blind-set.v1.json`、`blind-set-labels.v1.json`、review sheet、
verdict template 和 `calibration.json`，是根据 Dataset Case input/expected
值生成的历史占位文件。v2 `verify` 命令会拒绝这些文件；它们不能用于 Acceptance
聚合，也不能支撑 Judge 已完成校准的声明。
