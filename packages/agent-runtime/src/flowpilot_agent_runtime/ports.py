from __future__ import annotations

from typing import Protocol

from .models import AgentRunRequest, AgentRunResult


class AgentRuntimePort(Protocol):
    async def run(self, request: AgentRunRequest) -> AgentRunResult: ...
