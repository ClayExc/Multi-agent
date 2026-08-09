# WP-072-a1 S4-QUALITY Web / Studio 安全投影交接

## 基本信息

- Work Package：WP-072
- Attempt ID：WP-072-a1
- Chain ID：CHAIN-M7-LOCAL-PRODUCT-01
- Step ID：M7-09-S4-WEB-STUDIO-RESUME
- 责任会话：S4-QUALITY
- 下一会话：S4-QUALITY（WP-073-a1-quality，等待精确激活信封）
- Agent ID：experience-builder
- 功能 ID：FP-FLOW-002、FP-FLOW-004、FP-OBS-001、FP-OBS-002
- 输入提交：`e95eeba72a7c03637f63a99fbc3648819d3d30db`
- 实现提交：`b7cedbc63e338dfd225557208ecb2f0737a7e792`
- 分支：`codex/s4/m7-experience-evaluation`
- ContractSet：`sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：PASS_HANDOFF；未宣称 VERIFIED 或 RELEASED

## 完成内容

- Web 新增 `demo` / `live` 明确模式。Live 模式只使用服务端配置的 API Base 与
  Tenant，不转发浏览器伪造租户；浏览器提交原始 TaskCommand 时稳定拒绝。
- SSE 仅作为通知流使用：每个 Event 后重新读取权威 Task；保留
  `Last-Event-ID`，检测 sequence gap、同 Event ID 异内容和同 Task sequence 异
  Event，并在冲突时失败关闭。
- 建立五阶段安全 Studio 投影与内容无关的进度卡；仅展示稳定阶段、计数、模型、
  引用和恢复码，不展示请求正文、回答、ACL、Tenant、Session、凭据或隐藏思维链。
- 真实本地 Agent Server Oracle 覆盖稳定图、合法双 Interrupt/Resume、retry、
  Checkpoint 历史、安全投影及清理；非法 Profile、Scenario、权威字段和敏感字段
  在 Pregel 前拒绝，Thread state/history/tasks 为空。
- 独立复算错类型 Resume、陈旧 Resume、clarification 历史 Checkpoint 与终态
  approval Checkpoint replay；失败前后 state/history/write 变化均为 0。
- 复算 WP-074 安全 Event 修复：未知 key/value、非法 shape/type/producer/
  classification 及凭据 family 不能进入 construction、subscriber、replay、SSE、
  `str`/`repr`/日志；合法 `xoxo`/`xoxz` 业务 ID 和 opaque ref 无回归。

## 修改文件

- `web/server.py`、`web/README.md`、`web/shell/app.js`、`web/shell/index.html`
- `web/src/flowpilot_shell/live.py`
- `web/src/flowpilot_shell/projection.py`
- `web/src/flowpilot_shell/render/progress.py`
- `web/src/flowpilot_shell/api_client.py`
- `web/src/flowpilot_shell/sse_client.py`
- `web/src/flowpilot_shell/__init__.py`
- `web/src/flowpilot_shell/render/__init__.py`
- `tests/experience/test_live_mode.py`
- `tests/experience/test_studio_projection.py`
- `tests/experience/test_sse_client.py`
- `tests/experience/test_adapter_boundary.py`
- `tests/acceptance/m7/test_web_live_blackbox.py`
- `tests/acceptance/studio/oracle_v2.py`
- `tests/acceptance/studio/test_agent_server_blackbox.py`
- `tests/acceptance/m7/evidence/WP-072-a1-PROOF.json`
- `tests/acceptance/m7/evidence/WP-072-a1-HANDOFF.md`

## 契约、数据与共享文件

- Contract、Schema、ADR：无变化；ContractSet 与输入摘要一致。
- 数据库、Migration、RLS、Outbox：无变化。
- `pyproject.toml`、`uv.lock`、Makefile、根配置：无变化。
- 未访问真实 Provider、生产凭据或付费端点；online/paid provider calls 为 0。

## 验证

| 命令 | 结果 |
|---|---|
| `pytest tests/experience tests/acceptance/m7 -q` | PASS：77 passed |
| `pytest tests/acceptance/studio -q` | PASS：4 passed；真实 Agent Server Oracle |
| `pytest tests/acceptance -q` | PASS：265 passed |
| 全仓 `pytest -q` | PASS：1327 passed、1 个显式 online skip |
| `scripts/quality.ps1 test-contract` | PASS：20 Schema、35 Case、43 语义负例、52 Feature |
| `scripts/quality.ps1 test-security` | PASS：163 passed |
| `scripts/quality.ps1 lint` | PASS：Ruff；strict Mypy 129 files |
| `pytest tests/experience/test_secret_scan.py -q` | PASS：2 passed |
| UTF-8/LF/无 BOM、`git diff --check`、`.langgraph_api` 清理 | PASS |
| `make acceptance` | NOT_RUN：M7 固定分母发布门禁属于 WP-073 |

完整命令和结构化结果见 `WP-072-a1-PROOF.json`。

## 未完成与风险

- P2：真实在线 Provider Smoke 未授权，不能由本离线结果外推真实模型质量。
- P2：Live 模式没有新增正文上传入口；生产接入仍须由可信入口提供 opaque message
  reference，浏览器不得提交业务事实或 Tenant 权威。
- P2：同 Thread 跨进程并发的 latest-checkpoint 读取与执行仍不是原子 CAS；未来开放
  并发 Run 时需由 S2 增加调度串行化或持久化 CAS。
- P2：Studio Oracle v2 在 S4 测试范围内复用旧 Runner 的进程生命周期并替换其
  probe；旧 artifacts 生成器未在本范围改动。Runner 私有辅助函数变化会显式使测试
  失败，不会静默放宽边界。
- 本 Step 不声明固定分母 Case、模型成功率、Token 提升、VERIFIED 或 RELEASED。

## 学习候选

```text
LEARNING_CANDIDATE=Browser stream events must be notifications, not Task facts
MATURITY=VERIFIED
TRIGGER=SSE reconnect, duplicate, gap, or forged browser authority
MECHANISM=Treat Event as a wake signal and refresh the authoritative Task after every accepted Event
STRUCTURE=server-owned tenant + Last-Event-ID + event fingerprint + sequence conflict gate + authoritative Task refresh
EVIDENCE=tests/acceptance/m7/evidence/WP-072-a1-PROOF.json
RESIDUAL_RISK=same-thread cross-process CAS remains outside Web ownership
TARGET=WP-073 quality gate and future Web live consumers
```

## 下一步

1. 接收方核验 NEW_HEAD、Handoff/Proof Hash、ContractSet、输入提交到 NEW_HEAD 的
   线性祖先、授权路径和 clean 状态，仅用 `--ff-only` 消费。
2. 收到精确 WP-073-a1-quality 激活信封后，再执行固定分母 M7 质量门禁；本 Handoff
   本身不构成该 Attempt 的授权。
3. 新的 P0/P1、公共契约变化、越权路径或门禁失败必须停链上报 S1。

## 机器摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M7-LOCAL-PRODUCT-01
STEP_ID=M7-09-S4-WEB-STUDIO-RESUME
ATTEMPT_ID=WP-072-a1
INPUT_HEAD=e95eeba72a7c03637f63a99fbc3648819d3d30db
IMPLEMENTATION_HEAD=b7cedbc63e338dfd225557208ecb2f0737a7e792
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/acceptance/m7/evidence/WP-072-a1-HANDOFF.md
PROOF=tests/acceptance/m7/evidence/WP-072-a1-PROOF.json
NEXT_ROLE=S4-QUALITY
NEXT_ATTEMPT_ID=WP-073-a1-quality
ESCALATE_TO_S1=no
```

## 回滚

- 按逆序 `git revert` Handoff 提交和实现提交；禁止 reset、rebase 或 force-push。
- 本 Attempt 没有数据库、外部系统或生产数据写入，无数据回滚。
