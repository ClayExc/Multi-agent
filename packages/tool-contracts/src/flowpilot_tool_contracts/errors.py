from __future__ import annotations

from enum import StrEnum


class ToolContractErrorCode(StrEnum):
    CONTRACT_INVALID = "PLATFORM_TOOL_CONTRACT_INVALID"
    ACTION_DIGEST_MISMATCH = "PLATFORM_ACTION_DIGEST_MISMATCH"
    SCHEMA_INVALID = "PLATFORM_TOOL_SCHEMA_INVALID"
    SCHEMA_HASH_MISMATCH = "PLATFORM_TOOL_SCHEMA_HASH_MISMATCH"
    INPUT_INVALID = "PLATFORM_TOOL_INPUT_INVALID"
    OUTPUT_INVALID = "PLATFORM_TOOL_OUTPUT_INVALID"


class ToolContractError(ValueError):
    """Deterministic contract rejection with no raw payload in its message."""

    def __init__(self, code: ToolContractErrorCode, safe_message: str) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
