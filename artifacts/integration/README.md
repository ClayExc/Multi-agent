# 集成证据产物

`scripts/integration/verify_wp040.py` 会在 `artifacts/integration/runs/` 下生成
可确定性复现的组合清单和证据报告。

生成的运行结果不会纳入版本控制。S7 Handoff 会记录从干净检出状态复现本次运行所需的
准确命令、候选提交以及 SHA-256 值。
