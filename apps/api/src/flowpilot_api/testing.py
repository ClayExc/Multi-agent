from __future__ import annotations

from fastapi import Request
from flowpilot_domain import TaskCommand

from .errors import ApiError
from .security import RequestSecurityPort, TrustedRequestIdentity


class StaticRequestSecurity(RequestSecurityPort):
    def __init__(self, identity: TrustedRequestIdentity) -> None:
        self.identity = identity
        self.command_calls: list[TaskCommand] = []
        self.task_read_calls: list[str] = []
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
