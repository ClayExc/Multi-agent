# WP-040-a4 S1 M1 Platform 最终集成评审

## 裁决

```text
SESSION_ROLE=S1-ARCH
CHAIN_ID=CHAIN-M1-PLATFORM-01
WORK_PACKAGE=WP-040
ATTEMPT_ID=WP-040-a4
VERDICT=ACCEPT_M1_PLATFORM_CANDIDATE
VALIDATED_S7_HEAD=197a2eaafa354c590e8a130c4a1118cf0f0035d3
VALIDATED_COMPOSITION_HEAD=edc18fe37fdfd2e971908ee7f0264a41bd2e235c
CONTRACT_CONTENT_DIGEST=sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc
P0_P1_BLOCKERS=none
MERGED_TO_MASTER=no
RELEASED=no
FROZEN=no
USER_GATE_REQUIRED=yes
```

S1 接受本候选进入用户合并门禁。该裁决证明 MCP Gateway、Policy、
Security、只读模拟 MCP、Workspace/Lock、安全黑盒和集成证据形成可安装、
可测试、可恢复、可观察的 M1 平台切片。它不代表生产身份、真实企业 MCP、
完整 Audit Sink、120/36 数据集或产品发布已经完成。

## 输入与组合

| 输入 | Head |
|---|---|
| 当前 S1 控制面 | `1ae7a79dd7e0d4da819b93dfa0d916771fb0d265` |
| S3 Platform | `ff6cc282c81166317f995b975491167479aa1c8d` |
| S5 Workspace/Handoff | `192ebe38df84ed9097e4045847aa991632a2ff63` |
| S4 安全黑盒 | `31f4b8b14150bd769910f144d9116578be6124ad` |
| S7 Integration | `197a2eaafa354c590e8a130c4a1118cf0f0035d3` |
| S1 Final 组合 | `edc18fe37fdfd2e971908ee7f0264a41bd2e235c` |

S1 Final 组合只在独立分支存在。它以当前控制面和完整 S7 候选为两个父
提交，没有把不完整的 S3/S5/S4 中间状态逐个暴露到主分支。

## S1 独立复现

| 门禁 | 结果 |
|---|---|
| M1 S1 Final Verifier | PASS：37/37 |
| Core + Runtime + Data + Platform + Acceptance + Integration | PASS：279 |
| Contract Conformance | PASS：20 Schema、43 个语义负例、52 Feature |
| Offline Acceptance | PASS：2 Case、0 Findings |
| 影响范围 Ruff | PASS |
| Mypy strict | PASS：82 source files |
| Handoff / Proof Hash | PASS |
| S7 `Base..Head` 路径所有权 | PASS |
| `git diff --check` | PASS |

S7 对同一产品候选完成了 RELEASE 档组合复现：14 个 Wheel、全新离线安装、
依赖审计、Secret Scan、五服务 Compose、Migration 0002 重复应用、RLS、
PostgreSQL Adapter、Redis 丢失恢复和资源清理全部通过。S1 组合只增加
控制面合并，不改变产品树、ContractSet、`uv.lock`、Migration 或 Compose，
因此不重复创建外部 Compose 资源。

## 架构与安全结论

- Gateway 在 Ledger 占位前完成可信 SecurityContext、双主体、租户、
  Purpose/Audience、Tool Registry、Policy、Approval 与职责分离校验。
- 写路径只消费 S6 Execution Ledger/UoW；重复已验证结果回放，
  `UNKNOWN` 只进入对账，权威证明未执行后才允许继续。
- Capability 绑定 Tenant、Audience、Scope、动作摘要和短 TTL，不透传
  长期凭据。
- Gateway 生命周期能重建入口、身份、Registry、Policy、Approval、
  Ledger、Upstream、Readback、Audit/Security 与结果阶段。
- `debug_projection` 是闭合白名单；Trace 不参与授权，Audit/Security
  不采样，敏感 Context、Payload、Secret 和隐藏思维链不进入投影。
- S4 黑盒确认跨租户成功、工具旁路、重复逻辑写入和 Secret 泄漏均为 0。

## 保留项

| 级别 | 事项 | Owner | 影响 |
|---|---|---|---|
| P2 | `make acceptance` 尚未实现 | S4/S5 | 阻断发布级一键验收，不阻断 M1 候选 |
| P2 | 旧 S4 Evaluation/Observability 范围有 26 个 Ruff Findings | S4 | 不在本增量与 14 包 Workspace 内；后续统一关闭 |
| P2 | Compose 默认只自动挂载 Migration 0001 | S6 | 0002 已手工实库验证；发布前必须自动接入 |
| P2 | Audit/Security Draft 缺最终 Stream/sequence/integrity | S6/S4 | 需可信 Sink/Store，不能把草稿当最终 AuditEvent |
| P2 | Traceability 仍使用设计期测试路径与空证据引用 | S1/S4 | 本轮不擅自提升 `VERIFIED`，后续做证据映射闭包 |

这些事项不构成本候选的 P0/P1，但共同阻断 `RELEASED`。当前
`traceability.v1.json` 状态保持不变，避免只改状态、不绑定真实
`test_id/evidence_id`、文件哈希、Run 和独立验证角色。

## 学习候选

```text
LEARNING_CANDIDATE=增量基线不等于最终 Head 的直接父提交
MATURITY=IMPLEMENTED
TRIGGER=S7 在实现提交后追加 Handoff/Proof，S1 初检按 HEAD^ 比较 Base
MECHANISM=把增量区间身份和单提交父关系混为一谈会误拒绝合规证据提交
STRUCTURE=校验 Base 为祖先、Base..Head 全路径与逐提交线性关系
EVIDENCE=WP-040-a4 两个 S7 提交、37/37 S1 final verifier
RESIDUAL_RISK=未来非线性修复仍必须显式记录所有父提交与 Owner
TARGET=ENGINEERING_PLAYBOOK.md#4.12
```

## 用户门禁

主分支尚未改变，链路状态为 `PAUSED / USER_GATE_REQUIRED`。用户明确
选择继续后，S1 才能把完整 Final 候选作为一次主分支转换，并在主分支复跑
FAST final gate；否则保留候选分支和全部证据，不自动合并或启动下一链。

## 用户门禁结果

```text
USER_DECISION=CONTINUE
MERGED_TO_MASTER=yes
MERGED_CANDIDATE_HEAD=1fd14a83ae775691c4516b7bde647f7672c7f624
MERGE_MODE=FAST_FORWARD_ONLY
POST_MERGE_FAST_GATE=37/37_PASS
RELEASED=no
FROZEN=no
```

该段记录用户门禁后的事实，不改写上方评审发生时的历史裁决。后续控制面
提交可以位于候选 Head 之后，但不得改变已接受产品树的身份。
