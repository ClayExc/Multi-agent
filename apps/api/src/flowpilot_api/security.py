from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from fastapi import Request
from flowpilot_domain import ActorType, TaskCommand


@dataclass(frozen=True, slots=True)
class TrustedRequestIdentity:
    tenant_id: str
    subject_id: str
    subject_type: ActorType
    purpose: str
    security_context_id: str
    security_context_ref: str
    security_context_hash: str


class RequestSecurityPort(Protocol):
    """Authentication/authorization boundary supplied by the API composition."""

    async def authenticate(self, request: Request) -> TrustedRequestIdentity: ...

    async def authorize_command(
        self, identity: TrustedRequestIdentity, command: TaskCommand
    ) -> None: ...

    async def authorize_task_read(
        self, identity: TrustedRequestIdentity, task_id: str
    ) -> None: ...

    async def authorize_event_stream(
        self, identity: TrustedRequestIdentity
    ) -> None:
        """Authorize a tenant-scoped subscription to the task event stream."""
