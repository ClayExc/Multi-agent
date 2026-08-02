"""Shared M5-2 recovery harness for the onboarding composite graph.

Sibling of ``tests/acceptance/onboarding/conftest.py`` kept in the runtime
layer so recovery tests never depend on acceptance fixtures (layering).
Deterministic fakes for every OnboardingCompositeGraph port plus:

- ``OnboardingProbeOptions.crash_after_tool``: simulates a Worker process
  death right after the upstream write committed (the resource is created,
  the verified outcome is cached, the graph never sees the outcome).  A
  ``KeyboardInterrupt`` (a BaseException) escapes every ``except Exception``
  in the graph, exactly like a killed process.
- helpers to revoke / expire an approval and to build a graph with a
  different ``graph_version`` for the migration-rejection test.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from flowpilot_context import ContextBuilder
from flowpilot_domain import (
    Approval,
    ApprovalStatus,
    CommandType,
    TaskCommand,
    ToolOperation,
    canonical_sha256,
)
from flowpilot_graph import (
    PERMISSION_GRANT_SCHEMA_PIN,
    InMemoryCheckpointStore,
    InMemoryLeaseStore,
    OnboardingArtifactDraft,
    OnboardingArtifactReceipt,
    OnboardingCompositeGraph,
    OnboardingGatewayCall,
    OnboardingGraphConfig,
    OnboardingLedgerEntry,
    OnboardingObservation,
    OnboardingResultStatus,
    OnboardingToolResult,
)
from langgraph.checkpoint.memory import InMemorySaver

ROOT = Path(__file__).resolve().parents[3]
TENANT_A = "tenant-a"
REQUESTER = "hr-operator-01"
MANAGER = "manager-alice"
PURPOSE = "onboarding"

CATALOG = json.loads(
    (ROOT / "evals" / "fixtures" / "onboarding-catalog-v1.json").read_text(
        encoding="utf-8"
    )
)

READ_TOOL_BY_BRANCH = {
    "device_standard": "catalog.device-standard.read.v1",
    "inventory": "inventory.query.read.v1",
    "permission_template": "permission.template.read.v1",
}


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def stable_id(prefix: str, value: str) -> str:
    return f"{prefix}_{hashlib.sha256(value.encode()).hexdigest()[:20]}"


# --------------------------------------------------------------------------
# Request resolver: accumulates fields across submitted message references.
# --------------------------------------------------------------------------


class FakeOnboardingResolver:
    def __init__(self) -> None:
        self.fields_by_ref: dict[str, dict[str, str]] = {}
        self.resolved: list[OnboardingObservation] = []

    def set_fields(self, message_ref: str, fields: Mapping[str, str]) -> None:
        self.fields_by_ref[message_ref] = dict(fields)

    def merged_fields(self, task_id: str) -> dict[str, str]:
        merged: dict[str, str] = {}
        for _ref, fields in self.fields_by_ref.items():
            merged.update(fields)
        return merged

    async def resolve(self, command: TaskCommand) -> OnboardingObservation:
        if command.command_type is CommandType.CREATE:
            message_id = str(command.payload["initial_message_id"])
            message_ref = str(command.payload["initial_message_ref"])
        elif command.command_type is CommandType.SUBMIT_MESSAGE:
            message_id = str(command.payload["message_id"])
            message_ref = str(command.payload["message_ref"])
        else:
            raise RuntimeError("resolver does not serve approval commands")
        merged = self.merged_fields(command.task_id)
        observation = OnboardingObservation(
            tenant_id=command.tenant_id,
            task_id=command.task_id,
            message_id=message_id,
            message_ref=message_ref,
            intent="onboarding_request",
            fields=merged,
            observation_ref=f"observation://{command.tenant_id}/{command.task_id}",
            source_digest=canonical_sha256({"task": command.task_id}),
        )
        self.resolved.append(observation)
        return observation


# --------------------------------------------------------------------------
# Gateway probe: simulated MCP tools with idempotency + readback + faults.
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OnboardingProbeOptions:
    branch_failures: Mapping[str, str] | None = None
    permission_failure: str | None = None
    device_unknown_once: bool = False
    read_latency: float = 0.05
    # M5-2: simulate a Worker crash immediately after the upstream write
    # for this tool committed (resource created + verified outcome cached).
    crash_after_tool: str | None = None


class OnboardingCrash(BaseException):
    """Simulated Worker process death (M5-2 recovery fault injection).

    A BaseException so it escapes every ``except Exception`` in the graph
    (exactly like a killed process) while staying pytest-friendly (pytest
    treats KeyboardInterrupt as a user interrupt, not an assertion target).
    """


class OnboardingGatewayProbe:
    """Transport-shaped Gateway client preserving logical execution counts."""

    def __init__(self, options: OnboardingProbeOptions | None = None) -> None:
        self.options = options or OnboardingProbeOptions()
        self.read_branches: list[str] = []
        self.write_calls: list[OnboardingGatewayCall] = []
        self.logical_counts: dict[str, int] = {}
        # M5-2: every execute() attempt per tool (cache hits included) so
        # tests can distinguish "replayed under an idempotency key" from
        # "actually executed a write".
        self.execute_counts: dict[str, int] = {}
        self._cache: dict[tuple[str, str, str], OnboardingToolResult] = {}
        self._assignments: dict[str, dict[str, Any]] = {}
        self._grants: dict[str, dict[str, Any]] = {}
        self._tickets: dict[str, dict[str, Any]] = {}
        self._device_unknown_fired = False
        self._crash_fired = False

    def role_for(self, department: str) -> str:
        return str(CATALOG["role_by_department"].get(department, "backend_engineer"))

    def _verified(
        self,
        call: OnboardingGatewayCall,
        data: Mapping[str, Any] | None,
        *,
        evidence: str,
    ) -> OnboardingToolResult:
        return OnboardingToolResult(
            request_id=call.request_id,
            operation=call.operation,
            status=OnboardingResultStatus.VERIFIED,
            data=dict(data) if data else None,
            display_summary="verified",
            output_classification="internal",
            policy_decision_id=call.policy_decision_id,
            started_at=_now(),
            finished_at=_now(),
            verification_matched=True,
            evidence_ref=evidence,
        )

    def _failed(
        self,
        call: OnboardingGatewayCall,
        error_code: str,
        *,
        retryable: bool = False,
    ) -> OnboardingToolResult:
        return OnboardingToolResult(
            request_id=call.request_id,
            operation=call.operation,
            status=(
                OnboardingResultStatus.FAILED_RETRYABLE
                if retryable
                else OnboardingResultStatus.FAILED_FINAL
            ),
            data=None,
            display_summary="denied",
            output_classification="internal",
            policy_decision_id=call.policy_decision_id,
            error_code=error_code,
            started_at=_now(),
            finished_at=_now(),
            verification_matched=None,
        )

    async def execute(self, call: OnboardingGatewayCall) -> OnboardingToolResult:
        tool = call.action.tool.name
        self.execute_counts[tool] = self.execute_counts.get(tool, 0) + 1
        key = (call.action.tenant_id, tool, call.idempotency_key)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        if call.operation is ToolOperation.READ:
            await asyncio.sleep(self.options.read_latency)
            result = await self._read(call)
        else:
            result = await self._write(call)
        if result.status is OnboardingResultStatus.VERIFIED:
            self._cache[key] = result
        return result

    async def _read(self, call: OnboardingGatewayCall) -> OnboardingToolResult:
        branch = str(call.action.arguments.get("branch") or "")
        self.read_branches.append(branch)
        failure = (self.options.branch_failures or {}).get(branch)
        if failure:
            return self._failed(call, failure)
        tool = call.action.tool.name
        if tool == "catalog.device-standard.read.v1":
            role = self.role_for(str(call.action.arguments["department"]))
            standard = next(
                item for item in CATALOG["device_standards"] if item["role"] == role
            )
            return self._verified(
                call,
                {
                    "standard_id": standard["standard_id"],
                    "role": standard["role"],
                    "model": standard["model"],
                    "spec": standard["spec"],
                    "assignable": standard["assignable"],
                },
                evidence=f"evidence://onboarding/read/{branch}",
            )
        if tool == "inventory.query.read.v1":
            location = str(call.action.arguments["location"])
            stock = next(
                item for item in CATALOG["inventory"] if item["location"] == location
            )
            return self._verified(
                call,
                {
                    "stock_id": stock["stock_id"],
                    "location": stock["location"],
                    "model": stock["model"],
                    "available": stock["available"],
                },
                evidence=f"evidence://onboarding/read/{branch}",
            )
        if tool == "permission.template.read.v1":
            role = self.role_for(str(call.action.arguments["department"]))
            template = next(
                item
                for item in CATALOG["permission_templates"]
                if item["role"] == role
            )
            return self._verified(
                call,
                {
                    "template_id": template["template_id"],
                    "role": template["role"],
                    "grants": list(template["grants"]),
                },
                evidence=f"evidence://onboarding/read/{branch}",
            )
        return self._failed(call, "RUNTIME_READ_TOOL_UNKNOWN")

    async def _write(self, call: OnboardingGatewayCall) -> OnboardingToolResult:
        self.write_calls.append(call)
        tool = call.action.tool.name
        if tool == "device.allocate.v1":
            result = await self._device_allocate(call, call.action.arguments, tool)
        elif tool == "permission.grant.v1":
            result = await self._permission_grant(call, call.action.arguments, tool)
        elif tool == "ticket.create.v1":
            result = await self._ticket_create(call, call.action.arguments, tool)
        else:
            result = self._failed(call, "RUNTIME_WRITE_TOOL_UNKNOWN")
        if (
            tool == self.options.crash_after_tool
            and result.status is OnboardingResultStatus.VERIFIED
            and not self._crash_fired
        ):
            # The write committed upstream (resource created).  Cache the
            # verified outcome BEFORE the simulated process death so the
            # crash-replay under the same idempotency key deduplicates —
            # exactly like an upstream store that already persisted it.
            self._crash_fired = True
            self._cache[(call.action.tenant_id, tool, call.idempotency_key)] = result
            raise OnboardingCrash("simulated worker process crash")
        return result

    async def _device_allocate(
        self,
        call: OnboardingGatewayCall,
        arguments: Mapping[str, Any],
        tool: str,
    ) -> OnboardingToolResult:
        if call.reconcile:
            record = self._assignments.get(call.idempotency_key)
            if record is None:
                return self._failed(call, "NOT_FOUND")
            return self._verified(
                call, record, evidence="evidence://onboarding/reconcile"
            )
        if self.options.device_unknown_once and not self._device_unknown_fired:
            self._device_unknown_fired = True
            record = {
                "assignment_id": stable_id("asg", call.idempotency_key),
                "employee": arguments["employee"],
                "model": arguments["model"],
                "location": arguments["location"],
                "status": "allocated",
            }
            self._assignments[call.idempotency_key] = record
            self.logical_counts[tool] = self.logical_counts.get(tool, 0) + 1
            return OnboardingToolResult(
                request_id=call.request_id,
                operation=call.operation,
                status=OnboardingResultStatus.UNKNOWN,
                data=None,
                display_summary="outcome unknown; reconciliation required",
                output_classification="internal",
                policy_decision_id=call.policy_decision_id,
                error_code="PLATFORM_UPSTREAM_OUTCOME_UNKNOWN",
                started_at=_now(),
                finished_at=_now(),
                verification_matched=None,
            )
        stock = next(
            (
                item
                for item in CATALOG["inventory"]
                if item["location"] == arguments["location"]
                and item["model"] == arguments["model"]
            ),
            None,
        )
        if stock is None or int(stock["available"]) < 1:
            return self._failed(call, "INVENTORY_INSUFFICIENT")
        record = {
            "assignment_id": stable_id("asg", call.idempotency_key),
            "employee": arguments["employee"],
            "model": arguments["model"],
            "location": arguments["location"],
            "status": "allocated",
        }
        self._assignments[call.idempotency_key] = record
        self.logical_counts[tool] = self.logical_counts.get(tool, 0) + 1
        return self._verified(
            call, record, evidence="evidence://onboarding/device/readback"
        )

    async def _permission_grant(
        self,
        call: OnboardingGatewayCall,
        arguments: Mapping[str, Any],
        tool: str,
    ) -> OnboardingToolResult:
        if call.reconcile:
            record = self._grants.get(call.idempotency_key)
            if record is None:
                return self._failed(call, "NOT_FOUND")
            return self._verified(
                call, record, evidence="evidence://onboarding/reconcile"
            )
        if self.options.permission_failure:
            return self._failed(call, self.options.permission_failure)
        record = {
            "grant_id": stable_id("grt", call.idempotency_key),
            "employee": arguments["employee"],
            "template_id": arguments["template_id"],
            "location": arguments["location"],
            "status": "granted",
        }
        self._grants[call.idempotency_key] = record
        self.logical_counts[tool] = self.logical_counts.get(tool, 0) + 1
        return self._verified(
            call, record, evidence="evidence://onboarding/permission/readback"
        )

    async def _ticket_create(
        self,
        call: OnboardingGatewayCall,
        arguments: Mapping[str, Any],
        tool: str,
    ) -> OnboardingToolResult:
        if call.reconcile:
            record = self._tickets.get(call.idempotency_key)
            if record is None:
                return self._failed(call, "NOT_FOUND")
            return self._verified(
                call, record, evidence="evidence://onboarding/reconcile"
            )
        record = {
            "ticket_id": arguments["ticket_id"],
            "title": arguments["title"],
            "requester": arguments["requester"],
            "location": arguments["location"],
            "start_date": arguments["start_date"],
            "status": "created",
        }
        self._tickets[call.idempotency_key] = record
        self.logical_counts[tool] = self.logical_counts.get(tool, 0) + 1
        return self._verified(
            call, record, evidence="evidence://onboarding/ticket/readback"
        )


# --------------------------------------------------------------------------
# Ledger / artifacts / approvals fakes.
# --------------------------------------------------------------------------


class FakeOnboardingLedger:
    def __init__(self) -> None:
        self.entries: list[OnboardingLedgerEntry] = []

    async def record(self, entry: OnboardingLedgerEntry) -> None:
        self.entries.append(entry)

    def by_tool(self, tool: str) -> list[OnboardingLedgerEntry]:
        return [entry for entry in self.entries if entry.tool == tool]


class FakeOnboardingArtifacts:
    def __init__(self) -> None:
        self.saved: list[OnboardingArtifactDraft] = []
        self.by_ref: dict[str, OnboardingArtifactDraft] = {}

    async def save(
        self, draft: OnboardingArtifactDraft
    ) -> OnboardingArtifactReceipt:
        ref = f"artifact://onboarding/{draft.task_id}/summary"
        self.saved.append(draft)
        self.by_ref[ref] = draft
        return OnboardingArtifactReceipt(result_ref=ref)


class FakeApprovalRepository:
    def __init__(self) -> None:
        self.approvals: dict[tuple[str, str], Approval] = {}
        # M5-2: re-authorization assertions count every resolve (each
        # approval-interrupt validation re-checks the record).
        self.resolve_count: dict[str, int] = {}

    async def approve(self, approval_id: str, approver_id: str) -> Approval:
        stored = self.approvals[(TENANT_A, approval_id)]
        decided = stored.to_mapping()
        decided["status"] = "approved"
        decided["approver_id"] = approver_id
        decided["decision_reason"] = "manager approval granted"
        decided["separation_of_duties_result"] = True
        decided["decided_at"] = _iso(_now())
        approval = Approval.from_mapping(decided)
        self.approvals[(TENANT_A, approval_id)] = approval
        return approval

    def revoke(self, approval_id: str) -> None:
        stored = self.approvals[(TENANT_A, approval_id)]
        revoked = stored.to_mapping()
        revoked["status"] = "revoked"
        revoked["decided_at"] = _iso(_now())
        self.approvals[(TENANT_A, approval_id)] = Approval.from_mapping(revoked)

    def expire(self, approval_id: str) -> None:
        stored = self.approvals[(TENANT_A, approval_id)]
        expired = stored.to_mapping()
        expired["expires_at"] = _iso(_now() - timedelta(minutes=1))
        self.approvals[(TENANT_A, approval_id)] = Approval.from_mapping(expired)

    async def resolve(self, approval_id: str) -> Approval:
        self.resolve_count[approval_id] = self.resolve_count.get(approval_id, 0) + 1
        stored = self.approvals.get((TENANT_A, approval_id))
        if stored is None:
            raise RuntimeError("approval not found")
        return stored


class RepoApprovalSource:
    def __init__(self, repository: FakeApprovalRepository) -> None:
        self._repository = repository

    async def resolve(self, approval_id: str) -> Approval:
        return await self._repository.resolve(approval_id)


def build_approval_from_card(
    card: Mapping[str, Any],
    *,
    create: TaskCommand,
    config: OnboardingGraphConfig,
) -> Approval:
    basis = card["basis"]
    return Approval(
        approval_id=str(card["approval_id"]),
        tenant_id=create.tenant_id,
        task_id=create.task_id,
        requester_id=create.actor.id,
        action_id=str(card["action_id"]),
        action_digest=str(card["action_digest"]),
        tool_schema_hash=PERMISSION_GRANT_SCHEMA_PIN,
        policy_decision_id=str(basis["policy_decision_id"]),
        policy_version=str(basis["policy_version"]),
        status=ApprovalStatus.PENDING,
        approver_id=None,
        decision_reason=None,
        separation_of_duties_result=None,
        requested_at=create.issued_at,
        decided_at=None,
        expires_at=datetime.fromisoformat(
            str(card["expires_at"]).replace("Z", "+00:00")
        ),
    )


# --------------------------------------------------------------------------
# Command builders (valid digests, real-clock timestamps).
# --------------------------------------------------------------------------


def _security_context(actor_id: str, *, issued_at: datetime) -> dict[str, Any]:
    context_id = stable_id("secctx", f"{TENANT_A}:{actor_id}:{PURPOSE}")
    return {
        "context_id": context_id,
        "context_ref": f"security-context://{TENANT_A}/{actor_id}",
        "context_hash": canonical_sha256(
            {"tenant_id": TENANT_A, "subject_id": actor_id, "purpose": PURPOSE}
        ),
        "tenant_id": TENANT_A,
        "subject_id": actor_id,
        "subject_type": "user",
        "purpose": PURPOSE,
        "authentication": {
            "method": "oidc",
            "assurance_level": "high",
            "session_id_hash": canonical_sha256({"session": context_id}),
        },
        "data_classification_ceiling": "confidential",
        "issued_at": _iso(issued_at),
        "expires_at": _iso(issued_at + timedelta(hours=1)),
    }


def _sign(value: dict[str, Any]) -> TaskCommand:
    unsigned = TaskCommand.from_mapping(value)
    value["command_digest"] = unsigned.recompute_digest()
    return TaskCommand.from_mapping(value)


def build_create_command(
    task_id: str,
    message_ref: str,
    *,
    actor_id: str = REQUESTER,
    issued_at: datetime | None = None,
) -> TaskCommand:
    issued_at = issued_at or (_now() - timedelta(minutes=10))
    message_id = f"msg_{task_id}_create"
    return _sign(
        {
            "command_id": stable_id("cmd", f"{task_id}:create"),
            "command_type": "task.create.v1",
            "tenant_id": TENANT_A,
            "task_id": task_id,
            "actor": {"type": "user", "id": actor_id},
            "security_context": _security_context(actor_id, issued_at=issued_at),
            "expected_task_version": None,
            "idempotency_key": canonical_sha256({"create": task_id}),
            "command_digest": "sha256:" + "0" * 64,
            "correlation_id": f"corr-{task_id}",
            "payload": {
                "initial_message_id": message_id,
                "initial_message_ref": message_ref,
                "channel": "web",
                "purpose": PURPOSE,
            },
            "issued_at": _iso(issued_at),
        }
    )


def build_submit_command(
    task_id: str,
    message_ref: str,
    *,
    actor_id: str = REQUESTER,
    issued_at: datetime | None = None,
) -> TaskCommand:
    issued_at = issued_at or (_now() - timedelta(minutes=5))
    message_id = f"msg_{task_id}_{hashlib.sha256(message_ref.encode()).hexdigest()[:8]}"
    return _sign(
        {
            "command_id": stable_id("cmd", f"{task_id}:submit:{message_ref}"),
            "command_type": "task.message.submit.v1",
            "tenant_id": TENANT_A,
            "task_id": task_id,
            "actor": {"type": "user", "id": actor_id},
            "security_context": _security_context(actor_id, issued_at=issued_at),
            "expected_task_version": 1,
            "idempotency_key": canonical_sha256({"submit": message_ref}),
            "command_digest": "sha256:" + "0" * 64,
            "correlation_id": f"corr-{task_id}",
            "payload": {"message_id": message_id, "message_ref": message_ref},
            "issued_at": _iso(issued_at),
        }
    )


def build_decide_command(
    task_id: str,
    *,
    approval_id: str,
    action_digest: str,
    decision: str,
    actor_id: str = MANAGER,
    issued_at: datetime | None = None,
) -> TaskCommand:
    issued_at = issued_at or _now()
    return _sign(
        {
            "command_id": stable_id("cmd", f"{task_id}:decide:{approval_id}"),
            "command_type": "task.approval.decide.v1",
            "tenant_id": TENANT_A,
            "task_id": task_id,
            "actor": {"type": "user", "id": actor_id},
            "security_context": _security_context(actor_id, issued_at=issued_at),
            "expected_task_version": 2,
            "idempotency_key": canonical_sha256(
                {"decide": approval_id, "digest": action_digest}
            ),
            "command_digest": "sha256:" + "0" * 64,
            "correlation_id": f"corr-{task_id}",
            "payload": {
                "approval_id": approval_id,
                "action_digest": action_digest,
                "decision": decision,
            },
            "issued_at": _iso(issued_at),
        }
    )


def tamper_decide_command(command: TaskCommand, **changes: Any) -> TaskCommand:
    """Rebuild a decide command with tampered payload (re-signed digest).

    Pass ``security_context`` to tamper the security binding itself.
    """
    value = {
        "command_id": command.command_id,
        "command_type": command.command_type.value,
        "tenant_id": command.tenant_id,
        "task_id": command.task_id,
        "actor": command.actor.to_mapping(),
        "security_context": command.security_context.to_mapping(),
        "expected_task_version": command.expected_task_version,
        "idempotency_key": command.idempotency_key,
        "command_digest": command.command_digest,
        "payload": dict(command.payload),
        "issued_at": command.issued_at.isoformat().replace("+00:00", "Z"),
        "correlation_id": command.correlation_id,
    }
    value["payload"].update(changes.pop("payload", {}))
    if "security_context" in changes:
        value["security_context"] = changes.pop("security_context")
    value["payload"].update(changes)
    return _sign(value)


# --------------------------------------------------------------------------
# Harness.
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OnboardingHarness:
    graph: OnboardingCompositeGraph
    checkpoints: InMemoryCheckpointStore
    leases: InMemoryLeaseStore
    probe: OnboardingGatewayProbe
    ledger: FakeOnboardingLedger
    artifacts: FakeOnboardingArtifacts
    approvals: FakeApprovalRepository
    resolver: FakeOnboardingResolver
    saver: InMemorySaver
    create: TaskCommand
    config: OnboardingGraphConfig


async def build_harness(
    task_id: str = "task_onbrec001",
    *,
    probe_options: OnboardingProbeOptions | None = None,
    approvals_enabled: bool = True,
    graph_version: str | None = None,
    create: TaskCommand | None = None,
    leases: InMemoryLeaseStore | None = None,
    checkpoints: InMemoryCheckpointStore | None = None,
    saver: InMemorySaver | None = None,
) -> OnboardingHarness:
    probe = OnboardingGatewayProbe(probe_options)
    ledger = FakeOnboardingLedger()
    artifacts = FakeOnboardingArtifacts()
    resolver = FakeOnboardingResolver()
    approvals = FakeApprovalRepository()
    config = OnboardingGraphConfig(
        **({"graph_version": graph_version} if graph_version else {})
    )
    checkpoints = checkpoints or InMemoryCheckpointStore()
    leases = leases or InMemoryLeaseStore()
    saver = saver or InMemorySaver()
    graph = OnboardingCompositeGraph(
        resolver=resolver,
        gateway=probe,
        checkpoints=checkpoints,
        ledger=ledger,
        artifacts=artifacts,
        context_builder=ContextBuilder(),
        config=config,
        approvals=RepoApprovalSource(approvals) if approvals_enabled else None,
        checkpointer=saver,
    )
    create = create or build_create_command(
        task_id,
        f"message://tenant-a/onboarding/{task_id}",
    )
    return OnboardingHarness(
        graph=graph,
        checkpoints=checkpoints,
        leases=leases,
        probe=probe,
        ledger=ledger,
        artifacts=artifacts,
        approvals=approvals,
        resolver=resolver,
        saver=saver,
        create=create,
        config=config,
    )


def rebuild_harness(
    previous: OnboardingHarness,
    *,
    task_id: str | None = None,
    probe_options: OnboardingProbeOptions | None = None,
    graph_version: str | None = None,
) -> OnboardingHarness:
    """A fresh "worker process" over the same durable state.

    Shares the checkpoints / leases / probe / ledger / artifacts /
    approval repository but uses a NEW control-plane thread checkpointer,
    exactly like a process crash followed by a restart.
    """
    task_id = task_id or previous.create.task_id
    harness = _build_shared(
        previous,
        task_id=task_id,
        probe_options=probe_options,
        graph_version=graph_version,
    )
    return harness


def _build_shared(
    previous: OnboardingHarness,
    *,
    task_id: str,
    probe_options: OnboardingProbeOptions | None,
    graph_version: str | None,
) -> OnboardingHarness:
    probe = previous.probe if probe_options is None else OnboardingGatewayProbe(
        probe_options
    )
    checkpoints = previous.checkpoints
    leases = previous.leases
    saver = InMemorySaver()
    config = OnboardingGraphConfig(
        **({"graph_version": graph_version} if graph_version else {})
    )
    graph = OnboardingCompositeGraph(
        resolver=previous.resolver,
        gateway=probe,
        checkpoints=checkpoints,
        ledger=previous.ledger,
        artifacts=previous.artifacts,
        context_builder=ContextBuilder(),
        config=config,
        approvals=(
            RepoApprovalSource(previous.approvals)
            if previous.graph._approvals is not None
            else None
        ),
        checkpointer=saver,
    )
    create = previous.create
    return OnboardingHarness(
        graph=graph,
        checkpoints=checkpoints,
        leases=leases,
        probe=probe,
        ledger=previous.ledger,
        artifacts=previous.artifacts,
        approvals=previous.approvals,
        resolver=previous.resolver,
        saver=saver,
        create=create,
        config=config,
    )


async def execute(
    harness: OnboardingHarness,
    command: TaskCommand,
    *,
    run_id: str,
    execution_ref: str = "execution://onboarding/recovery",
) -> Any:
    lease = await harness.leases.acquire(TENANT_A, command.task_id, run_id)
    try:
        return await harness.graph.execute(
            command,
            execution_ref=execution_ref,
            lease=lease,
        )
    finally:
        await harness.leases.release(lease)


def interrupt_card(harness: OnboardingHarness) -> Mapping[str, Any]:
    state = harness.graph.last_safe_state
    assert state is not None, "graph must have produced a safe state"
    interrupts = state.get("__interrupt__")
    assert interrupts, "graph must interrupt with a card"
    first = interrupts[0] if isinstance(interrupts, (tuple, list)) else interrupts
    value = getattr(first, "value", first)
    assert isinstance(value, Mapping)
    return value


def complete_fields(task_id: str) -> dict[str, str]:
    return {
        "full_name": "Chen Yi",
        "department": "engineering",
        "manager": MANAGER,
        "location": "Shanghai",
        "start_date": "2026-09-01",
    }


async def run_until_approval(
    harness: OnboardingHarness,
) -> tuple[Any, Mapping[str, Any]]:
    """create (partial) -> submit -> submit -> WAITING_APPROVAL."""
    task_id = harness.create.task_id
    create_ref = str(harness.create.payload["initial_message_ref"])
    harness.resolver.set_fields(
        create_ref,
        {"full_name": "Chen Yi", "department": "engineering"},
    )
    outcome = await execute(harness, harness.create, run_id="run_onb_create")
    assert outcome.state.status.value == "WAITING_USER", outcome.state

    ref1 = f"message://tenant-a/onboarding/{task_id}/step1"
    harness.resolver.set_fields(
        ref1, {"manager": MANAGER, "location": "Shanghai"}
    )
    outcome = await execute(
        harness,
        build_submit_command(task_id, ref1),
        run_id="run_onb_submit1",
    )
    assert outcome.state.status.value == "WAITING_USER", outcome.state

    ref2 = f"message://tenant-a/onboarding/{task_id}/step2"
    harness.resolver.set_fields(ref2, {"start_date": "2026-09-01"})
    outcome = await execute(
        harness,
        build_submit_command(task_id, ref2),
        run_id="run_onb_submit2",
    )
    assert outcome.state.status.value == "WAITING_APPROVAL", outcome.state
    return outcome, interrupt_card(harness)


async def approve_and_resume(
    harness: OnboardingHarness,
    card: Mapping[str, Any],
    *,
    approver: str = MANAGER,
    decision: str = "approve",
) -> Any:
    approval = build_approval_from_card(
        card, create=harness.create, config=harness.config
    )
    harness.approvals.approvals[(TENANT_A, str(card["approval_id"]))] = approval
    if decision == "approve":
        await harness.approvals.approve(str(card["approval_id"]), approver)
    decide = build_decide_command(
        harness.create.task_id,
        approval_id=str(card["approval_id"]),
        action_digest=str(card["action_digest"]),
        decision=decision,
        actor_id=approver,
    )
    return await execute(harness, decide, run_id="run_onb_decide")


__all__ = [
    "MANAGER",
    "PURPOSE",
    "REQUESTER",
    "TENANT_A",
    "FakeApprovalRepository",
    "FakeOnboardingArtifacts",
    "FakeOnboardingLedger",
    "FakeOnboardingResolver",
    "OnboardingCrash",
    "OnboardingGatewayProbe",
    "OnboardingHarness",
    "OnboardingProbeOptions",
    "RepoApprovalSource",
    "approve_and_resume",
    "build_approval_from_card",
    "build_create_command",
    "build_decide_command",
    "build_harness",
    "build_submit_command",
    "complete_fields",
    "execute",
    "interrupt_card",
    "rebuild_harness",
    "run_until_approval",
    "stable_id",
    "tamper_decide_command",
]
