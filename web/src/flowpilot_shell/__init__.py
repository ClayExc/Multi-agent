"""FlowPilot replaceable web shell (track C, first phase).

Boundaries (enforced by tests/experience/):
- reads Task/Command/Event v1 contracts through the API/SSE adapter only
- never persists business facts (in-memory per session)
- never issues approval write calls and never infers approval success
- never connects to PostgreSQL or MCP directly
- stdlib-only runtime so the shell stays replaceable and copy-portable
"""

from __future__ import annotations

from .models import (
    ApprovalView,
    CitationView,
    EventView,
    PlannedActionView,
    ResultArtifactView,
    ShellContractError,
    ShellError,
    ShellNotFoundError,
    ShellServerError,
    ShellUnavailableError,
    TaskErrorView,
    TaskView,
    WaitingOnView,
)

__all__ = [
    "ApprovalView",
    "CitationView",
    "EventView",
    "PlannedActionView",
    "ResultArtifactView",
    "ShellContractError",
    "ShellError",
    "ShellNotFoundError",
    "ShellServerError",
    "ShellUnavailableError",
    "TaskErrorView",
    "TaskView",
    "WaitingOnView",
]
