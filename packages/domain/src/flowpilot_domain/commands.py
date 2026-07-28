from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from .canonical import canonical_sha256
from .errors import DomainErrorCode, DomainViolation
from .primitives import (
    MAX_SAFE_INTEGER,
    FrozenJson,
    ensure_utc,
    freeze_json,
    require_exact_keys,
    require_identifier,
    require_sha256,
    require_text,
    thaw_json,
)
from .security import CommandActor, SecurityContextRef


class CommandType(StrEnum):
    CREATE = "task.create.v1"
    SUBMIT_MESSAGE = "task.message.submit.v1"
    DECIDE_APPROVAL = "task.approval.decide.v1"
    REQUEST_CANCEL = "task.cancel.request.v1"
    REQUEST_RETRY = "task.retry.request.v1"


_PAYLOAD_FIELDS: dict[CommandType, tuple[set[str], set[str]]] = {
    CommandType.CREATE: (
        {"initial_message_id", "initial_message_ref", "channel", "purpose"},
        {"attachment_refs"},
    ),
    CommandType.SUBMIT_MESSAGE: (
        {"message_id", "message_ref"},
        {"attachment_refs"},
    ),
    CommandType.DECIDE_APPROVAL: (
        {"approval_id", "action_digest", "decision"},
        {"reason"},
    ),
    CommandType.REQUEST_CANCEL: (set(), {"reason"}),
    CommandType.REQUEST_RETRY: ({"failed_run_id"}, {"reason"}),
}


@dataclass(frozen=True, slots=True)
class TaskCommand:
    command_id: str
    command_type: CommandType
    tenant_id: str
    task_id: str
    actor: CommandActor
    security_context: SecurityContextRef
    expected_task_version: int | None
    idempotency_key: str
    command_digest: str
    payload: Mapping[str, FrozenJson]
    issued_at: datetime
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        require_identifier(
            self.command_id,
            "command_id",
            r"^cmd_[A-Za-z0-9_-]{8,128}$",
        )
        require_text(self.tenant_id, "tenant_id", maximum=128)
        require_identifier(
            self.task_id,
            "task_id",
            r"^task_[A-Za-z0-9_-]{8,128}$",
        )
        require_sha256(self.idempotency_key, "idempotency_key")
        require_sha256(self.command_digest, "command_digest")
        if self.correlation_id is not None and len(self.correlation_id) > 128:
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "correlation_id exceeds 128 characters",
            )
        issued_at = ensure_utc(self.issued_at, "issued_at")
        object.__setattr__(self, "issued_at", issued_at)
        frozen_payload = freeze_json(self.payload, "payload")
        if not isinstance(frozen_payload, Mapping):
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "payload must be a JSON object",
            )
        object.__setattr__(self, "payload", frozen_payload)
        self._validate_version()
        self._validate_payload()

    def _validate_version(self) -> None:
        if self.command_type is CommandType.CREATE:
            if self.expected_task_version is not None:
                raise DomainViolation(
                    DomainErrorCode.CONTRACT_VIOLATION,
                    "create commands require expected_task_version=null",
                )
            return
        if (
            isinstance(self.expected_task_version, bool)
            or not isinstance(self.expected_task_version, int)
            or
            self.expected_task_version is None
            or self.expected_task_version < 0
            or self.expected_task_version > MAX_SAFE_INTEGER
        ):
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "non-create commands require a safe non-negative task version",
            )

    def _validate_payload(self) -> None:
        required, optional = _PAYLOAD_FIELDS[self.command_type]
        require_exact_keys(
            self.payload,
            required=required,
            optional=optional,
            field="payload",
        )
        payload = thaw_json(self.payload)
        if not isinstance(payload, dict):
            raise AssertionError("payload was frozen from an object")
        if self.command_type is CommandType.CREATE:
            require_identifier(
                payload["initial_message_id"],
                "payload.initial_message_id",
                r"^msg_[A-Za-z0-9_-]{8,128}$",
            )
            require_text(
                payload["initial_message_ref"],
                "payload.initial_message_ref",
                maximum=512,
            )
            if payload["channel"] not in {"web", "api", "service_desk"}:
                raise DomainViolation(
                    DomainErrorCode.CONTRACT_VIOLATION,
                    "payload.channel is not part of the v1 contract",
                )
            require_text(payload["purpose"], "payload.purpose", maximum=256)
        elif self.command_type is CommandType.SUBMIT_MESSAGE:
            require_identifier(
                payload["message_id"],
                "payload.message_id",
                r"^msg_[A-Za-z0-9_-]{8,128}$",
            )
            require_text(
                payload["message_ref"],
                "payload.message_ref",
                maximum=512,
            )
        elif self.command_type is CommandType.DECIDE_APPROVAL:
            require_identifier(
                payload["approval_id"],
                "payload.approval_id",
                r"^apr_[A-Za-z0-9_-]{8,128}$",
            )
            require_sha256(payload["action_digest"], "payload.action_digest")
            if payload["decision"] not in {"approve", "reject"}:
                raise DomainViolation(
                    DomainErrorCode.CONTRACT_VIOLATION,
                    "payload.decision is not part of the v1 contract",
                )
        elif self.command_type is CommandType.REQUEST_RETRY:
            require_identifier(
                payload["failed_run_id"],
                "payload.failed_run_id",
                r"^run_[A-Za-z0-9_-]{8,128}$",
            )
        attachments = payload.get("attachment_refs", [])
        if not isinstance(attachments, list) or len(attachments) != len(
            set(attachments)
        ):
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "payload.attachment_refs must contain unique references",
            )
        for attachment in attachments:
            require_text(attachment, "payload.attachment_refs", maximum=512)
        reason = payload.get("reason")
        if reason is not None and (
            not isinstance(reason, str) or len(reason) > 2000
        ):
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "payload.reason exceeds the v1 contract",
            )

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> TaskCommand:
        require_exact_keys(
            value,
            required={
                "command_id",
                "command_type",
                "tenant_id",
                "task_id",
                "actor",
                "security_context",
                "expected_task_version",
                "idempotency_key",
                "command_digest",
                "payload",
                "issued_at",
            },
            optional={"correlation_id"},
            field="task_command",
        )
        try:
            command_type = CommandType(value["command_type"])
        except ValueError as exc:
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "command_type is not part of the v1 contract",
            ) from exc
        payload = value["payload"]
        if not isinstance(payload, dict):
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "payload must be a JSON object",
            )
        actor = value["actor"]
        security_context = value["security_context"]
        if not isinstance(actor, dict) or not isinstance(security_context, dict):
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "actor and security_context must be objects",
            )
        return cls(
            command_id=value["command_id"],
            command_type=command_type,
            tenant_id=value["tenant_id"],
            task_id=value["task_id"],
            actor=CommandActor.from_mapping(actor),
            security_context=SecurityContextRef.from_mapping(security_context),
            expected_task_version=value["expected_task_version"],
            idempotency_key=value["idempotency_key"],
            command_digest=value["command_digest"],
            correlation_id=value.get("correlation_id"),
            payload=payload,
            issued_at=ensure_utc(value["issued_at"], "issued_at"),
        )

    def digest_projection(self) -> dict[str, Any]:
        return {
            "command_type": self.command_type.value,
            "tenant_id": self.tenant_id,
            "task_id": self.task_id,
            "actor": self.actor.to_mapping(),
            "expected_task_version": self.expected_task_version,
            "payload": thaw_json(self.payload),
        }

    def recompute_digest(self) -> str:
        return canonical_sha256(self.digest_projection())

    def assert_digest(self) -> None:
        if self.command_digest != self.recompute_digest():
            raise DomainViolation(
                DomainErrorCode.DIGEST_MISMATCH,
                "command_digest does not match the contract projection",
            )

    def assert_security_binding(self) -> None:
        context = self.security_context
        if (
            self.tenant_id != context.tenant_id
            or self.actor.id != context.subject_id
            or self.actor.type is not context.subject_type
        ):
            raise DomainViolation(
                DomainErrorCode.SECURITY_BINDING_MISMATCH,
                "command identity does not match the trusted security context",
            )
        if (
            self.command_type is CommandType.CREATE
            and self.payload["purpose"] != context.purpose
        ):
            raise DomainViolation(
                DomainErrorCode.SECURITY_BINDING_MISMATCH,
                "command purpose does not match the trusted security context",
            )
