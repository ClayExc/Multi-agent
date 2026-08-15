from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from flowpilot_domain import (
    DataClassification,
    PlannedAction,
    SecurityContextRef,
    canonical_sha256,
)
from flowpilot_tool_contracts import (
    AgentPrincipal,
    FrozenJson,
    freeze_json,
    thaw_json,
)

from .errors import PolicyError, PolicyErrorCode
from .models import (
    PolicyDecision,
    PolicyDecisionKind,
    ResolvedPolicyDecision,
)

_VERSION = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,127})$")
_SHA256 = re.compile(r"^sha256:[a-f0-9]{64}$")
_MODULE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./-]{0,255}\.rego$")
_RISK_LEVELS = frozenset({"low", "medium", "high", "critical"})
_CLASSIFICATION_RANK = {
    DataClassification.PUBLIC: 0,
    DataClassification.INTERNAL: 1,
    DataClassification.CONFIDENTIAL: 2,
    DataClassification.RESTRICTED: 3,
}


def _utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PolicyError(
            PolicyErrorCode.INVALID,
            f"{field} must be timezone-aware",
        )
    return value.astimezone(UTC)


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _version(value: str, field: str) -> str:
    if _VERSION.fullmatch(value) is None:
        raise PolicyError(
            PolicyErrorCode.INVALID,
            f"{field} is not a valid policy version",
        )
    return value


def _sha256(value: str, field: str) -> str:
    if _SHA256.fullmatch(value) is None:
        raise PolicyError(
            PolicyErrorCode.INVALID,
            f"{field} must be a lowercase sha256 digest",
        )
    return value


@dataclass(frozen=True, slots=True)
class PolicyBundle:
    """Immutable Rego bundle whose digest covers code and data, not release state."""

    version: str
    digest: str
    modules: tuple[tuple[str, str], ...]
    data: Mapping[str, FrozenJson]

    @classmethod
    def create(
        cls,
        *,
        version: str,
        modules: Mapping[str, str],
        data: Mapping[str, Any],
    ) -> PolicyBundle:
        _version(version, "bundle.version")
        if not modules:
            raise PolicyError(
                PolicyErrorCode.INVALID,
                "policy bundle must contain at least one Rego module",
            )
        normalized_modules: list[tuple[str, str]] = []
        for name, source in sorted(modules.items()):
            if _MODULE_NAME.fullmatch(name) is None:
                raise PolicyError(
                    PolicyErrorCode.INVALID,
                    "policy bundle contains an invalid Rego module name",
                )
            if not isinstance(source, str) or not source.strip():
                raise PolicyError(
                    PolicyErrorCode.INVALID,
                    "policy bundle contains an empty Rego module",
                )
            normalized_modules.append((name, source))
        frozen_data = freeze_json(data, "policy_bundle.data")
        if not isinstance(frozen_data, Mapping):
            raise PolicyError(
                PolicyErrorCode.INVALID,
                "policy bundle data must be an object",
            )
        preimage = {
            "format": "flowpilot.rego-bundle.v1",
            "modules": dict(normalized_modules),
            "data": thaw_json(frozen_data),
        }
        return cls(
            version=version,
            digest=canonical_sha256(preimage),
            modules=tuple(normalized_modules),
            data=frozen_data,
        )

    def assert_integrity(self) -> None:
        thawed_data = thaw_json(self.data)
        if not isinstance(thawed_data, Mapping):
            raise PolicyError(
                PolicyErrorCode.BUNDLE_UNTRUSTED,
                "policy bundle data is not an object",
            )
        rebuilt = PolicyBundle.create(
            version=self.version,
            modules=dict(self.modules),
            data=thawed_data,
        )
        if rebuilt != self:
            raise PolicyError(
                PolicyErrorCode.BUNDLE_UNTRUSTED,
                "policy bundle digest does not match its content",
            )

    def with_version(self, version: str) -> PolicyBundle:
        return replace(self, version=_version(version, "bundle.version"))


@dataclass(frozen=True, slots=True)
class VerifiedPolicyBundle:
    bundle: PolicyBundle
    verifier_id: str
    verified_at: datetime

    def __post_init__(self) -> None:
        if not self.verifier_id or len(self.verifier_id) > 128:
            raise PolicyError(
                PolicyErrorCode.INVALID,
                "bundle verifier id is invalid",
            )
        object.__setattr__(
            self,
            "verified_at",
            _utc(self.verified_at, "bundle.verified_at"),
        )
        self.bundle.assert_integrity()


class PolicyBundleVerifierPort(Protocol):
    async def verify(
        self, bundle: PolicyBundle, *, now: datetime
    ) -> VerifiedPolicyBundle: ...


class RegoOpaPolicyPort(Protocol):
    """Executes Rego only; callers retain all lifecycle and business state."""

    async def evaluate(
        self,
        *,
        bundle: VerifiedPolicyBundle,
        input_document: Mapping[str, FrozenJson],
    ) -> Sequence[Mapping[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class PolicyBundleRelease:
    bundle: PolicyBundle
    parent_version: str | None
    published_at: datetime
    revoked_at: datetime | None = None
    rollback_of: str | None = None

    @property
    def active(self) -> bool:
        return self.revoked_at is None


class MemoryPolicyBundleRepository:
    """Deterministic local release history with optimistic linear publication."""

    def __init__(self) -> None:
        self._releases: dict[str, PolicyBundleRelease] = {}
        self._history: list[str] = []
        self._current_version: str | None = None

    def current(self) -> PolicyBundleRelease | None:
        if self._current_version is None:
            return None
        return self._releases[self._current_version]

    def get(self, version: str) -> PolicyBundleRelease | None:
        return self._releases.get(version)

    def history(self) -> tuple[PolicyBundleRelease, ...]:
        return tuple(self._releases[item] for item in self._history)

    def publish(
        self,
        *,
        bundle: PolicyBundle,
        expected_current_version: str | None,
        published_at: datetime,
        rollback_of: str | None = None,
    ) -> PolicyBundleRelease:
        published_at = _utc(published_at, "bundle.published_at")
        if self._current_version != expected_current_version:
            raise PolicyError(
                PolicyErrorCode.VERSION_CONFLICT,
                "policy publication lost the current-version comparison",
            )
        if bundle.version in self._releases:
            raise PolicyError(
                PolicyErrorCode.VERSION_CONFLICT,
                "policy version has already been published",
            )
        if rollback_of is not None and rollback_of not in self._releases:
            raise PolicyError(
                PolicyErrorCode.VERSION_REVOKED,
                "rollback target is not in policy history",
            )
        if self._current_version is not None:
            current = self._releases[self._current_version]
            self._releases[self._current_version] = replace(
                current,
                revoked_at=published_at,
            )
        release = PolicyBundleRelease(
            bundle=bundle,
            parent_version=expected_current_version,
            published_at=published_at,
            rollback_of=rollback_of,
        )
        self._releases[bundle.version] = release
        self._history.append(bundle.version)
        self._current_version = bundle.version
        return release


class PinnedDigestBundleVerifier:
    """Development verifier standing in for an enterprise bundle trust service."""

    def __init__(self, *, allowed_digests: frozenset[str]) -> None:
        if not allowed_digests or any(
            _SHA256.fullmatch(item) is None for item in allowed_digests
        ):
            raise PolicyError(
                PolicyErrorCode.INVALID,
                "bundle verifier requires pinned sha256 digests",
            )
        self._allowed_digests = allowed_digests
        self.verify_count = 0

    async def verify(
        self, bundle: PolicyBundle, *, now: datetime
    ) -> VerifiedPolicyBundle:
        self.verify_count += 1
        bundle.assert_integrity()
        if bundle.digest not in self._allowed_digests:
            raise PolicyError(
                PolicyErrorCode.BUNDLE_UNTRUSTED,
                "policy bundle digest is not pinned",
            )
        return VerifiedPolicyBundle(
            bundle=bundle,
            verifier_id="pinned-digest-development-v1",
            verified_at=now,
        )


@dataclass(frozen=True, slots=True)
class PolicyEvaluationRequest:
    context: SecurityContextRef
    agent: AgentPrincipal
    action: PlannedAction
    risk_level: str
    environment_fingerprint: str


@dataclass(frozen=True, slots=True)
class _Candidate:
    decision: PolicyDecisionKind
    reason_codes: tuple[str, ...]
    obligations: tuple[Mapping[str, Any], ...]
    approval_requirements: Mapping[str, Any] | None


class VersionedPolicyControlPlane:
    """Local publication, verified cache and short-lived decision source."""

    def __init__(
        self,
        *,
        repository: MemoryPolicyBundleRepository,
        verifier: PolicyBundleVerifierPort,
        opa: RegoOpaPolicyPort,
        maximum_decision_ttl_seconds: int = 900,
    ) -> None:
        if not 1 <= maximum_decision_ttl_seconds <= 900:
            raise PolicyError(
                PolicyErrorCode.INVALID,
                "maximum policy decision TTL is outside local bounds",
            )
        self._repository = repository
        self._verifier = verifier
        self._opa = opa
        self._maximum_ttl = maximum_decision_ttl_seconds
        self._verified: dict[tuple[str, str], VerifiedPolicyBundle] = {}
        self._decisions_by_input: dict[str, ResolvedPolicyDecision] = {}
        self._decisions_by_id: dict[str, ResolvedPolicyDecision] = {}

    async def publish(
        self,
        *,
        bundle: PolicyBundle,
        expected_current_version: str | None,
        now: datetime,
    ) -> PolicyBundleRelease:
        verified = await self._verify(bundle, now=now)
        release = self._repository.publish(
            bundle=bundle,
            expected_current_version=expected_current_version,
            published_at=now,
        )
        self._invalidate()
        self._verified[(bundle.version, bundle.digest)] = verified
        return release

    async def rollback(
        self,
        *,
        target_version: str,
        new_version: str,
        expected_current_version: str,
        now: datetime,
    ) -> PolicyBundleRelease:
        target = self._repository.get(target_version)
        if target is None:
            raise PolicyError(
                PolicyErrorCode.VERSION_REVOKED,
                "rollback target is not in policy history",
            )
        rollback_bundle = target.bundle.with_version(new_version)
        verified = await self._verify(rollback_bundle, now=now)
        release = self._repository.publish(
            bundle=rollback_bundle,
            expected_current_version=expected_current_version,
            published_at=now,
            rollback_of=target_version,
        )
        self._invalidate()
        self._verified[(new_version, rollback_bundle.digest)] = verified
        return release

    async def evaluate(
        self,
        request: PolicyEvaluationRequest,
        *,
        now: datetime,
    ) -> ResolvedPolicyDecision:
        now = _utc(now, "policy.evaluated_at")
        self._validate_request(request, now=now)
        if request.action.expires_at > now + timedelta(
            seconds=self._maximum_ttl
        ):
            raise PolicyError(
                PolicyErrorCode.INVALID,
                "planned action exceeds the maximum policy decision lifetime",
            )
        release = self._active_release(request.action.policy_version)
        verified = await self._verified_bundle(release.bundle, now=now)
        preimage = self._input_preimage(
            request,
            bundle_digest=release.bundle.digest,
        )
        input_hash = canonical_sha256(preimage)
        cached = self._decisions_by_input.get(input_hash)
        if cached is not None and now < cached.decision.expires_at:
            return cached
        try:
            frozen_input = freeze_json(preimage, "policy_input")
            if not isinstance(frozen_input, Mapping):
                raise PolicyError(
                    PolicyErrorCode.INVALID,
                    "policy input must be an object",
                )
            raw_candidates = await self._opa.evaluate(
                bundle=verified,
                input_document=frozen_input,
            )
        except PolicyError:
            raise
        except Exception as exc:
            raise PolicyError(
                PolicyErrorCode.UNAVAILABLE,
                "OPA policy evaluation is unavailable",
            ) from exc
        candidate = self._reduce_candidates(raw_candidates)
        expires_at = request.action.expires_at
        if expires_at <= now:
            raise PolicyError(
                PolicyErrorCode.EXPIRED,
                "policy inputs expire before a decision can be issued",
            )
        outcome_projection = {
            "decision": candidate.decision.value,
            "reason_codes": list(candidate.reason_codes),
            "obligations": [dict(item) for item in candidate.obligations],
            "approval_requirements": (
                dict(candidate.approval_requirements)
                if candidate.approval_requirements is not None
                else None
            ),
        }
        decision_digest = canonical_sha256(
            {
                "input_hash": input_hash,
                "outcome": outcome_projection,
                "evaluated_at": _format_utc(now),
            }
        )
        mapping: dict[str, Any] = {
            "decision_id": "pd_" + decision_digest.removeprefix("sha256:")[:32],
            "tenant_id": request.action.tenant_id,
            "task_id": request.action.task_id,
            "subject_ref": request.context.context_ref,
            "subject_context_hash": request.context.context_hash,
            "agent": {
                "id": request.agent.id,
                "version": request.agent.version,
                "principal_ref": request.agent.principal_ref,
            },
            "action": {
                "tool": request.action.tool.name,
                "operation": request.action.tool.operation.value,
                "action_digest": request.action.digest(),
            },
            **outcome_projection,
            "policy_version": request.action.policy_version,
            "input_canonicalization": "rfc8785",
            "input_hash": input_hash,
            "evaluated_at": _format_utc(now),
            "expires_at": _format_utc(expires_at),
        }
        decision = PolicyDecision.from_mapping(mapping)
        record = ResolvedPolicyDecision.create(
            decision=decision,
            input_preimage=preimage,
        )
        self._decisions_by_input[input_hash] = record
        self._decisions_by_id[decision.decision_id] = record
        return record

    async def resolve(self, decision_id: str) -> ResolvedPolicyDecision:
        record = self._decisions_by_id.get(decision_id)
        if record is None:
            raise PolicyError(
                PolicyErrorCode.UNAVAILABLE,
                "policy decision is not available",
            )
        self._active_release(record.decision.policy_version)
        record.assert_integrity()
        return record

    def _invalidate(self) -> None:
        self._verified.clear()
        self._decisions_by_input.clear()
        self._decisions_by_id.clear()

    async def _verify(
        self, bundle: PolicyBundle, *, now: datetime
    ) -> VerifiedPolicyBundle:
        try:
            verified = await self._verifier.verify(bundle, now=now)
        except PolicyError:
            raise
        except Exception as exc:
            raise PolicyError(
                PolicyErrorCode.BUNDLE_UNTRUSTED,
                "policy bundle verification failed",
            ) from exc
        if verified.bundle != bundle:
            raise PolicyError(
                PolicyErrorCode.BUNDLE_UNTRUSTED,
                "bundle verifier returned a different bundle",
            )
        return verified

    async def _verified_bundle(
        self, bundle: PolicyBundle, *, now: datetime
    ) -> VerifiedPolicyBundle:
        key = (bundle.version, bundle.digest)
        cached = self._verified.get(key)
        if cached is not None:
            cached.bundle.assert_integrity()
            return cached
        verified = await self._verify(bundle, now=now)
        self._verified[key] = verified
        return verified

    def _active_release(self, version: str) -> PolicyBundleRelease:
        current = self._repository.current()
        if current is None or current.bundle.version != version:
            raise PolicyError(
                PolicyErrorCode.VERSION_REVOKED,
                "policy version is not active",
            )
        return current

    @staticmethod
    def _validate_request(
        request: PolicyEvaluationRequest, *, now: datetime
    ) -> None:
        if request.risk_level not in _RISK_LEVELS:
            raise PolicyError(
                PolicyErrorCode.INVALID,
                "policy risk level is missing or unsupported",
            )
        _sha256(
            request.environment_fingerprint,
            "policy.environment_fingerprint",
        )
        if (
            request.context.tenant_id != request.action.tenant_id
            or request.context.subject_id != request.action.requester_id
            or request.context.purpose != request.action.purpose
            or request.agent.id != request.action.agent.id
            or request.agent.version != request.action.agent.version
        ):
            raise PolicyError(
                PolicyErrorCode.BINDING_MISMATCH,
                "trusted policy inputs do not have matching identities",
            )
        if _CLASSIFICATION_RANK[request.action.data_classification] > (
            _CLASSIFICATION_RANK[
                request.context.data_classification_ceiling
            ]
        ):
            raise PolicyError(
                PolicyErrorCode.DENIED,
                "action classification exceeds the trusted context ceiling",
            )
        if (
            now < request.context.issued_at
            or now >= request.context.expires_at
            or now >= request.action.expires_at
            or request.action.expires_at > request.context.expires_at
        ):
            raise PolicyError(
                PolicyErrorCode.EXPIRED,
                "trusted policy input is not active",
            )

    @staticmethod
    def _input_preimage(
        request: PolicyEvaluationRequest,
        *,
        bundle_digest: str,
    ) -> dict[str, Any]:
        return {
            "tenant_id": request.action.tenant_id,
            "task_id": request.action.task_id,
            "subject_ref": request.context.context_ref,
            "subject_context_hash": request.context.context_hash,
            "authentication": request.context.authentication.to_mapping(),
            "agent": {
                "id": request.agent.id,
                "version": request.agent.version,
                "principal_ref": request.agent.principal_ref,
            },
            "action": {
                "tool": request.action.tool.name,
                "operation": request.action.tool.operation.value,
                "action_digest": request.action.digest(),
                "tool_schema_hash": request.action.tool.schema_hash,
            },
            "resource": request.action.resource.to_mapping(),
            "purpose": request.action.purpose,
            "data_classification": request.action.data_classification.value,
            "risk_level": request.risk_level,
            "environment_fingerprint": request.environment_fingerprint,
            "policy_version": request.action.policy_version,
            "bundle_digest": bundle_digest,
            "expires_at": _format_utc(request.action.expires_at),
        }

    @classmethod
    def _reduce_candidates(
        cls, values: Sequence[Mapping[str, Any]]
    ) -> _Candidate:
        if (
            not isinstance(values, Sequence)
            or isinstance(values, (str, bytes, bytearray))
            or not values
        ):
            raise PolicyError(
                PolicyErrorCode.EVALUATION_FAILED,
                "OPA returned no policy decisions",
            )
        candidates = tuple(cls._candidate(value) for value in values)
        denied = tuple(
            item
            for item in candidates
            if item.decision is PolicyDecisionKind.DENY
        )
        if denied:
            reasons = cls._unique(
                reason
                for candidate in denied
                for reason in candidate.reason_codes
            )
            return _Candidate(
                decision=PolicyDecisionKind.DENY,
                reason_codes=reasons,
                obligations=(),
                approval_requirements=None,
            )
        decision = (
            PolicyDecisionKind.REQUIRE_APPROVAL
            if any(
                item.decision is PolicyDecisionKind.REQUIRE_APPROVAL
                for item in candidates
            )
            else PolicyDecisionKind.ALLOW
        )
        requirements = {
            canonical_sha256(item.approval_requirements): item.approval_requirements
            for item in candidates
            if item.approval_requirements is not None
        }
        if decision is PolicyDecisionKind.REQUIRE_APPROVAL and len(requirements) != 1:
            raise PolicyError(
                PolicyErrorCode.EVALUATION_FAILED,
                "OPA returned conflicting approval requirements",
            )
        obligations: dict[str, Mapping[str, Any]] = {}
        obligation_digests: dict[str, str] = {}
        for candidate in candidates:
            for obligation in candidate.obligations:
                name = obligation.get("name")
                if not isinstance(name, str):
                    raise PolicyError(
                        PolicyErrorCode.EVALUATION_FAILED,
                        "OPA returned a malformed obligation",
                    )
                digest = canonical_sha256(obligation)
                if name in obligation_digests and obligation_digests[name] != digest:
                    raise PolicyError(
                        PolicyErrorCode.EVALUATION_FAILED,
                        "OPA returned conflicting obligations",
                    )
                obligation_digests[name] = digest
                obligations[name] = obligation
        return _Candidate(
            decision=decision,
            reason_codes=cls._unique(
                reason
                for candidate in candidates
                for reason in candidate.reason_codes
            ),
            obligations=tuple(obligations[name] for name in sorted(obligations)),
            approval_requirements=(
                next(iter(requirements.values()))
                if requirements
                else None
            ),
        )

    @staticmethod
    def _candidate(value: Mapping[str, Any]) -> _Candidate:
        if not isinstance(value, Mapping) or set(value) != {
            "decision",
            "reason_codes",
            "obligations",
            "approval_requirements",
        }:
            raise PolicyError(
                PolicyErrorCode.EVALUATION_FAILED,
                "OPA returned a malformed policy result",
            )
        try:
            decision = PolicyDecisionKind(value["decision"])
        except (TypeError, ValueError) as exc:
            raise PolicyError(
                PolicyErrorCode.EVALUATION_FAILED,
                "OPA returned an unknown policy decision",
            ) from exc
        reasons = value["reason_codes"]
        obligations = value["obligations"]
        requirements = value["approval_requirements"]
        if (
            not isinstance(reasons, Sequence)
            or isinstance(reasons, (str, bytes, bytearray))
            or not reasons
            or any(
                not isinstance(item, str) or not item or len(item) > 128
                for item in reasons
            )
            or not isinstance(obligations, Sequence)
            or isinstance(obligations, (str, bytes, bytearray))
            or any(not isinstance(item, Mapping) for item in obligations)
            or (
                requirements is not None
                and not isinstance(requirements, Mapping)
            )
            or (
                decision is PolicyDecisionKind.REQUIRE_APPROVAL
                and requirements is None
            )
            or (
                decision is not PolicyDecisionKind.REQUIRE_APPROVAL
                and requirements is not None
            )
        ):
            raise PolicyError(
                PolicyErrorCode.EVALUATION_FAILED,
                "OPA returned an invalid policy result",
            )
        return _Candidate(
            decision=decision,
            reason_codes=tuple(reasons),
            obligations=tuple(obligations),
            approval_requirements=requirements,
        )

    @staticmethod
    def _unique(values: Any) -> tuple[str, ...]:
        return tuple(dict.fromkeys(values))
