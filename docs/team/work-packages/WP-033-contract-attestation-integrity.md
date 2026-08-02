# WP-033：Contract Review Attestation 完整性修复

## 元数据

- 状态：READY
- Attempt ID：WP-033-a1
- 风险等级：R2
- 责任会话：S1-ARCH
- 后续评审：S2-RUNTIME～S6-DATA
- 功能 ID：FP-OPS-002
- 依赖工作包：WP-032 已接受
- 执行模式：ORDERED
- Chain ID：CHAIN-M6-ACCEPTANCE-REMEDIATION-01
- Step ID：M6-REM-03-S1-CONTRACT
- 输入 Head：`e0bc54d8de50f0965163efb54247ce3f11b2d939`

## 问题

当前 ContractSet 的 `reviews[*]` 已机械改写为最新 `content_digest`，但其引用的
Attestation 文件仍声明旧摘要。验证器只校验证据文件 Hash，不解析文件内的角色、
结论和摘要，因此会错误接受“文件未变但声明被外部改写”的审签记录。

## 目标

- 让 Review 证据的文件内容与 ContractSet 中的角色、结论和摘要确定性绑定。
- 任何角色错配、结论错配、摘要错配、字段缺失或重复都失败关闭。
- Contract 内容变化后，将旧 Review 全部失效为 `PENDING`，再启动五角色 DELTA 复审。

## 允许修改路径

- `contracts/**`
- `docs/review/**`
- 本工作包、Chain Authorization 与工作包索引

## 实施内容

1. 在 `contracts/conformance/validate.py` 增加 Attestation 内容解析与语义校验。
2. 主门禁与 `manifest_semantic_cases` 共用同一校验函数，避免两套规则漂移。
3. 增加摘要、角色、结论、缺失/重复字段负例；不得只靠证据文件 Hash 判定有效。
4. 把五条旧 Review 重置为 `PENDING` 和空证据字段。
5. 更新 Validator Artifact Hash、ContractSet `content_digest` 及候选就绪说明。

## 不变量

- `reviews/status/frozen_at/content_digest` 继续排除在稳定内容摘要投影外，避免审签哈希悖论。
- PENDING Review 不引用历史证据；非 PENDING Review 必须绑定同一内容摘要。
- 不改变任何业务 Schema、Runtime Port、数据库或 API 契约。
- 新候选在五方复审前保持 `candidate`，不得宣称 frozen 或已发布。

## 验收

```powershell
uv run --all-packages --all-groups --locked python -B contracts/conformance/validate.py
uv run --all-packages --all-groups --locked python -B -m pytest tests/acceptance/evaluation -q
uv run --all-packages --all-groups --locked ruff check contracts/conformance
uv run --all-packages --all-groups --locked mypy --strict --explicit-package-bases contracts/conformance/validate.py
```

必须额外证明：旧 `RC2-0A82-*` 文件即使文件 Hash 正确，也不能为新摘要提供有效
ACCEPT；角色、结论或摘要任一单字段错配均失败。

## 完成定义

- Contract Conformance 通过，新增语义负例全部按预期失败。
- 五条 Review 均为 PENDING，旧 Attestation 仅保留历史记录。
- 新 `content_digest` 与 Validator Artifact Hash 可独立复算。
- S1 生成五角色最小 DELTA 复审输入后，才解锁 Step 4。
