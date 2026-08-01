# WP-030-a4 S4-QUALITY VPN 固定 Case 与黑盒交接

## 基本信息

- Work Package：WP-030
- Attempt ID：WP-030-a4
- Chain ID：CHAIN-P1-VPN-READONLY-01
- Step ID：P1-VPN-04-S4
- DEDUP Key：`CHAIN-P1-VPN-READONLY-01/P1-VPN-04-S4/WP-030-a4/c5c118d808931492d7ee44455b1c2a9360625675`
- 责任会话：S4-QUALITY
- 接收会话：S7-INTEGRATION
- 交接策略：CONSUMER_GATE
- 功能 ID：FP-EVAL-003、FP-OBS-001；黑盒复核 FP-FLOW-001、
  FP-FLOW-002、FP-FLOW-003、FP-MCP-001、FP-MCP-002、FP-SEC-003、
  FP-CTX-001、FP-OPS-002
- 基线提交：`c5c118d808931492d7ee44455b1c2a9360625675`
- 实现提交：`99a60f21e0b114b19be9c5b35d912b202e461e14`
- 分支/最终提交：`codex/s4/wp-030-quality-bootstrap`；本文件所在提交，
  精确 SHA 由唤醒信封提供
- ContractSet 摘要：
  `sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`
- Knowledge Schema Pin：
  `sha256:b7679fde5be1187e8a36b4cd4dd95a95b63a50dc56532294174b0088f0e6600b`
- 状态：完成，等待 S7 消费门禁

## 完成内容

- 建立恰好 20 条固定 VPN 本地候选 Case、数据卡和 SHA-256 清单。加载器
  强制 Case 数量、排序、ID/Scenario 唯一性、闭合字段及 Card/Case 文件哈希；
  任一漂移失败关闭。
- 从 API Command Intake、Application 请求引用、Worker LangGraph、Gateway
  Client Port、Knowledge MCP 授权过滤和结果 Artifact 的公开/稳定边界完成
  端到端黑盒；没有导入 `tests/core`、`tests/runtime` 或 `tests/platform`
  Fixture。
- 覆盖完整请求、替代环境、缺环境 Interrupt/Resume/Worker 重建、补充仍
  不完整、零结果、Artifact 恢复、重复 API/Task Command、Gateway 结果绑定
  错误、错租户、Subject/Workload/Purpose/Classification/Scope ACL、过期知识、
  两层恶意查询拒绝、引用哈希异常和闭合安全投影。
- 每条 Case 都复核 Task 最终状态、稳定错误码、逻辑知识读取数、Gateway
  尝试数、`result_ref` 状态和引用数；重复终态投递保持同一 `result_ref`，
  Artifact 恢复只发生一次逻辑知识读取。
- 规则评分优先。独立负例证明：即使所有确定性断言为真且语义 Judge 为
  1.0，`execution_status=failed` 仍保留 `failed`；确定性断言失败时 Judge
  同样不能提升状态。
- 候选报告生成器固定 `all_declared_cases` 分母并保留 failed/skipped/
  quarantined；生成逐 Case JSONL、Aggregate、Report 和 Manifest。Manifest
  固定 `candidate_only=true`、`release_eligible=false`，并记录自动 Secret/
  PII 扫描均为 0。
- 消费 S2 Head 后，既有 S4 Acceptance 暴露两个上游接口演进：Credential
  Broker 增加 Subject/ACL/Workload/Purpose/Classification 绑定，Studio
  Projection 增加闭合 `knowledge` 字段。仅更新 S4 Fixture/Oracle 后，全量
  Acceptance 恢复通过；未修改上游生产代码。

## 未完成与非目标

- 20 条 Case 是本地候选集，未进入公共 ContractSet Registry，不代表 120
  条功能集或 36 条安全/故障集完成，不构成 VERIFIED/RELEASED。
- 未修改 `contracts/**`、ADR、Traceability、公共 Registry、Makefile、
  Workspace、Lock、`web/**` 或 `packages/retrieval/**`。
- 未连接真实 Provider、企业 Knowledge、生产 API、RLS、Outbox、数据库、
  外部网络、生产凭据或真实 PII；未加入依赖。
- 未测量或报告 Token、延迟或质量提升；未手工填写成功率。
- 真实远端 Gateway 传输、数据库隔离 Compose 和组合发布门禁属于 S7。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `evals/datasets/functional/vpn-readonly-p1/**` | 20 Case、数据卡、本地哈希清单 | S4-QUALITY |
| `packages/evaluation/vpn_readonly.py`、`packages/evaluation/__init__.py` | 严格候选集加载与导出 | S4-QUALITY |
| `tests/acceptance/vpn/**` | API/Application/Worker/Gateway/Knowledge 黑盒、逐 Case 与负向门禁 | S4-QUALITY |
| `artifacts/acceptance/generators/vpn_readonly.py`、`__init__.py` | 候选报告、Manifest、Secret/PII 扫描 | S4-QUALITY |
| `tests/acceptance/conftest.py` | 增加已交付稳定源码边界 | S4-QUALITY |
| `tests/acceptance/platform_security/blackbox.py` | 同步 Credential Broker 完整绑定 Fixture | S4-QUALITY |
| `artifacts/acceptance/generators/studio_agent_server.py` | 接受并验证闭合 Knowledge 投影 | S4-QUALITY |
| `tests/acceptance/evidence/WP-030-a4-*` | Proof 与交接 | S4-QUALITY |

## 契约、数据库与配置变化

- 契约版本 / ContractSet / Knowledge Schema：无变化；摘要与 Pin 均保持输入值。
- Migration / RLS / PostgreSQL / Redis / Outbox：无变化。
- `pyproject.toml` / `uv.lock` / Makefile / 环境变量：无变化。
- 第三方生产依赖：无新增。
- 兼容性：只消费已交付的稳定 Python/API Port，不复制或放宽公共枚举/字段。

## 验证

环境：Windows，锁定 CPython 3.12.11、Pytest 9.1.1；外部网络关闭。

| 命令 | 结果 | 证据 |
|---|---|---|
| `.venv\Scripts\python.exe -m pytest tests/acceptance/vpn -q` | PASS：24 passed；其中恰好 20 个参数化 VPN Case | `WP-030-a4-PROOF.json` |
| `.venv\Scripts\python.exe -m pytest tests/acceptance -q` | PASS：89 passed in 18.93s | 同上 |
| `.venv\Scripts\python.exe scripts/acceptance/validate_offline.py` | PASS：2 Case、0 Findings | 同上 |
| `.venv\Scripts\python.exe contracts/conformance/validate.py` | PASS：20 Schema、35 Case、43 语义负例、52 Feature | 同上 |
| 本 Attempt Python 文件 Ruff | PASS：All checks passed | 同上 |
| 新候选边界与生成器 Mypy `--strict` | PASS：5 source files | 同上 |
| UTF-8/LF/无 BOM、严格 JSON 重复键、Secret/PII Scan | PASS：重复键 0、Secret 0、PII 0 | 同上 |
| Agent Server `.langgraph_api` 残留 | PASS：0 | 同上 |
| `git diff --check` 与授权路径复核 | PASS：0 whitespace / 0 越权路径 | 同上 |
| `make acceptance` | NOT_RUN：目标尚未实现，Makefile 不在本 Step 写范围 | 同上 |

Contract Conformance：

```text
CONTRACT_CONFORMANCE_OK schemas=20 cases=35 positive=18 negative=17 mutation_cases=19 mutation_positive=3 mutation_negative=16 semantic_cases=43 semantic_positive=0 semantic_negative=43 audit_chain_cases=5 audit_chain_positive=1 audit_chain_negative=4 manifest_cases=21 manifest_positive=1 manifest_negative=20 features=52
```

## 安全与失败路径

- 错租户、缺 Subject ACL、伪造 Workload、错误 Purpose、Classification 越级、
  缺 Scope 和过期知识均产生 0 次未授权逻辑读取、0 `result_ref`、0 引用。
- 含空格的攻击字段在 Worker 请求构造前拒绝；`acl_subjects` 攻击查询在
  Knowledge Adapter 候选形成前拒绝；两者都没有知识正文访问。
- 结果请求绑定错误和非法引用哈希均失败关闭，不生成 Artifact 或伪引用。
- Graph/Projection/Proof 不含请求正文、答案正文、ACL、凭据、生产 Secret、
  PII、Provider Session 或隐藏思维链。
- 生成器自动扫描候选 Card/Case/逐 Case 结果；发现 Secret/PII 时拒绝生成
  Manifest，不能靠人工写入 0 绕过。

## 已知问题

- 本地候选集不是公共 Registry 的冻结发布集；S7/S1 不得把 20 Case PASS
  外推为 120/36 或发布成功率。
- 当前黑盒使用确定性本地 Port/Adapter；真实远端传输、持久 Checkpoint、
  数据库隔离和 Compose 故障由 S7 RELEASE Gate 复算。
- `make acceptance` 仍未实现；本 Attempt 只提供可直接运行的锁内命令。

## 学习候选

```text
LEARNING_CANDIDATE=none
MATURITY=VERIFIED
TRIGGER=none
MECHANISM=none
STRUCTURE=none
EVIDENCE=tests/acceptance/evidence/WP-030-a4-PROOF.json
RESIDUAL_RISK=none
TARGET=none
```

## 接收会话下一步

1. 核验任务、Worktree/Branch、DEDUP、NEW_HEAD、Handoff Hash、ContractSet、
   Knowledge Pin、`c5c118d8...` 到 NEW_HEAD 的线性提交和授权路径。
2. 只用 `--ff-only` 精确到达 S4 NEW_HEAD；未精确到达立即停链。
3. 按 WP-040-a6 RELEASE Gate 独立复算 20 Case 清单/哈希、逐 Case 结果、
   Workspace/Lock、产品/安全/Acceptance/Contract、Wheel、Secret Scan、
   隔离 Compose、错租户读取 0、恢复无重复调用和清理结果。
4. 完成后按链路仅唤醒 S1-ARCH final gate；S7 不自行批准合并。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-P1-VPN-READONLY-01
STEP_ID=P1-VPN-04-S4
ATTEMPT_ID=WP-030-a4
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=c5c118d808931492d7ee44455b1c2a9360625675
INPUT_HEAD=c5c118d808931492d7ee44455b1c2a9360625675
IMPLEMENTATION_HEAD=99a60f21e0b114b19be9c5b35d912b202e461e14
CONTRACT_CONTENT_DIGEST=sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc
KNOWLEDGE_SCHEMA_PIN=sha256:b7679fde5be1187e8a36b4cd4dd95a95b63a50dc56532294174b0088f0e6600b
GATE=PASS
HANDOFF=tests/acceptance/evidence/WP-030-a4-HANDOFF.md
NEXT_ROLE=S7-INTEGRATION
NEXT_ATTEMPT_ID=WP-040-a6
ESCALATE_TO_S1=no
```

## 可回滚方式

- 按逆序 `git revert` 本 Attempt 的 S4 提交；禁止 reset/rebase。
- 本 Attempt 没有数据库、Migration、外部系统或生产数据写入，无数据回滚。
