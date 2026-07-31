# WP-020-a2 S3-PLATFORM P1 Knowledge Gateway 交接

## 基本信息

- Work Package：WP-020
- Attempt ID：WP-020-a2
- Chain ID：CHAIN-P1-VPN-READONLY-01
- Step ID：P1-VPN-02-S3
- DEDUP Key：
  `CHAIN-P1-VPN-READONLY-01/P1-VPN-02-S3/WP-020-a2/1d6870764464cd4762351e7cf278bacd8e4fbced`
- 责任会话：S3-PLATFORM
- 接收会话：S2-RUNTIME
- 交接策略：CONSUMER_GATE
- 风险等级：R2
- 功能 ID：FP-FLOW-002、FP-FLOW-003、FP-AGT-001、FP-CTX-001、
  FP-MCP-001、FP-MCP-002、FP-SEC-003、FP-EVAL-003、FP-OPS-002
- 基线 / 输入提交：
  `1d6870764464cd4762351e7cf278bacd8e4fbced`
- 实现提交：`371236a776d75fbdc81c323ba1948f0cd53012d6`
- 分支：`codex/s3/wp-020-platform-bootstrap`
- 最终提交：本文件所在提交；精确 SHA 由唤醒信封返回
- ContractSet 摘要：
  `sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`
- 状态：完成，等待 S2 消费门禁

## 授权与线性候选

- S3 原 Head `ff6cc282c81166317f995b975491167479aa1c8d` 是 S5 输入
  Head `1d6870764464cd4762351e7cf278bacd8e4fbced` 的祖先。
- S3 在干净工作树上使用 `git merge --ff-only` 精确到达 S5 Head；
  Handoff SHA 为
  `sha256:413e59aa5177827185a294f2af795fc7f86a02aa19496eab1884433f9fa66c44`。
- 消费判定为 `CONSUMER_VERDICT=ACCEPT`；未执行 rebase、reset、强制合并
  或跨分支复制。
- 实现差异严格位于 `apps/mcp-gateway/**`、
  `packages/tool-contracts/**`、`packages/security/**`、
  `mcp-servers/knowledge/**` 和 `tests/platform/**`。
- `contracts/**`、`pyproject.toml`、`uv.lock`、`Makefile`、
  Migration、S6 路径和其他角色目录均未变化。

## 完成内容

- 将 `knowledge.search.v1` 固定为 P1 只读 Tool：
  - 新 Schema Pin：
    `sha256:b7679fde5be1187e8a36b4cd4dd95a95b63a50dc56532294174b0088f0e6600b`。
  - 旧 M0 Pin
    `sha256:fa39a6eb55d2d2bf68174a47dcb00d63a58e771e7ba5e3781cde4d716a319c04`
    在 Registry 阶段失败关闭。
  - 闭合输出仅包含 `source_ref`、`document_version`、`section`、
    `redacted_summary`、`content_hash` 和 `classification`；
    不返回内部 ACL、原始正文、凭据或敏感 Context。
- 扩展短时内部 Capability 的受信绑定：
  - 用户主体、可信 ACL membership、Agent workload principal；
  - Tenant、Purpose、Scope、动作摘要和动作数据分类上限；
  - Gateway 对 Credential Broker 回执逐字段重验。
- Knowledge Adapter 使用两阶段读取：
  1. 只读取元数据完成双主体、Tenant、Purpose、`knowledge.search`
     Scope、分类、ACL 和有效期过滤；
  2. 仅对通过过滤的记录读取脱敏摘要并进行确定性匹配。
- 增加稳定拒绝码 `PLATFORM_KNOWLEDGE_ACCESS_DENIED` 和
  `PLATFORM_KNOWLEDGE_QUERY_REJECTED`，恶意查询在候选过滤和内容读取前
  失败关闭，并产生独立 Security Event。
- 提供 `flowpilot.worker-gateway.p1.v1`：
  - `GatewayCall` / `GatewayClientPort` 不携带 workload、Capability、
    ACL 或 Secret；
  - `DeterministicGatewayClientFake` 固定 Schema Pin、校验结果绑定、
    按 Tenant/Tool/幂等键去重，并明确拒绝写动作；
  - S2 可用该 Port/Fake 完成恢复与单次知识调用测试，无需直连
    `KnowledgeMcpAdapter`。
- 使用 S5 的 Domain Pack v2 知识样本验证当前/过期引用、引用元数据和
  content hash 对齐。

## 未完成与非目标

- 未实现 LangGraph VPN 产品图、Interrupt/Resume、Task 终态或结果 Artifact
  保存；这些属于 S2 / WP-010-a3。
- 未实现真实企业 Knowledge MCP、网络连接、生产凭据、向量检索或 Rerank。
- 未增加写工具、数据库表、Migration、RLS、Redis 或新第三方依赖。
- 未修改公共 ContractSet、ADR、Traceability、Registry 或功能状态。
- 本步骤不宣称 P1 已 VERIFIED/RELEASED；仍需 S2、S4、S7、S1 与用户门禁。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `apps/mcp-gateway/src/flowpilot_mcp_gateway/gateway.py` | 可信 ACL/双主体/Purpose/分类能力绑定与 read error mapping | S3 |
| `apps/mcp-gateway/src/flowpilot_mcp_gateway/errors.py` | 稳定 Knowledge 拒绝码 | S3 |
| `apps/mcp-gateway/README.md` | P1 Gateway 安全边界 | S3 |
| `packages/security/src/flowpilot_security/models.py` | 内部 Capability 与 Broker Port 声明 | S3 |
| `packages/tool-contracts/src/flowpilot_tool_contracts/gateway.py` | Worker Gateway Port 与确定性 Fake | S3 |
| `packages/tool-contracts/src/flowpilot_tool_contracts/__init__.py` | 导出 P1 Port/Fake | S3 |
| `packages/tool-contracts/README.md` | Worker 消费边界说明 | S3 |
| `mcp-servers/knowledge/src/flowpilot_mcp_knowledge/server.py` | P1 Schema、Pin、预检索授权和稳定输出 | S3 |
| `mcp-servers/knowledge/src/flowpilot_mcp_knowledge/__init__.py` | 导出 Pin/Scope | S3 |
| `mcp-servers/knowledge/README.md` | 检索前过滤与输出白名单说明 | S3 |
| `tests/platform/factories.py` | 可信双主体/ACL/Scope Fixture | S3 |
| `tests/platform/test_gateway_security.py` | 新知识输出契约断言 | S3 |
| `tests/platform/test_knowledge_search.py` | Domain Pack、隔离、Pin、Fake 和泄漏负例 | S3 |
| `tests/platform/evidence/WP-020-a2/HANDOFF.md` | 本交接证据 | S3 |

## 契约、数据库与配置变化

- 公共契约：无变化；ContractSet content digest 不变。
- 内部 Python Port：新增 `flowpilot.worker-gateway.p1.v1`；内部 Capability
  增加受信检索声明。
- Tool Schema：`knowledge.search.v1` 的本地 Pin 有意变化；旧 Pin
  不兼容并失败关闭，S2 必须消费本交接的新 Pin。
- Migration / RLS / PostgreSQL / Redis：无变化。
- `pyproject.toml` / `uv.lock` / `Makefile`：无变化。
- 依赖、环境变量、生产配置：无变化。

## 验证

环境：Windows、CPython 3.12.11、uv 0.11.32。当前 PowerShell 未安装
`make.exe`；因此按仓库 Makefile 原样运行其锁定底层命令，不修改环境或
共享文件。

| 命令 / 门禁 | 结果 |
|---|---|
| 分支、Worktree、祖先、DEDUP、Handoff SHA、ContractSet | PASS |
| `git merge --ff-only 1d687076...` | PASS：精确到达 S5 Head |
| `uv sync --all-packages --all-groups --locked` | PASS：116 resolved / 113 checked |
| Makefile `test` 的锁定底层命令 | PASS：248 passed |
| Makefile `test-contract` 的锁定底层命令 | PASS：20 schemas / 35 cases / 43 semantic cases / 52 features |
| Makefile `test-security` 的锁定底层命令 | PASS：68 passed |
| Ruff（全部 S3 源码与 Platform 测试） | PASS |
| Mypy `--strict`（14 包源码） | PASS：84 source files |
| `uv build --all-packages --wheel` | PASS：14 wheels |
| S3 差异路径 / Contract / Shared 文件检查 | PASS：越权 0、共享变化 0 |
| Runtime/Worker 直接 Knowledge Adapter 引用扫描 | PASS：0 |
| 本 Attempt 高置信 Secret Scan | PASS：0 matches |
| `git diff --check` | PASS |

Contract Conformance：

```text
CONTRACT_CONFORMANCE_OK schemas=20 cases=35 positive=18 negative=17 mutation_cases=19 mutation_positive=3 mutation_negative=16 semantic_cases=43 semantic_positive=0 semantic_negative=43 audit_chain_cases=5 audit_chain_positive=1 audit_chain_negative=4 manifest_cases=21 manifest_positive=1 manifest_negative=20 features=52
```

## 安全与失败路径

- 已验证：本租户、有效 ACL、双主体、Purpose、Scope、分类和有效期全部
  匹配时只返回有效 SOP。
- 已验证：错租户、缺用户 ACL、伪造 workload principal、错 Purpose、
  缺 Scope、越级分类和过期 SOP 均不会进入候选；逻辑越权读取数为 0。
- 已验证：零结果是安全的 verified read，不伪造引用。
- 已验证：恶意查询在任何记录访问前被稳定拒绝并产生 Security Event。
- 已验证：旧 Schema Pin、随机 Schema 漂移和额外输出字段失败关闭。
- 已验证：上游内部异常不泄漏原始主机/异常；secret-like 摘要被 DLP 阻断，
  不进入 ToolResult、debug projection、Audit 或 Security Event。
- 已验证：Worker Fake 重放两次只形成一次逻辑执行；Port 不暴露 workload、
  Capability 或 ACL。
- Secret/PII：仅使用合成主体、租户、文档和攻击标记；无真实凭据、PII、
  生产 Prompt、原始附件或隐藏思考过程。

## 已知问题

- 当前本机 PowerShell 缺少 GNU Make，可复现入口只能运行 Makefile 中的
  等价锁定底层命令；仓库 Makefile 本身未变化。S2/S7 若环境具备 Make，
  应重新运行稳定入口。
- 真实 Knowledge MCP 的网络出口、存储 ACL 查询和远端故障恢复不属于本
  Attempt；当前确定性 Adapter 仅是可信边界 Fixture。
- 本 Attempt 无依赖或 Lock 变化，因此未重复运行第三方漏洞审计；沿用输入
  Head 已记录的 0 known vulnerabilities 结果。

## 学习候选

```text
LEARNING_CANDIDATE=none
```

## 接收会话下一步

1. S2 核验最终 Head、Handoff SHA、ContractSet、线性父提交、授权范围和
   干净 Worktree，输出 `CONSUMER_VERDICT=ACCEPT` 后仅用 `--ff-only`
   精确到达最终 Head。
2. 只消费 `GatewayClientPort` / `GatewayCall` 和
   `DeterministicGatewayClientFake`；固定
   `KNOWLEDGE_SCHEMA_PIN=b7679fde...`。
3. 禁止导入或实例化 `KnowledgeMcpAdapter`，禁止直连上游 MCP、数据库、
   企业网络或构造受信 workload / Capability。
4. 在 VPN 图中证明完整请求只调用一次知识 Gateway；缺
   `environment` 时 Interrupt 前调用数为 0，恢复/重放仍为 1。
5. 只将最小引用元数据放入结果 Context，通过 S5 `ResultArtifactPort`
   保存正文，Task 只暴露 `result_ref`。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-P1-VPN-READONLY-01
STEP_ID=P1-VPN-02-S3
ATTEMPT_ID=WP-020-a2
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=1d6870764464cd4762351e7cf278bacd8e4fbced
INPUT_HEAD=1d6870764464cd4762351e7cf278bacd8e4fbced
IMPLEMENTATION_HEAD=371236a776d75fbdc81c323ba1948f0cd53012d6
CONTRACT_CONTENT_DIGEST=sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc
KNOWLEDGE_SCHEMA_PIN=sha256:b7679fde5be1187e8a36b4cd4dd95a95b63a50dc56532294174b0088f0e6600b
GATE=PASS
HANDOFF=tests/platform/evidence/WP-020-a2/HANDOFF.md
NEXT_ROLE=S2-RUNTIME
NEXT_ATTEMPT_ID=WP-010-a3
ESCALATE_TO_S1=no
```

## 可回滚方式

- 实现提交和 Handoff 提交可由链路 Owner 按逆序 `git revert`；禁止
  reset/rebase。
- 本 Attempt 没有数据库、Migration、外部系统写入或依赖变化，无数据、
  Schema Registry 或 Lock 回滚。
