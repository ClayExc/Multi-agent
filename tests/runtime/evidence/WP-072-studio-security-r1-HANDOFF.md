# WP-072-studio-r1 S2-RUNTIME Studio 权威边界修复交接

## 基本信息

- Work Package：WP-072
- Attempt ID：WP-072-studio-r1
- Chain ID：CHAIN-M7-LOCAL-PRODUCT-01
- Step ID：M7-08R-S2-STUDIO-AUTHORITY
- 责任会话：S2-RUNTIME
- 接收会话：S4-QUALITY
- 交接策略：CONSUMER_GATE
- 功能 ID：FP-FLOW-002、FP-FLOW-004、FP-OBS-001、FP-OBS-002
- 授权基线提交：`f1c911c7a8605958947b9f01ad38a86781d89418`
- 消费输入提交：`7185eae7b96234ee9d75f064fcb89e934a151834`
- 分支：`codex/s2/wp-070-provider-runtime-adapters`
- 最终提交：本文件所在提交；精确 SHA 由唤醒信封返回
- ContractSet 摘要：
  `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：PASS_HANDOFF

## 完成内容

- 将新 Studio Thread 的初始输入收窄为显式 allowlist：只允许注册的
  `scenario`；`profile`、`visited_nodes`、`debug_projection`、计数、运行状态、
  Tenant、凭据、隐藏思维链及所有未知字段在进入 Pregel 前失败关闭。
- 对输入中的 Mapping/Sequence 递归检查敏感或权威键；连字符、空格和大小写变体
  统一归一化后检查，避免 `tenant-id`、`access-token`、`chain-of-thought` 等变体
  绕过。
- 为真实 Agent Server 使用的 `CompiledStateGraph.copy(update=...)` 路径保留同一
  ingress guard。非法输入返回稳定 `GraphError`，Run 状态为 `error`；Thread
  values、next、history 和 Checkpointer pending writes 均为空。
- `_append_visits` 对 reducer 左右两侧的每个节点执行注册表校验；浏览器节点、拼写
  变体和损坏的持久化节点均拒绝。
- `_merge_frames` 对左右两侧每个 Frame 执行完整闭集、嵌套字段、类型、标识绑定、
  JSON 安全和大小校验。同 `frame_id` 仅允许同规范指纹幂等重放；不同内容碰撞失败
  关闭，不再 last-write-wins。
- 保留原 LangGraph 拓扑、真实 Interrupt/Resume、Checkpoint、Handoff、Retry 和
  服务端安全投影；没有把 Studio 变为业务事实源或授权入口。

## 未完成与非目标

- S4 所有的 `artifacts/acceptance/generators/studio_agent_server.py` 仍按旧语义断言：
  拒绝后应存在 `step_count=0`、空数组和 `next=[prepare]`，并把未知浏览器字段静默
  丢弃后完成。新安全边界要求拒绝发生在 Pregel/Checkpointer 之前，因此 S4 必须
  更新为：稳定 `__error__`、空 Thread state/history、未知字段同样拒绝。
- 未修改 `tests/acceptance/**`、`artifacts/acceptance/**`、公共 Contract、共享依赖或
  S5/S3 边界；未执行真实 Provider、网络或付费调用。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `packages/graph/src/flowpilot_graph/debug.py` | Studio 输入递归 allowlist；Frame 完整校验与规范指纹 | S2-RUNTIME |
| `packages/graph/src/flowpilot_graph/__init__.py` | 导出 Frame 校验与指纹函数 | S2-RUNTIME |
| `apps/worker/src/flowpilot_worker/studio.py` | Agent Server copy-safe ingress guard；节点与 Frame reducer 失败关闭 | S2-RUNTIME |
| `tests/runtime/security/test_studio_security.py` | 输入注入、持久化损坏、碰撞、零保留及 Server copy 负例 | S2-RUNTIME |
| `tests/runtime/evidence/WP-072-studio-security-r1-HANDOFF.md` | 本交接证据 | S2-RUNTIME |

## 契约、数据库与配置变化

- 契约版本：无变化；ContractSet Conformance PASS。
- Migration、数据库、Redis：无变化。
- `langgraph.json`、`pyproject.toml`、`uv.lock`、`Makefile`、环境变量：无变化。
- 兼容性：合法 `scenario` 与 `Command` Resume 保持兼容；此前被静默丢弃的未知或
  权威浏览器字段改为显式失败关闭，这是本 P1 的预期安全收窄。

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| 定向 Studio Runtime/安全测试 | PASS；37 passed | 包含直接图与 Agent Server `copy(update=...)` 零 Checkpoint/零 pending write |
| 真实本地 `langgraph dev` + SDK 负向探针 | PASS | `__error__={error: GraphError, message: Studio input cannot select another execution profile}`；Run=`error`；state/history 均空；端口释放 |
| `.\scripts\quality.ps1 lint` | PASS | Ruff PASS；strict Mypy 125 source files |
| `uv run --all-packages --all-groups --locked python -B -m pytest tests/runtime tests/core -q` | PASS；334 passed、1 explicit online skip | 在线 Provider Smoke 仍需显式授权 |
| `.\scripts\quality.ps1 test-contract` | PASS | 20 schemas / 35 cases / 43 semantic cases / 52 features |
| `.\scripts\quality.ps1 test-security` | PASS；131 passed | 含全仓高置信 Secret 扫描 |
| `.\scripts\quality.ps1 audit` | PASS | 0 known vulnerabilities；editable Workspace 包按入口定义跳过 |
| 全仓排除 S4 旧 Studio oracle | PASS；893 passed、1 explicit online skip | `--ignore=tests/acceptance/studio` |
| `tests/acceptance/studio` | EXPECTED_CONSUMER_UPDATE；4 fixture setup errors | Server 已返回稳定错误且 state 为空；旧 S4 oracle 将“空 state”误判为执行推进 |
| `git diff --check`、路径范围、`.langgraph_api` 清理 | PASS | 仅 S2 授权路径；本地 Runtime 目录不存在 |

## 安全与失败路径

- 已验证负向路径：伪造 profile、frame_id、Tenant、凭据、reasoning、visited node、
  未知字段、嵌套键变体、损坏的 reducer 左侧 Frame、右侧未注册节点、同 ID 不同
  Frame、非法计数和非法 Frame 结构。
- 已验证恢复边界：相同 Frame 指纹可幂等重放；合法 Interrupt/Resume 和普通
  Checkpoint 路径不变；拒绝输入不会创建可恢复的恶意状态。
- Secret/PII：Security/Secret 门禁 PASS；真实凭据、正文、ACL、隐藏思维链和付费
  Provider 调用均为 0。

## 已知问题

- P2：安全门禁依赖锁定 LangGraph Agent Server 对
  `CompiledStateGraph.copy(update=...)` 的装配路径；当前真实 Server 与离线 copy
  测试均已证明。升级 LangGraph API/Runtime 时必须复跑真实 Server 门禁。
- P2：S4 验收生成器尚未表达“输入拒绝前零持久化”的新语义；这不应通过恢复旧的
  图内错误状态解决，否则会重新把恶意原始输入写入 pending writes。

## 学习候选

```text
LEARNING_CANDIDATE=LangGraph TypedDict 输入过滤不是安全边界
MATURITY=VERIFIED
TRIGGER=未知 Studio 字段被 TypedDict 静默丢弃；在 reducer 内拒绝时 Pregel pending writes 已保存原始输入
MECHANISM=State channel 过滤发生在执行装配内，节点/reducer 校验晚于 Agent Server Checkpointer 写入；Agent Server 又会 copy 已注册的 CompiledStateGraph
STRUCTURE=在 Pregel/Checkpointer 前对 stream/astream 执行显式 allowlist，并使 guard 随 CompiledStateGraph.copy 传播；reducer 继续校验持久化左右两侧
EVIDENCE=tests/runtime/security/test_studio_security.py；真实本地 Agent Server 探针；WP-072-studio-r1 提交
RESIDUAL_RISK=LangGraph Server 装配 API 升级后需重新验证 copy/stream 路径
TARGET=ENGINEERING_PLAYBOOK LangGraph Studio 输入权威边界候选
```

## 接收会话下一步

1. 核验 S2 `NEW_HEAD`、本文件 SHA256、ContractSet、线性祖先、分支、授权路径与
   clean，只用 `--ff-only` 到达精确 Head。
2. 在 S4 路径更新 Studio Agent Server oracle：非法 profile、未知/敏感/权威字段
   必须返回稳定 `__error__`，并断言 Thread values/next/history 全空；不得期待
   `prepare` 初始 Checkpoint，也不得继续静默丢弃后完成。
3. 复跑真实 Graph 注册、拓扑、合法双 Interrupt/Resume、Checkpoint 对齐、安全
   投影和清理黑盒；继续验证 SSE/Event 的 S5 P0 修复。
4. P0/P1、Contract/S3 边界、越权路径、新门禁失败或未授权外部调用立即停链上报
   S1；正常按原 `WP-072-a1` 继续。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M7-LOCAL-PRODUCT-01
STEP_ID=M7-08R-S2-STUDIO-AUTHORITY
ATTEMPT_ID=WP-072-studio-r1
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=7185eae7b96234ee9d75f064fcb89e934a151834
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/runtime/evidence/WP-072-studio-security-r1-HANDOFF.md
NEXT_ROLE=S4-QUALITY
NEXT_ATTEMPT_ID=WP-072-a1
ESCALATE_TO_S1=no
```

## 可回滚方式

- Revert 本 Handoff 所在提交；禁止 reset、rebase 或 force-push。
