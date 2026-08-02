"""FP-CTX-005: Baseline/Optimized context ablation runner.

Compares two deterministic context pipelines over the same synthetic
conversation and reports the *real* measured token distribution:

- ``baseline``: every call carries the full accumulated transcript in
  ``L4_RECENT_MESSAGES``; handoff forwards a broad field set unchanged.
- ``optimized``: the transcript is compressed into a layered summary
  (``L3_CONVERSATION_SUMMARY``, FP-CTX-002) plus a sliding recent-message
  window; handoff rebuilds a minimal context with allowlist-filtered
  tools (FP-CTX-003 / FP-AGT-001).

No conclusion number is hard-coded: every figure in the report is computed
from the actual envelopes built on the fly.  Run directly:

    python packages/evaluation/context_ablation.py

and read ``artifacts/context-ablation.json``.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from collections.abc import Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

if __package__ in (None, ""):
    # Direct execution: make the workspace packages importable.
    for package in ("domain", "context", "agent-runtime"):
        source = REPOSITORY_ROOT / "packages" / package / "src"
        if str(source) not in sys.path:
            sys.path.insert(0, str(source))

from flowpilot_context import (  # noqa: E402
    ContextBudgetLedger,
    ContextBuilder,
    ContextBuildRequest,
    ContextLayer,
    ContextPolicy,
    LayeredSummary,
    LayerName,
    SummaryItem,
    SummaryKind,
    TrustLevel,
    build_summary_layer,
    estimate_tokens,
    forbidden_field_scan,
)
from flowpilot_domain import (  # noqa: E402
    DataClassification,
    TaskCommand,
)

SCHEMA = "flowpilot.context-ablation.v1"

# Synthetic conversation: 20 rounds, 3 messages each, growing transcript.
ROUNDS = 20
MESSAGES_PER_ROUND = 3
MESSAGE_TEXT = "user reported a VPN outage; environment is production; " * 4
RECENT_WINDOW = 3


def _load_command() -> TaskCommand:
    case_file = REPOSITORY_ROOT / "contracts" / "conformance" / "rc2-cases.json"
    cases = json.loads(case_file.read_text(encoding="utf-8"))
    for case in cases["cases"]:
        if case["case_id"] == "task_command.create.valid":
            command = TaskCommand.from_mapping(
                copy.deepcopy(case["instance"])
            )
            # The conformance case carries a fixed-epoch security context;
            # re-issue it relative to now so the envelope binding holds.
            now = datetime.now(UTC)
            refreshed = replace(
                command.security_context,
                issued_at=now - timedelta(minutes=5),
                expires_at=now + timedelta(hours=1),
            )
            return replace(command, security_context=refreshed)
    raise LookupError("task_command.create.valid")


def _context_policy(token_budget: int) -> ContextPolicy:
    return ContextPolicy(
        context_policy_version="ctx-policy-v1",
        data_classification_ceiling=DataClassification.CONFIDENTIAL,
        provider_allowlist=("ablation-provider",),
        token_budget=token_budget,
    )


def _recent_messages_layer(messages: list[str]) -> ContextLayer:
    return ContextLayer(
        name=LayerName.RECENT_MESSAGES,
        trust=TrustLevel.UNTRUSTED_DATA,
        classification=DataClassification.INTERNAL,
        content={"messages": list(messages)},
        source_refs=(f"message://ablation/round-{len(messages)}",),
    )


def _summary_for(messages: list[str]) -> LayeredSummary:
    """Compress the transcript into strictly partitioned buckets."""
    claimed = SummaryItem(
        kind=SummaryKind.CLAIMED,
        text="user claims VPN access is flaky since the last maintenance",
        source_refs=("message://ablation/round-1",),
    )
    verified = SummaryItem(
        kind=SummaryKind.VERIFIED,
        text="tenant policy allows VPN for the production environment",
        source_refs=("message://ablation/round-2",),
    )
    inferred = SummaryItem(
        kind=SummaryKind.INFERRED,
        text=(
            "ticket is likely network-zone related; "
            f"based on {len(messages)} messages"
        ),
        source_refs=(f"message://ablation/round-{len(messages)}",),
    )
    return LayeredSummary(items=(claimed, verified, inferred))


def _run_baseline(
    builder: ContextBuilder,
    command: TaskCommand,
    policy: ContextPolicy,
    messages: list[str],
) -> dict[str, Any]:
    """Full-transcript context: the pre-optimization pipeline."""
    layer = _recent_messages_layer(messages)
    envelope = builder.build(
        ContextBuildRequest(
            context_id="ctx_baseline",
            task_id=command.task_id,
            agent_id="baseline-agent",
            purpose=command.security_context.purpose,
            security_context=command.security_context,
            task_state={"status": "RUNNING", "intent": "vpn_escalation"},
            task_state_ref=f"task://{command.task_id}/baseline",
            system_policy_ref="policy://runtime/v1",
            policy=policy,
            optional_layers=(layer,),
        )
    )
    output_tokens = estimate_tokens(
        {"reply": "handled round " + str(len(messages))}
    )
    return {
        "input_tokens": envelope.manifest.input_tokens_estimated,
        "output_tokens": output_tokens,
        "total_tokens": envelope.manifest.input_tokens_estimated + output_tokens,
        "layers": {
            layer.name.value: estimate_tokens(layer.to_mapping())
            for layer in envelope.layers
        },
    }


def _run_optimized(
    builder: ContextBuilder,
    command: TaskCommand,
    policy: ContextPolicy,
    messages: list[str],
    summary: LayeredSummary,
) -> dict[str, Any]:
    """Summary + sliding-window context: the FP-CTX-002/004 pipeline."""
    envelope = builder.build(
        ContextBuildRequest(
            context_id="ctx_optimized",
            task_id=command.task_id,
            agent_id="optimized-agent",
            purpose=command.security_context.purpose,
            security_context=command.security_context,
            task_state={"status": "RUNNING", "intent": "vpn_escalation"},
            task_state_ref=f"task://{command.task_id}/optimized",
            system_policy_ref="policy://runtime/v1",
            policy=policy,
            optional_layers=(
                build_summary_layer(
                    summary=summary,
                    ref=f"summary://ablation/round-{len(messages)}",
                ),
                _recent_messages_layer(messages[-RECENT_WINDOW:]),
            ),
        )
    )
    output_tokens = estimate_tokens(
        {"reply": "handled round " + str(len(messages))}
    )
    return {
        "input_tokens": envelope.manifest.input_tokens_estimated,
        "output_tokens": output_tokens,
        "total_tokens": envelope.manifest.input_tokens_estimated + output_tokens,
        "layers": {
            layer.name.value: estimate_tokens(layer.to_mapping())
            for layer in envelope.layers
        },
    }


def _run_handoff_baseline(
    builder: ContextBuilder,
    command: TaskCommand,
    policy: ContextPolicy,
    messages: list[str],
) -> dict[str, Any]:
    """Pre-optimization handoff: broad field forwarding, no tool filtering."""
    source = builder.build(
        ContextBuildRequest(
            context_id="ctx_handoff_source",
            task_id=command.task_id,
            agent_id="baseline-agent",
            purpose=command.security_context.purpose,
            security_context=command.security_context,
            task_state={
                "status": "RUNNING",
                "intent": "vpn_escalation",
                "approval": {"card_id": "apr_1"},
                "session_ref": "session://provider/1",
                "tool_credentials": {"vpn_admin": "unused"},
            },
            task_state_ref=f"task://{command.task_id}/handoff-source",
            system_policy_ref="policy://runtime/v1",
            policy=policy,
            optional_layers=(_recent_messages_layer(messages),),
        )
    )
    # The naive path forwards the full field set verbatim.
    forwarded = dict(
        cast(Mapping[str, Any], source.layer(LayerName.TASK_STATE).content)
    )
    leaks = forbidden_field_scan(forwarded)
    return {
        "input_tokens": source.manifest.input_tokens_estimated,
        "forwarded_fields": len(forwarded),
        "leak_count": len(leaks),
        "leaked_fields": list(leaks),
    }


def _run_handoff_optimized(
    builder: ContextBuilder,
    command: TaskCommand,
    policy: ContextPolicy,
) -> dict[str, Any]:
    """FP-CTX-003 pipeline: rebuild minimal context, filter tools."""
    source = builder.build(
        ContextBuildRequest(
            context_id="ctx_handoff_source",
            task_id=command.task_id,
            agent_id="baseline-agent",
            purpose=command.security_context.purpose,
            security_context=command.security_context,
            task_state={
                "status": "RUNNING",
                "intent": "vpn_escalation",
                "approval": {"card_id": "apr_1"},
                "session_ref": "session://provider/1",
                "tool_credentials": {"vpn_admin": "unused"},
            },
            task_state_ref=f"task://{command.task_id}/handoff-source",
            system_policy_ref="policy://runtime/v1",
            policy=policy,
        )
    )
    bundle = builder.rebuild_for_handoff(
        source=source,
        security_context=command.security_context,
        target_agent_id="ablation-target",
        new_context_id="ctx_handoff_target",
        required_task_fields=("status", "intent"),
        allowed_tools=("knowledge.search.v1", "vpn.admin.write.v1"),
        target_tool_allowlist=("knowledge.search.v1",),
    )
    leaks = forbidden_field_scan(bundle.to_mapping())
    return {
        "input_tokens": bundle.manifest.input_tokens,
        "included_fields": len(bundle.manifest.included_fields),
        "excluded_categories": len(bundle.manifest.excluded_categories),
        "tools_before_filter": 2,
        "tools_after_filter": len(bundle.manifest.allowed_tools),
        "leak_count": len(leaks),
        "leaked_fields": list(leaks),
    }


def run_ablation(*, rounds: int = ROUNDS) -> dict[str, Any]:
    """Execute both pipelines and return the real measured distribution."""
    command = _load_command()
    builder = ContextBuilder()
    policy = _context_policy(token_budget=1_000_000)
    ledger = ContextBudgetLedger(
        cumulative_token_budget=10_000_000,
        maximum_rounds=rounds,
    )

    messages: list[str] = []
    summary = LayeredSummary(
        items=(
            SummaryItem(
                kind=SummaryKind.CLAIMED,
                text="user claims VPN access is flaky",
                source_refs=("message://ablation/round-1",),
            ),
        )
    )
    baseline_turns: list[dict[str, Any]] = []
    optimized_turns: list[dict[str, Any]] = []
    for round_index in range(1, rounds + 1):
        messages.extend(
            [MESSAGE_TEXT] * MESSAGES_PER_ROUND
        )
        baseline = _run_baseline(builder, command, policy, messages)
        optimized = _run_optimized(
            builder, command, policy, messages, summary
        )
        baseline_turns.append(
            {"round": round_index, **baseline}
        )
        optimized_turns.append(
            {"round": round_index, **optimized}
        )
        ledger.charge(
            turn_index=round_index - 1,
            request_id=f"arq_{round_index}",
            context_id="ctx_optimized",
            agent_id="optimized-agent",
            input_tokens=optimized["input_tokens"],
            output_tokens=optimized["output_tokens"],
            layer_tokens=tuple(
                (name, tokens)
                for name, tokens in optimized["layers"].items()
            ),
        )
        if round_index % 5 == 0:
            summary = summary.merge(_summary_for(messages))

    handoff_baseline = _run_handoff_baseline(
        builder, command, policy, messages
    )
    handoff_optimized = _run_handoff_optimized(builder, command, policy)

    baseline_input = sum(turn["input_tokens"] for turn in baseline_turns)
    optimized_input = sum(turn["input_tokens"] for turn in optimized_turns)
    baseline_total = sum(turn["total_tokens"] for turn in baseline_turns)
    optimized_total = sum(turn["total_tokens"] for turn in optimized_turns)
    ledger_report = ledger.report()

    report: dict[str, Any] = {
        "schema": SCHEMA,
        "run_id": "ablation_" + hashlib.sha256(
            f"{rounds}:{baseline_total}:{optimized_total}".encode()
        ).hexdigest()[:12],
        "generated_at": datetime.now(UTC).isoformat(),
        "rounds": rounds,
        "messages_per_round": MESSAGES_PER_ROUND,
        "recent_window": RECENT_WINDOW,
        "baseline": {
            "total_input_tokens": baseline_input,
            "total_output_tokens": sum(
                turn["output_tokens"] for turn in baseline_turns
            ),
            "total_tokens": baseline_total,
            "final_round_input_tokens": baseline_turns[-1]["input_tokens"],
            "turns": baseline_turns,
        },
        "optimized": {
            "total_input_tokens": optimized_input,
            "total_output_tokens": sum(
                turn["output_tokens"] for turn in optimized_turns
            ),
            "total_tokens": optimized_total,
            "final_round_input_tokens": optimized_turns[-1]["input_tokens"],
            "turns": optimized_turns,
            "ledger": ledger_report,
        },
        "handoff": {
            "baseline": handoff_baseline,
            "optimized": handoff_optimized,
        },
        "measured_reduction_input_pct": round(
            (1 - optimized_input / baseline_input) * 100, 2
        )
        if baseline_input
        else 0,
    }
    return report


def main() -> None:
    report = run_ablation()
    output = REPOSITORY_ROOT / "artifacts" / "context-ablation.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"wrote {output}")
    print(
        "baseline total tokens: "
        f"{report['baseline']['total_tokens']} / "
        f"optimized: {report['optimized']['total_tokens']}"
    )
    print(
        "handoff leak count: "
        f"baseline={report['handoff']['baseline']['leak_count']} "
        f"optimized={report['handoff']['optimized']['leak_count']}"
    )


if __name__ == "__main__":
    main()
