# WP-036：工程控制面与质量入口收口

## 元数据

- 状态：DONE
- Attempt ID：WP-036-a1
- 风险等级：R2
- 责任会话：S1-ARCH
- 评审会话：S1-ARCH 机器门禁；GitHub CI 首次运行后补充外部复现
- 功能 ID：FP-OPS-002、FP-EVAL-001、FP-EVAL-002、FP-AGT-002
- 依赖工作包：M0～M6、WP-P2 已进入主分支
- 执行模式：ORDERED
- Chain ID：无
- Step ID：CONTROL-PLANE-RECONCILIATION
- 交接策略：S1_GATE
- 下一角色：USER
- 目标分支：`master`（当前无并行写会话）

## 目标

- 统一当前契约摘要、Workspace 数量、里程碑和活动链状态。
- 将工程质量入口收口为全仓测试、契约、安全、覆盖率、静态检查和依赖审计。
- 建立最小 GitHub CI，并以锁文件安装依赖。
- 明确保留 OpenAI/Claude Agents SDK 为正式 Runtime Adapter 技术栈。
- 将 M7 拆为四个可独立验收的工作包，但不启动 M7 实现。
- 从工程仓库移出未受 Git 管理的本地生成目录，并建立忽略规则。

## 非目标

- 不实现 LiteLLM、DeepSeek、Agents SDK Adapter 或新的产品链。
- 不修改 `contracts/**`、`docs/acceptance/traceability.v1.json` 或当前
  ContractSet 摘要。
- 不把 M0～M6 提升为 `RELEASED` 或 `FROZEN`。
- 不执行真实企业系统、付费模型或生产凭据调用。

## 允许修改路径

- S1 独占文档路径。
- `.gitignore`、`Makefile`、`pyproject.toml`、`uv.lock`。
- `.github/workflows/quality.yml`。
- `scripts/quality.ps1`（Windows 等价工程质量入口）。
- 根工程设计总稿。

共享文件由 S1 在本包内作为唯一写入者；当前没有其他工作树或活动开发链。

## 输入契约

| 契约 | 版本 | 提供者 |
|---|---|---|
| ContractSet | `1.0.0-rc.2` / `1cad07bd…` | WP-000 |
| Python Workspace | 15 个成员 / `uv.lock` | M0～M6 |
| 实施路线 | M7～M20 approved-not-started | S1-ARCH |

## 输出契约

| 契约 | 版本 | 消费者 |
|---|---|---|
| 工程质量命令 | `make test-all/ci` v1 | 所有后续工作包 |
| M7 工作包集合 | WP-070～WP-073 | M7 Agent Registry |
| 当前事实说明 | M0～M6 / M7 next | 用户与所有角色 |

## 架构与安全约束

- GitHub Actions 只获得 `contents: read` 权限，第三方 Action 固定到完整提交 SHA。
- 依赖安装必须使用 `uv.lock`，依赖审计失败时 CI 失败关闭。
- 覆盖率只作为代码执行证据，不替代契约、安全、恢复与产品验收。
- 历史 Chain 的输入摘要和证据不得被改写；只关闭错误的活动状态。
- 机器追踪表属于当前 ContractSet Artifact，本包只澄清状态，不绕过五角色审签修改。

## 实施内容

1. 清理仓库外本地生成物并增加忽略规则。
2. 修正 README、STRUCTURE、Handoff、Session、工作包索引和活动链状态。
3. 接入 pytest-cov、pip-audit、全仓测试、静态检查和 CI。
4. 移除设计总稿中与工程交付无关的内容。
5. 创建 WP-070～WP-073，写清路径、输入、输出、风险和解锁条件。

## 必须测试

- 正常路径：全仓 Python 测试、Contract Conformance、Ruff、strict Mypy 通过。
- 边界条件：`tests/integration` 被默认与 `test-all` 收集。
- 失败路径：覆盖率低于阈值、依赖漏洞或契约漂移使命令非零退出。
- 安全负向：固定 Action SHA；跨租户、凭据和策略测试继续进入安全门禁。
- 恢复/幂等：重复执行 `uv lock --locked` 和质量命令不改变受管文件。

## 验收命令

```bash
make lint
make test-all
make test-security
make test-coverage
make audit
git diff --check
```

## 证据

- 本地命令结果见 [`WP-036-A1-S1-REVIEW.md`](../../review/WP-036-A1-S1-REVIEW.md)。
- GitHub CI 首次运行结果由远端 Workflow 保留。

## 完成定义

- 当前事实源不再把历史链误报为活动链。
- 默认测试覆盖集成目录，覆盖率与依赖审计可在本地和 CI 重复运行。
- M7 四个工作包全部处于未激活状态，且没有 M7 产品代码变更。
