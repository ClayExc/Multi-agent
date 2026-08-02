# 验收产物

本目录专用于存放自动生成且已经脱敏的验收证据。

WP-030 的生成器位于 `scripts/acceptance/generate_bundle.py`。在独立验证者完成
已声明测试/证据 ID、哈希、运行 metadata 和密钥扫描结果校验之前，生成的运行目录
不能作为发布证据。

空验收包或零 Case 验收包必须输出 `gate_result=fail`、
`report_state=empty`，且不提供成功率。不得将其描述为通过的验收运行，也不得将其
作为 120 条功能用例和 36 条安全/故障用例已经存在的证明。
