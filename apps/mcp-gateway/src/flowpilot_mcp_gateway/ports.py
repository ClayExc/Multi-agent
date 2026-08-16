from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

from flowpilot_security import CapabilityHandle, SecretLease


@dataclass(frozen=True, slots=True)
class ToolInvocationResult:
    data: Mapping[str, Any]
    content: Mapping[str, Any] | None = None

    def safety_projection(self) -> dict[str, Any]:
        return {
            "data": dict(self.data),
            "content": dict(self.content) if self.content is not None else None,
        }


@dataclass(frozen=True, slots=True)
class ReadbackResult:
    data: Mapping[str, Any]
    evidence_ref: str
    observed_ref: str
    matched: bool
    method: str = "read_back"

    def safety_projection(self) -> dict[str, Any]:
        return {
            "data": dict(self.data),
            "evidence_ref": self.evidence_ref,
            "observed_ref": self.observed_ref,
            "matched": self.matched,
            "method": self.method,
        }


class ReconciliationDisposition(StrEnum):
    VERIFIED = "verified"
    CONFIRMED_NOT_EXECUTED = "confirmed_not_executed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    disposition: ReconciliationDisposition
    data: Mapping[str, Any] | None
    evidence_ref: str | None
    observed_ref: str | None
    method: str

    def safety_projection(self) -> dict[str, Any]:
        return {
            "disposition": self.disposition.value,
            "data": dict(self.data) if self.data is not None else None,
            "evidence_ref": self.evidence_ref,
            "observed_ref": self.observed_ref,
            "method": self.method,
        }


class ToolAdapter(Protocol):
    async def invoke(
        self,
        *,
        arguments: Mapping[str, Any],
        capability: CapabilityHandle,
        idempotency_key: str,
    ) -> ToolInvocationResult: ...

    async def readback(
        self,
        *,
        arguments: Mapping[str, Any],
        invocation: ToolInvocationResult,
        capability: CapabilityHandle,
        idempotency_key: str,
    ) -> ReadbackResult: ...

    async def reconcile(
        self,
        *,
        arguments: Mapping[str, Any],
        capability: CapabilityHandle,
        idempotency_key: str,
    ) -> ReconciliationResult: ...


@runtime_checkable
class SecretAwareToolAdapter(Protocol):
    async def invoke_with_secret(
        self,
        *,
        arguments: Mapping[str, Any],
        capability: CapabilityHandle,
        idempotency_key: str,
        secret: SecretLease,
    ) -> ToolInvocationResult: ...

    async def readback_with_secret(
        self,
        *,
        arguments: Mapping[str, Any],
        invocation: ToolInvocationResult,
        capability: CapabilityHandle,
        idempotency_key: str,
        secret: SecretLease,
    ) -> ReadbackResult: ...

    async def reconcile_with_secret(
        self,
        *,
        arguments: Mapping[str, Any],
        capability: CapabilityHandle,
        idempotency_key: str,
        secret: SecretLease,
    ) -> ReconciliationResult: ...


class Clock(Protocol):
    def __call__(self) -> datetime: ...
