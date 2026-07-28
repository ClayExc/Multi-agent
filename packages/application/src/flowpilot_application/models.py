from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from flowpilot_domain import TaskCommand

APPLICATION_PORT_VERSION = "flowpilot.application-ports.m0.v1"


class ExecutionDisposition(StrEnum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class ExecutionReceipt:
    command_id: str
    tenant_id: str
    task_id: str
    disposition: ExecutionDisposition
    execution_ref: str


@dataclass(frozen=True, slots=True)
class StoredCommand:
    command: TaskCommand
    accepted_at: datetime
    execution_receipt: ExecutionReceipt | None = None

    def __post_init__(self) -> None:
        if self.accepted_at.tzinfo is None or self.accepted_at.utcoffset() is None:
            raise ValueError("accepted_at must be timezone-aware")
        object.__setattr__(self, "accepted_at", self.accepted_at.astimezone(UTC))


@dataclass(frozen=True, slots=True)
class CommandAcceptance:
    command_id: str
    tenant_id: str
    task_id: str
    accepted_at: datetime
    replayed: bool
    execution_receipt: ExecutionReceipt
