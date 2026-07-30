from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from flowpilot_security import CapabilityHandle


@dataclass(frozen=True, slots=True)
class ToolInvocationResult:
    data: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ReadbackResult:
    data: Mapping[str, Any]
    evidence_ref: str
    observed_ref: str
    matched: bool
    method: str = "read_back"


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


class Clock(Protocol):
    def __call__(self) -> datetime: ...
