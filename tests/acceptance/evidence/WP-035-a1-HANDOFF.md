# WP-035-a1 S4-QUALITY 交接

## 基本信息

- Work Package：WP-035；Attempt：WP-035-a1
- Chain/Step：CHAIN-M6-ACCEPTANCE-REMEDIATION-01 / M6-REM-05-JUDGE-PIPELINE
- 功能 ID：FP-EVAL-004；风险：R2；模式：IMPLEMENTATION
- 责任 Agent：judge-calibration-hardener（S4-QUALITY）

## OUTCOME

- Blind Set v2 只接收 `flowpilot.acceptance-observations.v1`，逐项绑定 Case ID、真实候选输出 SHA-256、确定性断言及 evidence_refs 的可复算 Hash。
- 仅 functional、包含 `judge.semantic.*` rubric 且确定性 Gate 全通过的观察进入语义分母；Case input/expected、安全故障用例均不能充当候选输出或参考标签。
- 人工第一轮、第二轮、分歧裁决和独立 Judge predictions 为四份不可互相替代的输入。Judge predictions 必须绑定模型身份和 Prompt Hash。
- 样本少于 30、人工/Judge kappa 低于 0.75、缺项或 proxy 均输出 `USER_GATE_REQUIRED` 和 `no_effect`；只有完整可信合成输入可复算为 calibrated，不代表生产校准结论。
- 旧 v1 Blind Set、labels、review sheet 明确标记为历史无效占位产物；v2 verify 拒绝旧 profile。

## EVIDENCE

- `uv run --all-packages --all-groups --locked python -B -m pytest tests/acceptance/evaluation/test_calibrate_judge.py -q`：9 passed。
- `uv run --all-packages --all-groups --locked python -B -m pytest tests/acceptance/evaluation -q`：125 passed。
- `uv run --all-packages --all-groups --locked ruff check evals/runners packages/evaluation tests/acceptance/evaluation`：PASS。
- `uv run --all-packages --all-groups --locked mypy --strict --explicit-package-bases evals/runners/calibrate_judge.py`：PASS。
- 未调用外部模型，未产生或填写人工标签。

## RISKS

- 真实 Acceptance Observation Bundle、两轮人工标签、裁决与 Judge 预测尚不存在，因此当前生产门禁仍为 `USER_GATE_REQUIRED`。
- v2 CLI 对旧语义错误接口是有意不兼容收紧；旧 freeze 仅保留历史审计用途，不能证明 Judge 校准。
- contracts、Dataset Case、业务代码、外部系统均未修改。

## NEXT_ACTION

- S1 复核可信输入边界与有意不兼容 CLI；后续真实 Executor 产出观察包后，由人工完成双轮盲审和分歧裁决，再以独立 Judge predictions 运行校准。
- `LEARNING_CANDIDATE=none`
