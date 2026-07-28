from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from .canonical import canonical_sha256
from .errors import DomainErrorCode, DomainViolation
from .primitives import (
    FrozenJson,
    ensure_utc,
    format_utc,
    freeze_json,
    require_exact_keys,
    require_identifier,
    require_sha256,
    require_text,
    thaw_json,
)
from .security import DataClassification


class ToolOperation(StrEnum):
    READ = "read"
    WRITE = "write"


@dataclass(frozen=True, slots=True)
class ActionAgent:
    id: str
    version: str

    def __post_init__(self) -> None:
        require_text(self.id, "agent.id", maximum=128)
        require_text(self.version, "agent.version", maximum=128)

    def to_mapping(self) -> dict[str, str]:
        return {"id": self.id, "version": self.version}


@dataclass(frozen=True, slots=True)
class ActionTool:
    name: str
    schema_hash: str
    operation: ToolOperation

    def __post_init__(self) -> None:
        if re.fullmatch(
            r"^[a-z0-9]+(?:[._-][a-z0-9]+)*\.v[1-9][0-9]*$", self.name
        ) is None:
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "tool.name is not a versioned v1 tool identifier",
            )
        require_sha256(self.schema_hash, "tool.schema_hash")

    def to_mapping(self) -> dict[str, str]:
        return {
            "name": self.name,
            "schema_hash": self.schema_hash,
            "operation": self.operation.value,
        }


@dataclass(frozen=True, slots=True)
class ActionResource:
    type: str
    id: str | None = None
    owner_id: str | None = None

    def __post_init__(self) -> None:
        require_text(self.type, "resource.type", maximum=128)
        for field, value in (
            ("resource.id", self.id),
            ("resource.owner_id", self.owner_id),
        ):
            if value is not None and len(value) > 256:
                raise DomainViolation(
                    DomainErrorCode.CONTRACT_VIOLATION,
                    f"{field} exceeds 256 characters",
                )

    def to_mapping(self) -> dict[str, str | None]:
        result: dict[str, str | None] = {"type": self.type}
        if self.id is not None:
            result["id"] = self.id
        if self.owner_id is not None:
            result["owner_id"] = self.owner_id
        return result


@dataclass(frozen=True, slots=True)
class PlannedAction:
    action_id: str
    tenant_id: str
    task_id: str
    requester_id: str
    agent: ActionAgent
    tool: ActionTool
    arguments: Mapping[str, FrozenJson]
    resource: ActionResource
    purpose: str
    data_classification: DataClassification
    policy_version: str
    expires_at: datetime

    def __post_init__(self) -> None:
        require_identifier(
            self.action_id, "action_id", r"^act_[A-Za-z0-9_-]{8,128}$"
        )
        require_text(self.tenant_id, "tenant_id", maximum=128)
        require_identifier(
            self.task_id, "task_id", r"^task_[A-Za-z0-9_-]{8,128}$"
        )
        require_text(self.requester_id, "requester_id", maximum=256)
        require_text(self.purpose, "purpose", maximum=256)
        require_text(self.policy_version, "policy_version", maximum=128)
        frozen_arguments = freeze_json(self.arguments, "arguments")
        if not isinstance(frozen_arguments, Mapping):
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "arguments must be a JSON object",
            )
        object.__setattr__(self, "arguments", frozen_arguments)
        object.__setattr__(
            self, "expires_at", ensure_utc(self.expires_at, "expires_at")
        )

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> PlannedAction:
        require_exact_keys(
            value,
            required={
                "action_id",
                "tenant_id",
                "task_id",
                "requester_id",
                "agent",
                "tool",
                "arguments",
                "resource",
                "purpose",
                "data_classification",
                "policy_version",
                "expires_at",
            },
            optional=set(),
            field="planned_action",
        )
        for field in ("agent", "tool", "arguments", "resource"):
            if not isinstance(value[field], dict):
                raise DomainViolation(
                    DomainErrorCode.CONTRACT_VIOLATION,
                    f"{field} must be an object",
                )
        require_exact_keys(
            value["agent"],
            required={"id", "version"},
            optional=set(),
            field="agent",
        )
        require_exact_keys(
            value["tool"],
            required={"name", "schema_hash", "operation"},
            optional=set(),
            field="tool",
        )
        require_exact_keys(
            value["resource"],
            required={"type"},
            optional={"id", "owner_id"},
            field="resource",
        )
        try:
            operation = ToolOperation(value["tool"]["operation"])
            classification = DataClassification(value["data_classification"])
        except ValueError as exc:
            raise DomainViolation(
                DomainErrorCode.CONTRACT_VIOLATION,
                "planned action enum is not part of the v1 contract",
            ) from exc
        return cls(
            action_id=value["action_id"],
            tenant_id=value["tenant_id"],
            task_id=value["task_id"],
            requester_id=value["requester_id"],
            agent=ActionAgent(**value["agent"]),
            tool=ActionTool(
                name=value["tool"]["name"],
                schema_hash=value["tool"]["schema_hash"],
                operation=operation,
            ),
            arguments=value["arguments"],
            resource=ActionResource(**value["resource"]),
            purpose=value["purpose"],
            data_classification=classification,
            policy_version=value["policy_version"],
            expires_at=ensure_utc(value["expires_at"], "expires_at"),
        )

    def to_mapping(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "tenant_id": self.tenant_id,
            "task_id": self.task_id,
            "requester_id": self.requester_id,
            "agent": self.agent.to_mapping(),
            "tool": self.tool.to_mapping(),
            "arguments": thaw_json(self.arguments),
            "resource": self.resource.to_mapping(),
            "purpose": self.purpose,
            "data_classification": self.data_classification.value,
            "policy_version": self.policy_version,
            "expires_at": format_utc(self.expires_at),
        }

    def digest(self) -> str:
        return canonical_sha256(self.to_mapping())
