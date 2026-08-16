# WP-119-a1 Unit 顺序隔离修复交接

## 基本信息

- Chain：`CHAIN-M10-KNOWLEDGE-01`
- Step：`M10-09A-S4-UNIT-ORDER-ISOLATION`
- Work Package：`WP-119-R1`
- Attempt：`WP-119-a1-unit-r1`
- Owner：`S4-QUALITY`
- Blocker：`S4-WP119-A1-001`
- Base：`1119f8e3af1781840ff665819b17a43bab42650f`
- ContractSet：`sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：`PASS_HANDOFF`；仅回 S1，未唤醒 S7

## 根因与最小复现

官方 Runner 两次在 `tests/core tests/runtime/unit tests/experience` 顺序下将
`test_live_command_error_does_not_expose_upstream_message` 的预期安全 409 映射成 503。
当前 Base 上单次官方 unit 组合可以通过，因此进一步从前置模块二分切换到 Fixture
生命周期压力复现。

不加载任何前置测试模块，只启动一次 `identity_servers`，先验证 Cookie-only GET，再连续
提交 500 次相同 Shell Command：修复前实测 `409=489, 503=11`。最小污染源是
`IdentityApiHandler.do_POST` 在返回 409 前没有读取 API Client 发送的 JSON body。
HTTP/1.1 连接带未读入站数据关闭时，Windows 会间歇产生 TCP reset；产品 Web 正确把该
传输失败映射为 503，所以不存在产品端全局状态或权限泄漏。

## 修复

- 仅修改 `tests/experience/test_identity_shell.py`。
- Fake API 在分派 POST 前读取并验证 `Content-Length`，最多接受 1 MiB，短读、负数、
  非整数和超限均失败关闭。
- Fixture 记录实际消费字节数；原 409 测试增加确定性断言，确保回归不会重新引入未读 body。
- 未修改 `web/**`；409 稳定码、上游 canary 零泄漏、Cookie-only 权威边界和浏览器无
  tenant/role 输入均保持。
- 修复后同一 500 次最小压力复现为 `409=500, 503=0`，累计完整消费 617000 bytes。

## 验证

| 命令/观察 | 结果 |
|---|---|
| 修复前单 Fixture 500 次生命周期压力 | 489×409 / 11×503 |
| 修复后同一压力 | 500×409 / 0×503 |
| `python -B -m pytest -q tests/core tests/runtime/unit tests/experience` | PASS：575 passed |
| `python -B -m pytest tests/experience -q` | PASS：103 passed |
| `python -m ruff check tests/experience/test_identity_shell.py` | PASS |
| `python -m mypy --strict web/src web/server.py` | PASS：25 source files |
| `python -m pytest tests/experience/test_secret_scan.py -q` | PASS：2 passed，Secret Scan 0 |
| `git diff --check` | PASS |

诊断时直接对整个既有 pytest 文件运行 strict Mypy 会暴露该文件及其导入的 `web/server.py`
既存非严格测试注解问题，因此未冒充通过；最终使用仓库既有 S4 稳定 Mypy 入口检查全部
Web 产品源。按 S1 要求未重跑官方 156 Runner。

## 变化边界

- 公共 Contract、Dataset、固定分母、Executor、产品 Web、Cookie、身份与租户语义：无变化。
- 网络重试、随机 sleep、断言放宽、503 接受：均未引入。
- 子 Agent：0。

## 下一动作

S1 可精确消费本提交并关闭 `S4-WP119-A1-001`。剩余
`S7-WP119-A1-001` 由 S7 Owner 修复旧三 Executor 组合 oracle；两项闭合后再统一运行
官方 Runner。

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M10-KNOWLEDGE-01
STEP_ID=M10-09A-S4-UNIT-ORDER-ISOLATION
WORK_PACKAGE=WP-119-R1
ATTEMPT_ID=WP-119-a1-unit-r1
BASE_COMMIT=1119f8e3af1781840ff665819b17a43bab42650f
NEW_HEAD=<this-handoff-commit>
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
FIXED=S4-WP119-A1-001
NEXT_ROLE=S1-ARCH
```
