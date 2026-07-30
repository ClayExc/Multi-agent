from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from flowpilot_domain import SecurityContextRef


def utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class TrustedSecurityContext:
    context: SecurityContextRef
    active: bool
    roles: frozenset[str]


class SecurityContextSource(Protocol):
    async def resolve(self, context_ref: str) -> TrustedSecurityContext: ...


@dataclass(frozen=True, slots=True)
class AuthenticatedWorkload:
    agent_id: str
    agent_version: str
    principal_ref: str
    audience: str
    tenant_ids: frozenset[str]
    purposes: frozenset[str]
    allowed_tools: frozenset[str]
    issued_at: datetime
    expires_at: datetime
    attested: bool = True

    def __post_init__(self) -> None:
        for field, value in (
            ("agent_id", self.agent_id),
            ("agent_version", self.agent_version),
            ("principal_ref", self.principal_ref),
            ("audience", self.audience),
        ):
            if not value:
                raise ValueError(f"{field} cannot be empty")
        issued = utc(self.issued_at, "workload.issued_at")
        expires = utc(self.expires_at, "workload.expires_at")
        if expires <= issued:
            raise ValueError("workload identity must expire after issuance")
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "expires_at", expires)


@dataclass(frozen=True, slots=True)
class CapabilityHandle:
    handle_ref: str
    audience: str
    scopes: frozenset[str]
    tenant_id: str
    action_digest: str
    issued_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if not self.handle_ref.startswith("capability://"):
            raise ValueError("capability handle must be opaque")
        issued = utc(self.issued_at, "capability.issued_at")
        expires = utc(self.expires_at, "capability.expires_at")
        if expires <= issued:
            raise ValueError("capability must expire after issuance")
        object.__setattr__(self, "issued_at", issued)
        object.__setattr__(self, "expires_at", expires)


class CredentialBrokerPort(Protocol):
    async def issue(
        self,
        *,
        tenant_id: str,
        audience: str,
        scopes: frozenset[str],
        action_digest: str,
        ttl_seconds: int,
        now: datetime,
    ) -> CapabilityHandle: ...
