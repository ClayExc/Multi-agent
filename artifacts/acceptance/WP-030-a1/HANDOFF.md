# WP-030 S4-QUALITY Handoff

## 基本信息

- Work Package：`WP-030`
- Attempt：`WP-030-a1`
- 责任会话：`S4-QUALITY`
- 接收会话：`S1-ARCH`；跨角色复核 `S2-RUNTIME`、`S3-PLATFORM`
- 功能 ID：`FP-OBS-001`、`FP-EVAL-001`、`FP-EVAL-002`、`FP-EVAL-003`、`FP-OPS-002`
- 分支：`codex/s4/wp-030-quality-bootstrap`
- 基线提交：`b5caaf2448c2860cfa67d8c5a39b9cda62eca809`
- 实现提交：`04a0e6da504aaad4cd25ada40f5c3b1b3c0e8578`
- ContractSet 摘要：`sha256:0a82e7f58c4223362721c95a50e9a820d714e550e72eebc7a90ab01e283100fc`
- 状态：离线范围完成，等待跨角色复核；未合并

## 完成内容

- 提供无应用依赖的 ContractSet 内容摘要、文件哈希、Schema Catalog/`$ref`、五角色 Review、发布依赖和可移植字节校验。
- 提供 Traceability 父 ID、独立验证角色、结构化 Evidence、文件存在与 SHA-256 门禁。
- 固定功能 120、安全/故障 36 配额及 `all_declared_cases` 分母；`failed`、`skipped`、`quarantined` 全部计失败。
- 提供两份合成最小 EvaluationCase Fixture；它们未加入 candidate Dataset Manifest，不代表 120/36 数据集完成。
- 提供确定性评分接口和 Judge `semantic_only` 边界；Judge 高分不能覆盖确定性失败。
- 提供零 Case/最小 Case 可复现报告和 Acceptance Manifest 生成骨架；零 Case 明确为失败、无成功率。
- 提供结构化 Feature Evidence 生成接口，拒绝实现者自验、未声明 ID、缺失文件和哈希漂移。
- 提供 Trace/Audit/Security Event 分流 Fixture；Trace 可采样，Audit/Security 不可被采样丢弃，并校验双向安全事件关联。
- 提供 Secret/PII/隐藏思维链字段阻断和报告聚合幂等测试。

## 未完成与非目标

- 未接入 Runtime、API、Gateway、RLS、Outbox、执行账本或恢复路径；分别等待 WP-010/011/020/021。
- 未修改 `Makefile`；`make acceptance` 需由后续共享文件工作包接入。
- 未填充 120/36 数据集，未运行 Provider/Judge，未报告成功率、Token 或质量提升。
- 未修改公共契约、ADR、Traceability 状态或其他角色生产代码。

## 修改文件

| 路径 | 变化 | 所有者 |
|---|---|---|
| `packages/evaluation/**` | 校验、评分、聚合、Evidence 与 Bundle 生成 | S4-QUALITY |
| `packages/observability/**` | 信号分流和关联门禁 | S4-QUALITY |
| `evals/fixtures/**` | 两个最小 Case 与信号路由 Fixture | S4-QUALITY |
| `scripts/acceptance/**` | 直接运行的离线校验和 Bundle 入口 | S4-QUALITY |
| `tests/acceptance/**` | 正常、边界、失败、安全和幂等测试 | S4-QUALITY |
| `artifacts/acceptance/**` | 生成目录说明与本次 Handoff/Proof | S4-QUALITY |

## 契约、数据库与配置变化

- 契约版本：无变化；只消费 rc2 实现基线。
- Migration：无。
- 环境变量：无。
- 新生产依赖：无。
- 兼容性：Python 3.12+；离线入口只使用标准库。

## 验证

| 命令 | 结果 | 证据 |
|---|---|---|
| `python scripts/acceptance/validate_offline.py` | PASS，2 Cases、0 Findings | `proof.json` |
| `python contracts/conformance/validate.py` | NOT_RUN：默认环境缺少 `jsonschema>=4.23` | `proof.json` |
| 参考解释器运行 Contract Conformance | PASS：20 Schema、43 语义负例、5 Audit 链用例、21 Manifest 用例 | `proof.json` |
| `python -m pytest tests/acceptance -q` | NOT_RUN：默认环境缺少 `pytest` | `proof.json` |
| 参考解释器运行 `pytest` | PASS：26 tests | `proof.json` |
| AST/JSON 解析与 `git diff --cached --check` | PASS | `proof.json` |

Evidence：

- `artifacts/acceptance/WP-030-a1/proof.json`
- SHA-256：`sha256:c48dce3aeb23fb91e7a683c4ff0327219a70d123ab9ebda36d1031b3f0938808`

## 安全与失败路径

- 已验证：未知 Feature、重复 Case、Schema 引用缺失、Contract/Case 哈希漂移、120/36 配额缩减、五角色门禁缩减、伪造 Feature Evidence。
- 已验证：Judge 越权到安全集被拒绝；高 Judge 分不能覆盖确定性失败。
- 已验证：零 Case、缺失结果、重复结果、跳过、隔离、聚合重放。
- 已验证：Audit/Security 被采样丢弃、跨事件错链和 secret-like payload 均被拒绝。
- Secret/PII 检查：0 个实际发现；测试与实现中仅保留检测规则本身。

## 已知问题

- 默认 Python 环境尚未具备 `pytest` 与 `jsonschema>=4.23`；由 WP-011 接入公共 Workspace 后必须重跑用户指定的原始命令。
- 参考环境加载了仓库外的 `pytest-asyncio` 插件并产生一条配置弃用警告，不影响 26 项离线测试结果；公共 Workspace 应固定自己的插件配置。
- 当前 Registry/Dataset/Fixture/Traceability 仍为 `candidate`，功能状态仍由 S1 保持 `DESIGNED`，本 Handoff 不构成发布级 Evidence。

## 接收会话下一步

1. `S1-ARCH` 审查分母、Judge 边界、Evidence 结构和报告字段，确认未漂移公共契约。
2. `S2-RUNTIME` 复核 Trace 关联字段和未来 Fake Runtime 接口。
3. `S3-PLATFORM` 复核 Audit/Security 分流、不可采样与双向关联负例。
4. WP-011 公共 Workspace 合入后，用默认 `python` 重跑两条激活验收命令。
5. WP-010/011/020/021 交接后，为跨组件范围创建后续 Attempt；不得在本 Attempt 内推断其已通过。

## 可回滚方式

- 在未合并前丢弃本分支即可；若已集成，使用普通 `git revert` 依次回退 Handoff 提交和实现提交，不重写其他会话历史。
