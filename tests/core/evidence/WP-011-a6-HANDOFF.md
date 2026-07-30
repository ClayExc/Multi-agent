# WP-011-a6 S5-CORE VPN 只读引用边界交接

## 基本信息

- Work Package：WP-011
- Attempt ID：WP-011-a6
- Chain ID：CHAIN-P1-VPN-READONLY-01
- Step ID：P1-VPN-01-S5
- DEDUP Key：
  `CHAIN-P1-VPN-READONLY-01/P1-VPN-01-S5/WP-011-a6/3256f064423f4b80a610b7efeefbdc5584e9e236`
- 责任会话：S5-CORE
- 接收会话：S3-PLATFORM
- 交接策略：CONSUMER_GATE
- 风险等级：R2
- 功能 ID：FP-FLOW-002、FP-FLOW-003、FP-AGT-001、FP-CTX-001、
  FP-MCP-001、FP-MCP-002、FP-SEC-003、FP-EVAL-003、FP-OPS-002
- 基线 / 输入提交：
  `3256f064423f4b80a610b7efeefbdc5584e9e236`
- 实现提交：`64538c382acd6ded91e8ffb4ced35d6af1dc8486`
- 分支：`codex/s5/wp-011-core-bootstrap`
- 最终提交：本文件所在提交；精确 SHA 由唤醒信封返回
- ContractSet 摘要：
  `sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`
- 状态：完成，等待 S3 消费门禁

## 授权与线性候选

- S5 原 Head `c6b250e3b3a5b7df93b60857b5ee438027ee2ff3` 是激活提交
  `3256f064423f4b80a610b7efeefbdc5584e9e236` 的祖先。
- S5 在干净工作树上使用 `git merge --ff-only` 精确到达激活提交；
  没有执行 merge commit、rebase、reset、强制合并或跨分支复制文件。
- 链授权：
  `docs/team/chain-authorizations/CHAIN-P1-VPN-READONLY-01.md`。
- 实现差异严格位于 `apps/api/**`、`packages/domain/**`、
  `packages/application/**`、`domain-packs/it-service/**` 和
  `tests/core/**`；实际没有修改 `apps/api/**` 或 `packages/domain/**`。
- `contracts/**`、`pyproject.toml`、`uv.lock`、`Makefile`、Migration、
  S6 路径和其他角色目录均未变化。

## 完成内容

- 新增内部 Port 版本 `flowpilot.reference-ports.p1.v1`：
  - `RequestReferenceResolverPort` 只接收受信的租户、Task、Message、
    Purpose 和 Security Context 引用绑定。
  - `ResultArtifactPort` 原子保存结果正文，只向调用者返回不透明
    `result_ref`。
- `RequestObservationService`：
  - 从既有 `TaskCommand` 的 `initial_message_ref` / `message_ref` 构建
    受信查询，不扩大公共 Command 契约。
  - 校验完整绑定、数据分类上限和观察摘要；未知、错租户、错用途、
    错安全上下文、分类越级和摘要篡改均失败关闭。
  - 只返回脱敏字段和缺失字段，不返回原始请求正文。
- `ResultArtifactService`：
  - 结果摘要绑定租户、Task、媒体类型、正文和引用。
  - 每个可完成结果至少需要一个可回查引用。
  - `(tenant_id, idempotency_key)` 下同摘要重放返回相同 `result_ref`；
    不同摘要返回稳定冲突，不静默覆盖。
  - 回执绑定不匹配时失败关闭；公共 Task 投影仍只暴露 `result_ref`。
- 新增稳定的 Application 错误码，覆盖引用未找到、绑定不匹配、篡改、
  解析服务不可用、协议错误、结果冲突、结果篡改、结果存储不可用和
  错误回执；错误消息不回显原始引用内容或底层异常。
- 扩展数据型 IT Service Domain Pack 到 `flowpilot.domain-pack.v2` /
  `0.2.0`：
  - 完整的 Windows VPN 691 家庭网络请求 Fixture。
  - 缺失 `environment` 的确定性中断 Fixture。
  - 当前有效与已过期的合成知识样本。
  - 每个 Case 的预期引用与排除引用。
  - 加载时校验租户绑定、时间窗、ACL、分类、引用元数据、摘要、
    完整 Case 覆盖，以及完整请求至少一个引用。
- 新增确定性 Fake 和正常、边界、失败、安全、幂等及公共 API 契约测试。

## 未完成与非目标

- 未实现 Knowledge MCP、Gateway 过滤、真实 Provider、真实数据库、
  检索排序或写工具；这些不属于本步骤。
- 未实现 LangGraph Interrupt/Resume、知识调用节点或 Task 终态；
  S2 必须在 S3 安全工具边界完成后消费本 Port。
- 未修改公共 ContractSet；`TaskCommand` 仍只携带受信引用，
  Task 投影仍只携带 `result_ref`。
- 未把 Domain Pack 合成内容当作冻结 120 Case 数据集或发布证据。
- `make acceptance` 仍未实现，本步骤不宣称完整产品验收或发布。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `packages/application/src/flowpilot_application/models.py` | 引用、观察、结果草稿、引用和回执类型 | S5-CORE |
| `packages/application/src/flowpilot_application/ports.py` | 请求解析与结果 Artifact Port | S5-CORE |
| `packages/application/src/flowpilot_application/services.py` | 绑定、摘要、分类和幂等服务 | S5-CORE |
| `packages/application/src/flowpilot_application/testing.py` | 两个确定性 Fake | S5-CORE |
| `packages/application/src/flowpilot_application/errors.py` | 稳定错误类型 | S5-CORE |
| `packages/application/src/flowpilot_application/domain_packs.py` | v1 兼容的 v2 数据 Pack 加载边界 | S5-CORE |
| `packages/application/src/flowpilot_application/__init__.py` | 公共 Python 导出 | S5-CORE |
| `packages/application/README.md` | 内部 Port 与安全边界说明 | S5-CORE |
| `domain-packs/it-service/manifest.yaml` | v2 Pack 注册 | S5-CORE |
| `domain-packs/it-service/evals/*.json` | 完整/缺失字段请求与引用预期 | S5-CORE |
| `domain-packs/it-service/knowledge/*.json` | 当前/过期合成知识 | S5-CORE |
| `tests/core/test_references.py` | 引用、结果、安全与幂等测试 | S5-CORE |
| `tests/core/test_domain_pack.py` | Pack 正常与篡改负例 | S5-CORE |
| `tests/core/test_api.py` | 公共请求/结果不泄漏正文的契约断言 | S5-CORE |
| `tests/core/evidence/WP-011-a6-HANDOFF.md` | 本交接证据 | S5-CORE |

## 契约、数据库与配置变化

- 公共契约：无变化。
- 内部 Python Port：新增 `flowpilot.reference-ports.p1.v1`。
- Domain Pack：数据格式从 v1 扩展为向后兼容的 v2；现有 v1 加载仍受支持。
- Migration / RLS / PostgreSQL / Redis：无变化。
- `pyproject.toml` / `uv.lock` / `Makefile`：无变化。
- 依赖：无新增；无需许可证、替代方案或新增第三方攻击面裁决。
- 环境变量和生产配置：无变化。

## 验证

环境：Windows、CPython 3.12.11、uv 0.11.32、GNU Make 4.4.1。

| 命令 / 门禁 | 结果 |
|---|---|
| 消费前 Head、分支、祖先、干净树、摘要与 DEDUP | PASS |
| `git merge --ff-only` 到激活提交 | PASS：精确到达输入 Head |
| `make bootstrap` | PASS：116 个锁定包，14 个内部 Workspace 包 |
| `make studio-smoke` | PASS：LangGraph CLI 0.4.31 |
| `make test` | PASS：231 passed |
| `make test-contract` | PASS：20 schemas / 35 cases / 43 semantic cases / 52 features |
| `make test-security` | PASS：51 passed |
| Ruff（S5 授权源码与 Core 测试） | PASS：All checks passed |
| Mypy `--strict`（14 包源码） | PASS：83 source files |
| `uv build --all-packages --wheel` | PASS：14 wheels |
| 全新环境安装并导入 14 wheels | PASS：`WHEEL_IMPORT_OK packages=14` |
| `pip-audit` 联合安装闭包 | PASS：0 known vulnerabilities；14 个内部包按预期跳过 PyPI 查询 |
| 本 Attempt 变更路径高置信 Secret Scan | PASS：0 matches |
| `git diff --check` | PASS |
| Contract / Workspace / Lock 静态差异 | PASS：无变化 |
| `make acceptance` | 未实现：`No rule to make target 'acceptance'` |

阶段耗时约为：Bootstrap 0.5 秒、Static 4.7 秒、Tests/Contract/Security
12 秒、Build 与隔离安装 10.4 秒、依赖与 Secret 扫描 18.6 秒。
Compose、Database/Recovery 和 Cleanup 不属于本 S5 步骤，未运行。

Contract Conformance：

```text
CONTRACT_CONFORMANCE_OK schemas=20 cases=35 positive=18 negative=17 mutation_cases=19 mutation_positive=3 mutation_negative=16 semantic_cases=43 semantic_positive=0 semantic_negative=43 audit_chain_cases=5 audit_chain_positive=1 audit_chain_negative=4 manifest_cases=21 manifest_positive=1 manifest_negative=20 features=52
```

全仓 Ruff 的额外探测在激活提交已有的 S4 独占
`packages/evaluation/**`、`packages/observability/**` 中报告 22 条格式告警；
本 Attempt 对这些路径的差异为 0。该基线噪音不计入 S5 授权范围的
PASS，也没有被越权修改；后续 S4 步骤应在自身范围处理。

## 安全与失败路径

- 已验证：完整请求、缺失 `environment`、未知引用、错租户绑定、
  引用字段篡改、分类越级、解析服务异常、未知意图。
- 已验证：结果同内容重放、同键不同内容冲突、结果摘要篡改、错误回执、
  缺失引用。
- 已验证：Domain Pack 的错租户 Knowledge 引用、未知引用源、引用元数据
  错配、请求观察摘要篡改和未知字段。
- 已验证：公共 OpenAPI 不新增请求正文、结果正文或引用数组字段。
- Secret/PII：合成租户、主体、请求和知识，不含真实凭据、真实 PII、
  生产 Prompt、Trace、原始附件或隐藏思考过程；高置信扫描为 0。

## 已知风险

- S3 必须把本 Domain Pack 样本当安全 Tool Fixture 输入，在形成候选前
  执行租户、ACL、Purpose、分类和有效期过滤；不得先检索后过滤。
- S3 必须返回稳定、可摘要验证的最小知识结果；S2 不得直连上游 MCP
  或 Knowledge Adapter。
- S2 必须只消费脱敏 `RequestObservation`，在缺失字段时 Interrupt；
  恢复后只调用一次知识工具，并通过 `ResultArtifactPort` 保存正文。
- 全仓 Ruff 的 S4 基线告警需要由 S4 在其授权步骤修复或提供裁决；
  本步骤没有掩盖或修改该状态。

## 学习候选

```text
LEARNING_CANDIDATE=不透明结果引用必须由内容摘要绑定原子幂等
MATURITY=IMPLEMENTED
TRIGGER=图恢复或重复投递再次保存同一 Task 结果
MECHANISM=只按幂等键去重会让不同正文静默复用旧引用，重新生成引用则会产生重复结果
STRUCTURE=以 tenant_id 和 idempotency_key 原子保留结果摘要；同摘要返回原 result_ref，不同摘要稳定冲突
EVIDENCE=64538c382acd6ded91e8ffb4ced35d6af1dc8486；tests/core/test_references.py
RESIDUAL_RISK=真实 Artifact Adapter 仍需由后续数据工作包证明事务原子性与恢复语义
TARGET=docs/architecture/ENGINEERING_PLAYBOOK.md
```

## 接收会话下一步

1. S3 核验本交接 NEW_HEAD、Handoff SHA、ContractSet、线性父提交、
   授权范围和干净 Worktree。
2. S3 分支只以 `--ff-only` 精确到达 S5 NEW_HEAD；禁止 rebase、reset、
   强制合并或复制文件绕过。
3. 按 WP-020-a2 在 S3 独占路径实现 Knowledge Tool 的租户、ACL、
   Purpose、分类、有效期和恶意查询过滤，以及 Gateway 调用边界与 Fake。
4. S3 的输出必须携带与本 Pack 一致的 source ref、document version、
   section 和 content hash；零结果和失败默认拒绝。
5. S3 完成后只唤醒授权的 S2-RUNTIME / WP-010-a3；仅在 P0/P1、契约或
   共享文件变化、路径越权、新门禁失败或非线性 Head 时上报 S1。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-P1-VPN-READONLY-01
STEP_ID=P1-VPN-01-S5
ATTEMPT_ID=WP-011-a6
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=3256f064423f4b80a610b7efeefbdc5584e9e236
INPUT_HEAD=3256f064423f4b80a610b7efeefbdc5584e9e236
IMPLEMENTATION_HEAD=64538c382acd6ded91e8ffb4ced35d6af1dc8486
CONTRACT_CONTENT_DIGEST=sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc
GATE=PASS
HANDOFF=tests/core/evidence/WP-011-a6-HANDOFF.md
NEXT_ROLE=S3-PLATFORM
NEXT_ATTEMPT_ID=WP-020-a2
NEXT_TASK_THREAD_ID=019fa698-9217-71b1-bb1d-114f3d453935
ESCALATE_TO_S1=no
```

## 可回滚方式

- 实现提交和本 Handoff 提交可由链路 Owner 按逆序 `git revert`；禁止
  reset/rebase。
- 本 Attempt 没有数据库、Migration、外部系统写入或依赖变化，无数据
  回滚和 Lock 回滚。
