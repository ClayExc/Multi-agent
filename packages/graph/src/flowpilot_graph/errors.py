from __future__ import annotations

from enum import StrEnum


class GraphErrorCode(StrEnum):
    STATE_INVALID = "GRAPH_STATE_INVALID"
    CHECKPOINT_CONFLICT = "GRAPH_CHECKPOINT_CONFLICT"
    CHECKPOINT_UNAVAILABLE = "GRAPH_CHECKPOINT_UNAVAILABLE"
    LEASE_CONFLICT = "GRAPH_LEASE_CONFLICT"
    LEASE_LOST = "GRAPH_LEASE_LOST"
    VERSION_MIGRATION_REQUIRED = "GRAPH_VERSION_MIGRATION_REQUIRED"
    COMMAND_MISMATCH = "GRAPH_COMMAND_MISMATCH"
    COMMAND_UNSUPPORTED = "GRAPH_COMMAND_UNSUPPORTED"
    SECURITY_BINDING_MISMATCH = "GRAPH_SECURITY_BINDING_MISMATCH"
    PARALLEL_REDUCER_CONFLICT = "GRAPH_PARALLEL_REDUCER_CONFLICT"


class GraphError(RuntimeError):
    def __init__(
        self,
        code: GraphErrorCode,
        safe_message: str,
        *,
        retryable: bool = False,
    ) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.retryable = retryable
