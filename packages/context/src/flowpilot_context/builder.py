from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from flowpilot_domain import DataClassification, SecurityContextRef

from .errors import ContextError, ContextErrorCode
from .models import (
    CLASSIFICATION_RANK,
    ContextEnvelope,
    ContextLayer,
    ContextManifest,
    ContextPolicy,
    HandoffBundle,
    HandoffManifest,
    LayeredSummary,
    LayerName,
    TrustLevel,
)

_OPTIONAL_DROP_ORDER = {
    LayerName.EXAMPLES: 0,
    LayerName.RECENT_MESSAGES: 1,
    LayerName.RETRIEVAL_EVIDENCE: 2,
    LayerName.TOOL_OBSERVATIONS: 3,
    LayerName.CONVERSATION_SUMMARY: 4,
}

_FORBIDDEN_HANDOFF_FIELDS = {
    "approval",
    "approval_id",
    "credential",
    "credentials",
    "provider_session",
    "session_ref",
    "tool_credentials",
}


def build_summary_layer(
    *,
    summary: LayeredSummary,
    ref: str,
) -> ContextLayer:
    """Wrap a layered summary as the L3 conversation-summary layer.

    The summary is data (``DERIVED_DATA``), never an instruction: it rides
    below L0-L2 in the trust model and is the first optional layer dropped
    under budget pressure after recent messages (FP-CTX-002).
    """
    if not ref:
        raise ContextError(
            ContextErrorCode.INVALID_CONTEXT,
            "summary layer requires a non-empty reference",
        )
    return ContextLayer(
        name=LayerName.CONVERSATION_SUMMARY,
        trust=TrustLevel.DERIVED_DATA,
        classification=DataClassification.INTERNAL,
        content=summary.to_mapping(),
        source_refs=(ref,),
    )


def forbidden_field_scan(
    value: object,
    forbidden: frozenset[str] = frozenset(_FORBIDDEN_HANDOFF_FIELDS),
) -> tuple[str, ...]:
    """Recursively find forbidden handoff fields in any serialized payload.

    Field names are matched case-insensitively so ``approval``,
    ``ApprovalId`` or ``APPROVAL`` all count as leaks (FP-CTX-003).
    """
    hits: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, Mapping):
            for key, child in node.items():
                if str(key).lower() in forbidden:
                    hits.append(str(key))
                walk(child)
        elif isinstance(node, (tuple, list)):
            for child in node:
                walk(child)

    walk(value)
    return tuple(dict.fromkeys(hits))


def estimate_tokens(value: object) -> int:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return max(1, math.ceil(len(serialized) / 4))


@dataclass(frozen=True, slots=True)
class ContextBuildRequest:
    context_id: str
    task_id: str
    agent_id: str
    purpose: str
    security_context: SecurityContextRef
    task_state: Mapping[str, Any]
    task_state_ref: str
    system_policy_ref: str
    policy: ContextPolicy
    optional_layers: tuple[ContextLayer, ...] = ()
    excluded_fields: tuple[str, ...] = ("credential",)
    redactions: tuple[str, ...] = ()


class ContextBuilder:
    def __init__(self, *, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))

    def build(self, request: ContextBuildRequest) -> ContextEnvelope:
        self._validate_security_binding(request)
        layers: list[ContextLayer] = [
            ContextLayer(
                name=LayerName.SYSTEM_POLICY,
                trust=TrustLevel.CONTROLLED_INSTRUCTION,
                classification=DataClassification.INTERNAL,
                content={"policy_ref": request.system_policy_ref},
                source_refs=(request.system_policy_ref,),
            ),
            ContextLayer(
                name=LayerName.SECURITY_VIEW,
                trust=TrustLevel.AUTHENTICATED_DERIVED,
                classification=request.policy.data_classification_ceiling,
                content={
                    "subject_ref": request.security_context.context_ref,
                    "subject_type": request.security_context.subject_type.value,
                },
                source_refs=(request.security_context.context_ref,),
            ),
            ContextLayer(
                name=LayerName.TASK_STATE,
                trust=TrustLevel.BUSINESS_STATE,
                classification=DataClassification.INTERNAL,
                content=dict(request.task_state),
                source_refs=(request.task_state_ref,),
            ),
            *request.optional_layers,
        ]
        self._validate_layer_security(layers, request.security_context, request.policy)
        kept_layers, removed = self._fit_budget(layers, request.policy.token_budget)
        included_refs = tuple(
            dict.fromkeys(
                source_ref
                for layer in kept_layers
                for source_ref in layer.source_refs
            )
        )
        estimated = estimate_tokens(
            [layer.to_mapping() for layer in kept_layers]
        )
        return ContextEnvelope(
            context_id=request.context_id,
            task_id=request.task_id,
            tenant_id=request.security_context.tenant_id,
            agent_id=request.agent_id,
            purpose=request.purpose,
            policy=request.policy,
            layers=tuple(kept_layers),
            manifest=ContextManifest(
                included_refs=included_refs,
                excluded_fields=tuple(dict.fromkeys(request.excluded_fields)),
                redactions=tuple(dict.fromkeys(request.redactions)),
                input_tokens_estimated=estimated,
                truncation_reason=(
                    "token_budget:"
                    + ",".join(item.value for item in removed)
                    if removed
                    else None
                ),
            ),
        )

    def rebuild_for_handoff(
        self,
        *,
        source: ContextEnvelope,
        security_context: SecurityContextRef,
        target_agent_id: str,
        new_context_id: str,
        required_task_fields: Sequence[str],
        allowed_tools: Sequence[str],
        target_tool_allowlist: Sequence[str] | None = None,
    ) -> HandoffBundle:
        if target_agent_id == source.agent_id:
            raise ContextError(
                ContextErrorCode.HANDOFF_DENIED,
                "handoff target must differ from the source agent",
            )
        forbidden = _FORBIDDEN_HANDOFF_FIELDS.intersection(required_task_fields)
        if forbidden:
            raise ContextError(
                ContextErrorCode.HANDOFF_DENIED,
                "handoff requested forbidden task fields",
            )
        task_content = source.layer(LayerName.TASK_STATE).content
        if not isinstance(task_content, Mapping):
            raise ContextError(
                ContextErrorCode.HANDOFF_DENIED,
                "task state layer must be an object for handoff",
            )
        missing = [field for field in required_task_fields if field not in task_content]
        if missing:
            raise ContextError(
                ContextErrorCode.HANDOFF_DENIED,
                "handoff requested unavailable task fields",
            )
        filtered_task_state = {
            field: task_content[field] for field in required_task_fields
        }
        rebuilt = self.build(
            ContextBuildRequest(
                context_id=new_context_id,
                task_id=source.task_id,
                agent_id=target_agent_id,
                purpose=source.purpose,
                security_context=security_context,
                task_state=filtered_task_state,
                task_state_ref=source.layer(
                    LayerName.TASK_STATE
                ).source_refs[0],
                system_policy_ref=source.layer(
                    LayerName.SYSTEM_POLICY
                ).source_refs[0],
                policy=source.policy,
                excluded_fields=tuple(
                    sorted(
                        set(source.manifest.excluded_fields)
                        | _FORBIDDEN_HANDOFF_FIELDS
                        | {"unrelated_messages"}
                    )
                ),
            )
        )
        included_fields = tuple(f"task.{item}" for item in required_task_fields)
        effective_tools = self._filter_tools(
            allowed_tools,
            target_tool_allowlist,
        )
        bundle = HandoffBundle(
            context=rebuilt,
            manifest=HandoffManifest(
                source_agent_id=source.agent_id,
                target_agent_id=target_agent_id,
                context_policy_version=source.policy.context_policy_version,
                included_fields=included_fields,
                included_refs=rebuilt.manifest.included_refs,
                excluded_categories=(
                    "approval",
                    "provider_session",
                    "tool_credentials",
                    "unrelated_messages",
                ),
                allowed_tools=effective_tools,
                input_tokens=rebuilt.manifest.input_tokens_estimated,
            ),
        )
        leaks = forbidden_field_scan(bundle.to_mapping())
        if leaks:
            raise ContextError(
                ContextErrorCode.HANDOFF_DENIED,
                "handoff bundle carries forbidden fields",
            )
        return bundle

    @staticmethod
    def _filter_tools(
        proposed: Sequence[str],
        target_allowlist: Sequence[str] | None,
    ) -> tuple[str, ...]:
        """Intersect proposed tools with the target agent's allowlist.

        Without an allowlist the proposal passes through unchanged
        (backward compatible); with one, tools the target agent is not
        authorized to call are dropped, not forwarded (FP-AGT-001
        linkage).  Order of the proposal is preserved.
        """
        if target_allowlist is None:
            return tuple(dict.fromkeys(proposed))
        allowlist = set(target_allowlist)
        return tuple(
            dict.fromkeys(tool for tool in proposed if tool in allowlist)
        )

    def _validate_security_binding(self, request: ContextBuildRequest) -> None:
        if request.purpose != request.security_context.purpose:
            raise ContextError(
                ContextErrorCode.SECURITY_BINDING_MISMATCH,
                "context purpose does not match the security context",
            )
        now = self._clock().astimezone(UTC)
        if request.security_context.expires_at <= now:
            raise ContextError(
                ContextErrorCode.SECURITY_CONTEXT_EXPIRED,
                "security context has expired",
            )

    @staticmethod
    def _validate_layer_security(
        layers: Sequence[ContextLayer],
        security_context: SecurityContextRef,
        policy: ContextPolicy,
    ) -> None:
        security_rank = CLASSIFICATION_RANK[
            security_context.data_classification_ceiling
        ]
        policy_rank = CLASSIFICATION_RANK[policy.data_classification_ceiling]
        if policy_rank > security_rank:
            raise ContextError(
                ContextErrorCode.CLASSIFICATION_DENIED,
                "context policy exceeds the security classification ceiling",
            )
        if any(
            CLASSIFICATION_RANK[layer.classification] > min(security_rank, policy_rank)
            for layer in layers
        ):
            raise ContextError(
                ContextErrorCode.CLASSIFICATION_DENIED,
                "context layer exceeds an effective classification ceiling",
            )

    @staticmethod
    def _fit_budget(
        layers: list[ContextLayer],
        token_budget: int,
    ) -> tuple[list[ContextLayer], list[LayerName]]:
        kept = list(layers)
        removed: list[LayerName] = []
        while estimate_tokens([layer.to_mapping() for layer in kept]) > token_budget:
            optional = [
                layer for layer in kept if layer.name in _OPTIONAL_DROP_ORDER
            ]
            if not optional:
                raise ContextError(
                    ContextErrorCode.BUDGET_EXHAUSTED,
                    "required context layers exceed the hard token budget",
                )
            drop = min(optional, key=lambda item: _OPTIONAL_DROP_ORDER[item.name])
            kept.remove(drop)
            removed.append(drop.name)
        return kept, removed
