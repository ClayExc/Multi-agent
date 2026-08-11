from __future__ import annotations

from flowpilot_domain import SecurityContextRef
from flowpilot_graph import GraphError, GraphErrorCode


class MutableSecurityContextValidator:
    """Credential-free test port with explicit revocation and call tracking."""

    def __init__(self) -> None:
        self.active = True
        self.retryable = False
        self.calls: list[SecurityContextRef] = []
        self.fail_on_call: int | None = None

    async def validate_current(
        self,
        presented: SecurityContextRef,
    ) -> SecurityContextRef:
        self.calls.append(presented)
        if not self.active or (
            self.fail_on_call is not None
            and len(self.calls) >= self.fail_on_call
        ):
            raise GraphError(
                GraphErrorCode.SECURITY_BINDING_MISMATCH,
                "trusted security context is not current",
                retryable=self.retryable,
            )
        return presented


__all__ = ["MutableSecurityContextValidator"]
