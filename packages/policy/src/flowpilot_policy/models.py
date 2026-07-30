from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from flowpilot_domain import canonical_sha256
from flowpilot_tool_contracts import FrozenJson, freeze_json, thaw_json

from .errors import PolicyError, PolicyErrorCode

_SHA256 = re.compile(r"^sha256:[a-f0-9]{64}$")
_POLICY_DECISION_ID = re.compile(r"^pd_[A-Za-z0-9_-]{8,128}$")
_TASK_ID = re.compile(r"^task_[A-Za-z0-9_-]{8,128}$")
_TOOL_NAME = re.compile(
    r"^[a-z0-9]+(?:[._-][a-z0-9]+)*\.v[1-9][0-9]*$"
)


def _utc(value: object, field: str) -> datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise PolicyError(
                PolicyErrorCode.INVALID,
                f"{field} must be an RFC 3339 timestamp",
            ) from exc
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise PolicyError(
            PolicyErrorCode.INVALID,
            f"{field} must be an RFC 3339 timestamp",
        )
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PolicyError(
            PolicyErrorCode.INVALID,
            f"{field} must be timezone-aware",
        )
    return parsed.astimezone(UTC)


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _exact(
    value: Mapping[str, Any],
    required: set[str],
    *,
    field: str,
) -> None:
    if set(value) != required:
        raise PolicyError(
            PolicyErrorCode.INVALID,
            f"{field} fields do not match the public v1 contract",
        )


def _text(value: object, field: str, maximum: int = 128) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise PolicyError(
            PolicyErrorCode.INVALID,
            f"{field} must contain between 1 and {maximum} characters",
        )
    return value


def _sha(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise PolicyError(
            PolicyErrorCode.INVALID,
            f"{field} must be a lowercase sha256 digest",
        )
    return value


class PolicyDecisionKind(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


@dataclass(frozen=True, slots=True)
class PolicyAgent:
    id: str
    version: str
    principal_ref: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> PolicyAgent:
        _exact(
            value,
            {"id", "version", "principal_ref"},
            field="policy.agent",
        )
        return cls(
            id=_text(value["id"], "policy.agent.id"),
            version=_text(value["version"], "policy.agent.version"),
            principal_ref=_text(
                value["principal_ref"],
                "policy.agent.principal_ref",
                512,
            ),
        )

    def to_mapping(self) -> dict[str, str]:
        return {
            "id": self.id,
            "version": self.version,
            "principal_ref": self.principal_ref,
        }


@dataclass(frozen=True, slots=True)
class PolicyAction:
    tool: str
    operation: str
    action_digest: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> PolicyAction:
        _exact(
            value,
            {"tool", "operation", "action_digest"},
            field="policy.action",
        )
        operation = value["operation"]
        if operation not in {"read", "write"}:
            raise PolicyError(
                PolicyErrorCode.INVALID,
                "policy action operation is not part of v1",
            )
        tool = _text(value["tool"], "policy.action.tool", 256)
        if _TOOL_NAME.fullmatch(tool) is None:
            raise PolicyError(
                PolicyErrorCode.INVALID,
                "policy action tool is not a versioned identifier",
            )
        return cls(
            tool=tool,
            operation=operation,
            action_digest=_sha(
                value["action_digest"], "policy.action.action_digest"
            ),
        )

    def to_mapping(self) -> dict[str, str]:
        return {
            "tool": self.tool,
            "operation": self.operation,
            "action_digest": self.action_digest,
        }


class Obligation(Protocol):
    @property
    def name(self) -> str: ...

    def to_mapping(self) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class MaskFields:
    fields: tuple[str, ...]
    name: str = "mask_fields"

    def to_mapping(self) -> dict[str, Any]:
        return {"name": self.name, "parameters": {"fields": list(self.fields)}}


@dataclass(frozen=True, slots=True)
class LimitRecords:
    maximum: int
    name: str = "limit_records"

    def to_mapping(self) -> dict[str, Any]:
        return {"name": self.name, "parameters": {"maximum": self.maximum}}


@dataclass(frozen=True, slots=True)
class AuditLevel:
    level: str
    name: str = "audit_level"

    def to_mapping(self) -> dict[str, Any]:
        return {"name": self.name, "parameters": {"level": self.level}}


@dataclass(frozen=True, slots=True)
class RequireMfa:
    minimum_assurance: str
    name: str = "require_mfa"

    def to_mapping(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "parameters": {"minimum_assurance": self.minimum_assurance},
        }


@dataclass(frozen=True, slots=True)
class RestrictProvider:
    providers: tuple[str, ...]
    name: str = "restrict_provider"

    def to_mapping(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "parameters": {"providers": list(self.providers)},
        }


@dataclass(frozen=True, slots=True)
class CredentialTtl:
    seconds: int
    name: str = "credential_ttl_seconds"

    def to_mapping(self) -> dict[str, Any]:
        return {"name": self.name, "parameters": {"seconds": self.seconds}}


type PolicyObligation = (
    MaskFields
    | LimitRecords
    | AuditLevel
    | RequireMfa
    | RestrictProvider
    | CredentialTtl
)


def _obligation(value: Mapping[str, Any]) -> PolicyObligation:
    _exact(value, {"name", "parameters"}, field="obligation")
    name = value["name"]
    parameters = value["parameters"]
    if not isinstance(parameters, Mapping):
        raise PolicyError(
            PolicyErrorCode.INVALID,
            "obligation parameters must be an object",
        )
    if name == "mask_fields":
        _exact(parameters, {"fields"}, field="mask_fields.parameters")
        fields = parameters["fields"]
        if (
            not isinstance(fields, Sequence)
            or isinstance(fields, (str, bytes, bytearray))
            or not fields
            or any(not isinstance(item, str) or not item for item in fields)
            or len(set(fields)) != len(fields)
        ):
            raise PolicyError(
                PolicyErrorCode.INVALID,
                "mask_fields parameters are malformed",
            )
        return MaskFields(tuple(fields))
    if name == "limit_records":
        _exact(parameters, {"maximum"}, field="limit_records.parameters")
        maximum = parameters["maximum"]
        if (
            isinstance(maximum, bool)
            or not isinstance(maximum, int)
            or not 1 <= maximum <= 10_000
        ):
            raise PolicyError(
                PolicyErrorCode.INVALID,
                "limit_records maximum is outside v1 bounds",
            )
        return LimitRecords(maximum)
    if name == "audit_level":
        _exact(parameters, {"level"}, field="audit_level.parameters")
        level = parameters["level"]
        if level not in {"standard", "detailed", "security"}:
            raise PolicyError(
                PolicyErrorCode.INVALID,
                "audit_level is not part of v1",
            )
        return AuditLevel(level)
    if name == "require_mfa":
        _exact(parameters, {"minimum_assurance"}, field="require_mfa.parameters")
        minimum = parameters["minimum_assurance"]
        if minimum not in {"substantial", "high"}:
            raise PolicyError(
                PolicyErrorCode.INVALID,
                "require_mfa assurance is not part of v1",
            )
        return RequireMfa(minimum)
    if name == "restrict_provider":
        _exact(
            parameters,
            {"providers"},
            field="restrict_provider.parameters",
        )
        providers = parameters["providers"]
        if (
            not isinstance(providers, Sequence)
            or isinstance(providers, (str, bytes, bytearray))
            or not providers
            or any(not isinstance(item, str) or not item for item in providers)
            or len(set(providers)) != len(providers)
        ):
            raise PolicyError(
                PolicyErrorCode.INVALID,
                "restrict_provider parameters are malformed",
            )
        return RestrictProvider(tuple(providers))
    if name == "credential_ttl_seconds":
        _exact(
            parameters,
            {"seconds"},
            field="credential_ttl_seconds.parameters",
        )
        seconds = parameters["seconds"]
        if (
            isinstance(seconds, bool)
            or not isinstance(seconds, int)
            or not 30 <= seconds <= 3_600
        ):
            raise PolicyError(
                PolicyErrorCode.INVALID,
                "credential TTL is outside v1 bounds",
            )
        return CredentialTtl(seconds)
    raise PolicyError(
        PolicyErrorCode.OBLIGATION_UNSUPPORTED,
        "policy contains an unknown obligation",
    )


@dataclass(frozen=True, slots=True)
class ApprovalRequirements:
    roles: tuple[str, ...]
    minimum_approvers: int
    separation_of_duties: bool

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any]
    ) -> ApprovalRequirements:
        _exact(
            value,
            {"roles", "minimum_approvers", "separation_of_duties"},
            field="approval_requirements",
        )
        roles = value["roles"]
        if (
            not isinstance(roles, Sequence)
            or isinstance(roles, (str, bytes, bytearray))
            or not roles
            or any(not isinstance(item, str) or not item for item in roles)
            or any(len(item) > 128 for item in roles)
            or len(set(roles)) != len(roles)
            or isinstance(value["minimum_approvers"], bool)
            or value["minimum_approvers"] != 1
            or value["separation_of_duties"] is not True
        ):
            raise PolicyError(
                PolicyErrorCode.INVALID,
                "approval requirements violate the v1 single-approval protocol",
            )
        return cls(tuple(roles), 1, True)

    def to_mapping(self) -> dict[str, Any]:
        return {
            "roles": list(self.roles),
            "minimum_approvers": self.minimum_approvers,
            "separation_of_duties": self.separation_of_duties,
        }


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    decision_id: str
    tenant_id: str
    task_id: str
    subject_ref: str
    subject_context_hash: str
    agent: PolicyAgent
    action: PolicyAction
    decision: PolicyDecisionKind
    reason_codes: tuple[str, ...]
    obligations: tuple[PolicyObligation, ...]
    approval_requirements: ApprovalRequirements | None
    policy_version: str
    input_hash: str
    evaluated_at: datetime
    expires_at: datetime
    input_canonicalization: str = "rfc8785"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> PolicyDecision:
        _exact(
            value,
            {
                "decision_id",
                "tenant_id",
                "task_id",
                "subject_ref",
                "subject_context_hash",
                "agent",
                "action",
                "decision",
                "reason_codes",
                "obligations",
                "approval_requirements",
                "policy_version",
                "input_canonicalization",
                "input_hash",
                "evaluated_at",
                "expires_at",
            },
            field="policy_decision",
        )
        if _POLICY_DECISION_ID.fullmatch(str(value["decision_id"])) is None:
            raise PolicyError(
                PolicyErrorCode.INVALID,
                "decision_id is not a public v1 identifier",
            )
        try:
            kind = PolicyDecisionKind(value["decision"])
        except (TypeError, ValueError) as exc:
            raise PolicyError(
                PolicyErrorCode.INVALID,
                "policy decision is not part of v1",
            ) from exc
        if value["input_canonicalization"] != "rfc8785":
            raise PolicyError(
                PolicyErrorCode.INVALID,
                "policy input canonicalization must be RFC 8785",
            )
        reasons = value["reason_codes"]
        obligations = value["obligations"]
        if (
            not isinstance(reasons, Sequence)
            or isinstance(reasons, (str, bytes, bytearray))
            or not reasons
            or any(not isinstance(item, str) or not item for item in reasons)
            or any(len(item) > 128 for item in reasons)
            or len(set(reasons)) != len(reasons)
            or not isinstance(obligations, Sequence)
            or isinstance(obligations, (str, bytes, bytearray))
            or len(obligations) > 6
        ):
            raise PolicyError(
                PolicyErrorCode.INVALID,
                "policy reason codes or obligations are malformed",
            )
        parsed_obligations = tuple(
            _obligation(item)
            if isinstance(item, Mapping)
            else _raise_invalid_obligation()
            for item in obligations
        )
        names = [item.name for item in parsed_obligations]
        if len(names) != len(set(names)):
            raise PolicyError(
                PolicyErrorCode.OBLIGATION_CONFLICT,
                "policy contains duplicate obligations",
            )
        requirements_value = value["approval_requirements"]
        if requirements_value is None:
            requirements = None
        elif isinstance(requirements_value, Mapping):
            requirements = ApprovalRequirements.from_mapping(
                requirements_value
            )
        else:
            raise PolicyError(
                PolicyErrorCode.INVALID,
                "approval requirements must be an object or null",
            )
        if (
            kind is PolicyDecisionKind.REQUIRE_APPROVAL
            and requirements is None
        ) or (
            kind is not PolicyDecisionKind.REQUIRE_APPROVAL
            and requirements is not None
        ):
            raise PolicyError(
                PolicyErrorCode.INVALID,
                "approval requirements do not match the policy decision",
            )
        if not isinstance(value["agent"], Mapping) or not isinstance(
            value["action"], Mapping
        ):
            raise PolicyError(
                PolicyErrorCode.INVALID,
                "policy agent and action must be objects",
            )
        evaluated_at = _utc(value["evaluated_at"], "evaluated_at")
        expires_at = _utc(value["expires_at"], "expires_at")
        if expires_at <= evaluated_at:
            raise PolicyError(
                PolicyErrorCode.INVALID,
                "policy decision must expire after evaluation",
            )
        task_id = _text(value["task_id"], "task_id", 133)
        if _TASK_ID.fullmatch(task_id) is None:
            raise PolicyError(
                PolicyErrorCode.INVALID,
                "task_id is not a public v1 identifier",
            )
        return cls(
            decision_id=str(value["decision_id"]),
            tenant_id=_text(value["tenant_id"], "tenant_id"),
            task_id=task_id,
            subject_ref=_text(value["subject_ref"], "subject_ref", 512),
            subject_context_hash=_sha(
                value["subject_context_hash"], "subject_context_hash"
            ),
            agent=PolicyAgent.from_mapping(value["agent"]),
            action=PolicyAction.from_mapping(value["action"]),
            decision=kind,
            reason_codes=tuple(reasons),
            obligations=parsed_obligations,
            approval_requirements=requirements,
            policy_version=_text(value["policy_version"], "policy_version"),
            input_hash=_sha(value["input_hash"], "input_hash"),
            evaluated_at=evaluated_at,
            expires_at=expires_at,
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "tenant_id": self.tenant_id,
            "task_id": self.task_id,
            "subject_ref": self.subject_ref,
            "subject_context_hash": self.subject_context_hash,
            "agent": self.agent.to_mapping(),
            "action": self.action.to_mapping(),
            "decision": self.decision.value,
            "reason_codes": list(self.reason_codes),
            "obligations": [item.to_mapping() for item in self.obligations],
            "approval_requirements": (
                self.approval_requirements.to_mapping()
                if self.approval_requirements is not None
                else None
            ),
            "policy_version": self.policy_version,
            "input_canonicalization": self.input_canonicalization,
            "input_hash": self.input_hash,
            "evaluated_at": _format_utc(self.evaluated_at),
            "expires_at": _format_utc(self.expires_at),
        }


def _raise_invalid_obligation() -> PolicyObligation:
    raise PolicyError(
        PolicyErrorCode.INVALID,
        "obligation must be an object",
    )


@dataclass(frozen=True, slots=True)
class ResolvedPolicyDecision:
    decision: PolicyDecision
    input_preimage: Mapping[str, FrozenJson]

    @classmethod
    def create(
        cls,
        *,
        decision: PolicyDecision,
        input_preimage: Mapping[str, Any],
    ) -> ResolvedPolicyDecision:
        frozen = freeze_json(input_preimage, "policy_input_preimage")
        if not isinstance(frozen, Mapping):
            raise PolicyError(
                PolicyErrorCode.INVALID,
                "policy input preimage must be an object",
            )
        record = cls(decision=decision, input_preimage=frozen)
        record.assert_integrity()
        return record

    def assert_integrity(self) -> None:
        try:
            reparsed = PolicyDecision.from_mapping(self.decision.to_mapping())
        except (PolicyError, TypeError, ValueError) as exc:
            raise PolicyError(
                PolicyErrorCode.INVALID,
                "trusted policy record violates the public v1 contract",
            ) from exc
        if reparsed != self.decision:
            raise PolicyError(
                PolicyErrorCode.INVALID,
                "trusted policy record is not canonically represented",
            )
        if canonical_sha256(thaw_json(self.input_preimage)) != (
            self.decision.input_hash
        ):
            raise PolicyError(
                PolicyErrorCode.INPUT_HASH_MISMATCH,
                "trusted policy input hash does not match its preimage",
            )


class PolicyDecisionSource(Protocol):
    async def resolve(self, decision_id: str) -> ResolvedPolicyDecision: ...
