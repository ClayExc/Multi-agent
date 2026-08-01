"""TaskCommand v1 draft builders for the shell's user actions.

The shell only builds non-approval commands:
- task.message.submit.v1 (info completion form)
- task.retry.request.v1 (retry entry on the error panel)

Digest semantics match the v1 contract description (RFC 8785 + SHA-256 over
command_type/tenant_id/task_id/actor/expected_task_version/payload) and are
bit-compatible with flowpilot_domain.canonical.canonical_sha256 (verified by
tests/experience). No approval command builder exists by design.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from .canonical import canonical_digest


def build_submit_message_command(
    *,
    tenant_id: str,
    task_id: str,
    actor: Mapping[str, str],
    security_context: Mapping[str, Any],
    expected_task_version: int,
    message_id: str,
    message_ref: str,
    attachment_refs: list[str] | None = None,
    issued_at: datetime | None = None,
    command_id: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    payload = {
        "message_id": message_id,
        "message_ref": message_ref,
        "attachment_refs": attachment_refs or [],
    }
    return _finish(
        command_type="task.message.submit.v1",
        tenant_id=tenant_id,
        task_id=task_id,
        actor=actor,
        security_context=security_context,
        expected_task_version=expected_task_version,
        payload=payload,
        issued_at=issued_at,
        command_id=command_id,
        correlation_id=correlation_id,
    )


def build_retry_command(
    *,
    tenant_id: str,
    task_id: str,
    actor: Mapping[str, str],
    security_context: Mapping[str, Any],
    expected_task_version: int,
    failed_run_id: str,
    reason: str | None = None,
    issued_at: datetime | None = None,
    command_id: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    payload = {"failed_run_id": failed_run_id}
    if reason:
        payload["reason"] = reason
    return _finish(
        command_type="task.retry.request.v1",
        tenant_id=tenant_id,
        task_id=task_id,
        actor=actor,
        security_context=security_context,
        expected_task_version=expected_task_version,
        payload=payload,
        issued_at=issued_at,
        command_id=command_id,
        correlation_id=correlation_id,
    )


def _finish(
    *,
    command_type: str,
    tenant_id: str,
    task_id: str,
    actor: Mapping[str, str],
    security_context: Mapping[str, Any],
    expected_task_version: int | None,
    payload: dict[str, Any],
    issued_at: datetime | None,
    command_id: str | None,
    correlation_id: str | None,
) -> dict[str, Any]:
    digest_projection = {
        "command_type": command_type,
        "tenant_id": tenant_id,
        "task_id": task_id,
        "actor": dict(actor),
        "expected_task_version": expected_task_version,
        "payload": payload,
    }
    idempotency_projection = {
        "command_type": command_type,
        "tenant_id": tenant_id,
        "task_id": task_id,
        "payload": payload,
    }
    return {
        "command_id": command_id or f"cmd_{uuid.uuid4().hex[:20]}",
        "command_type": command_type,
        "tenant_id": tenant_id,
        "task_id": task_id,
        "actor": dict(actor),
        "security_context": dict(security_context),
        "expected_task_version": expected_task_version,
        "idempotency_key": canonical_digest(idempotency_projection),
        "command_digest": canonical_digest(digest_projection),
        "correlation_id": correlation_id,
        "payload": payload,
        "issued_at": (issued_at or datetime.now(UTC))
        .isoformat()
        .replace("+00:00", "Z"),
    }
