# WP-011-a5 S5-CORE Studio 依赖闭包交接

## 基本信息

- Work Package：WP-011（WP-012 共享依赖子步）
- Attempt ID：WP-011-a5
- Chain ID：CHAIN-M2-STUDIO-01
- Step ID：M2-STUDIO-01-S5
- 责任会话：S5-CORE
- 接收会话：S2-RUNTIME
- 交接策略：CONSUMER_GATE
- 风险等级：R2
- 功能 ID：FP-FLOW-001、FP-FLOW-004、FP-FLOW-005、FP-FLOW-006、
  FP-OBS-001、FP-OPS-002
- 基线 / 输入提交：
  `31f244c7ab28f8c635cc973dab1f591b55105429`
- 实现提交：`19fa132e4a9a4d1bc71d7951c5c2645af9e39e30`
- 分支：`codex/s5/wp-011-core-bootstrap`
- 最终提交：本文件所在提交；精确 SHA 由唤醒信封返回
- ContractSet 摘要：
  `sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`
- 状态：完成，等待 S2 消费门禁

## 授权与线性候选

- S5 原 Head `192ebe38df84ed9097e4045847aa991632a2ff63` 是激活提交
  `31f244c7ab28f8c635cc973dab1f591b55105429` 的祖先。
- S5 在干净工作树上使用 `git merge --ff-only` 精确到达激活提交；
  没有执行 merge commit、rebase、reset、强制合并或跨分支文件复制。
- 链授权：
  `docs/team/chain-authorizations/CHAIN-M2-STUDIO-01.md`。
- 本 Attempt 的变更严格限制为 `pyproject.toml`、`uv.lock`、`Makefile`
  和本 Handoff；未创建 `langgraph.json`，未修改任何 S2 路径。

## 完成内容

- 在根开发依赖组声明
  `langgraph-cli[inmem]>=0.4.31,<0.5`，由 `uv.lock` 精确锁定：
  - `langgraph-cli==0.4.31`
  - `langgraph-api==0.11.2`
  - `langgraph-runtime-inmem==0.31.2`
- 锁文件从 78 个包扩展到 116 个包；新增 38 个包均属于本地 Agent
  Server / Studio 开发闭包。锁哈希：
  `sha256:9c9ab3febad1a13571d51e567c6546f27be809f86927e03b0e64339e4ac957c2`。
- 新增稳定命令：
  - `make studio`：在 `127.0.0.1:2024` 启动本地 Agent Server，
    `LANGSMITH_TRACING=false`，不自动打开浏览器且不传 `--tunnel`。
  - `make studio-smoke`：在 S2 创建 `langgraph.json` 前即可验证锁定 CLI
    和 `dev` 命令面。
- `STUDIO_CONFIG`、`STUDIO_HOST`、`STUDIO_PORT` 只允许调用者显式覆盖；
  默认配置为根 `langgraph.json`、回环地址和端口 2024。
- Windows 稳定命令显式设置 `PYTHONUTF8=1`，避免 CLI 帮助文本中的
  Unicode 图标在 GBK 控制台触发编码失败。

## 未完成与非目标

- 未创建 `langgraph.json`、graph factory、Studio entrypoint、
  `debug_projection`、拓扑快照或 Runtime 测试；这些属于
  S2-RUNTIME / WP-012。
- 未启动真实 Agent Server，因为输入提交尚无 S2 所有的
  `langgraph.json`。本步只验证官方 CLI、锁文件和安全命令面。
- 未启用 LangSmith 远程 Trace、LangSmith API Key、生产 `.env`、
  公网 Tunnel、生产 Provider、企业 MCP、生产数据库或真实 PII。
- `make acceptance` 仍未实现；本 Handoff 不声明 WP-012 已验收、
  已发布或已完成 Studio 黑盒门禁。

## 修改文件

| 文件 | 变化 | 所有者 |
|---|---|---|
| `pyproject.toml` | 声明锁定范围内的 Studio 开发依赖 | S5-CORE |
| `uv.lock` | 锁定官方本地 Agent Server 开发闭包 | S5-CORE |
| `Makefile` | 新增安全的 `studio` / `studio-smoke` 稳定入口 | S5-CORE |
| `tests/core/evidence/WP-011-a5-HANDOFF.md` | 本交接证据 | S5-CORE |

## 契约、数据库与配置变化

- 公共契约：无变化。
- ContractSet：
  `sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`。
- Domain / Application / API 公共行为：无变化。
- Migration / RLS / PostgreSQL / Redis：无变化。
- 生产依赖：无新增；新增内容只位于根 `dev` 依赖组。
- 环境变量：稳定命令把 `LANGSMITH_TRACING` 固定为 `false`，并设置
  `PYTHONUTF8=1`；没有新增生产 Secret 或生产配置。

## 依赖、许可证、替代方案与攻击面

### 用途与版本

- `langgraph-cli[inmem]` 是官方推荐的无 Docker 本地 Agent Server
  安装方式，用于连接本地 LangGraph 应用与 Studio。
- 约束固定在兼容的 CLI `0.4.x`，锁文件当前选择 `0.4.31`；升级到
  `0.5` 或更高版本必须经过新的 Workspace 复核。
- 官方参考：
  - <https://docs.langchain.com/oss/python/langgraph/studio>
  - <https://docs.langchain.com/langsmith/cli>

### 许可证

- `langgraph-cli 0.4.31`：MIT。
- `langgraph-api 0.11.2`、`langgraph-runtime-inmem 0.31.2`：
  Elastic License 2.0。
- 其余新增传递依赖的包元数据或随包许可证为 Apache-2.0、MIT、
  BSD、MIT-0 或兼容的双许可证；其中 `forbiddenfruit` 随包同时提供
  GPLv3+ 和 MIT 文本，`blockbuster` 随包提供 Apache-2.0 文本。
- 由于 Agent Server 核心包含 Elastic-2.0 组件，本闭包只授权本地开发
  和自动化验证，不据此授权产品分发、托管服务或生产部署。

### 替代方案

- `langgraph up` / Docker：需要额外容器服务，不符合本链要求的轻量
  `inmem` 本地入口。
- 临时 `uvx` 或开发者自行安装：无法绑定仓库锁文件，不能提供可复现
  的消费者门禁。
- 自建 FastAPI/ASGI 调试服务器：会复制官方 Agent Server 协议并扩大
  维护与安全面，且容易形成 Studio 与 Worker 两套入口。

### 攻击面与控制

- 本地 HTTP 服务：默认只绑定 `127.0.0.1`；不能自动改为
  `0.0.0.0`。
- 公网 Tunnel：CLI 只有显式 `--tunnel` 才开启；稳定命令不传该选项。
- 远程 Trace：稳定命令固定 `LANGSMITH_TRACING=false`。
- 浏览器与远程 UI：稳定命令使用 `--no-browser`；S2/S4 通过本地 API
  做自动化 Smoke 和黑盒断言。
- 配置 / 环境加载：S5 命令不传生产环境文件；S2 的根
  `langgraph.json` 必须使用 `studio-safe` 合成配置，不能引用生产
  `.env`。
- 热重载、文件监视、内存数据库和本地 API 扩大了开发机攻击面；
  因此该依赖只在开发组内，默认 Profile 禁止外部网络、真实凭据和
  生产数据。

## 验证

环境：Windows、CPython 3.12.11、uv 0.11.32、GNU Make 4.4.1。

| 命令 / 门禁 | 结果 |
|---|---|
| `uv lock`、`uv lock --locked` | PASS：116 packages，锁哈希稳定 |
| `make bootstrap` | PASS：14 个内部包和全部锁定组可安装 |
| `make studio-smoke` | PASS：LangGraph CLI 0.4.31；`dev --help` 正常 |
| `make --dry-run studio` 安全断言 | PASS：Trace=false、回环地址、no-browser、无 tunnel |
| `make test` | PASS：194 passed |
| `make test-contract` | PASS：`CONTRACT_CONFORMANCE_OK` |
| `make test-security` | PASS：51 passed |
| Ruff（14 包源码及 Core/Runtime/Data/Platform 测试） | PASS：All checks passed |
| Mypy `--strict`（14 包源码） | PASS：80 source files |
| `uv build --all-packages --wheel` | PASS：14 wheels |
| 全新环境安装并导入 14 wheels | PASS：`WHEEL_IMPORT_OK packages=14` |
| `pip-audit` 联合安装闭包 | PASS：0 known vulnerabilities |
| 本 Attempt 变更路径高置信 Secret Scan | PASS：0 matches |
| `git diff --check` | PASS |
| `make acceptance` | 未实现：`No rule to make target 'acceptance'` |

Contract Conformance：

```text
CONTRACT_CONFORMANCE_OK schemas=20 cases=35 positive=18 negative=17 mutation_cases=19 mutation_positive=3 mutation_negative=16 semantic_cases=43 semantic_positive=0 semantic_negative=43 audit_chain_cases=5 audit_chain_positive=1 audit_chain_negative=4 manifest_cases=21 manifest_positive=1 manifest_negative=20 features=52
```

`pip-audit` 第一次访问 PyPI 时发生 15 秒 TLS 握手超时，没有形成审计
结论；使用同一环境和 60 秒 socket timeout 重试后完成，结果为 0 个已知
漏洞。内部 `flowpilot-*` 包不发布到 PyPI，审计工具按预期将其列为跳过。

## 安全与失败路径

- `make studio-smoke` 在不存在 `langgraph.json` 时仍能验证 CLI 和
  `dev` 命令，因此不会诱使 S5 创建或复制 S2 的图配置。
- `make --dry-run studio` 证明默认命令固定回环地址、关闭远程 Trace、
  不打开浏览器且没有公网 Tunnel 参数。
- 完整产品与平台安全测试保持 194 / 51 全通过；Domain、Application、
  Approval、租户、Ledger 和 Outbox 不变量未因 Studio 依赖放宽。
- 全仓直接搜索会命中 `tests/integration/test_wp040_composition.py` 中
  故意构造的密钥负例；本门禁与仓库集成脚本一致，只扫描本 Attempt
  变更路径，结果为 0。

## 已知风险

- S2 必须确保 `langgraph.json` 不引用生产 `.env`，并让默认
  `studio-safe` 使用 Fake Runtime/Tool、合成租户和关闭的外部网络。
- S2 后续真实启动 Smoke 必须证明 Studio 与 Worker 使用同一 graph
  factory；本依赖闭包不证明图语义。
- Elastic-2.0 组件不能被本 Handoff 解释为生产分发或托管授权；若产品
  形态需要部署 Agent Server，必须由 S1 重新评估许可证、架构和风险。
- `make acceptance` 尚未实现，不能把当前门禁写成完整验收或发布结论。

## LEARNING_CANDIDATE

```text
LEARNING_CANDIDATE=含 Unicode 图标的 Python CLI 在 Windows GBK 控制台可能在输出帮助文本前失败
MATURITY=IMPLEMENTED
TRIGGER=Windows 默认代码页运行 langgraph dev --help
MECHANISM=Click 帮助文本包含 Unicode 图标，stdout 使用 GBK 编码时触发 UnicodeEncodeError
STRUCTURE=跨平台稳定命令显式设置 PYTHONUTF8=1，并把 CLI help 纳入无配置 Smoke
EVIDENCE=make studio-smoke 在 Windows、CPython 3.12.11、langgraph-cli 0.4.31 下通过
RESIDUAL_RISK=绕过 Makefile 直接调用 CLI 的开发者仍可能受本机代码页影响
TARGET=docs/architecture/ENGINEERING_PLAYBOOK.md
```

## 接收会话下一步

1. S2 核验本交接 NEW_HEAD、Handoff SHA、ContractSet、线性父提交和干净
   Worktree。
2. S2 分支只以 `--ff-only` 精确到达 S5 NEW_HEAD；不能 rebase、reset、
   强制合并或复制文件绕过。
3. 按 WP-012 在 S2 独占路径和根 `langgraph.json` 授权内实现同源 graph
   factory、稳定图 ID `flowpilot_it_service`、`studio-safe`、
   `debug_projection`、拓扑快照与 Runtime 测试。
4. S2 使用 `make studio` 做真实本地 Agent Server Smoke；不得启用公网
   Tunnel、生产凭据、生产 `.env` 或远程 Trace。
5. S2 完成后按原链路直接唤醒 S4-QUALITY；仅在 P0/P1、契约变化、
   路径越权、门禁失败或非线性 Head 时上报 S1。

## 机器可读交接摘要

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M2-STUDIO-01
STEP_ID=M2-STUDIO-01-S5
ATTEMPT_ID=WP-011-a5
NEW_HEAD=<this-handoff-commit>
BASE_COMMIT=31f244c7ab28f8c635cc973dab1f591b55105429
INPUT_HEAD=31f244c7ab28f8c635cc973dab1f591b55105429
IMPLEMENTATION_HEAD=19fa132e4a9a4d1bc71d7951c5c2645af9e39e30
CONTRACT_CONTENT_DIGEST=sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc
GATE=PASS
HANDOFF=tests/core/evidence/WP-011-a5-HANDOFF.md
NEXT_ROLE=S2-RUNTIME
NEXT_ATTEMPT_ID=WP-012-a1
NEXT_TASK_THREAD_ID=019fa697-7be1-7811-8afe-5d8763bbfd9f
ESCALATE_TO_S1=no
```

## 可回滚方式

- 实现提交和本 Handoff 提交可由链路 Owner 按逆序 `git revert`；
  禁止 reset/rebase。
- 本 Attempt 没有数据库、Migration 或外部系统写入，无数据回滚。
