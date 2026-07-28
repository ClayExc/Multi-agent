# WP-000：M0 公共契约冻结

## 元数据

- 状态：IN_PROGRESS（实现基线已评审，发布冻结待质量资产）
- 责任会话：S1-ARCH
- 评审会话：S2-RUNTIME、S3-PLATFORM、S4-QUALITY、S5-CORE、S6-DATA
- 功能 ID：FP-FLOW-001、FP-FLOW-009、FP-AGT-001、FP-AGT-002、FP-CTX-001、FP-MCP-002、FP-MCP-005、FP-APR-001、FP-SEC-001、FP-SEC-004、FP-DATA-001、FP-DATA-003、FP-OBS-001、FP-OBS-002、FP-OBS-003、FP-EVAL-001、FP-EVAL-002、FP-EVAL-003
- 依赖工作包：无
- 目标分支：`codex/s1-arch/wp-000-m0-contract-freeze`

## 目标

- 为 M0 冻结 Task、Command、Event、Tool、Approval、Audit 及其必要依赖的唯一公共 JSON Schema。
- 明确命令并发、事件投递、授权决策和安全上下文引用语义。
- 为五个实现会话提供可审查、可生成测试的输入契约。

## 非目标

- 实现 Python 数据模型、API、LangGraph、数据库表或 MCP Gateway。
- 把任何功能状态更新为 `IMPLEMENTED` 或 `VERIFIED`。
- 冻结 OpenAPI、具体 MCP Server 能力或数据库物理 Schema。

## 允许修改路径

- `contracts/**`
- `docs/architecture/**`
- `docs/decisions/**`
- `docs/acceptance/**`
- `docs/team/**`
- `README.md`
- `STRUCTURE.md`
- `.gitattributes`

## 输入契约

| 契约 | 版本 | 提供者 |
|---|---|---|
| 架构不变量 | 当前基线 | S1-ARCH |
| 验收定义与追踪矩阵 | 当前基线 | S1-ARCH |
| M0 实施范围 | 当前基线 | S1-ARCH |

## 输出契约

| 契约 | 版本 | 消费者 |
|---|---|---|
| `contracts/contract-set.v1.json` | `1.0.0-rc.2` candidate → implementation baseline → frozen | S2、S3、S4、S5、S6 |
| Task / Command / Event JSON Schema | v1 | S2、S4、S5、S6 |
| Tool / Approval / Policy JSON Schema | v1 | S3、S4、S5、S6 |
| Agent Runtime / Context JSON Schema | v1 | S2、S4 |
| Audit / Security Event JSON Schema | v1 | S3、S4 |
| Evaluation / Dataset / Fixture / Registry / Traceability JSON Schema | v1 | S4 |
| ContractSet / Review Attestation JSON Schema | v1 | S2、S3、S4、S5、S6 |
| ADR-0001～0004 | Accepted | S2、S3、S4、S5、S6 |

## 架构与安全约束

- LangGraph 是唯一跨业务节点的持久化状态机；Task 是外部投影。
- Command 不能设置内部节点或直接宣告终态。
- SecurityContext 只按受信引用传递，公共对象不得携带凭据。
- PolicyDecision 只能由确定性 PDP 产生。
- Event 至少一次投递，消费者去重并检测任务内序号缺口。
- 写动作继续受 ADR-0002 的审批、幂等、`UNKNOWN` 和回读协议约束。

## 实施内容

1. 补齐并校验 M0 公共 Schema。
2. 发布带文件哈希的候选契约集。
3. 记录 Task/Command/Event 一致性 ADR。
4. 更新功能追踪矩阵。
5. 创建 S2、S3、S4、S5、S6 M0 工作包。
6. 收集五会话可实现性结论并处理 RFC。
7. rc1 被原三方拒绝后发布 rc2，并要求五个实现角色针对稳定 `content_digest` 重新复审。
8. 固定 120/36 配额、Dataset/Fixture 哈希、Feature 结构化证据和 Audit 链前像。

## 必须测试

- 正常路径：所有 Schema 可由 Draft 2020-12 Validator 加载。
- 边界条件：可选字段和合法终态被接受。
- 失败路径：额外字段、错误枚举、缺失必填和错误条件组合被拒绝。
- 安全负向：明文凭据不能由 SecurityContextRef 表达；`require_approval` 缺少审批要求被拒绝。
- 恢复/幂等：Command 具备版本和幂等语义；Event 具备序号和去重标识。
- 状态负向：Task、Approval、ToolResult 的矛盾字段组合被拒绝。
- 生产者负向：未授权服务不能产生任务终态事件，阻断 Audit 必须关联 SecurityEvent。
- 评测负向：未知 Feature、Category、Assertion、Rubric 和漂移的 Registry Hash 被拒绝。
- 证据负向：任意字符串、跨 Feature ID、缺失文件、错误哈希和同角色自验不能提升 Feature 状态。
- 冻结负向：内容摘要漂移、Review 摘要错配、PENDING/REJECT 或未冻结依赖不能冻结契约集。
- Audit 链负向：正文篡改、序号缺口、重复序号和跨 Stream 串链被拒绝。

## 验收命令

```bash
# 当前仓库尚未提供稳定 make 命令；在 WP-010 前只能运行底层 Schema/文档校验。
# make test-contract 尚未实现
python contracts/conformance/validate.py
```

## 证据

- 候选契约：`contracts/contract-set.v1.json`
- 架构决定：`docs/decisions/ADR-0001-orchestration-boundary.md`、`ADR-0002-safe-side-effects.md`、`ADR-0003-task-command-event-protocol.md`、`ADR-0004-reproducible-acceptance-and-freeze.md`
- rc1 裁决：`docs/review/WP-000-RC1-DISPOSITION.md`
- rc2 底层用例：`contracts/conformance/rc2-cases.json`
- rc2 实现基线证明：`docs/review/WP-000-RC2-IMPLEMENTATION-BASELINE.md`
- rc2 Review Evidence：`docs/review/attestations/RC2-0A82-*.md`

## 完成定义

- 中间里程碑：S2/S3/S4/S5/S6 对同一 `content_digest` 全部 ACCEPT 后，rc2 candidate 成为实现基线，WP-010/011/020/021/030 可在独立 Git Worktree 中启动。
- 契约清单中的哈希与文件一致。
- JSON 语法和 Draft 2020-12 编译通过。
- S2、S3、S4、S5、S6 均确认可实现，或所有阻塞 RFC 已裁决。
- 契约集状态更新为 `frozen`，本工作包状态更新为 `DONE`。
- 功能状态仍为 `DESIGNED`，直到实现与自动化证据齐备。
