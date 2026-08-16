# WP-115-r2-quality S4-QUALITY Handoff

## 基本信息

- Chain / Step：`CHAIN-M10-KNOWLEDGE-01` / `M10-05R3-S4-CITATION-PROJECTION`
- Work Package / Attempt：`WP-115-R2` / `WP-115-r2-quality`
- 角色 / 下一角色：`S4-QUALITY` / `S3-PLATFORM`
- 执行：`ORDERED / IMPLEMENTATION_AFTER_CONSUMER_ACCEPT`，风险 `R2`
- 输入 Head：`2aa2a2c8915621492bc8175983579122fc48d545`
- 上游 Heads：S5 `45ed719207e5b00e4a0d71b80ed01e42fabdb8f0`；
  S6 `2aa2a2c8915621492bc8175983579122fc48d545`
- ContractSet：`sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2`
- 上游 Handoff：`tests/data/evidence/WP-115-r2-data-HANDOFF.md`
- 上游 Handoff SHA-256：`sha256:26ed6407446ab9c57731368f2b9e3ca59426f7a1f35d76cf3debbd59882d9271`
- 结果：`PASS_HANDOFF`

## 消费者门禁

- S4 分支消费前 Head 为 `629571c97631e31cab0c5a1eed241ce4f51ab3e0`，工作树 clean，
  且是输入 Head 的祖先。
- 只执行 `git merge --ff-only 2aa2a2c8915621492bc8175983579122fc48d545`，随后精确到达
  输入 Head；Handoff Hash 与 ContractSet digest 独立复算匹配。
- 复用 S5/S6 的 Query Service、exact-version PostgreSQL Projection、RLS、2048 字符截断和
  真实数据库证据；未重复运行 Owner 单测、PostgreSQL、Migration 或 Compose。

## 完成内容

- `RetrievalRequest.action_classification_ceiling` 改为强制、无默认值输入；不接受字符串或
  缺失字段，不提供 v1 兼容回退。
- Action ceiling 必须不高于可信 `SecurityContextRef.data_classification_ceiling`，并同时传入
  S6 Candidate Query 和 S5 `KnowledgeQueryService.resolve_citation`。超上限在 Embedding/
  Candidate 前失败，超分级候选在 Citation Projection/正文读取前失败。
- `KnowledgeCitationVerificationPort` 精确迁移到 v2 keyword-only
  `action_classification_ceiling` 签名；Mypy 静态守卫确认真实 `KnowledgeQueryService` 满足该 Port。
- `RetrievalHit` 新增 mandatory `content_excerpt`，只接受授权后的
  `KnowledgeCitationResolution` 结果；字段使用 `repr=False`，不进入 Retrieval 诊断。
- v2 Fake 记录 Citation 调用、Action ceiling 与正文读取次数。跨租户、错误 purpose、过期
  Context、超 Action ceiling、超分级候选、低相关/空结果、错误版本、Hash 漂移及授权拒绝
  均验证正文读取为 0；正确路径才投影 excerpt。
- 最终 Citation、content_ref 和 classification 仍必须与候选逐字段精确一致；不查询 latest，
  不把旧版本静默重定向到新版本。

## 变更路径

- `packages/retrieval/src/flowpilot_retrieval/engine.py`
- `packages/retrieval/src/flowpilot_retrieval/models.py`
- `packages/retrieval/src/flowpilot_retrieval/ports.py`
- `tests/acceptance/m10/test_retrieval_engine.py`
- `tests/acceptance/m10/evidence/WP-115-r2-quality-HANDOFF.md`

未修改公共 Contract、S5/S6/S3 生产代码、数据库、Migration、根 Workspace、`uv.lock`、
Makefile 或 `knowledge.search.v1` Schema。

## 验证

| 检查 | 结果 |
|---|---|
| `PYTHONPATH=packages/retrieval/src uv run python -m pytest tests/acceptance/m10 -q` | PASS：`51 passed` |
| `uv run ruff check packages/retrieval tests/acceptance/m10` | PASS |
| strict Mypy（Retrieval + M10 Acceptance，显式既有 Source roots） | PASS：`7 source files` |
| `python contracts/conformance/validate.py` | PASS：20 schemas / 35 cases / 43 semantic / 52 features |
| `uv build packages/retrieval`（系统临时目录，完成后清理） | PASS：sdist + wheel |
| `flowpilot_security.scan_secret_material`（本范围实现/测试/证据） | PASS：`0 findings` |
| `git diff --check` | PASS |

## 风险与下一步

- S3 原 P1 两个机理缺口已闭合：Action classification ceiling 可在 Candidate 形成前衰减；
  `redacted_summary` 可由授权后的 exact-version `content_excerpt` 提供。S3 不得自行读取正文、
  伪造摘要或恢复兼容默认值。
- 根 Workspace/Lock 仍按既定所有权留给 S5 WP-116；本修复不改变该 P2 组合前提。
- `BLOCKERS=none`。无新增 P0/P1；未声明 M10、Feature、`RELEASED` 或 `FROZEN`。
- `SUBAGENTS_USED=0`；`LEARNING_CANDIDATE=none`。

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M10-KNOWLEDGE-01
STEP_ID=M10-05R3-S4-CITATION-PROJECTION
ATTEMPT_ID=WP-115-r2-quality
INPUT_HEAD=2aa2a2c8915621492bc8175983579122fc48d545
NEW_HEAD=<this-handoff-commit>
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
GATE=PASS
HANDOFF=tests/acceptance/m10/evidence/WP-115-r2-quality-HANDOFF.md
NEXT_ROLE=S3-PLATFORM
NEXT_ATTEMPT_ID=WP-115-r2-platform
ESCALATE_TO_S1=no
SUBAGENTS_USED=0
USER_INPUT_REQUIRED=none
```
