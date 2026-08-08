# WP-036-a1 S1 本地验收记录

## 结论

```text
WORK_PACKAGE=WP-036
ATTEMPT_ID=WP-036-a1
BASE_COMMIT=9c53321d259ddb484e38c0ea393321270ebf84d8
VERDICT=PASS_LOCAL
REMOTE_CI=PENDING_FIRST_PUSH
M7_ACTIVATED=false
```

本包只收口工程控制面、质量入口和后续工作包，没有实现 M7 产品功能，也没有
修改 ContractSet Artifact 或机器 Traceability。

## 完成内容

- 当前契约摘要统一为 `1cad07bd…`，当前 Workspace 统一为 15 个成员。
- 历史活动链已关闭；M7～M20 保持 approved-not-started。
- OpenAI/Claude Agents SDK 保留为正式 Runtime Adapter 技术栈。
- M7 拆为 WP-070～WP-073，按 Provider → 产品装配 → Web/Studio → 执行器/门禁解锁。
- 默认 Pytest 收集 `tests/integration`，新增全仓、覆盖率、安全、审计和 CI 入口。
- GitHub Actions 使用只读权限和完整提交 SHA；Linux CI 运行 `make ci`。
- Windows 使用 `scripts/quality.ps1`，不依赖 GNU Make。
- 根目录本地生成物已移出仓库，并增加 `.codex-tmp/` 忽略规则。

## 本地证据

| 门禁 | 结果 |
|---|---|
| `uv sync --all-packages --all-groups --locked` | PASS，140 个锁定包 |
| Ruff | PASS |
| strict Mypy | PASS，116 个 Workspace/Web 源码文件 |
| 全仓 Pytest | PASS，729 passed |
| Contract Conformance | PASS，20 schemas / 43 semantic negatives / 52 features |
| Security | PASS，95 passed |
| 分支覆盖率 | PASS，82.15%，阈值 80% |
| Dependency Audit | PASS，0 个已知漏洞 |
| LangGraph CLI Smoke | PASS，CLI 0.4.31 |
| Markdown 关键链接 | PASS，0 个缺失 |
| 非工程术语检查 | PASS，0 个命中 |
| `git diff --check` | 最终提交前复算 |

依赖审计首次发现 `cryptography 49.0.0 / PYSEC-2026-3552`，已把直接开发约束
提升到 `cryptography>=50,<51` 并锁定 50.0.0；复跑审计为 0 个已知漏洞。

## 环境说明

- 当前 Windows 没有 `make.exe`，因此 Make 目标本机记为 `ENV_BLOCKED`；对应
  PowerShell 入口和底层 uv 命令均已通过。
- Docker Desktop 本轮未运行，本包没有修改 Compose、Migration 或运行时数据代码。
- GitHub CI 只有推送后才能产生远端运行记录；本地已经逐项复现同一门禁。

## 保留风险

- `packages/evaluation`、`packages/observability` 与 Web Server 尚未全部成为可安装
  Workspace 成员；strict Mypy 本轮保持已接受的 116 文件基线，M7 产品化时再收口。
- `FP-UI-001` 与 `FP-ONB-001` 仍未进入 ContractSet 管理的机器 Traceability；
  M7 激活前必须通过独立契约维护包和五角色摘要复审处理。
- PostgreSQL Adapter 的覆盖率低于全仓平均值；实库行为已有历史集成证据，但后续
  数据改动仍必须运行 Compose 恢复门禁。
