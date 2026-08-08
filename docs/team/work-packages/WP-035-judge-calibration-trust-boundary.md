# WP-035：Judge 校准可信输入边界

## 元数据

- 状态：DEFERRED_TO_M19
- Attempt ID：WP-035-a1
- 风险等级：R2
- 责任角色：S4-QUALITY
- 评审角色：S1-ARCH
- 功能 ID：FP-EVAL-004
- 依赖工作包：WP-034 已接受
- 执行模式：ORDERED
- Chain ID：CHAIN-M6-ACCEPTANCE-REMEDIATION-01
- Step ID：M6-REM-05-JUDGE-PIPELINE
- 输入 Head：`1c0ae3b96ed540c0e9391ee9e4eab9993e9af579`

## 已证实问题

- `build_blind_samples()` 从 EvaluationCase 的 `input` 提取 `candidate_output`；现有
  盲测表多数内容是用户请求，不是产品/模型实际回答。
- 当前 30 条盲测样本包含 12 条 `safety_fault`；Judge 不得判定安全、授权、审批、
  工具成功或任务终态。
- `calibrate --verdicts` 把单份 verdict 文件标记为 `human_review`，却与数据集派生的
  `reference_label` 比较，没有形成“两名人工或一人两轮”的参考标签，也没有独立的
  Judge 预测输入。
- 因此当前 `placeholder_proxy / kappa=0 / gate=false` 只能证明流水线可运行，不能用于
  Judge 校准或 120+36 质量结论。

## 目标

1. Blind Set 只接收 Acceptance 真实执行产生、Hash 可回绑的产品观察，不得从 Case
   输入或 Expected 字段伪造候选回答。
2. 只抽取 `functional + judge_rubrics + deterministic gates passed` 的语义样本；安全、
   授权、状态和工具成功用例不得进入 Judge 校准分母。
3. 明确分离人工参考与 Judge 预测：至少两轮人工标签（或等价的两评审输入）、分歧
   裁决记录和独立 Judge verdicts；缺一项均失败关闭。
4. `status=calibrated` 仅在样本数、人工一致性、Judge kappa、身份/Prompt 版本和 Hash
   均满足门禁时产生；proxy 始终 `no_effect`。
5. 现有错误 Blind Set/Review Sheet/Calibration 明确标记为历史 placeholder，不得误用。

## 允许修改路径

- `evals/runners/**`
- `packages/evaluation/**`
- `tests/acceptance/evaluation/**`

## 非目标

- 本包不调用外部模型、不产生付费 Token、不替用户填写人工标签。
- 不实现 156 个场景 Executor，不修改 Dataset Case、公共 Contract 或业务代码。
- 不宣称 Judge 已校准、kappa 已达标或评测成功率已完成。
- 当前没有产品执行器和真实产品 Observation，本包不再作为活动链等待项；可信
  输入流水线、人工参考和 Judge 预测随 M19 产品评测重新激活。

## 必须测试

- Case 输入不能作为候选输出；无真实 Observation 时构建失败。
- Observation 的 Case ID、输出摘要、Evidence Hash 或确定性 Gate 任一错配时失败。
- `safety_fault` 或无 Judge Rubric 的 Case 被排除且不能进入语义分母。
- 缺少第二轮人工标签、存在未裁决分歧、缺少 Judge 预测、Prompt/模型身份缺失时失败。
- Proxy、未达 kappa 或样本不足时状态保持未校准且聚合无效。
- 合成的完整双轮参考 + Judge 预测可生成可复算校准结果，但不得伪装成生产结论。

## 验收

```powershell
uv run --all-packages --all-groups --locked python -B -m pytest tests/acceptance/evaluation/test_calibrate_judge.py -q
uv run --all-packages --all-groups --locked python -B -m pytest tests/acceptance/evaluation -q
uv run --all-packages --all-groups --locked ruff check evals/runners packages/evaluation tests/acceptance/evaluation
uv run --all-packages --all-groups --locked mypy --strict --explicit-package-bases evals/runners/calibrate_judge.py
```

## 完成定义

- 旧错误 Blind Set 无法通过新 verify/calibrate。
- 本地合成可信输入的正负路径全部通过；无外部调用。
- 真实人工标签和 Judge 预测仍缺失时，门禁明确停在 `USER_GATE_REQUIRED`。
