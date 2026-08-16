# WP-109-a1 S7-INTEGRATION Handoff

## OUTCOME

`PASS_HANDOFF`。在精确输入 `f0b9c529e6408dd8faa53a734bb4e8dcb3844864` 上完成
M9 本地治理组合复算，可交给 S1 独立验证。M9 Manifest Gate 保持 `FAIL`；本交接不声明
M9、Feature、`RELEASED` 或 `FROZEN`，也不启动 M10。

## EVIDENCE

- 消费者门禁通过：S4 与 S7 Worktree clean，当前 S7 Head 是输入祖先；仅以
  `--ff-only` 精确消费输入；Contract、Handoff 和 Proof Hash 均匹配派发值。
- 沿唯一官方 `scripts.acceptance.run_acceptance` 的 `collect_cases →
  build_product_executors → evaluate_case → executor_registration` 路径逐条实测，没有建立
  第二 registry 或汇总器。
- 156 个唯一 Case、collection errors 0；39 completed、117 explicit failed、0 skip、
  0 quarantine。M7/M8/M9 精确支持数为 24/6/9，任一 Case 多 executor 匹配数为 0。
- 对所有 completed 执行证据独立汇总：dangerous output 0、cross-tenant success 0、
  Judge score 使用 0。
- Manifest Gate 明确保持 `FAIL`；117 个未注册执行器 Case 没有被跳过、隔离或移出分母。
- 提交后候选规则为：固定 `INPUT_HEAD` 必须是候选祖先，后继仅允许四个 WP-109 S7
  路径；Contract、Migration、Lock、OPA Bundle、apps 与 packages 对象不得被 S7 改写。

## GATES

- 公开 WP-109 verifier：PASS。
- M9 安全黑盒、M9 executor、WP-109 Integration、Secret Scan：22 passed。
- Contract Conformance：PASS（20 schemas / 35 cases / 43 semantic / 52 features）。
- `uv lock --check`、Ruff、strict Mypy（2 个受影响源文件）、diff-check：PASS。
- `pip-audit`：0 known vulnerabilities；Secret Scan：0 findings。

## REUSE / RISKS / NEXT ACTION

按上游 `DO_NOT_RECHECK` 复用 WP-087、WP-106、WP-107 的 Keycloak/RLS、真实
PostgreSQL/OPA/Migration/Secret 和 Web 证据，并用 Git 保护对象固定其前提；未重复 Compose、
实库、在线 Provider 或全仓。Cache 未用于替代这些门禁。

`BLOCKERS=none`。S1 必须在 clean committed candidate Head 重新运行公开 verifier 和定向
pytest，独立复算 Proof 后作最终裁决。S7 不批准自身结果。`LEARNING_CANDIDATE=none`。
本 Attempt 未使用子 Agent。

```text
OUTCOME=PASS_HANDOFF
CHAIN_ID=CHAIN-M9-GOVERNANCE-01
STEP_ID=M9-09-S7-COMPOSITION
ATTEMPT_ID=WP-109-a1
SESSION_ROLE=S7-INTEGRATION
BASE_COMMIT=f0b9c529e6408dd8faa53a734bb4e8dcb3844864
NEW_HEAD=<this-handoff-commit>
CONTRACT_CONTENT_DIGEST=sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2
HANDOFF=tests/integration/evidence/WP-109-a1-HANDOFF.md
PROOF=tests/integration/evidence/WP-109-a1-PROOF.json
M9_MANIFEST_GATE=FAIL
GATE=PASS
NEXT_ROLE=S1-ARCH
USER_GATE_REQUIRED=yes
```
