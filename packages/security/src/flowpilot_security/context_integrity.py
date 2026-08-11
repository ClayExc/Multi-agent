from __future__ import annotations

import hmac
from collections.abc import Iterable
from datetime import datetime

from flowpilot_domain import (
    ActorType,
    AuthenticationRef,
    DataClassification,
    canonical_sha256,
)

from .digests import require_sha256_digest
from .errors import SecurityError, SecurityErrorCode
from .models import TrustedSecurityContext, utc


def _timestamp(value: datetime, field: str) -> str:
    return utc(value, field).isoformat().replace("+00:00", "Z")


def trusted_context_snapshot_hash(
    *,
    context_id: str,
    context_ref: str,
    tenant_id: str,
    subject_id: str,
    subject_type: ActorType,
    issuer: str,
    authorized_party: str,
    roles: Iterable[str],
    scopes: Iterable[str],
    authentication: AuthenticationRef,
    purpose: str,
    data_classification_ceiling: DataClassification,
    issued_at: datetime,
    expires_at: datetime,
    source_token_hash: str,
) -> str:
    require_sha256_digest(source_token_hash, "context.source_token_hash")
    normalized_roles = sorted(frozenset(roles))
    normalized_scopes = sorted(frozenset(scopes))
    if not all(
        (
            context_id,
            context_ref,
            tenant_id,
            subject_id,
            issuer,
            authorized_party,
            purpose,
        )
    ):
        raise ValueError("trusted context snapshot fields must not be empty")
    return canonical_sha256(
        {
            "context_id": context_id,
            "context_ref": context_ref,
            "tenant_id": tenant_id,
            "subject_id": subject_id,
            "subject_type": subject_type.value,
            "issuer": issuer,
            "authorized_party": authorized_party,
            "roles": normalized_roles,
            "scopes": normalized_scopes,
            "authentication": authentication.to_mapping(),
            "purpose": purpose,
            "data_classification_ceiling": data_classification_ceiling.value,
            "issued_at": _timestamp(issued_at, "context.issued_at"),
            "expires_at": _timestamp(expires_at, "context.expires_at"),
            "source_token_hash": source_token_hash,
        }
    )


def verify_trusted_context_integrity(trusted: TrustedSecurityContext) -> None:
    try:
        issuer = trusted.issuer
        authorized_party = trusted.authorized_party
        token_hash = trusted.identity_token_hash
        if issuer is None or authorized_party is None or token_hash is None:
            raise ValueError("trusted context identity evidence is incomplete")
        context = trusted.context
        expected = trusted_context_snapshot_hash(
            context_id=context.context_id,
            context_ref=context.context_ref,
            tenant_id=context.tenant_id,
            subject_id=context.subject_id,
            subject_type=context.subject_type,
            issuer=issuer,
            authorized_party=authorized_party,
            roles=trusted.roles,
            scopes=trusted.scopes,
            authentication=context.authentication,
            purpose=context.purpose,
            data_classification_ceiling=context.data_classification_ceiling,
            issued_at=context.issued_at,
            expires_at=context.expires_at,
            source_token_hash=token_hash,
        )
    except (TypeError, ValueError):
        raise SecurityError(
            SecurityErrorCode.CONTEXT_UNTRUSTED,
            "trusted security context integrity evidence is invalid",
        ) from None
    if not hmac.compare_digest(expected, trusted.context.context_hash):
        raise SecurityError(
            SecurityErrorCode.CONTEXT_UNTRUSTED,
            "trusted security context authorization snapshot is invalid",
        )
