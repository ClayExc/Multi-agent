from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

import pytest
from factories import NOW, make_fixture
from flowpilot_domain import canonical_sha256
from flowpilot_policy import (
    MemoryPolicyBundleRepository,
    PinnedDigestBundleVerifier,
    PolicyBundle,
    PolicyDecisionKind,
    PolicyError,
    PolicyErrorCode,
    PolicyEvaluationRequest,
    VerifiedPolicyBundle,
    VersionedPolicyControlPlane,
)
from flowpilot_tool_contracts import FrozenJson

ENVIRONMENT = canonical_sha256({"environment": "platform-test"})


def result(
    decision: str = "allow",
    *,
    reasons: Sequence[str] = ("POLICY_TEST",),
    obligations: Sequence[Mapping[str, Any]] = (),
    approval_requirements: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "decision": decision,
        "reason_codes": list(reasons),
        "obligations": [dict(item) for item in obligations],
        "approval_requirements": (
            dict(approval_requirements)
            if approval_requirements is not None
            else None
        ),
    }


class FakeOpa:
    def __init__(self, results: Sequence[Mapping[str, Any]]) -> None:
        self.results = results
        self.calls: list[Mapping[str, FrozenJson]] = []
        self.failure: Exception | None = None

    async def evaluate(
        self,
        *,
        bundle: VerifiedPolicyBundle,
        input_document: Mapping[str, FrozenJson],
    ) -> Sequence[Mapping[str, Any]]:
        del bundle
        self.calls.append(input_document)
        if self.failure is not None:
            raise self.failure
        return self.results


def bundle(version: str, marker: str = "allow") -> PolicyBundle:
    return PolicyBundle.create(
        version=version,
        modules={
            "flowpilot/authz.rego": (
                "package flowpilot.authz\n"
                f"default {marker} := false\n"
            )
        },
        data={"policy": {"marker": marker}},
    )


def request(fixture, **changes: Any) -> PolicyEvaluationRequest:
    values: dict[str, Any] = {
        "context": fixture.invocation.request.security_context,
        "agent": fixture.invocation.request.agent_principal,
        "action": fixture.action,
        "risk_level": "high",
        "environment_fingerprint": ENVIRONMENT,
    }
    values.update(changes)
    return PolicyEvaluationRequest(**values)


async def control_plane(
    fixture,
    *,
    opa_results: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[
    VersionedPolicyControlPlane,
    MemoryPolicyBundleRepository,
    PinnedDigestBundleVerifier,
    FakeOpa,
    PolicyBundle,
]:
    initial = bundle(fixture.action.policy_version)
    repository = MemoryPolicyBundleRepository()
    verifier = PinnedDigestBundleVerifier(
        allowed_digests=frozenset({initial.digest})
    )
    opa = FakeOpa(opa_results or [result()])
    plane = VersionedPolicyControlPlane(
        repository=repository,
        verifier=verifier,
        opa=opa,
    )
    await plane.publish(
        bundle=initial,
        expected_current_version=None,
        now=NOW,
    )
    return plane, repository, verifier, opa, initial


@pytest.mark.asyncio
async def test_policy_decision_binds_complete_trusted_input_and_cache_key() -> None:
    fixture = make_fixture()
    plane, _, verifier, opa, initial = await control_plane(fixture)

    first = await plane.evaluate(request(fixture), now=NOW)
    second = await plane.evaluate(request(fixture), now=NOW)

    assert first is second
    assert verifier.verify_count == 1
    assert len(opa.calls) == 1
    preimage = first.input_preimage
    assert preimage["tenant_id"] == fixture.action.tenant_id
    assert preimage["subject_context_hash"] == (
        fixture.invocation.request.security_context.context_hash
    )
    assert preimage["resource"] == fixture.action.resource.to_mapping()
    assert preimage["purpose"] == fixture.action.purpose
    assert preimage["data_classification"] == (
        fixture.action.data_classification.value
    )
    assert preimage["risk_level"] == "high"
    assert preimage["bundle_digest"] == initial.digest
    assert preimage["environment_fingerprint"] == ENVIRONMENT
    assert first.decision.policy_version == fixture.action.policy_version
    assert first.decision.expires_at == fixture.action.expires_at
    first.assert_integrity()


@pytest.mark.asyncio
async def test_environment_change_invalidates_short_decision_cache() -> None:
    fixture = make_fixture()
    plane, _, _, opa, _ = await control_plane(fixture)

    await plane.evaluate(request(fixture), now=NOW)
    changed = request(
        fixture,
        environment_fingerprint=canonical_sha256({"environment": "changed"}),
    )
    second = await plane.evaluate(changed, now=NOW)

    assert len(opa.calls) == 2
    assert second.input_preimage["environment_fingerprint"] != ENVIRONMENT


@pytest.mark.asyncio
async def test_deny_overrides_allow_and_discards_allow_obligations() -> None:
    fixture = make_fixture()
    plane, _, _, _, _ = await control_plane(
        fixture,
        opa_results=[
            result(
                obligations=[
                    {
                        "name": "limit_records",
                        "parameters": {"maximum": 50},
                    }
                ]
            ),
            result("deny", reasons=("POLICY_DENY_OVERRIDE",)),
        ],
    )

    record = await plane.evaluate(request(fixture), now=NOW)

    assert record.decision.decision is PolicyDecisionKind.DENY
    assert record.decision.reason_codes == ("POLICY_DENY_OVERRIDE",)
    assert record.decision.obligations == ()


@pytest.mark.asyncio
async def test_require_approval_is_stronger_than_allow() -> None:
    fixture = make_fixture()
    requirements = {
        "roles": ["change_approver"],
        "minimum_approvers": 1,
        "separation_of_duties": True,
    }
    plane, _, _, _, _ = await control_plane(
        fixture,
        opa_results=[
            result(),
            result(
                "require_approval",
                reasons=("POLICY_APPROVAL_REQUIRED",),
                approval_requirements=requirements,
            ),
        ],
    )

    record = await plane.evaluate(request(fixture), now=NOW)

    assert record.decision.decision is PolicyDecisionKind.REQUIRE_APPROVAL
    assert record.decision.approval_requirements is not None
    assert record.decision.approval_requirements.separation_of_duties is True


@pytest.mark.asyncio
async def test_publish_and_rollback_form_linear_unique_version_history() -> None:
    fixture = make_fixture()
    original = bundle(fixture.action.policy_version)
    changed = bundle("policy-v2", marker="changed")
    repository = MemoryPolicyBundleRepository()
    verifier = PinnedDigestBundleVerifier(
        allowed_digests=frozenset({original.digest, changed.digest})
    )
    opa = FakeOpa([result()])
    plane = VersionedPolicyControlPlane(
        repository=repository,
        verifier=verifier,
        opa=opa,
    )
    await plane.publish(
        bundle=original,
        expected_current_version=None,
        now=NOW,
    )
    old = await plane.evaluate(request(fixture), now=NOW)
    await plane.publish(
        bundle=changed,
        expected_current_version=fixture.action.policy_version,
        now=NOW,
    )

    with pytest.raises(PolicyError) as captured:
        await plane.resolve(old.decision.decision_id)
    assert captured.value.code is PolicyErrorCode.UNAVAILABLE

    rollback = await plane.rollback(
        target_version=fixture.action.policy_version,
        new_version="policy-v3-rollback",
        expected_current_version="policy-v2",
        now=NOW,
    )

    assert rollback.bundle.digest == original.digest
    assert rollback.bundle.version == "policy-v3-rollback"
    assert rollback.rollback_of == fixture.action.policy_version
    assert [item.bundle.version for item in repository.history()] == [
        fixture.action.policy_version,
        "policy-v2",
        "policy-v3-rollback",
    ]
    assert [item.active for item in repository.history()] == [False, False, True]


@pytest.mark.asyncio
async def test_revoked_policy_version_cannot_issue_new_decision() -> None:
    fixture = make_fixture()
    original = bundle(fixture.action.policy_version)
    changed = bundle("policy-v2", marker="changed")
    repository = MemoryPolicyBundleRepository()
    verifier = PinnedDigestBundleVerifier(
        allowed_digests=frozenset({original.digest, changed.digest})
    )
    plane = VersionedPolicyControlPlane(
        repository=repository,
        verifier=verifier,
        opa=FakeOpa([result()]),
    )
    await plane.publish(
        bundle=original,
        expected_current_version=None,
        now=NOW,
    )
    await plane.publish(
        bundle=changed,
        expected_current_version=fixture.action.policy_version,
        now=NOW,
    )

    with pytest.raises(PolicyError) as captured:
        await plane.evaluate(request(fixture), now=NOW)

    assert captured.value.code is PolicyErrorCode.VERSION_REVOKED


@pytest.mark.asyncio
async def test_publication_conflict_and_untrusted_bundle_do_not_advance_history(
) -> None:
    fixture = make_fixture()
    plane, repository, _, _, _ = await control_plane(fixture)
    untrusted = bundle("policy-untrusted", marker="untrusted")

    with pytest.raises(PolicyError) as untrusted_error:
        await plane.publish(
            bundle=untrusted,
            expected_current_version=fixture.action.policy_version,
            now=NOW,
        )
    assert untrusted_error.value.code is PolicyErrorCode.BUNDLE_UNTRUSTED

    with pytest.raises(PolicyError) as conflict:
        await plane.publish(
            bundle=bundle("policy-conflict"),
            expected_current_version="forged-current",
            now=NOW,
        )
    assert conflict.value.code in {
        PolicyErrorCode.BUNDLE_UNTRUSTED,
        PolicyErrorCode.VERSION_CONFLICT,
    }
    assert len(repository.history()) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ("tenant", PolicyErrorCode.BINDING_MISMATCH),
        ("context", PolicyErrorCode.BINDING_MISMATCH),
        ("purpose", PolicyErrorCode.BINDING_MISMATCH),
        ("agent", PolicyErrorCode.BINDING_MISMATCH),
        ("classification", PolicyErrorCode.DENIED),
        ("risk", PolicyErrorCode.INVALID),
        ("environment", PolicyErrorCode.INVALID),
    ],
)
async def test_untrusted_or_missing_policy_inputs_fail_before_opa(
    change: str, expected: PolicyErrorCode
) -> None:
    fixture = make_fixture()
    plane, _, _, opa, _ = await control_plane(fixture)
    context = fixture.invocation.request.security_context
    action = fixture.action
    agent = fixture.invocation.request.agent_principal
    changes: dict[str, Any] = {}
    if change == "tenant":
        changes["context"] = replace(context, tenant_id="tenant-forged")
    elif change == "context":
        changes["context"] = replace(context, subject_id="user-forged")
    elif change == "purpose":
        changes["context"] = replace(context, purpose="different-purpose")
    elif change == "agent":
        changes["agent"] = replace(agent, version="forged-version")
    elif change == "classification":
        changes["context"] = replace(
            context,
            data_classification_ceiling=type(action.data_classification).PUBLIC,
        )
    elif change == "risk":
        changes["risk_level"] = ""
    else:
        changes["environment_fingerprint"] = "missing"

    with pytest.raises(PolicyError) as captured:
        await plane.evaluate(request(fixture, **changes), now=NOW)

    assert captured.value.code is expected
    assert opa.calls == []


@pytest.mark.asyncio
async def test_unknown_obligation_and_extra_opa_field_fail_closed() -> None:
    fixture = make_fixture()
    unknown = result(
        obligations=[{"name": "model_override", "parameters": {}}]
    )
    plane, _, _, _, _ = await control_plane(fixture, opa_results=[unknown])

    with pytest.raises(PolicyError) as obligation_error:
        await plane.evaluate(request(fixture), now=NOW)
    assert obligation_error.value.code is PolicyErrorCode.OBLIGATION_UNSUPPORTED

    extended = result()
    extended["model_authorized"] = True
    plane, _, _, _, _ = await control_plane(fixture, opa_results=[extended])
    with pytest.raises(PolicyError) as shape_error:
        await plane.evaluate(request(fixture), now=NOW)
    assert shape_error.value.code is PolicyErrorCode.EVALUATION_FAILED


@pytest.mark.asyncio
async def test_opa_timeout_is_safe_and_does_not_cache_a_decision() -> None:
    fixture = make_fixture()
    plane, _, _, opa, _ = await control_plane(fixture)
    opaque_marker = "upstream-sensitive-material"
    opa.failure = TimeoutError(opaque_marker)

    with pytest.raises(PolicyError) as captured:
        await plane.evaluate(request(fixture), now=NOW)

    assert captured.value.code is PolicyErrorCode.UNAVAILABLE
    assert opaque_marker not in str(captured.value)
    opa.failure = None
    record = await plane.evaluate(request(fixture), now=NOW)
    assert record.decision.decision is PolicyDecisionKind.ALLOW
    assert len(opa.calls) == 2
