# WP-040-a5 S1 M2 Studio 最终集成评审

## 裁决

```text
SESSION_ROLE=S1-ARCH
CHAIN_ID=CHAIN-M2-STUDIO-01
WORK_PACKAGE=WP-040
ATTEMPT_ID=WP-040-a5-S1-FINAL
VERDICT=ACCEPT_M2_STUDIO_CANDIDATE
VALIDATED_S7_HEAD=9e934460390414477a37209b077e0d9748aa7e23
CONTRACT_CONTENT_DIGEST=sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc
P0_P1_BLOCKERS=none
MERGED_TO_MASTER=no
RELEASED=no
FROZEN=no
USER_GATE_REQUIRED=yes
```

S1 接受本候选进入用户合并门禁。该裁决证明 FlowPilot 已形成可由本地
Agent Server 加载和自动化复现的 Studio 安全开发入口，可以观察稳定拓扑、
路由、Interrupt/Resume、并行只读、Handoff、重试、预算、Checkpoint 与
安全状态投影。它不代表生产 Profile、真实 Provider、完整业务工具闭环、
120/36 数据集或发布验收已经完成。

## 输入与线性候选

| 输入 | Head |
|---|---|
| M2 激活主分支 | `31f244c7ab28f8c635cc973dab1f591b55105429` |
| S5 Workspace/Lock | `c6b250e3b3a5b7df93b60857b5ee438027ee2ff3` |
| S2 Runtime/Studio | `cf5102d1ff66d3fd04362d68f48a6aba9b32acfa` |
| S4 Quality Black-box | `8a351326ad33db195098ffd4c2f8a4b9f6b5a598` |
| S7 Integration | `9e934460390414477a37209b077e0d9748aa7e23` |

S1 已证明上述 Heads 构成单父线性链，所有参与 Worktree 洁净。S5、S2、
S4、S7 各自增量只包含授权路径；S7 Handoff、Proof 和 Contract Digest
与唤醒信封精确一致，`git diff --check` 通过。

## S1 独立复现

S1 在独立 `codex/s1/wp-040-final-gate` 分支和全新锁定环境复现：

| 门禁 | 结果 |
|---|---|
| M2 S1 Final Verifier | PASS：43/43 |
| Core + Runtime + Data + Platform | PASS：213 |
| Acceptance / Studio Agent Server | PASS：65 |
| Integration | PASS：32 |
| Contract Conformance | PASS：20 Schema、43 个语义负例、52 Feature |
| 影响范围 Ruff | PASS |
| 严格 Mypy | PASS：19 个关键源文件 |
| Handoff / Proof Hash | PASS |
| 分支祖先、线性父链与路径所有权 | PASS |
| `git diff --check` | PASS |

S7 对同一产品候选完成了 RELEASE 档复现，包括 14 Wheel、锁定环境重装、
依赖审计、Secret Scan、真实 Agent Server、隔离 Compose、Migration、
RLS、PostgreSQL Adapter、Redis 丢失恢复和资源清理。S1 未重复执行不改变
候选身份的完整 Wheel/Compose 发布演练。

## 架构与安全结论

- 根 `langgraph.json` 只暴露稳定图 ID `flowpilot_it_service`，默认使用
  `studio-safe`，关闭外部网络、远程 Trace、自动浏览器和公网 Tunnel。
- Worker 与 Studio 都调用 `build_flowpilot_it_service_graph`；图 ID、
  factory ID、拓扑摘要和分叉负例能确定性检查。
- Studio 安全入口只装配合成租户、Fake Read-only 工具和无权威副作用的
  场景。`production` 与尚未装配可信端口的 `studio-integration` 均失败关闭。
- `debug_projection` 是闭合白名单；Task、Tenant、Approval、Lease Token、
  SecurityContext、工具 Payload、Provider Session、Secret、原始 Context
  和未来未知字段不会透出。
- Studio Thread/Run 只作为本地调试游标。PostgreSQL Task、Checkpoint、
  Lease 和执行账本仍是业务恢复与副作用事实源。
- 两次 Interrupt/Resume、并行只读、Handoff、retry 和最终状态均由真实
  Agent Server API 黑盒复现；编辑权威字段和 Profile 绕过失败关闭。
- 本轮所有写工具仍是合成 proposal/read-only 路径，没有把 Studio 变成
  MCP Gateway、策略或审批旁路。

生产 Runtime 当前共享完整稳定拓扑，但部分业务节点仍是显式
`unsupported_boundary`，只允许已经装配的路由实际进入。Studio 中展示的
完整演示路径属于 `studio-safe` 合成行为，不得表述为真实 IT 工单闭环已经
完成。

## 保留项

| 级别 | 事项 | Owner | 影响 |
|---|---|---|---|
| P2 | `make acceptance` 尚未实现 | S4/S5 | 阻断发布级一键验收 |
| P2 | Windows GNU Make 配合绝对 `UV` 覆盖时 `make studio-smoke` ENV_BLOCKED | S5 | 两条等价锁内命令与真实 Server 已通过；需改进跨平台入口 |
| P2 | Acceptance 中继承 4 个 I001 | S4 | 不在 M2 变更路径；后续统一关闭 |
| P2 | `studio-integration` 可信端口尚未装配 | S2/S3/S6 | 当前失败关闭，不阻断 safe Profile |
| P2 | 宿主已有默认 2024 Listener | Workspace Owner | 不属于本 Attempt；运行默认 `make studio` 前需确认资源 Owner |
| P2 | Traceability 仍是设计期映射 | S1/S4 | 不提升 Feature 到 `VERIFIED` |

这些事项不构成 M2 Studio 安全开发候选的 P0/P1，但共同阻断产品
`RELEASED`。当前数据集、真实 Provider、业务 E2E 和量化指标状态保持不变。

## 学习结论

本轮验证确认：本地服务清理必须绑定本次 Attempt 的根 PID、完整进程树、
随机端口和运行目录。测试不能因为发现预存 Listener 就终止其他会话资源，
也不能只检查固定端口或根进程。该经验已写入
[`ENGINEERING_PLAYBOOK.md`](../architecture/ENGINEERING_PLAYBOOK.md#414-本地开发服务器测试通过却误判或遗留了别人的进程)。

## 用户门禁

主分支仍停留在 M2 激活提交，链路状态为
`PAUSED / USER_GATE_REQUIRED`。用户明确选择继续后，S1 才能将精确最终
候选快进到主分支，并在主分支复跑 FAST final gate；本评审不自动合并、
不自动启动下一条开发链。

## 用户门禁结果

```text
USER_DECISION=CONTINUE
MERGED_TO_MASTER=yes
MERGED_CANDIDATE_HEAD=ec4fe48ed265dcdbe11b8d0aa8580dea7423ce01
MERGE_MODE=FAST_FORWARD_ONLY
POST_MERGE_FAST_GATE=43/43_PASS
RELEASED=no
FROZEN=no
NEXT_CHAIN_STARTED=no
```

该段记录用户门禁后的事实，不改写上方评审发生时的历史裁决。后续控制面
提交可以位于候选 Head 之后，但不得改变已接受产品树的身份。
