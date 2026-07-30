# WP-030-a2 S4-QUALITY 平台安全黑盒交接

## 基本信息

- Work Package：WP-030
- Attempt ID：WP-030-a2
- Chain ID：CHAIN-M1-PLATFORM-01
- Step ID：M1-PLATFORM-04-S4
- 责任会话：S4-QUALITY
- 接收会话：S7-INTEGRATION
- 交接策略：CONSUMER_GATE
- 功能 ID：FP-OBS-001、FP-EVAL-003；同时黑盒复核上游
  FP-MCP-001～005、FP-APR-001～003、FP-SEC-001、FP-SEC-004、FP-SEC-006
- 基线提交：`192ebe38df84ed9097e4045847aa991632a2ff63`
- 实现提交：`a27b8de946448bb027717001e8ef80b7a598f65d`
- 分支/最终提交：`codex/s4/wp-030-quality-bootstrap`；本文件所在提交，
  精确 SHA 由唤醒信封返回
- ContractSet 摘要：
  `sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`
- 状态：完成，等待 S7 消费门禁

## 完成内容

- 从 S5 Head
  `192ebe38df84ed9097e4045847aa991632a2ff63`
  以 `--ff-only` 精确消费 Workspace、Lock 与 Platform 稳定入口；消费前
  Handoff SHA-256、ContractSet、祖先关系、分支和洁净工作树均通过。
- 新增独立 Platform 安全黑盒 Fixture。Fixture 只使用 Gateway、Policy、
  Security、Tool Contract 与 Persistence 的公开端口，不导入
  `tests/platform`、生产者私有 Fixture 或 `_deps` 等私有属性。
- 以 33 项独立测试覆盖：
  - 用户/Agent 双主体、跨租户、Purpose/Audience、Context 过期与 Agent/
    审批角色伪造。
  - Approval 的动作摘要、Tool Schema Hash、策略版本、请求主体、租户和
    有效期绑定篡改。
  - 未知/重复冲突 Obligation、策略不可用、未注册工具旁路、恶意 Tool
    输出与 Secret-like 输出。
  - 重复写、Gateway 重启重放、`UNKNOWN` 禁止盲重试、权威未执行证明、
    回读不匹配、参数切换和恢复对账。
  - Trace 采样不影响 Audit/Security 保留；拒绝 Audit 与 Security Event
    的双向链接及公共关联字段稳定。
  - 确定性 Gateway 失败在全部断言通过且 Judge 为 1.0 时仍保持失败。
- 新增平台信号证据生成器。生成器从公开 Lifecycle/Audit/Security 映射
  重建时间线，并对以下情况失败关闭：
  - 缺失/乱序阶段和 sequence 缺口或重复。
  - `request_id`/`causation_id`、Trace、Task、Correlation 关联错乱。
  - 未注册原因码、Stage Metrics 或 Debug Projection 漂移。
  - Debug Projection 越过闭合白名单。
  - Audit/Security 双向链接缺失。
  - 敏感字段或 Secret-like 材料泄漏。
- 证据包显式标记 `release_gate=false`、
  `dataset_completion_claim=false`，不输出质量成功率，也不宣称 120/36
  数据集完成。

## 未完成与非目标

- 未修改 MCP Gateway、Policy、Security、Persistence、Runtime、API 或
  其他角色生产代码。
- 未修改公共契约、ADR、Makefile、Workspace 或 Lock。
- 未连接生产凭据、真实企业 MCP、外部网络、RLS 或真实 Outbox Sink。
- 未填充或宣称 120 条功能集、36 条安全/故障集完成。
- 未测量或报告任务成功率、Token、延迟或质量提升。
- `make acceptance` 仍未实现；本 Step 不构成发布级验收。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `artifacts/acceptance/generators/__init__.py` | 导出平台安全证据生成器 | S4-QUALITY |
| `artifacts/acceptance/generators/platform_security.py` | 闭合时间线、关联、采样、双向链接和 Secret 门禁 | S4-QUALITY |
| `tests/acceptance/conftest.py` | Acceptance 独立异步测试入口与公开源码根 | S4-QUALITY |
| `tests/acceptance/platform_security/blackbox.py` | 不依赖生产者测试代码的公共端口 Fixture | S4-QUALITY |
| `tests/acceptance/platform_security/test_authorization_blackbox.py` | 身份、租户、审批、策略、旁路、输出和 Judge 负例 | S4-QUALITY |
| `tests/acceptance/platform_security/test_recovery_blackbox.py` | 重放、UNKNOWN、对账、回读和幂等负例 | S4-QUALITY |
| `tests/acceptance/platform_security/test_timeline_evidence.py` | 信号采样、时间线重建和证据生成器负例 | S4-QUALITY |
| `tests/acceptance/evidence/WP-030-a2-PROOF.json` | 命令、覆盖与非发布声明的结构化 Proof | S4-QUALITY |
| `tests/acceptance/evidence/WP-030-a2-HANDOFF.md` | 本交接 | S4-QUALITY |

## 契约、数据库与配置变化

- 契约版本：无变化。
- ContractSet：
  `sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`。
- Migration / RLS / 数据库：无变化。
- Workspace / Lock / Makefile：无变化。
- 环境变量：无变化。
- 第三方生产依赖：无新增。
- 兼容性：测试只消费上游公开 M0 接口；没有扩展公共枚举或对象。

## 验证

环境：Windows、锁定 CPython 3.12.11、uv 0.11.32、Pytest 9.1.1、
GNU Make 4.4.1。

| 命令 | 结果 | 证据 |
|---|---|---|
| `python -m pytest tests/acceptance/platform_security -q` | PASS：33 passed | `WP-030-a2-PROOF.json` |
| `python -m pytest tests/acceptance -q` | PASS：61 passed | 同上 |
| `make test` | PASS：194 passed | 同上 |
| `make test-security` | PASS：51 passed | 同上 |
| `make test-contract` | PASS：`CONTRACT_CONFORMANCE_OK` | 同上 |
| `python -B scripts/acceptance/validate_offline.py` | PASS：2 Case、0 Findings | 同上 |
| 锁定 Workspace 直接运行 `contracts/conformance/validate.py` | PASS：包含 43 个语义负例 | 同上 |
| 新增文件 Ruff | PASS：All checks passed | 同上 |
| 证据生成器 Mypy `--strict` | PASS：2 source files | 同上 |
| `python -B contracts/conformance/validate.py`（系统 Python） | ENV_BLOCKED：系统 Python 3.14 未安装 `jsonschema`；锁定解释器同命令已 PASS | 同上 |
| `make acceptance` | NOT_RUN：目标尚未实现且不在本 Step 写范围 | 同上 |

Proof：
`tests/acceptance/evidence/WP-030-a2-PROOF.json`，SHA-256：
`bb118a6f48ef288e081d1d3c08b7f9bcacb7d9edeb9e8d83af6e4f91150e0f67`。

Contract Conformance：

```text
CONTRACT_CONFORMANCE_OK schemas=20 cases=35 positive=18 negative=17 mutation_cases=19 mutation_positive=3 mutation_negative=16 semantic_cases=43 semantic_positive=0 semantic_negative=43 audit_chain_cases=5 audit_chain_positive=1 audit_chain_negative=4 manifest_cases=21 manifest_positive=1 manifest_negative=20 features=52
```

## 安全与失败路径

- 所有授权拒绝测试均断言上游调用为 0、Ledger 记录为 0、Outbox 为 0，
  并保留 Audit/Security 双事件。
- 重复已验证写在 Gateway 对象重建后仍只产生 1 次逻辑写；`UNKNOWN`
  重放不再调用上游。
- 只有带 Evidence/Observed Ref 的权威未执行证明才能进入可重试状态；
  参数切换保持冲突且不对账。
- 恶意输出、Secret-like 字符串、调试投影越界、关联错乱与未知原因码均
  被确定性门禁拒绝。
- 新增证据生成器及 Proof 均为 UTF-8、LF、无 BOM；未保存真实 Secret、
  PII、Prompt、隐藏思考过程或原始附件。

## 已知问题

- `make acceptance` 不存在，不能把本包写成发布验收。
- 120/36 Registry/Dataset/Fixture 仍是候选范围，本交接没有填充分母。
- Gateway 产生的是 Audit/Security Draft；最终 Stream、sequence、
  integrity 和租户绑定仍必须由可信 Sink/Store 根据 Outbox envelope、
  租户注册表和持久化链头分配。
- 系统 Python 未安装仓库 Dev 依赖；复现应使用锁定 Workspace 解释器。

## 学习候选

```text
LEARNING_CANDIDATE=跨信号关联必须按契约语义映射而不是强求同名字段
MATURITY=VERIFIED
TRIGGER=Lifecycle 使用 request_id，而 Audit/Security 使用 causation_id 关联原请求
MECHANISM=生成器若把不同信号类型都套用同一字段集合，会把合法证据误判为关联失败；若放松为自由匹配，又会漏掉真实错链
STRUCTURE=为每类信号定义闭合字段投影；Lifecycle 直接校验 request_id，Audit/Security 校验 causation_id 到 request_id，并共同校验 trace_id/task_id/correlation_id
EVIDENCE=artifacts/acceptance/generators/platform_security.py；tests/acceptance/platform_security/test_timeline_evidence.py
RESIDUAL_RISK=未来公共事件版本改变关联字段时，生成器必须随版本显式升级而不能静默兼容
TARGET=docs/architecture/ENGINEERING_PLAYBOOK.md observability evidence section
```

## 接收会话下一步

1. 核验本交接 NEW_HEAD、Handoff SHA、ContractSet、实现提交、Proof Hash、
   路径范围与洁净 Worktree。
2. S7 分支只以 `--ff-only` 精确到达 S4 NEW_HEAD；禁止 rebase、reset、
   强制合并或复制文件绕过。
3. 按 `WP-040-a4` 复算 Workspace/Lock、Wheel、全仓/安全/Acceptance/
   Contract、Secret、机器时间线和证据闭包。
4. S7 完成后按链路唤醒 S1-ARCH final gate，并设置
   `USER_GATE_REQUIRED=yes`。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M1-PLATFORM-01
STEP_ID=M1-PLATFORM-04-S4
ATTEMPT_ID=WP-030-a2
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=192ebe38df84ed9097e4045847aa991632a2ff63
CONTRACT_CONTENT_DIGEST=sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc
GATE=PASS
HANDOFF=tests/acceptance/evidence/WP-030-a2-HANDOFF.md
NEXT_ROLE=S7-INTEGRATION
NEXT_ATTEMPT_ID=WP-040-a4
ESCALATE_TO_S1=no
```

## 可回滚方式

- 实现提交与本 Handoff 提交可由链路 Owner 按逆序 `git revert`；禁止
  reset/rebase。
- 本 Attempt 没有数据库、Migration 或外部系统写入，无数据回滚。
