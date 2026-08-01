from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from flowpilot_domain import DataClassification

from .errors import ContextError, ContextErrorCode


class LayerName(StrEnum):
    SYSTEM_POLICY = "L0_SYSTEM_POLICY"
    SECURITY_VIEW = "L1_SECURITY_VIEW"
    TASK_STATE = "L2_TASK_STATE"
    CONVERSATION_SUMMARY = "L3_CONVERSATION_SUMMARY"
    RECENT_MESSAGES = "L4_RECENT_MESSAGES"
    RETRIEVAL_EVIDENCE = "L5_RETRIEVAL_EVIDENCE"
    TOOL_OBSERVATIONS = "L6_TOOL_OBSERVATIONS"
    EXAMPLES = "L7_EXAMPLES"


class TrustLevel(StrEnum):
    CONTROLLED_INSTRUCTION = "controlled_instruction"
    AUTHENTICATED_DERIVED = "authenticated_derived"
    BUSINESS_STATE = "business_state"
    DERIVED_DATA = "derived_data"
    UNTRUSTED_DATA = "untrusted_data"


EXPECTED_TRUST: dict[LayerName, TrustLevel] = {
    LayerName.SYSTEM_POLICY: TrustLevel.CONTROLLED_INSTRUCTION,
    LayerName.SECURITY_VIEW: TrustLevel.AUTHENTICATED_DERIVED,
    LayerName.TASK_STATE: TrustLevel.BUSINESS_STATE,
    LayerName.CONVERSATION_SUMMARY: TrustLevel.DERIVED_DATA,
    LayerName.RECENT_MESSAGES: TrustLevel.UNTRUSTED_DATA,
    LayerName.RETRIEVAL_EVIDENCE: TrustLevel.UNTRUSTED_DATA,
    LayerName.TOOL_OBSERVATIONS: TrustLevel.UNTRUSTED_DATA,
    LayerName.EXAMPLES: TrustLevel.CONTROLLED_INSTRUCTION,
}

CLASSIFICATION_RANK: dict[DataClassification, int] = {
    DataClassification.PUBLIC: 0,
    DataClassification.INTERNAL: 1,
    DataClassification.CONFIDENTIAL: 2,
    DataClassification.RESTRICTED: 3,
}


def _require_non_empty_content(content: object) -> None:
    valid = (
        bool(content)
        if isinstance(content, (Mapping, tuple, list, str))
        else False
    )
    if not valid:
        raise ContextError(
            ContextErrorCode.INVALID_CONTEXT,
            "context layer content must be a non-empty object, array, or string",
        )


@dataclass(frozen=True, slots=True)
class ContextLayer:
    name: LayerName
    trust: TrustLevel
    classification: DataClassification
    content: Mapping[str, Any] | tuple[Any, ...] | str
    source_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.trust is not EXPECTED_TRUST[self.name]:
            raise ContextError(
                ContextErrorCode.INVALID_CONTEXT,
                f"{self.name.value} has an invalid trust level",
            )
        _require_non_empty_content(self.content)
        if not self.source_refs or any(not item for item in self.source_refs):
            raise ContextError(
                ContextErrorCode.INVALID_CONTEXT,
                "context layers require at least one non-empty source reference",
            )
        if len(self.source_refs) != len(set(self.source_refs)):
            raise ContextError(
                ContextErrorCode.INVALID_CONTEXT,
                "context layer source references must be unique",
            )

    def to_mapping(self) -> dict[str, Any]:
        content: object
        if isinstance(self.content, Mapping):
            content = dict(self.content)
        elif isinstance(self.content, tuple):
            content = list(self.content)
        else:
            content = self.content
        return {
            "name": self.name.value,
            "trust": self.trust.value,
            "classification": self.classification.value,
            "content": content,
            "source_refs": list(self.source_refs),
        }


@dataclass(frozen=True, slots=True)
class ContextPolicy:
    context_policy_version: str
    data_classification_ceiling: DataClassification
    provider_allowlist: tuple[str, ...]
    token_budget: int

    def __post_init__(self) -> None:
        if not self.context_policy_version:
            raise ContextError(
                ContextErrorCode.INVALID_CONTEXT,
                "context policy version is required",
            )
        if (
            not self.provider_allowlist
            or any(not item for item in self.provider_allowlist)
            or len(self.provider_allowlist) != len(set(self.provider_allowlist))
        ):
            raise ContextError(
                ContextErrorCode.INVALID_CONTEXT,
                "provider allowlist must be non-empty and unique",
            )
        if self.token_budget < 1:
            raise ContextError(
                ContextErrorCode.INVALID_CONTEXT,
                "context token budget must be positive",
            )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "context_policy_version": self.context_policy_version,
            "data_classification_ceiling": (
                self.data_classification_ceiling.value
            ),
            "provider_allowlist": list(self.provider_allowlist),
            "token_budget": self.token_budget,
        }


@dataclass(frozen=True, slots=True)
class ContextManifest:
    included_refs: tuple[str, ...]
    excluded_fields: tuple[str, ...]
    redactions: tuple[str, ...]
    input_tokens_estimated: int
    input_tokens_actual: int | None = None
    truncation_reason: str | None = None

    def __post_init__(self) -> None:
        if self.input_tokens_estimated < 0:
            raise ContextError(
                ContextErrorCode.INVALID_CONTEXT,
                "estimated input tokens cannot be negative",
            )
        if self.input_tokens_actual is not None and self.input_tokens_actual < 0:
            raise ContextError(
                ContextErrorCode.INVALID_CONTEXT,
                "actual input tokens cannot be negative",
            )
        for values, label in (
            (self.included_refs, "included references"),
            (self.excluded_fields, "excluded fields"),
            (self.redactions, "redactions"),
        ):
            if len(values) != len(set(values)):
                raise ContextError(
                    ContextErrorCode.INVALID_CONTEXT,
                    f"context manifest {label} must be unique",
                )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "included_refs": list(self.included_refs),
            "excluded_fields": list(self.excluded_fields),
            "redactions": list(self.redactions),
            "input_tokens_estimated": self.input_tokens_estimated,
            "input_tokens_actual": self.input_tokens_actual,
            "truncation_reason": self.truncation_reason,
        }


@dataclass(frozen=True, slots=True)
class ContextEnvelope:
    context_id: str
    task_id: str
    tenant_id: str
    agent_id: str
    purpose: str
    policy: ContextPolicy
    layers: tuple[ContextLayer, ...]
    manifest: ContextManifest

    def __post_init__(self) -> None:
        for value, label in (
            (self.context_id, "context_id"),
            (self.task_id, "task_id"),
            (self.tenant_id, "tenant_id"),
            (self.agent_id, "agent_id"),
            (self.purpose, "purpose"),
        ):
            if not value:
                raise ContextError(
                    ContextErrorCode.INVALID_CONTEXT,
                    f"{label} is required",
                )
        names = [layer.name for layer in self.layers]
        if len(names) != len(set(names)):
            raise ContextError(
                ContextErrorCode.INVALID_CONTEXT,
                "context layer names must be unique",
            )
        for required in (
            LayerName.SYSTEM_POLICY,
            LayerName.SECURITY_VIEW,
            LayerName.TASK_STATE,
        ):
            if names.count(required) != 1:
                raise ContextError(
                    ContextErrorCode.INVALID_CONTEXT,
                    f"context requires exactly one {required.value} layer",
                )
        ceiling_rank = CLASSIFICATION_RANK[
            self.policy.data_classification_ceiling
        ]
        if any(
            CLASSIFICATION_RANK[layer.classification] > ceiling_rank
            for layer in self.layers
        ):
            raise ContextError(
                ContextErrorCode.CLASSIFICATION_DENIED,
                "context layer exceeds the context classification ceiling",
            )
        if self.manifest.input_tokens_estimated > self.policy.token_budget:
            raise ContextError(
                ContextErrorCode.BUDGET_EXHAUSTED,
                "context exceeds its input token budget",
            )

    def layer(self, name: LayerName) -> ContextLayer:
        return next(layer for layer in self.layers if layer.name is name)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "context_id": self.context_id,
            "task_id": self.task_id,
            "tenant_id": self.tenant_id,
            "agent_id": self.agent_id,
            "purpose": self.purpose,
            "policy": self.policy.to_mapping(),
            "layers": [layer.to_mapping() for layer in self.layers],
            "manifest": self.manifest.to_mapping(),
        }


@dataclass(frozen=True, slots=True)
class HandoffManifest:
    source_agent_id: str
    target_agent_id: str
    context_policy_version: str
    included_fields: tuple[str, ...]
    included_refs: tuple[str, ...]
    excluded_categories: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    input_tokens: int


@dataclass(frozen=True, slots=True)
class HandoffBundle:
    context: ContextEnvelope
    manifest: HandoffManifest

    def to_mapping(self) -> dict[str, Any]:
        return {
            "context": self.context.to_mapping(),
            "manifest": {
                "source_agent_id": self.manifest.source_agent_id,
                "target_agent_id": self.manifest.target_agent_id,
                "context_policy_version": (
                    self.manifest.context_policy_version
                ),
                "included_fields": list(self.manifest.included_fields),
                "included_refs": list(self.manifest.included_refs),
                "excluded_categories": list(
                    self.manifest.excluded_categories
                ),
                "allowed_tools": list(self.manifest.allowed_tools),
                "input_tokens": self.manifest.input_tokens,
            },
        }


class SummaryKind(StrEnum):
    """Evidence status of a conversation summary item (FP-CTX-002)."""

    CLAIMED = "claimed"
    VERIFIED = "verified"
    INFERRED = "inferred"


@dataclass(frozen=True, slots=True)
class SummaryItem:
    kind: SummaryKind
    text: str
    source_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.text or not self.text.strip():
            raise ContextError(
                ContextErrorCode.INVALID_CONTEXT,
                "summary items require non-empty text",
            )
        if not self.source_refs or any(not item for item in self.source_refs):
            raise ContextError(
                ContextErrorCode.INVALID_CONTEXT,
                "summary items require at least one non-empty source reference",
            )
        if len(self.source_refs) != len(set(self.source_refs)):
            raise ContextError(
                ContextErrorCode.INVALID_CONTEXT,
                "summary item source references must be unique",
            )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "text": self.text,
            "source_refs": list(self.source_refs),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> SummaryItem:
        try:
            return cls(
                kind=SummaryKind(str(value["kind"])),
                text=str(value["text"]),
                source_refs=tuple(str(item) for item in value["source_refs"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ContextError(
                ContextErrorCode.INVALID_CONTEXT,
                "summary item does not match the v1 schema",
            ) from exc


@dataclass(frozen=True, slots=True)
class LayeredSummary:
    """Strictly partitioned conversation summary (FP-CTX-002).

    Items are bucketed by evidence status: ``claimed`` (stated by a party,
    not yet confirmed), ``verified`` (confirmed by a tool result or an
    authoritative source), and ``inferred`` (derived by the runtime). The
    buckets are mutually exclusive; one text cannot appear in two buckets.
    """

    items: tuple[SummaryItem, ...]

    def __post_init__(self) -> None:
        seen: set[tuple[SummaryKind, str]] = set()
        for item in self.items:
            identity = (item.kind, item.text)
            if identity in seen:
                raise ContextError(
                    ContextErrorCode.INVALID_CONTEXT,
                    "layered summary items must be unique per kind and text",
                )
            seen.add(identity)

    def sections(self) -> dict[SummaryKind, tuple[SummaryItem, ...]]:
        return {
            kind: tuple(item for item in self.items if item.kind is kind)
            for kind in SummaryKind
        }

    def merge(self, other: LayeredSummary) -> LayeredSummary:
        """Append items without duplicating existing (kind, text) pairs."""
        known = {(item.kind, item.text) for item in self.items}
        merged = list(self.items)
        for item in other.items:
            if (item.kind, item.text) not in known:
                merged.append(item)
                known.add((item.kind, item.text))
        return LayeredSummary(items=tuple(merged))

    def to_mapping(self) -> dict[str, Any]:
        return {"items": [item.to_mapping() for item in self.items]}

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> LayeredSummary:
        try:
            return cls(
                items=tuple(
                    SummaryItem.from_mapping(item) for item in value["items"]
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ContextError(
                ContextErrorCode.INVALID_CONTEXT,
                "layered summary does not match the v1 schema",
            ) from exc


@dataclass(frozen=True, slots=True)
class TokenUsageRecord:
    """One model-call accounting entry (FP-CTX-004)."""

    turn_index: int
    request_id: str
    context_id: str
    agent_id: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    layer_tokens: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        if self.turn_index < 0:
            raise ContextError(
                ContextErrorCode.INVALID_CONTEXT,
                "turn index cannot be negative",
            )
        if any(
            value < 0
            for value in (
                self.input_tokens,
                self.output_tokens,
                self.total_tokens,
            )
        ):
            raise ContextError(
                ContextErrorCode.INVALID_CONTEXT,
                "token usage cannot be negative",
            )
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ContextError(
                ContextErrorCode.INVALID_CONTEXT,
                "total tokens must equal input plus output tokens",
            )
        layer_names = [name for name, _ in self.layer_tokens]
        if len(layer_names) != len(set(layer_names)):
            raise ContextError(
                ContextErrorCode.INVALID_CONTEXT,
                "layer token breakdown must be unique per layer",
            )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "turn_index": self.turn_index,
            "request_id": self.request_id,
            "context_id": self.context_id,
            "agent_id": self.agent_id,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "layer_tokens": [
                {"layer": name, "tokens": tokens}
                for name, tokens in self.layer_tokens
            ],
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> TokenUsageRecord:
        try:
            return cls(
                turn_index=int(value["turn_index"]),
                request_id=str(value["request_id"]),
                context_id=str(value["context_id"]),
                agent_id=str(value["agent_id"]),
                input_tokens=int(value["input_tokens"]),
                output_tokens=int(value["output_tokens"]),
                total_tokens=int(value["total_tokens"]),
                layer_tokens=tuple(
                    (str(item["layer"]), int(item["tokens"]))
                    for item in value["layer_tokens"]
                ),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ContextError(
                ContextErrorCode.INVALID_CONTEXT,
                "token usage record does not match the v1 schema",
            ) from exc
