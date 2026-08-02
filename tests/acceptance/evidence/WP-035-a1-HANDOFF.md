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

## S1 P1 返修（同 Attempt）

- verify 改为确定性复算：Blind Set、Bindings、人工两轮、裁决、Judge
  predictions、calibration 与 S1 freeze 全部建立规范 JSON SHA-256 链；任一输入、
  摘要或输出篡改均失败。伪造 `status=calibrated` 不能通过。
- 恢复混淆矩阵、Wilson 95% 区间、FP/FN rate、逐 rubric kappa、阈值建议和
  固定 seed 分层抽样；freeze 同时绑定所有输入摘要与 calibration 摘要。
- CLI 使用 `--bindings`，各 artifact 使用独立精确 profile。人工身份必须非空且
  不同；模型、backend、Prompt Hash、执行器身份/版本、断言集合和 Observation
  provenance 均失败关闭；重复 Case/Blind/Evidence ref 被拒绝。
- 统计门禁通过只生成 `candidate/no_effect`。只有独立 S1 approval freeze 的整链
  verify 才成功；合成测试本身不产生 release-effective calibration。
- 专项测试由首轮 9 项增至 23 项，是加入全部 artifact 篡改矩阵、身份/类型/摘要、
  freeze 和企业统计回归；完整 evaluation 由首轮 125 增至 139，增加 14 个净测试，
  未删除其他 evaluation 测试。
- 返修验证：专项 `23 passed`；完整 evaluation `139 passed`；Ruff PASS；strict
  Mypy PASS。
