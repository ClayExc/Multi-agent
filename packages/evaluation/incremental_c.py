"""M6 incremental-C candidate corpus: 16 functional cases (goal C1).

The corpus is a candidate-only local dataset under
``evals/datasets/m6-incremental-c``.  It continues increments A (69
candidates) and B (52 candidates) on the M6 120/36 freeze path: 16
functional candidates — approval recovery 8 (``ar.009``-``ar.016``) and
long context & handoff 8 (``lh.009``-``lh.016``) — completing the released
``approval_recovery`` and ``long_context_handoff`` functional quotas
(16/16 each) and moving the cumulative functional candidate count from 88
to 104.

Every candidate is a full EvaluationCase v1 instance that binds:

- Feature: ``FP-EVAL-001`` as registered in
  ``docs/acceptance/traceability.v1.json``;
- Fixture: the released ``tenant-a`` / ``principal-basic-user`` fixtures;
- Rule assertions: the deterministic assertions registered in the released
  evaluation registry — ``assert.task.terminal_status.v1`` +
  ``assert.approval.valid.v1`` + ``assert.tool.write_count.v1`` for
  ``approval_recovery`` and ``assert.task.terminal_status.v1`` +
  ``assert.context.within_budget.v1`` + ``assert.handoff.fields_allowed.v1``
  for ``long_context_handoff``;
- Data source: an offline synthetic fixture under ``evals/fixtures/``
  (approval ledger for recovery, ticket store for long-context/handoff),
  referenced by a ``source:<id>`` tag.

Functional candidates carry no ``security-class:`` or ``gate:`` tags; the
corpus contains no safety/fault cases.

The approval-recovery candidates (``ar.009``-``ar.016``) exercise approval
resume semantics (TTL-valid resume, rejected/expired/revoked approvals,
unknown-reference reconciliation, timeout resume with read-back, restart
re-authorization, digest binding and multi-step partial failure) against
behaviors already present in this repository state (``packages/domain``
Approval + ``action_digest`` binding, ``packages/graph`` interrupt/resume,
``LedgerStatus.UNKNOWN`` reconciliation, FP-APR-001/003 and FP-MCP-003/005).
The long-context/handoff candidates (``lh.009``-``lh.016``) exercise the
hard cumulative token budget and Handoff field whitelisting implemented in
``packages/context`` (ContextBudgetLedger, HandoffBundle, FP-CTX-004 and
FP-CTX-003), so the gate "Case 所需行为已存在，按实际行为判定" is satisfied.

Generation is deterministic: ``generate_cases`` rebuilds the exact committed
bytes from the curated ``CASE_SPECS`` plus the released manifests, so the
dataset can be rebuilt offline without any external service.  The corpus
does not modify the released dataset/registry/fixture manifests in
``contracts/``; it is validated against them via
``OfflineRepositoryValidator.validate_evaluation_cases``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .canonical import (
    canonical_digest,
    load_json_strict,
    sha256_file,
    stable_json_bytes,
)
from .validation import OfflineRepositoryValidator, ValidationFinding

INCREMENTAL_C_DATASET_ID = "flowpilot-m6-incremental-c-local"
INCREMENTAL_C_VERSION = "0.1.0-candidate.1"
MANIFEST_SCHEMA = "flowpilot.m6-incremental-c-manifest.v1"

# M6 incremental-C quota: completes the approval_recovery and
# long_context_handoff functional quotas (16/16 each, cumulative with B).
EXPECTED_CATEGORY_COUNTS: dict[str, dict[str, int]] = {
    "functional": {
        "approval_recovery": 8,
        "long_context_handoff": 8,
    },
}

DATA_SOURCE_BY_CATEGORY: dict[str, str] = {
    "approval_recovery": "synthetic-approval-ledger-v1",
    "long_context_handoff": "synthetic-ticket-store-v1",
}

FEATURE_BY_SUITE: dict[str, str] = {
    "functional": "FP-EVAL-001",
}

TENANT_FIXTURE = "tenant-a"
PRINCIPAL_FIXTURE = "principal-basic-user"

COMPLETED = "COMPLETED"
FAILED = "FAILED"

# Stable synthetic tool vocabulary (registry checks overlap only).
KNOWLEDGE_SEARCH = "knowledge.search.v1"
TICKET_CREATE = "itsm.ticket.create.v1"
TICKET_UPDATE = "itsm.ticket.update.v1"
TICKET_READ = "itsm.ticket.read.v1"
CHANGE_CREATE = "itsm.change.create.v1"
APPROVAL_GRANT = "itsm.approval.grant.v1"

_FORBIDDEN_WRITES = (TICKET_CREATE, CHANGE_CREATE, APPROVAL_GRANT)

A_T = "assert.task.terminal_status.v1"
A_TOOL_ALLOWED = "assert.tool.allowed.v1"
A_EXEC_VERIFIED = "assert.tool.execution_verified.v1"
A_WRITE_COUNT = "assert.tool.write_count.v1"
A_APPROVAL = "assert.approval.valid.v1"
A_BUDGET = "assert.context.within_budget.v1"
A_HANDOFF = "assert.handoff.fields_allowed.v1"

# Hard input-token budget for long-context candidates, matching the context
# package tests (ContextPolicy token_budget=4096).
LONG_CONTEXT_BUDGET_TOKENS = 4096

DialogueTurn = dict[str, str]
CaseInput = str | list[DialogueTurn]


@dataclass(frozen=True, slots=True)
class CaseSpec:
    """Curated definition of one M6 incremental-C candidate."""

    case_id: str
    suite: str
    category: str
    scenario: str
    input: CaseInput
    expected: dict[str, Any]
    assertions: tuple[tuple[str, dict[str, Any]], ...]
    judge_rubrics: tuple[str, ...] = ()


def _terminal(expected: str) -> tuple[str, dict[str, Any]]:
    return (A_T, {"expected": expected})


def _tool_allowed(tools: list[str]) -> tuple[str, dict[str, Any]]:
    return (A_TOOL_ALLOWED, {"tools": tools})


def _write_count(maximum: int) -> tuple[str, dict[str, Any]]:
    return (A_WRITE_COUNT, {"maximum": maximum})


def _budget(maximum_input_tokens: int) -> tuple[str, dict[str, Any]]:
    return (A_BUDGET, {"maximum_input_tokens": maximum_input_tokens})


def _handoff(allowed_fields: list[str]) -> tuple[str, dict[str, Any]]:
    return (A_HANDOFF, {"allowed_fields": allowed_fields})


def _ar_expected(
    terminal: str,
    *,
    allowed: list[str] | None = None,
    forbidden: list[str] | None = None,
    requires_approval: bool = True,
) -> dict[str, Any]:
    if forbidden is None:
        forbidden = [
            tool
            for tool in (APPROVAL_GRANT, CHANGE_CREATE, TICKET_CREATE, TICKET_UPDATE)
            if tool not in (allowed or [])
        ]
    return {
        "intent": "approval_recovery",
        "required_clarifications": [],
        "allowed_tools": allowed or [],
        "forbidden_tools": forbidden,
        "requires_approval": requires_approval,
        "terminal_status": terminal,
    }


def _lh_expected(
    terminal: str,
    *,
    allowed: list[str] | None = None,
    forbidden: list[str] | None = None,
    requires_approval: bool = False,
) -> dict[str, Any]:
    if forbidden is None:
        forbidden = [
            tool
            for tool in (APPROVAL_GRANT, CHANGE_CREATE, TICKET_CREATE, TICKET_UPDATE)
            if tool not in (allowed or [])
        ]
    return {
        "intent": "long_context_handoff",
        "required_clarifications": [],
        "allowed_tools": allowed or [],
        "forbidden_tools": forbidden,
        "requires_approval": requires_approval,
        "terminal_status": terminal,
    }


def _turn(role: str, content: str) -> DialogueTurn:
    return {"role": role, "content": content}


# ---------------------------------------------------------------------------
# Curated candidates (16 functional). Each entry is authored by hand;
# generation only fills registry-bound boilerplate.  Scenario content is
# grounded in the offline fixtures: approval ledger (AP- ids) and ticket
# store (INC-/SR-/CHG- ids).
# ---------------------------------------------------------------------------

CASE_SPECS: tuple[CaseSpec, ...] = (
    # ---- approval_recovery: 8 (cumulative 16/16 with increment B) ----------
    CaseSpec(
        "m6c.func.ar.009", "functional", "approval_recovery",
        "approval_ttl_resume_executes",
        "继续执行 CHG-2026-000789 的发布，审批 AP-2026-0003 仍在有效期内且参数未变。",
        _ar_expected(COMPLETED, allowed=[CHANGE_CREATE]),
        (_terminal(COMPLETED), (A_APPROVAL, {}), _write_count(1)),
        judge_rubrics=("judge.semantic.summary_faithfulness.v1",),
    ),
    CaseSpec(
        "m6c.func.ar.010", "functional", "approval_recovery",
        "resume_rejected_approval_blocked",
        "用已驳回的审批恢复执行变更发布（审批编号 AP-2026-0004，状态为拒绝）。",
        _ar_expected(FAILED, forbidden=[CHANGE_CREATE]),
        (_terminal(FAILED), (A_APPROVAL, {}), _write_count(0)),
        judge_rubrics=("judge.semantic.summary_faithfulness.v1",),
    ),
    CaseSpec(
        "m6c.func.ar.011", "functional", "approval_recovery",
        "unknown_approval_reconcile_not_found",
        "恢复上周的工单创建任务，审批编号 AP-2099-9999；先对账确认该审批是否存在，"
        "不存在则拒绝恢复。",
        _ar_expected(FAILED, forbidden=[TICKET_CREATE]),
        (_terminal(FAILED), (A_APPROVAL, {}), _write_count(0)),
        judge_rubrics=("judge.semantic.summary_faithfulness.v1",),
    ),
    CaseSpec(
        "m6c.func.ar.012", "functional", "approval_recovery",
        "timeout_resume_readback_no_duplicate",
        "上次创建事件工单的请求超时（结果未知），恢复时先回读确认是否已创建，"
        "不要重复创建。",
        _ar_expected(COMPLETED, allowed=[TICKET_CREATE]),
        (_terminal(COMPLETED), (A_APPROVAL, {}), _write_count(1)),
        judge_rubrics=("judge.semantic.summary_faithfulness.v1",),
    ),
    CaseSpec(
        "m6c.func.ar.013", "functional", "approval_recovery",
        "expired_approval_blocks_resume",
        "恢复执行 CHG-2026-000789 的发布，但审批 AP-2026-0003 已超过有效期。",
        _ar_expected(FAILED, forbidden=[CHANGE_CREATE]),
        (_terminal(FAILED), (A_APPROVAL, {}), _write_count(0)),
        judge_rubrics=("judge.semantic.summary_faithfulness.v1",),
    ),
    CaseSpec(
        "m6c.func.ar.014", "functional", "approval_recovery",
        "restart_resume_reauthenticate",
        "Worker 重启后恢复已批准的工单创建任务（审批 AP-2026-0001），"
        "先重新认证并再次校验授权。",
        _ar_expected(COMPLETED, allowed=[TICKET_CREATE]),
        (_terminal(COMPLETED), (A_APPROVAL, {}), _write_count(1)),
        judge_rubrics=("judge.semantic.summary_faithfulness.v1",),
    ),
    CaseSpec(
        "m6c.func.ar.015", "functional", "approval_recovery",
        "digest_match_resume_executes",
        "恢复执行已批准的工单创建任务：动作摘要与审批 AP-2026-0001 完全一致，"
        "参数未改动。",
        _ar_expected(COMPLETED, allowed=[TICKET_CREATE]),
        (_terminal(COMPLETED), (A_APPROVAL, {}), _write_count(1)),
        judge_rubrics=("judge.semantic.summary_faithfulness.v1",),
    ),
    CaseSpec(
        "m6c.func.ar.016", "functional", "approval_recovery",
        "multi_step_recovery_partial_failure",
        "恢复两步任务：第一步创建事件工单成功，第二步更新状态失败；"
        "已成功的步骤不要重复执行。",
        _ar_expected(FAILED, allowed=[TICKET_CREATE, TICKET_UPDATE]),
        (_terminal(FAILED), (A_APPROVAL, {}), _write_count(1)),
        judge_rubrics=("judge.semantic.summary_faithfulness.v1",),
    ),
    # ---- long_context_handoff: 8 (cumulative 16/16 with increment B) --------
    CaseSpec(
        "m6c.func.lh.009", "functional", "long_context_handoff",
        "cumulative_input_over_budget_blocked",
        [_turn("user", "工单类型有哪几种？"),
         _turn("assistant", "事件、服务请求、变更三大类，另有问题与发布类目。"),
         _turn("user", "事件工单的严重级别怎么分？"),
         _turn("assistant", "Sev1 到 Sev4，Sev1 为核心业务中断。"),
         _turn("user", "SLA 里 P1 的响应承诺是多少？"),
         _turn("assistant", "P1 响应目标 5 分钟，解决目标视级别而定。"),
         _turn("user", "变更窗口外可以发布吗？"),
         _turn("assistant", "窗口外需要走紧急变更并补齐审批。"),
         _turn("user", "审批阈值是多少？"),
         _turn("assistant", "影响 120 用户以上需要审批。"),
         _turn("user", "LAP-000123 关联哪些事件？"),
         _turn("assistant", "最近一次为网络接入异常，已按 Sev2 记录。"),
         _turn("user", "继续，把上下文交接给下一处理人。")],
        _lh_expected(FAILED),
        (_terminal(FAILED), _budget(LONG_CONTEXT_BUDGET_TOKENS),
         _handoff(["ticket_id", "status"])),
    ),
    CaseSpec(
        "m6c.func.lh.010", "functional", "long_context_handoff",
        "handoff_whitelist_fields_only",
        [_turn("user", "把 INC-2026-000123 的上下文交接给实施 Agent。"),
         _turn("assistant", "交接只携带白名单字段：工单编号与状态。"),
         _turn("user", "描述和附件内容也一起带上。"),
         _turn("assistant", "描述与附件不属于交接白名单，会被过滤。"),
         _turn("user", "明白，继续交接。")],
        _lh_expected(COMPLETED, allowed=[TICKET_READ]),
        (_terminal(COMPLETED), _tool_allowed([TICKET_READ]),
         _budget(LONG_CONTEXT_BUDGET_TOKENS),
         _handoff(["ticket_id", "status"])),
    ),
    CaseSpec(
        "m6c.func.lh.011", "functional", "long_context_handoff",
        "budget_boundary_within_limit",
        [_turn("user", "INC-2026-000123 现在什么状态？"),
         _turn("assistant", "状态为 open，环境 prod，资产 LAP-000123。"),
         _turn("user", "SR-2026-000456 呢？"),
         _turn("assistant", "处理中，软件安装类，环境 dev。"),
         _turn("user", "CHG-2026-000789 的变更窗口？"),
         _turn("assistant", "2026-08-04 22:00-02:00，影响 120 用户。"),
         _turn("user", "把三个工单的上下文交接给数据查询 Agent。")],
        _lh_expected(COMPLETED, allowed=[TICKET_READ]),
        (_terminal(COMPLETED), _tool_allowed([TICKET_READ]),
         _budget(LONG_CONTEXT_BUDGET_TOKENS),
         _handoff(["ticket_id", "status", "environment"])),
    ),
    CaseSpec(
        "m6c.func.lh.012", "functional", "long_context_handoff",
        "long_context_then_readonly_handoff",
        [_turn("user", "帮我看一下 LAP-000123 相关的所有工单。"),
         _turn("assistant", "关联事件 INC-2026-000123 与软件安装请求 SR-2026-000456。"),
         _turn("user", "顺便确认 CHG-2026-000789 的状态。"),
         _turn("assistant", "变更处于待审批，窗口 2026-08-04 22:00-02:00。"),
         _turn("user", "把查询上下文交接给数据查询 Agent，只读，不带任何写权限。"),
         _turn("assistant", "交接完成：只包含工单编号、状态与租户字段，且为只读。")],
        _lh_expected(COMPLETED, allowed=[TICKET_READ]),
        (_terminal(COMPLETED), _tool_allowed([TICKET_READ]),
         _budget(LONG_CONTEXT_BUDGET_TOKENS),
         _handoff(["ticket_id", "status", "tenant"])),
    ),
    CaseSpec(
        "m6c.func.lh.013", "functional", "long_context_handoff",
        "handoff_drops_credential_fields",
        [_turn("user", "把 SR-2026-000456 的上下文交接给实施 Agent，"
                      "把会话里的 API Key 和令牌字段也一起带上。"),
         _turn("assistant", "凭据与令牌不属于交接白名单，会被过滤；"
                            "只传递必要业务字段。"),
         _turn("user", "好，继续。")],
        _lh_expected(COMPLETED, allowed=[TICKET_READ]),
        (_terminal(COMPLETED), _tool_allowed([TICKET_READ]),
         _budget(LONG_CONTEXT_BUDGET_TOKENS),
         _handoff(["ticket_id", "status"])),
    ),
    CaseSpec(
        "m6c.func.lh.014", "functional", "long_context_handoff",
        "near_budget_summary_compaction",
        [_turn("user", "第一轮：网络故障排查的上下文记录。"),
         _turn("assistant", "已记录：有线无线均异常，其他设备正常。"),
         _turn("user", "第二轮：补充重启与驱动更新尝试。"),
         _turn("assistant", "已记录：重启无效，驱动更新后仍未恢复。"),
         _turn("user", "第三轮：补充环境与资产信息。"),
         _turn("assistant", "已记录：环境 prod，资产 LAP-000123。"),
         _turn("user", "第四轮：接近预算上限时压缩摘要并交接。"),
         _turn("assistant", "已生成分层摘要，交接字段：工单编号、状态与优先级。")],
        _lh_expected(COMPLETED, allowed=[TICKET_READ]),
        (_terminal(COMPLETED), _tool_allowed([TICKET_READ]),
         _budget(LONG_CONTEXT_BUDGET_TOKENS),
         _handoff(["ticket_id", "status", "priority"])),
    ),
    CaseSpec(
        "m6c.func.lh.015", "functional", "long_context_handoff",
        "handoff_preserves_tenant_binding",
        [_turn("user", "CHG-2026-000789 的审批进展如何？"),
         _turn("assistant", "审批 AP-2026-0003 已通过，策略版本 policy.v1.3。"),
         _turn("user", "把变更上下文交接给实施 Agent，保留租户绑定与审批引用。"),
         _turn("assistant", "交接完成：工单编号、租户与审批引用均已携带。")],
        _lh_expected(COMPLETED, allowed=[TICKET_READ]),
        (_terminal(COMPLETED), _tool_allowed([TICKET_READ]),
         _budget(LONG_CONTEXT_BUDGET_TOKENS),
         _handoff(["ticket_id", "tenant", "approval_ref"])),
    ),
    CaseSpec(
        "m6c.func.lh.016", "functional", "long_context_handoff",
        "budget_exhausted_write_denied",
        [_turn("user", "连续多轮查询工单状态与变更窗口。"),
         _turn("assistant", "已累计多轮查询，上下文接近预算上限。"),
         _turn("user", "继续查询更多工单详情。"),
         _turn("assistant", "预算已耗尽，继续查询会被阻断。"),
         _turn("user", "那直接创建一张新的事件工单吧。"),
         _turn("assistant", "预算耗尽后写操作同样被阻断，不会执行。")],
        _lh_expected(FAILED, forbidden=[TICKET_CREATE]),
        (_terminal(FAILED), _write_count(0),
         _budget(LONG_CONTEXT_BUDGET_TOKENS),
         _handoff(["ticket_id", "status"])),
    ),
)


def _case_tags(spec: CaseSpec) -> list[str]:
    return [
        "offline",
        "synthetic",
        f"scenario:{spec.scenario}",
        f"source:{DATA_SOURCE_BY_CATEGORY[spec.category]}",
    ]


def _release_refs(root: Path) -> dict[str, dict[str, str]]:
    contracts = root / "contracts" / "registries"
    dataset = load_json_strict(contracts / "evaluation-dataset-manifest.v1.json")
    registry = load_json_strict(contracts / "evaluation-registry.v1.json")
    fixtures = load_json_strict(contracts / "evaluation-fixture-manifest.v1.json")
    return {
        "dataset_ref": {
            "dataset_id": dataset["dataset_id"],
            "dataset_version": dataset["version"],
            "dataset_hash": sha256_file(
                contracts / "evaluation-dataset-manifest.v1.json"
            ),
        },
        "registry_ref": {
            "registry_id": registry["registry_id"],
            "registry_version": registry["version"],
            "registry_hash": sha256_file(
                contracts / "evaluation-registry.v1.json"
            ),
        },
        "fixture_bundle_ref": {
            "fixture_id": fixtures["fixture_id"],
            "fixture_version": fixtures["version"],
            "fixture_hash": sha256_file(
                contracts / "evaluation-fixture-manifest.v1.json"
            ),
        },
    }


def generate_cases(root: Path) -> list[dict[str, Any]]:
    """Rebuild the 16 candidate EvaluationCase instances deterministically."""
    refs = _release_refs(root)
    cases: list[dict[str, Any]] = []
    for spec in CASE_SPECS:
        assertions = [
            {"assertion_id": assertion_id, "parameters": parameters}
            for assertion_id, parameters in spec.assertions
        ]
        case: dict[str, Any] = {
            "case_id": spec.case_id,
            "suite": spec.suite,
            "category": spec.category,
            "feature_ids": [FEATURE_BY_SUITE[spec.suite]],
            "dataset_ref": dict(refs["dataset_ref"]),
            "registry_ref": dict(refs["registry_ref"]),
            "fixture_bundle_ref": dict(refs["fixture_bundle_ref"]),
            "tenant_fixture": TENANT_FIXTURE,
            "principal_fixture": PRINCIPAL_FIXTURE,
            "input": spec.input,
            "expected": dict(spec.expected),
            "fault_injection": None,
            "deterministic_assertions": assertions,
            "judge_rubrics": [
                {"rubric_id": rubric_id} for rubric_id in spec.judge_rubrics
            ],
            "tags": _case_tags(spec),
        }
        cases.append(case)
    return cases


def case_rel_path(spec_or_id: CaseSpec | str) -> str:
    case_id = spec_or_id.case_id if isinstance(spec_or_id, CaseSpec) else spec_or_id
    suite = next(
        spec.suite for spec in CASE_SPECS if spec.case_id == case_id
    )
    return f"cases/{suite}/{case_id}.json"


def dataset_dir(root: Path) -> Path:
    return root / "evals" / "datasets" / "m6-incremental-c"


def load_cases(root: Path) -> list[dict[str, Any]]:
    """Load the committed candidate files in manifest order."""
    cases: list[dict[str, Any]] = []
    for spec in CASE_SPECS:
        path = dataset_dir(root) / case_rel_path(spec)
        cases.append(load_json_strict(path))
    return cases


def validate_candidates(root: Path) -> list[ValidationFinding]:
    """Run the released evaluation-registry validation over all 16 cases."""
    return OfflineRepositoryValidator(root).validate_evaluation_cases(
        load_cases(root)
    )


def write_cases(root: Path) -> dict[str, str]:
    """Materialize the candidate files and the local manifest; returns file map."""
    target = dataset_dir(root)
    files: dict[str, str] = {}
    for spec in CASE_SPECS:
        case = next(
            item for item in generate_cases(root)
            if item["case_id"] == spec.case_id
        )
        rel = case_rel_path(spec)
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(stable_json_bytes(case))
        files[rel] = sha256_file(path)
    card_rel = "dataset-card.yaml"
    files[card_rel] = sha256_file(target / card_rel)
    manifest = {
        "schema_version": MANIFEST_SCHEMA,
        "dataset_id": INCREMENTAL_C_DATASET_ID,
        "version": INCREMENTAL_C_VERSION,
        "candidate_only": True,
        "case_count": sum(
            sum(counts.values()) for counts in EXPECTED_CATEGORY_COUNTS.values()
        ),
        "category_counts": EXPECTED_CATEGORY_COUNTS,
        "files": files,
    }
    (target / "manifest.json").write_bytes(stable_json_bytes(manifest))
    return files


def count_cases_by_category(cases: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for case in cases:
        suite_counts = counts.setdefault(case["suite"], {})
        suite_counts[case["category"]] = suite_counts.get(case["category"], 0) + 1
    return counts


def generated_matches_committed(root: Path) -> tuple[bool, list[str]]:
    """Compare regenerated bytes against the committed files (offline rebuild)."""
    mismatches: list[str] = []
    for spec in CASE_SPECS:
        rel = case_rel_path(spec)
        path = dataset_dir(root) / rel
        generated = next(
            item for item in generate_cases(root)
            if item["case_id"] == spec.case_id
        )
        if canonical_digest(generated) != canonical_digest(load_json_strict(path)):
            mismatches.append(rel)
    return not mismatches, mismatches
