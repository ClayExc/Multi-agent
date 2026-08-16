# WP-114-a1 S4-QUALITY Handoff

## 基本信息

- Chain / Step：`CHAIN-M10-KNOWLEDGE-01` / `M10-04-S4-RETRIEVAL`
- Work Package / Attempt：`WP-114` / `WP-114-a1`
- 角色 / 下一角色：`S4-QUALITY` / `S3-PLATFORM`
- 执行：`ORDERED / IMPLEMENTATION_AFTER_CONSUMER_ACCEPT`，风险 `R2`
- 输入 Head：`040be0351b3d4ddadd7a2759b643452aff10e1fd`
- ContractSet：`sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 上游 Handoff：`tests/data/evidence/WP-113-a1-HANDOFF.md`
- 上游 Handoff SHA-256：`sha256:278fc0d6e70c563b9c692421ed2aad942e76aae5d421f88f1748afa2f4510272`
- 结果：`PASS_HANDOFF`

## 消费者门禁

- 任务、角色、Worktree 与分支匹配；消费前工作树 clean。
- 消费前 S4 Head 是输入 Head 的祖先，仅执行 `git merge --ff-only`，随后精确到达
  `040be0351b3d4ddadd7a2759b643452aff10e1fd`。
- 独立复算 WP-113 Handoff Hash 与 ContractSet digest 均匹配。
- 复用 WP-113 已验证的 PostgreSQL/pgvector、RLS、ACL/purpose/classification 过滤、索引恢复
  和跨租户候选为 0 的证据；未重复运行数据库、Migration、Compose 或 S6 Owner 单测。

## 完成内容

- 新建可构建的 `flowpilot-retrieval` 包，公开 `HybridRetrievalEngine`、检索 Port、版本化排序
  策略、安全结果与稳定错误码。
- 引擎使用固定离线 Embedding identity，构造 S6 `KnowledgeCandidateQuery`；tenant、purpose、
  classification ceiling 只取自 server-built `KnowledgeRequestContext/SecurityContextRef`。
- 以版本化权重融合向量相似度和关键词 rank，执行阈值过滤；相同文档精确版本只保留最高分
  Section，同分使用 `(document_id, document_version, section_id)` 稳定键。
- 候选在输出前逐项复验 tenant、分级上限、score-input version、有限分数、Opaque
  `knowledge-content://<sha256>` 引用及 `StableCitation` 的精确版本/Section/Hash。
- 最终 Hit 必须通过 `KnowledgeCitationVerificationPort.resolve_citation`，且回传 Citation、
  `content_ref`、classification 与候选逐字段精确一致。过期、撤销、不存在、Hash/版本漂移或
  Port 异常统一失败关闭，不暴露原异常。
- 无候选或低于阈值返回显式空 Hit；不调用 Judge，也不把安全断言交给语义评分。
- 诊断仅包含算法/Embedding/score-input version 与聚合计数；不包含查询正文、source_ref、
  ACL 主体、向量、SecurityContext 或未授权候选标识。

## 变更路径

- `packages/retrieval/pyproject.toml`
- `packages/retrieval/src/flowpilot_retrieval/**`
- `tests/acceptance/m10/conftest.py`
- `tests/acceptance/m10/test_retrieval_engine.py`
- `tests/acceptance/m10/evidence/WP-114-a1-HANDOFF.md`

未修改公共 Contract、数据库、Migration、Gateway、模型、根 Workspace、`uv.lock`、Makefile
或其他角色生产代码。

## 验证

| 检查 | 结果 |
|---|---|
| `PYTHONPATH=packages/retrieval/src uv run python -m pytest tests/acceptance/m10 -q` | PASS：`44 passed` |
| `uv run ruff check packages/retrieval tests/acceptance/m10` | PASS |
| strict Mypy（Retrieval + M10 Acceptance，显式既有 Source roots） | PASS：`7 source files` |
| `python contracts/conformance/validate.py` | PASS：20 schemas / 35 cases / 43 semantic / 52 features |
| `uv build packages/retrieval`（系统临时目录，完成后清理） | PASS：sdist + wheel |
| `flowpilot_security.scan_secret_material`（9 个实现/测试/证据文件） | PASS：`0 findings` |
| `git diff --check` | PASS |

44 条确定性测试覆盖：正常融合、同分稳定顺序、实际 Hash Embedding 重放、精确版本去重、
空/低相关结果、跨租户候选、超分级候选、候选上限扩张、score-input 漂移、非有限分数、
Opaque Ref、冲突重复项、上下文 tenant/purpose/有效期、Embedding identity/输出、候选 Port
失败，以及 Citation version/hash/content_ref/classification 漂移。安全负例均在引用输出前失败。

## 风险与下一步

- `packages/retrieval` 已具备独立 pyproject，但按路径所有权未修改根 Workspace/Lock；由
  WP-116 的 S5 Workspace 闭包注册并锁定。S3 WP-115 在当前线性 Head 上消费其 Source Port，
  不应复制排序或引用校验逻辑。
- S3 必须保持 `knowledge.search.v1` Schema Hash 不变，并在可信 Gateway/MCP 边界完成
  SecurityContext、tenant、purpose、ACL、classification 和 DLP/Prompt Injection 门禁后才调用
  Retrieval Engine。正文读取不得先于授权与引用复验。
- `BLOCKERS=none`。未声明 M10、Feature、`RELEASED` 或 `FROZEN`。
- `SUBAGENTS_USED=0`；`LEARNING_CANDIDATE=none`。

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M10-KNOWLEDGE-01
STEP_ID=M10-04-S4-RETRIEVAL
ATTEMPT_ID=WP-114-a1
INPUT_HEAD=040be0351b3d4ddadd7a2759b643452aff10e1fd
NEW_HEAD=<this-handoff-commit>
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/acceptance/m10/evidence/WP-114-a1-HANDOFF.md
NEXT_ROLE=S3-PLATFORM
NEXT_ATTEMPT_ID=WP-115-a1
ESCALATE_TO_S1=no
SUBAGENTS_USED=0
USER_INPUT_REQUIRED=none
```
