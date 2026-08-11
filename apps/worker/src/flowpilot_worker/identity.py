from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from flowpilot_domain import SecurityContextRef
from flowpilot_graph import GraphError, GraphErrorCode
from flowpilot_security import (
    SecurityContextSource,
    SecurityError,
    SecurityErrorCode,
    SecurityVerifier,
)


class RuntimeSecurityContextValidator:
    """Re-resolve revocable identity state without retaining source tokens."""

    def __init__(
        self,
        *,
        contexts: SecurityContextSource,
        verifier: SecurityVerifier,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._contexts = contexts
        self._verifier = verifier
        self._clock = clock or (lambda: datetime.now(UTC))

    async def validate_current(
        self,
        presented: SecurityContextRef,
    ) -> SecurityContextRef:
        try:
            trusted = await self._contexts.resolve(presented.context_ref)
            return self._verifier.verify_context(
                presented=presented,
                trusted=trusted,
                now=self._now(),
            )
        except SecurityError as exc:
            retryable = exc.code in {
                SecurityErrorCode.CONTEXT_UNAVAILABLE,
                SecurityErrorCode.IDENTITY_SOURCE_UNAVAILABLE,
            }
            raise GraphError(
                GraphErrorCode.SECURITY_BINDING_MISMATCH,
                (
                    "trusted security context is temporarily unavailable"
                    if retryable
                    else "trusted security context is not current"
                ),
                retryable=retryable,
            ) from None
        except Exception:
            raise GraphError(
                GraphErrorCode.SECURITY_BINDING_MISMATCH,
                "trusted security context is temporarily unavailable",
                retryable=True,
            ) from None

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("runtime identity clock must be timezone-aware")
        return value.astimezone(UTC)


__all__ = ["RuntimeSecurityContextValidator"]
