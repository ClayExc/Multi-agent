from __future__ import annotations

import logging
from dataclasses import FrozenInstanceError, fields

import pytest
from flowpilot_security import (
    CREDENTIAL_FAMILIES,
    CredentialFamily,
    SecretFinding,
    SecurityError,
    SecurityErrorCode,
    assert_no_secret_material,
    assert_safe_projection,
    scan_secret_material,
)


def _positive_examples() -> dict[str, str]:
    return {
        "aws_access_key": "A" + "KIA" + "A1" * 8,
        "openai_legacy": "sk" + "-" + "Ab9" * 8,
        "openai_project": "sk" + "-proj-" + "Ab9_" * 7,
        "openai_admin": "sk" + "-admin-" + "Ab9_" * 7,
        "openai_service_account": "sk" + "-svcacct-" + "Ab9_" * 7,
        "anthropic_secret_key": "sk" + "-ant-api03-" + "Ab9_" * 7,
        "slack_xox_token": "xoxb" + "-2-" + "1" * 12 + "-" + "Ab9" * 8,
        "slack_xapp_token": "xapp" + "-1-" + "A" * 12 + "-" + "Ab9" * 8,
        "github_classic_token": "ghp" + "_" + "Ab9" * 12,
        "github_fine_grained_token": "github" + "_pat_" + "Ab9_" * 8,
        "authorization_bearer": "Bearer " + "Ab9._-" * 4,
        "authorization_basic": "Basic " + "QWxhZGRpbjpvcGVuIHNlc2FtZQ==",
        "jwt": (
            "eyJhbGciOiJIUzI1NiJ9."
            "eyJzdWIiOiIxMjM0NTY3ODkwIn0."
            "Ab9_Ab9_Ab9_Ab9_"
        ),
        "credential_assignment": "password=" + "Ab9._-" * 3,
        "credential_field_name": "password",
        "private_key_header": "-----BEGIN " + "ENCRYPTED PRIVATE KEY-----",
        "credential_uri": (
            "postgresql://user:" + "credential-value@example.internal/db"
        ),
    }


def _adjacent_non_examples() -> dict[str, str]:
    return {
        "aws_access_key": "A" + "KIA" + "A1" * 7,
        "openai_legacy": "sk" + "-" + "Ab9" * 6,
        "openai_project": "sk" + "-proj-" + "Ab9_" * 4,
        "openai_admin": "sk" + "-administrator-" + "Ab9_" * 7,
        "openai_service_account": "sk" + "-service-" + "Ab9_" * 7,
        "anthropic_secret_key": "sk" + "-ant-" + "Ab9_" * 4,
        "slack_xox_token": "xoxb" + "-single-segment",
        "slack_xapp_token": "xapp" + "-1-short-segment",
        "github_classic_token": "ghp" + "_" + "A" * 35,
        "github_fine_grained_token": "github" + "_pat_" + "A" * 19,
        "authorization_bearer": "Bearer placeholder",
        "authorization_basic": "Basic short",
        "jwt": "eyJhbGciOiJIUzI1NiJ9.payload.only-two-segments",
        "credential_assignment": "password=short",
        "credential_field_name": "password_policy",
        "private_key_header": "-----BEGIN " + "PUBLIC KEY-----",
        "credential_uri": "postgresql://user@example.internal/db",
    }


def test_registry_is_immutable_complete_and_has_unique_ids() -> None:
    examples = _positive_examples()
    family_ids = tuple(family.family_id for family in CREDENTIAL_FAMILIES)

    assert isinstance(CREDENTIAL_FAMILIES, tuple)
    assert family_ids == tuple(examples)
    assert len(family_ids) == len(set(family_ids))
    assert {field.name for field in fields(SecretFinding)} == {
        "family_id",
        "path",
    }
    with pytest.raises(FrozenInstanceError):
        CREDENTIAL_FAMILIES[0].description = "changed"


@pytest.mark.parametrize(
    "family",
    CREDENTIAL_FAMILIES,
    ids=lambda family: family.family_id,
)
def test_each_registered_family_has_a_positive_example(
    family: CredentialFamily,
) -> None:
    example = _positive_examples()[family.family_id]
    value: object = (
        {example: "safe"}
        if family.mapping_keys_only
        else {"safe": [example]}
    )

    findings = scan_secret_material(value, field="payload")

    assert family.family_id in {finding.family_id for finding in findings}
    assert all(example not in finding.path for finding in findings)


@pytest.mark.parametrize(
    "family",
    CREDENTIAL_FAMILIES,
    ids=lambda family: family.family_id,
)
def test_each_registered_family_has_an_adjacent_false_positive_guard(
    family: CredentialFamily,
) -> None:
    value: object = (
        {_adjacent_non_examples()[family.family_id]: "safe"}
        if family.mapping_keys_only
        else _adjacent_non_examples()[family.family_id]
    )

    assert scan_secret_material(value) == ()


@pytest.mark.parametrize("prefix", ("AKIA", "ASIA"))
def test_aws_registered_prefixes_are_covered(prefix: str) -> None:
    findings = scan_secret_material(prefix + "A1" * 8)

    assert {finding.family_id for finding in findings} == {
        "aws_access_key"
    }


@pytest.mark.parametrize(
    "prefix",
    ("xoxb", "xoxa", "xoxp", "xoxr", "xoxs", "xoxc", "xoxd"),
)
def test_slack_xox_registered_prefixes_are_covered(prefix: str) -> None:
    token = prefix + "-2-" + "1" * 12 + "-" + "Ab9" * 8

    assert "slack_xox_token" in {
        finding.family_id for finding in scan_secret_material(token)
    }


@pytest.mark.parametrize("prefix", ("ghp_", "gho_", "ghu_", "ghs_", "ghr_"))
def test_github_classic_registered_prefixes_are_covered(prefix: str) -> None:
    token = prefix + "Ab9" * 12

    assert "github_classic_token" in {
        finding.family_id for finding in scan_secret_material(token)
    }


@pytest.mark.parametrize(
    "kind",
    ("RSA", "EC", "OPENSSH", "DSA", "", "ENCRYPTED"),
    ids=("rsa", "ec", "openssh", "dsa", "generic", "encrypted-pkcs8"),
)
def test_private_key_header_variants_are_covered(kind: str) -> None:
    middle = f"{kind} " if kind else ""
    header = "-----BEGIN " + middle + "PRIVATE KEY-----"

    assert "private_key_header" in {
        finding.family_id for finding in scan_secret_material(header)
    }


def test_nested_mapping_keys_values_and_sequences_are_scanned() -> None:
    mapping_key = "sk" + "-admin-" + "Ab9_" * 7
    nested_value = "AS" + "IA" + "A1" * 8
    private_header = "-----BEGIN " + "ENCRYPTED PRIVATE KEY-----"
    value = {
        mapping_key: [
            {"safe": nested_value},
            ("safe", {private_header: "safe"}),
        ]
    }

    findings = scan_secret_material(value, field="event")

    assert {finding.family_id for finding in findings} == {
        "openai_admin",
        "aws_access_key",
        "private_key_header",
    }
    assert {finding.path for finding in findings} == {
        "event.keys[0]",
        "event.values[0][0].values[0]",
        "event.values[0][1][1].keys[0]",
    }
    assert all(
        material not in repr(findings)
        for material in (mapping_key, nested_value, private_header)
    )


def test_cycles_are_bounded_without_losing_sibling_findings() -> None:
    value: list[object] = []
    value.append(value)
    value.append("sk" + "-ant-" + "Ab9_" * 7)

    findings = scan_secret_material(value)

    assert {finding.family_id for finding in findings} == {
        "anthropic_secret_key"
    }


def test_errors_repr_and_logs_never_contain_matched_material(
    caplog: pytest.LogCaptureFixture,
) -> None:
    material = "xapp" + "-1-" + "A" * 12 + "-" + "Ab9" * 8
    caplog.set_level(logging.DEBUG)

    with pytest.raises(SecurityError) as captured:
        assert_no_secret_material({material: "safe"}, field=material)

    assert captured.value.code is SecurityErrorCode.UNSAFE_PROJECTION
    assert material not in str(captured.value)
    assert material not in repr(captured.value)
    assert material not in caplog.text

    with pytest.raises(SecurityError) as wrapped:
        assert_safe_projection({"password": "not-allowed"}, field=material)
    assert material not in str(wrapped.value)
    assert material not in repr(wrapped.value)


def test_assert_safe_projection_remains_a_compatible_wrapper() -> None:
    assert_safe_projection({"status": "safe", "counts": [0, 1]})

    with pytest.raises(SecurityError) as forbidden:
        assert_safe_projection({"password": "not-allowed"})
    assert forbidden.value.code is SecurityErrorCode.UNSAFE_PROJECTION

    with pytest.raises(SecurityError) as secret:
        assert_safe_projection(
            {"message": "sk" + "-admin-" + "Ab9_" * 7}
        )
    assert secret.value.code is SecurityErrorCode.UNSAFE_PROJECTION
