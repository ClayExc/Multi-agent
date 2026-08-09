# WP-072-studio-r2 S2-RUNTIME Studio Resume 权威边界交接

## 基本信息

- Work Package：WP-072
- Attempt ID：WP-072-studio-r2
- Chain ID：CHAIN-M7-LOCAL-PRODUCT-01
- Step ID：M7-08R2-S2-STUDIO-RESUME-AUTHORITY
- 责任会话：S2-RUNTIME
- 接收会话：S5-CORE
- 交接策略：CONSUMER_GATE
- 功能 ID：FP-FLOW-002、FP-FLOW-004、FP-OBS-001
- 基线/输入提交：`cabf4512c017efc8fd033cc641c204f13e336050`
- 分支：`codex/s2/wp-070-provider-runtime-adapters`
- 最终提交：本文件所在提交；精确 SHA 由唤醒信封返回
- ContractSet 摘要：
  `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：PASS_HANDOFF

## 完成内容

- 将 Studio `Command` 收窄为纯 Resume：`graph=None`、`update=None`、`goto` 仅
  允许 LangGraph 本地默认空元组或 Agent Server 映射后的 `None`。
- Resume 仅允许两个精确形状：`{"confirmed": true}` 或
  `{"approved": <bool>}`。额外字段、嵌套值、敏感键、字符串布尔值、空 Resume
  和其他形状均在调用 Pregel 前以
  `GRAPH_STUDIO_STATE_EDIT_FORBIDDEN` 失败关闭。
- `update_state`、`aupdate_state`、`bulk_update_state`、
  `abulk_update_state` 四个状态编辑入口全部拒绝；保护随
  `CompiledStateGraph.copy(update=...)` 传播，覆盖 Agent Server 实际装配路径。
- 对挂起 clarification 的拒绝前后执行完整状态指纹比较：values、next、历史数量、
  pending writes、`approval_granted`、`checkpoint_sequence` 和 status 全部不变；
  绕过成功数为 0。
- 真实本地 Agent Server 验证 Command update、goto finalize、额外/嵌套 Resume
  和直接 Thread update_state 均无法修改挂起状态；正常 clarification、approval、
  retry 和 `COMPLETED` 仍通过。
- 公共 Graph 对 `Command(graph=Command.PARENT, ...)` 在原图与 Server copy 两条
  路径均拒绝。Agent Server 的锁定 Wire `RunCommand` 只定义 update/goto/resume，
  不提供 graph 字段，因此真实 Wire 黑盒不伪造一个未注册的 graph 控制面。

## 未完成与非目标

- 不修改 S5 的 Task Event/SSE 引用和值扫描边界；下一步由 S5 按授权修复。
- 不修改 S4 的 Studio oracle/Web/体验测试；S5 完成后由 S4 在组合 Head 上更新并
  复算本轮 Command 绕过为 0。
- 未修改公共 Contract、共享依赖、`langgraph.json`、数据库或配置；未执行真实
  Provider、网络或付费调用。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `apps/worker/src/flowpilot_worker/studio.py` | 纯 Resume Command 校验；四类状态编辑入口与 copy 保护 | S2-RUNTIME |
| `tests/runtime/security/test_studio_security.py` | Command/状态编辑原图与 copy 负例；拒绝前后状态不变；合法 Resume 正例 | S2-RUNTIME |
| `tests/runtime/integration/test_studio_agent_server_authority.py` | 真实 Agent Server Command/Thread update_state 黑盒与合法双 Resume | S2-RUNTIME |
| `tests/runtime/evidence/WP-072-studio-security-r2-HANDOFF.md` | 本交接证据 | S2-RUNTIME |

## 契约、数据库与配置变化

- 契约版本与 ContractSet：无变化；Conformance PASS。
- Migration、PostgreSQL、Redis：无变化。
- `langgraph.json`、`pyproject.toml`、`uv.lock`、`Makefile`、环境变量：无变化。
- 兼容性：合法 clarification/approval Resume 保持兼容；复合 Command 和状态编辑
  API 从可写收窄为明确拒绝，这是本 P1 的预期安全变化。

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| Studio 定向安全/集成/真实 Server | PASS；63 passed | Command、copy、四类 update_state、双 Interrupt/Resume、Retry |
| 真实 Agent Server 权威黑盒 | PASS；1 passed | update/goto/额外或嵌套 Resume、直接 update_state 绕过 0；合法终态通过；进程/端口/运行目录清理 |
| `.\scripts\quality.ps1 lint` | PASS | Ruff；strict Mypy 125 source files |
| `uv run --all-packages --all-groups --locked python -B -m pytest tests/runtime -q` | PASS；239 passed、1 explicit online skip | 在线 Provider Smoke 未获授权，保持关闭 |
| `.\scripts\quality.ps1 test-contract` | PASS | 20 schemas / 35 cases / 43 semantic cases / 52 features |
| `.\scripts\quality.ps1 test-security` | PASS；156 passed | 含全仓高置信 Secret 扫描 |
| `.\scripts\quality.ps1 audit` | PASS | 0 known vulnerabilities；editable Workspace 包按入口定义跳过 |
| 全仓排除 S4 待更新 Studio oracle | PASS；919 passed、1 explicit online skip | `--ignore=tests/acceptance/studio`；真实 Server Runtime 测试包含在内 |
| `git diff --check`、路径范围、运行目录 | PASS | 仅 S2 授权路径；`.langgraph_api` 不存在 |

## 安全与失败路径

- Command 负例：update 注入 approval/checkpoint、goto finalize、graph parent、额外
  approval 字段、嵌套 confirmed、字符串 approved、敏感 token、空 Command。
- 状态 API 负例：同步/异步单步与 bulk update，原图与 Agent Server copy 共 8 种
  组合；真实 Thread update_state 失败后使用新连接复读，挂起状态与 5 条历史不变。
- 正例：confirmed=true、approved=true、approved=false；真实双 Interrupt/Resume、
  Handoff、一次 Retry、Checkpoint sequence=4 与终态均保持。
- Secret/PII：Security/Secret 门禁 PASS；真实凭据、业务正文、隐藏思维链和外部
  Provider 调用均为 0。

## 已知问题

- P2：锁定 Agent Server 将 Graph 的 `aupdate_state` 异常映射为通用 HTTP 500；
  S2 公共 Graph 仍提供稳定 `GRAPH_STUDIO_STATE_EDIT_FORBIDDEN`，且真实 Server
  状态/历史严格不变。若未来产品需要面向浏览器展示专用 4xx 错误，应由 API/体验
  工作包定义公开错误映射，不能开放状态编辑来换取友好响应。
- P2：Agent Server Wire `RunCommand` 不含 `graph` 字段；S2 已保护 LangGraph 公共
  `Command.graph`。锁定 Agent Server 对未知 Wire 字段的处理不作为业务控制面，S4
  应只按公开 SDK/Schema 构造请求。

## 学习候选

```text
LEARNING_CANDIDATE=LangGraph Resume 必须验证完整 Command 控制面
MATURITY=VERIFIED
TRIGGER=合法 resume 与 update/goto 可在同一 Command 中提交，绕过后续 Approval Interrupt；状态编辑 API 又绕过 stream ingress guard
MECHANISM=只校验 resume payload 不会移除 Command 的 update/goto/graph 权威能力；Agent Server 还会 copy Graph 并从独立 update_state 路径写 Checkpoint
STRUCTURE=纯 Resume 闭集校验 + 四类状态编辑入口拒绝 + guard 随 CompiledStateGraph.copy 传播 + 拒绝前后全状态/历史指纹比较
EVIDENCE=tests/runtime/security/test_studio_security.py；tests/runtime/integration/test_studio_agent_server_authority.py；WP-072-studio-r2 提交
RESIDUAL_RISK=LangGraph API/Runtime 升级后必须重验 Wire Command 映射和 copy/update_state 装配路径
TARGET=ENGINEERING_PLAYBOOK LangGraph Interrupt/Resume 权威边界候选
```

## 接收会话下一步

1. 核验 S2 `NEW_HEAD`、本文件 SHA256、ContractSet、线性祖先、分支、授权路径与
   clean，只用 `--ff-only` 到达精确 Head。
2. 执行 `M7-09R2-S5-SSE-REF-VALUE / WP-072-sse-r2`：对所有合法 `*_ref`
   非空值执行 opaque URI 约束，并对 Envelope 顶层和 payload 任意嵌套字符串执行
   高置信敏感值扫描；TaskEvent/EventStream/SSE 三层一致失败关闭且写入为 0。
3. S5 PASS 后只唤醒 S4 恢复原 `WP-072-a1`，由 S4 组合复算 Command 绕过、敏感
   ref SSE、跨租户 SSE 均为 0。
4. P0/P1、Contract 变化、路径越权、新门禁失败或必须改变公共 task-event.v1 时
   停链上报 S1；不得绕过或扩大范围。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M7-LOCAL-PRODUCT-01
STEP_ID=M7-08R2-S2-STUDIO-RESUME-AUTHORITY
ATTEMPT_ID=WP-072-studio-r2
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=cabf4512c017efc8fd033cc641c204f13e336050
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/runtime/evidence/WP-072-studio-security-r2-HANDOFF.md
NEXT_ROLE=S5-CORE
NEXT_ATTEMPT_ID=WP-072-sse-r2
ESCALATE_TO_S1=no
```

## 可回滚方式

- Revert 本 Handoff 所在提交；禁止 reset、rebase 或 force-push。
