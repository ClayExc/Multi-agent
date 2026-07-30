# WP-011-a4 S5-CORE Platform Workspace 交接

## 基本信息

- Work Package：WP-011
- Attempt ID：WP-011-a4
- Chain ID：CHAIN-M1-PLATFORM-01
- Step ID：M1-PLATFORM-03-S5
- 责任会话：S5-CORE
- 接收会话：S4-QUALITY
- 交接策略：CONSUMER_GATE
- 功能 ID：FP-FLOW-009、FP-MCP-001、FP-MCP-002、FP-SEC-001、FP-SEC-004
- 基线提交：`ff6cc282c81166317f995b975491167479aa1c8d`
- 分支：`codex/s5/wp-011-core-bootstrap`
- 最终提交：本文件所在提交；精确 SHA 由唤醒信封返回
- ContractSet 摘要：
  `sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`
- 状态：完成，等待 S4 消费门禁

## 授权与线性候选

- S5 从激活提交
  `c4062b2ac6a81aba4e3e1ac63cc01f54efecfed0` 以 `--ff-only`
  精确到达 S3 Head
  `ff6cc282c81166317f995b975491167479aa1c8d`。
- S3 Head 的唯一父提交是上述激活提交；S3 增量只包含 S3 WRITE_SCOPE。
- S3 Handoff：
  `tests/platform/evidence/WP-020-a1/HANDOFF.md`，复算 SHA-256 为
  `3a9fae37edecce2bf2251ae0d5b35f3dd9e79d69567cb7628aed99bcc6e0e888`。
- S6 `WP-020-r1-s6` 消费复核为 `ACCEPT`，不要求修改 Persistence Port、
  Migration、RLS 或事务语义。
- S5 实现提交
  `fe5ed876278fd82ea6be08f6a416fa0f0dbcad89` 的唯一父提交为精确 S3
  Head，差异只有 `pyproject.toml`、`uv.lock` 和 `Makefile`。
- 控制面 Scope Amendment 01 仅追加授权本文件：
  - Authority Commit：
    `1ae7a79dd7e0d4da819b93dfa0d916771fb0d265`
  - Authority Ref：
    `docs/team/chain-authorizations/CHAIN-M1-PLATFORM-01.md`
  - Authority SHA-256：
    `8279803e3b478196fe97757c638e53d93442ee266555606458053dd38ad1c8bf`

没有执行 merge commit、rebase、reset、强制合并或跨分支文件复制。

## 完成内容

- 在根 Workspace 注册 S3 的五个内部可安装包：
  - `flowpilot-mcp-gateway`
  - `flowpilot-mcp-knowledge`
  - `flowpilot-policy`
  - `flowpilot-security`
  - `flowpilot-tool-contracts`
- 为五包补齐 `tool.uv.sources`，保留其声明的内部依赖方向；没有新增或
  放宽第三方生产依赖。
- 把 `tests/platform` 纳入根 Pytest 稳定发现范围，使 `make test`
  覆盖 Core、Runtime、Data 与 Platform。
- 新增真实 `make test-security` 入口，使用同一锁定 Workspace 运行完整
  `tests/platform`，没有用手工命令冒充稳定入口。
- 刷新 `uv.lock`：总计 78 个包，包含 14 个内部可安装 FlowPilot 包和根
  Workspace 元包。锁哈希：
  `sha256:5111ba07d45f7d9ad3e1440663f6da2f4cfa078c4f52032621cd8cd6b89f08f1`。
- 在根 Workspace 无临时 `MYPYPATH` 的情况下完成 S3 五包与既有九包的
  联合类型闭包。

## 未完成与非目标

- 未修改 S3/S6 产品实现、公共契约、Migration、RLS、Infra 或事务语义。
- 未引入真实 OIDC、生产凭据、企业 MCP 写端点或新的网络出口。
- S4 独立安全黑盒、S7 组合门禁与 S1 最终接受尚未执行。
- `make acceptance` 仍未实现；本 Handoff 不声明完整验收、发布或
  120/36 数据集完成。
- Audit/Security 草稿的最终 Stream、sequence 和 integrity 仍由可信
  Sink/Store 分配；Workspace 闭包没有改变该边界。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `pyproject.toml` | 注册五个 S3 Workspace 包和 Platform 测试范围 | S5-CORE |
| `uv.lock` | 锁定 14 包联合安装闭包 | S5-CORE |
| `Makefile` | 新增稳定 `test-security` 入口 | S5-CORE |
| `tests/core/evidence/WP-011-a4-HANDOFF.md` | Scope Amendment 授权的交接证据 | S5-CORE |

## 契约、数据库与配置变化

- 公共契约：无变化。
- ContractSet：
  `sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`。
- 内部包：新增五个 S3 Workspace Member/Source；版本均为 `0.1.0`。
- 第三方生产依赖：无新增。
- Migration / RLS / 数据库 / Redis：无变化。
- 环境变量：无变化。
- 稳定测试配置：根 Pytest 增加 `tests/platform`；Make 增加
  `test-security`。

## 依赖、许可证与攻击面

本 Attempt 只注册内部包，不新增第三方依赖，因此既有第三方用途、许可证、
替代方案和攻击面记录保持不变。五个内部包的主要攻击面由 S3 测试覆盖：

- Gateway/Policy/Security：不可信 Schema、身份、租户、审批和 Obligation
  输入；使用闭合模型、默认拒绝和失败关闭。
- Knowledge MCP：不可信查询与跨租户读取；使用只读接口和可信 Tenant
  过滤。
- Tool Contracts：不可信输入/输出和 Schema Hash；使用严格适配和
  RFC 8785 绑定。

联合安装环境的第三方依赖审计结果为 0 个已知漏洞。

## 验证

环境：Windows、CPython 3.12.11、uv 0.11.32、GNU Make 4.4.1。

| 命令 / 门禁 | 结果 |
|---|---|
| `uv lock`、`uv lock --locked` | PASS：78 packages，锁哈希稳定 |
| `make bootstrap` | PASS：14 个内部包和全部锁定组可安装 |
| `make test` | PASS：194 passed（Core 44、Runtime 43、Data 56、Platform 51） |
| `make test-contract` | PASS：`CONTRACT_CONFORMANCE_OK` |
| `make test-security` | PASS：51 passed |
| Ruff（14 包源码及四角色测试） | PASS：All checks passed |
| Mypy `--strict`（14 包源码） | PASS：80 source files |
| `uv build --all-packages --wheel` | PASS：14 wheels |
| 全新环境安装并导入 14 wheels | PASS：`WHEEL_IMPORT_OK packages=14` |
| `pip-audit` 联合安装闭包 | PASS：0 known vulnerabilities |
| 高置信 Secret pattern scan | PASS：0 matches |
| `git diff --check` | PASS |

Contract Conformance：

```text
CONTRACT_CONFORMANCE_OK schemas=20 cases=35 positive=18 negative=17 mutation_cases=19 mutation_positive=3 mutation_negative=16 semantic_cases=43 semantic_positive=0 semantic_negative=43 audit_chain_cases=5 audit_chain_positive=1 audit_chain_negative=4 manifest_cases=21 manifest_positive=1 manifest_negative=20 features=52
```

## 安全与失败路径

- `make test-security` 覆盖双主体、跨租户、Purpose/Audience、Context
  过期、角色伪造、Schema Hash、Approval 绑定和 Obligation 失败关闭。
- 写路径覆盖重复已验证回放、`UNKNOWN` 禁止盲重试、权威未执行证明、
  回读确认、参数切换拒绝和持久化不确定结果。
- 拒绝路径验证 Ledger、Outbox 和上游逻辑写入为 0。
- Trace 采样不影响 Audit/Security；调试投影和安全草稿只包含白名单字段。
- Secret 扫描为 0；没有真实凭据、生产 PII、Prompt、Trace 或原始附件。

## 已知问题

- `make acceptance` 尚未实现，不能把当前安全入口写成发布级验收。
- S4 仍需以独立黑盒证明平台行为；本轮 S5 只证明可安装、可测试和稳定
  命令闭包。
- 下游 Sink 必须从可信 Outbox envelope、租户注册表和持久化流头分配
  Audit Stream/sequence/integrity，不得信任草稿自报的最终字段。

## LEARNING_CANDIDATE

```text
LEARNING_CANDIDATE=仓库内 Handoff 路径必须与实施文件一起显式授权
MATURITY=IMPLEMENTED
TRIGGER=有序链要求生产者提交模板化 Handoff，但 Step WRITE_SCOPE 只列产品或共享文件
MECHANISM=如果消费者自行推断证据目录可写，会形成路径越权；如果省略 Handoff，又会破坏可复现交接和下一步解锁条件
STRUCTURE=链授权同时列出精确 Handoff 路径；发现漏配时先保持产品提交不变，由 S1 追加单文件 Scope Amendment
EVIDENCE=docs/team/chain-authorizations/CHAIN-M1-PLATFORM-01.md Scope Amendment 01；S5 implementation Head fe5ed876278fd82ea6be08f6a416fa0f0dbcad89
RESIDUAL_RISK=未来链路模板若不自动校验 HANDOFF 与 WRITE_SCOPE 一致，仍可能重复漏配
TARGET=docs/team/CHAIN_EXECUTION_PROTOCOL.md
```

## 接收会话下一步

1. S4 核验本交接 NEW_HEAD、Handoff SHA、ContractSet、线性父提交和洁净
   Worktree。
2. S4 分支只以 `--ff-only` 精确到达 S5 NEW_HEAD；不能 rebase、reset、
   强制合并或复制文件绕过。
3. 按 `WP-030-a2` 在 S4 独占路径新增双主体、跨租户、审批篡改、
   Obligation、旁路、`UNKNOWN`、Secret 与信号时间线黑盒。
4. S4 完成后按原链路直接唤醒 S7-INTEGRATION / WP-040-a4。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M1-PLATFORM-01
STEP_ID=M1-PLATFORM-03-S5
ATTEMPT_ID=WP-011-a4
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=ff6cc282c81166317f995b975491167479aa1c8d
CONTRACT_CONTENT_DIGEST=sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc
GATE=PASS
HANDOFF=tests/core/evidence/WP-011-a4-HANDOFF.md
NEXT_ROLE=S4-QUALITY
NEXT_ATTEMPT_ID=WP-030-a2
ESCALATE_TO_S1=no
```

## 可回滚方式

- Workspace 实现提交和本 Handoff 提交可由链路 Owner 按逆序
  `git revert`；禁止 reset/rebase。
- 本 Attempt 没有数据库、Migration 或外部系统写入，无数据回滚。
