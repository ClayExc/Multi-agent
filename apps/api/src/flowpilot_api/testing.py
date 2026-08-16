from __future__ import annotations

from fastapi import Request
from flowpilot_domain import TaskCommand

from .errors import ApiError, ApiErrorCode
from .security import (
    GovernanceAccessPolicy,
    RequestSecurityPort,
    TrustedRequestIdentity,
)


class StaticRequestSecurity(RequestSecurityPort):
    def __init__(self, identity: TrustedRequestIdentity) -> None:
        self.identity = identity
        self.command_calls: list[TaskCommand] = []
        self.task_read_calls: list[str] = []
        self.event_stream_calls: list[str] = []
        self.governance_read_calls: list[str] = []
        self.failure: ApiError | None = None

    async def authenticate(self, _request: Request) -> TrustedRequestIdentity:
        if self.failure is not None:
            raise self.failure
        return self.identity

    async def authorize_command(
        self, _identity: TrustedRequestIdentity, command: TaskCommand
    ) -> None:
        if self.failure is not None:
            raise self.failure
        self.command_calls.append(command)

    async def authorize_task_read(
        self, _identity: TrustedRequestIdentity, task_id: str
    ) -> None:
        if self.failure is not None:
            raise self.failure
        self.task_read_calls.append(task_id)

    async def authorize_event_stream(self, identity: TrustedRequestIdentity) -> None:
        if self.failure is not None:
            raise self.failure
        self.event_stream_calls.append(identity.tenant_id)

    async def authorize_governance_read(
        self,
        identity: TrustedRequestIdentity,
        access: GovernanceAccessPolicy,
    ) -> None:
        if self.failure is not None:
            raise self.failure
        if (
            identity.purpose not in access.allowed_purposes
            or not identity.roles.intersection(access.allowed_roles)
        ):
            raise ApiError(
                ApiErrorCode.AUTHORIZATION_DENIED,
                "trusted identity is not authorized for governance reads",
                status_code=403,
            )
        self.governance_read_calls.append(identity.tenant_id)
