from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from .errors import DomainErrorCode, DomainViolation
from .primitives import (
    ensure_utc,
    format_utc,
    require_exact_keys,
    require_identifier,
    require_sha256,
    require_text,
)


class ActorType(StrEnum):
    USER = "user"
    SERVICE = "service"
    ADMINISTRATOR = "administrator"


class AuthenticationMethod(StrEnum):
    OIDC = "oidc"
    WORKLOAD_IDENTITY = "workload_identity"
    BREAK_GLASS = "break_glass"


class AssuranceLevel(StrEnum):
    LOW = "low"
    SUBSTANTIAL = "substantial"
    HIGH = "high"


class DataClassification(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


@dataclass(frozen=True, slots=True)
class AuthenticationRef:
    method: AuthenticationMethod
    assurance_level: AssuranceLevel
    session_id_hash: str | None = None

    def __post_init__(self) -> None:
        if self.session_id_hash is not None:
            require_sha256(self.session_id_hash, "authentication.session_id_hash")

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> AuthenticationRef:
        require_exact_keys(
            value,
            required={"method", "assurance_level"},
            optional={"session_id_hash"},
            field="authentication",
        )
        try:
            return cls(
                method=AuthenticationMethod(value["method"]),
                assurance_level=AssuranceLevel(value["assurance_level"]),
                session_id_hash=value.get("session_id_hash"),
            )
        except ValueError as exc:
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "authentication enum is not part of the v1 contract",
            ) from exc

    def to_mapping(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "method": self.method.value,
            "assurance_level": self.assurance_level.value,
        }
        if self.session_id_hash is not None:
            result["session_id_hash"] = self.session_id_hash
        return result


@dataclass(frozen=True, slots=True)
class SecurityContextRef:
    context_id: str
    context_ref: str
    context_hash: str
    tenant_id: str
    subject_id: str
    subject_type: ActorType
    purpose: str
    authentication: AuthenticationRef
    data_classification_ceiling: DataClassification
    issued_at: datetime
    expires_at: datetime
    delegation_id: str | None = None

    def __post_init__(self) -> None:
        require_identifier(
            self.context_id,
            "security_context.context_id",
            r"^secctx_[A-Za-z0-9_-]{8,128}$",
        )
        require_text(self.context_ref, "security_context.context_ref", maximum=512)
        require_sha256(self.context_hash, "security_context.context_hash")
        require_text(self.tenant_id, "security_context.tenant_id", maximum=128)
        require_text(self.subject_id, "security_context.subject_id", maximum=256)
        require_text(self.purpose, "security_context.purpose", maximum=256)
        if self.delegation_id is not None and len(self.delegation_id) > 256:
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "security_context.delegation_id exceeds 256 characters",
            )
        issued_at = ensure_utc(self.issued_at, "security_context.issued_at")
        expires_at = ensure_utc(self.expires_at, "security_context.expires_at")
        if expires_at <= issued_at:
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "security context must expire after it is issued",
            )
        object.__setattr__(self, "issued_at", issued_at)
        object.__setattr__(self, "expires_at", expires_at)

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> SecurityContextRef:
        require_exact_keys(
            value,
            required={
                "context_id",
                "context_ref",
                "context_hash",
                "tenant_id",
                "subject_id",
                "subject_type",
                "purpose",
                "authentication",
                "data_classification_ceiling",
                "issued_at",
                "expires_at",
            },
            optional={"delegation_id"},
            field="security_context",
        )
        authentication = value["authentication"]
        if not isinstance(authentication, dict):
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "authentication must be an object",
            )
        try:
            return cls(
                context_id=value["context_id"],
                context_ref=value["context_ref"],
                context_hash=value["context_hash"],
                tenant_id=value["tenant_id"],
                subject_id=value["subject_id"],
                subject_type=ActorType(value["subject_type"]),
                purpose=value["purpose"],
                authentication=AuthenticationRef.from_mapping(authentication),
                delegation_id=value.get("delegation_id"),
                data_classification_ceiling=DataClassification(
                    value["data_classification_ceiling"]
                ),
                issued_at=ensure_utc(value["issued_at"], "security_context.issued_at"),
                expires_at=ensure_utc(
                    value["expires_at"], "security_context.expires_at"
                ),
            )
        except ValueError as exc:
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "security context enum is not part of the v1 contract",
            ) from exc

    def to_mapping(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "context_id": self.context_id,
            "context_ref": self.context_ref,
            "context_hash": self.context_hash,
            "tenant_id": self.tenant_id,
            "subject_id": self.subject_id,
            "subject_type": self.subject_type.value,
            "purpose": self.purpose,
            "authentication": self.authentication.to_mapping(),
            "data_classification_ceiling": self.data_classification_ceiling.value,
            "issued_at": format_utc(self.issued_at),
            "expires_at": format_utc(self.expires_at),
        }
        if self.delegation_id is not None:
            result["delegation_id"] = self.delegation_id
        return result


@dataclass(frozen=True, slots=True)
class CommandActor:
    type: ActorType
    id: str

    def __post_init__(self) -> None:
        require_text(self.id, "actor.id", maximum=256)

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> CommandActor:
        require_exact_keys(
            value,
            required={"type", "id"},
            optional=set(),
            field="actor",
        )
        try:
            return cls(type=ActorType(value["type"]), id=value["id"])
        except ValueError as exc:
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "actor type is not part of the v1 contract",
            ) from exc

    def to_mapping(self) -> dict[str, str]:
        return {"type": self.type.value, "id": self.id}
