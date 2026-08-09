# WP-072-studio-r3 S2-RUNTIME Interrupt 绑定交接

## 基本信息

- Work Package：WP-072
- Attempt ID：WP-072-studio-r3
- Chain ID：CHAIN-M7-LOCAL-PRODUCT-01
- Step ID：M7-08R3-S2-STUDIO-INTERRUPT-BINDING
- 责任会话：S2-RUNTIME
- 接收会话：S5-CORE
- 交接策略：CONSUMER_GATE
- 功能 ID：FP-FLOW-002、FP-FLOW-004、FP-OBS-001
- 基线/输入提交：`7dacd8010d2654b681389bae46efabfabc64ff5a`
- 分支：`codex/s2/wp-070-provider-runtime-adapters`
- 最终提交：本文件所在提交；精确 SHA 由唤醒信封返回
- ContractSet 摘要：
  `sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 状态：PASS_HANDOFF

## 完成内容

- 保留 r2 的纯 Resume Command 闭集门禁，并新增当前 Checkpoint 快照绑定：在调用
  Pregel 前读取唯一 `next`、Task name 与 `Interrupt.value.kind`，三者必须一致，
  Resume 形状必须与当前 Interrupt 对应。
- `clarification_interrupt` 只接受精确 `{"confirmed": true}`；
  `approval_interrupt` 只接受精确 `{"approved": <bool>}`。旧 clarification
  Resume 重放到 approval、approval Resume 提前发送到 clarification 均以
  `GRAPH_STUDIO_STATE_EDIT_FORBIDDEN` 失败关闭。
- 保留两个节点恢复后的第二道精确校验。即使未来绕过 ingress，也必须在
  `_advance`、`approval_granted`、`failure_code` 或终态写入前拒绝 kind/形状不匹配。
- 首轮仅在节点内校验的定向测试证明会消费 pending Interrupt、使 `next` 变空；已
  据此将主门禁前移。最终拒绝前后 values 指纹、next、当前 Interrupt kind、
  checkpoint sequence、history 数量和 pending writes 完全一致。
- 正常 confirmed、approved=true、approved=false 保持可用；approved=false 仍是
  合法业务拒绝并产生 `STUDIO_APPROVAL_DENIED`，不会被误判为安全异常。
- In-memory 原图/copy 与真实 Agent Server 均覆盖；旧 Resume 重放不会创建新
  Checkpoint、终态、Artifact 或 failure code，绕过成功数为 0。

## 未完成与非目标

- 不修改 S5 Task Event/SSE Token family；下一步由 S5 按授权集中扩展凭据语法族。
- 不修改 S4 Studio oracle/Web/验收生成器；S5 完成后由 S4 在组合 Head 上更新并
  复算。
- 未修改公共 Contract、共享依赖、数据库、配置或 `langgraph.json`；未执行真实
  Provider、外部网络或付费调用。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `apps/worker/src/flowpilot_worker/studio.py` | Checkpoint/Task/Interrupt 快照绑定；节点二次 Resume 校验 | S2-RUNTIME |
| `tests/runtime/security/test_studio_security.py` | 两类错序 Resume 原图/copy 不变性与合法路径回归 | S2-RUNTIME |
| `tests/runtime/integration/test_studio_agent_server_authority.py` | 真实 Server 错序重放、当前 kind、不变性及 approved=false 正例 | S2-RUNTIME |
| `tests/runtime/evidence/WP-072-studio-security-r3-HANDOFF.md` | 本交接证据 | S2-RUNTIME |

## 契约、数据库与配置变化

- 契约版本与 ContractSet：无变化；Conformance PASS。
- Migration、PostgreSQL、Redis：无变化。
- `langgraph.json`、`pyproject.toml`、`uv.lock`、`Makefile`、环境变量：无变化。
- 兼容性：注册的 Resume 与合法业务拒绝不变；跨 Interrupt kind 的旧 Resume
  重放从错误推进状态收窄为执行前拒绝。

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| Studio 定向安全/集成/真实 Server | PASS；67 passed | 原图/copy、错序 Resume、完整状态不变、双 Interrupt、approved false |
| 真实 Agent Server authority 黑盒 | PASS；1 passed | approval 提前、旧 confirmed 重放、额外/嵌套 Resume、update/goto/update_state、合法 true/false |
| `.\scripts\quality.ps1 lint` | PASS | Ruff；strict Mypy 125 source files |
| `uv run --all-packages --all-groups --locked python -B -m pytest tests/runtime -q` | PASS；243 passed、1 explicit online skip | 在线 Provider Smoke 未获授权，保持关闭 |
| `.\scripts\quality.ps1 test-contract` | PASS | 20 schemas / 35 cases / 43 semantic cases / 52 features |
| `.\scripts\quality.ps1 test-security` | PASS；160 passed | 含全仓高置信 Secret 扫描 |
| `.\scripts\quality.ps1 audit` | PASS | 0 known vulnerabilities；editable Workspace 包按入口定义跳过 |
| 全仓排除 S4 待更新 Studio oracle | PASS；967 passed、1 explicit online skip | `--ignore=tests/acceptance/studio`；包含 S5 r2 与真实 Server Runtime 测试 |
| `git diff --check`、路径范围、运行目录 | PASS | 仅 S2 授权路径；`.langgraph_api` 不存在 |

## 安全与失败路径

- 错序负例：approval Resume 提前交给 clarification；旧 confirmed Resume 在
  approval 阶段重放。
- 结构负例：额外键、嵌套值、字符串布尔、敏感键、空 Resume、Command update、
  goto、graph、四类 update_state；r2 门禁继续通过。
- 拒绝不变性：唯一 next、当前 Interrupt kind、完整 values、checkpoint sequence、
  history count、pending writes、approval_granted、failure_code、Artifact 和 status。
- 正例：confirmed=true、approved=true、approved=false；真实双 Interrupt/Resume、
  Handoff、Retry、Checkpoint sequence=4 与终态保持。
- Secret/PII：Security/Secret 门禁 PASS；真实凭据、正文、隐藏思维链和外部调用均
  为 0。

## 已知问题

- P2：Resume ingress 在执行前读取一次 Checkpoint 快照并由 LangGraph 自身在后续
  执行中维持线程一致性；若未来启用不同的并发/多任务策略，必须复跑同 Thread
  竞争与 stale Resume 黑盒。
- P2：S4 旧 Studio oracle 仍待其所有者按已授权语义更新；不得恢复图内错误状态来
  兼容旧断言。
- 返修预算：本轮已经采用集中快照绑定与节点二次验证。若相同 Resume kind 再出现
  等价绕过，必须停链向 S1 提议集中式安全验证器重构，不继续第四次样本补丁。

## 学习候选

```text
LEARNING_CANDIDATE=Resume 结构合法不等于当前 Interrupt 合法
MATURITY=VERIFIED
TRIGGER=confirmed=true 结构上是合法 Resume，但在 approval 挂起点重放时被解释为 approved=false 并写入业务拒绝终态
MECHANISM=Ingress 仅验证 Command 闭集，节点只检查自身字段值；缺少 Checkpoint next、Task 与 Interrupt.kind 的联合绑定。只在节点抛错又会消费 pending Interrupt
STRUCTURE=执行前读取 Checkpoint 快照并联合验证唯一 next/Task/Interrupt.kind/Resume；节点恢复后再次验证，拒绝前后复算完整状态与历史
EVIDENCE=tests/runtime/security/test_studio_security.py；tests/runtime/integration/test_studio_agent_server_authority.py；WP-072-studio-r3 提交
RESIDUAL_RISK=并发策略或 LangGraph Checkpointer 语义升级需重验快照到执行的绑定
TARGET=ENGINEERING_PLAYBOOK LangGraph Interrupt/Resume 权威边界候选
```

## 接收会话下一步

1. 核验 S2 `NEW_HEAD`、本文件 SHA256、ContractSet、线性祖先、分支、授权路径与
   clean，只用 `--ff-only` 到达精确 Head。
2. 执行 `M7-09R3-S5-SSE-TOKEN-FAMILY / WP-072-sse-r3`：将凭据扫描实现为明确
   Token 语法族，覆盖 OpenAI `sk-`/`sk-proj-`/`sk-svcacct-`、Slack 分段
   `xox[baprs]-`、GitHub、Bearer/Basic、AWS、私钥头、JWT 与 key=value；扫描
   所有可输出字符串和 payload/ref 任意嵌套字符串。
3. 保留 opaque URI、字段名、Schema、Tenant 门禁和合法业务 ID；在构造、emit、
   replay/subscriber、SSE Frame 写入前一致拒绝，污染数为 0。
4. S5 PASS 后只唤醒 S4 恢复 `WP-072-a1`。若再次出现等价 Token family 绕过，按
   返修预算停链向 S1 提议集中验证器重构，不追加第四次样本正则。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M7-LOCAL-PRODUCT-01
STEP_ID=M7-08R3-S2-STUDIO-INTERRUPT-BINDING
ATTEMPT_ID=WP-072-studio-r3
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=7dacd8010d2654b681389bae46efabfabc64ff5a
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/runtime/evidence/WP-072-studio-security-r3-HANDOFF.md
NEXT_ROLE=S5-CORE
NEXT_ATTEMPT_ID=WP-072-sse-r3
ESCALATE_TO_S1=no
```

## 可回滚方式

- Revert 本 Handoff 所在提交；禁止 reset、rebase 或 force-push。
