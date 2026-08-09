from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .errors import SecurityError, SecurityErrorCode


@dataclass(frozen=True, slots=True)
class CredentialFamily:
    """Immutable metadata for one high-confidence credential syntax family."""

    family_id: str
    description: str
    pattern: str
    mapping_keys_only: bool = False


@dataclass(frozen=True, slots=True)
class SecretFinding:
    """A safe finding that never retains or renders the matched material."""

    family_id: str
    path: str


CREDENTIAL_FAMILIES: tuple[CredentialFamily, ...] = (
    CredentialFamily(
        family_id="aws_access_key",
        description="AWS access key identifiers with registered prefixes",
        pattern=(
            r"(?<![A-Z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Z0-9])"
        ),
    ),
    CredentialFamily(
        family_id="openai_legacy",
        description="OpenAI legacy secret keys",
        pattern=(
            r"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9]{20,164}"
            r"(?![A-Za-z0-9_-])"
        ),
    ),
    CredentialFamily(
        family_id="openai_project",
        description="OpenAI project secret keys",
        pattern=(
            r"(?<![A-Za-z0-9_-])sk-proj-[A-Za-z0-9_-]{20,200}"
            r"(?![A-Za-z0-9_-])"
        ),
    ),
    CredentialFamily(
        family_id="openai_admin",
        description="OpenAI administration secret keys",
        pattern=(
            r"(?<![A-Za-z0-9_-])sk-admin-[A-Za-z0-9_-]{20,200}"
            r"(?![A-Za-z0-9_-])"
        ),
    ),
    CredentialFamily(
        family_id="openai_service_account",
        description="OpenAI service account secret keys",
        pattern=(
            r"(?<![A-Za-z0-9_-])sk-svcacct-[A-Za-z0-9_-]{20,200}"
            r"(?![A-Za-z0-9_-])"
        ),
    ),
    CredentialFamily(
        family_id="anthropic_secret_key",
        description="Anthropic API secret keys",
        pattern=(
            r"(?<![A-Za-z0-9_-])sk-ant-(?:api[0-9]{2}-)?"
            r"[A-Za-z0-9_-]{20,200}(?![A-Za-z0-9_-])"
        ),
    ),
    CredentialFamily(
        family_id="slack_xox_token",
        description="Slack xox application and user token families",
        pattern=(
            r"(?<![A-Za-z0-9-])xox[a-z]-"
            r"(?=[A-Za-z0-9-]{20,200}(?![A-Za-z0-9-]))"
            r"(?:[A-Za-z0-9]{1,80}-){1,4}[A-Za-z0-9]{8,80}"
            r"(?![A-Za-z0-9-])"
        ),
    ),
    CredentialFamily(
        family_id="slack_xapp_token",
        description="Slack application-level tokens",
        pattern=(
            r"(?<![A-Za-z0-9-])xapp-[0-9]-"
            r"(?=[A-Za-z0-9-]{20,200}(?![A-Za-z0-9-]))"
            r"(?:[A-Za-z0-9]{1,80}-){1,4}[A-Za-z0-9]{8,80}"
            r"(?![A-Za-z0-9-])"
        ),
    ),
    CredentialFamily(
        family_id="github_classic_token",
        description="GitHub classic token prefixes",
        pattern=(
            r"(?<![A-Za-z0-9_])gh[pousr]_[A-Za-z0-9]{36,255}"
            r"(?![A-Za-z0-9])"
        ),
    ),
    CredentialFamily(
        family_id="github_fine_grained_token",
        description="GitHub fine-grained personal access tokens",
        pattern=(
            r"(?<![A-Za-z0-9_])github_pat_[A-Za-z0-9_]{20,255}"
            r"(?![A-Za-z0-9_])"
        ),
    ),
    CredentialFamily(
        family_id="authorization_bearer",
        description="Bearer authorization credentials",
        pattern=(
            r"(?i)(?<![A-Za-z0-9])bearer[ \t]+"
            r"[A-Za-z0-9._~+/-]{16,2048}={0,2}"
            r"(?![A-Za-z0-9._~+/=-])"
        ),
    ),
    CredentialFamily(
        family_id="authorization_basic",
        description="Basic authorization credentials",
        pattern=(
            r"(?i)(?<![A-Za-z0-9])basic[ \t]+"
            r"[A-Za-z0-9+/]{16,512}={0,2}"
            r"(?![A-Za-z0-9+/=])"
        ),
    ),
    CredentialFamily(
        family_id="jwt",
        description="Three-segment JSON Web Tokens",
        pattern=(
            r"(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{5,512}\."
            r"[A-Za-z0-9_-]{8,4096}\.[A-Za-z0-9_-]{16,1024}"
            r"(?![A-Za-z0-9_-])"
        ),
    ),
    CredentialFamily(
        family_id="credential_assignment",
        description="Common credential assignments with non-trivial values",
        pattern=(
            r"(?i)(?<![A-Za-z0-9_])(?:access[_-]?token|api[_-]?key|"
            r"authorization|client[_-]?secret|credential|password|"
            r"private[_-]?key|refresh[_-]?token|secret|session[_-]?token|"
            r"token)\s*[:=]\s*(?:[\"'][A-Za-z0-9._~+/=-]{8,256}[\"']|"
            r"[A-Za-z0-9._~+/=-]{8,256})(?![A-Za-z0-9._~+/=-])"
        ),
    ),
    CredentialFamily(
        family_id="credential_field_name",
        description="Mapping keys reserved for credential material",
        pattern=(
            r"(?i)^(?:access[_-]?token|api[_-]?key|authorization|"
            r"client[_-]?secret|credential|password|private[_-]?key|"
            r"refresh[_-]?token|secret|session[_-]?token|token)$"
        ),
        mapping_keys_only=True,
    ),
    CredentialFamily(
        family_id="private_key_header",
        description="PEM private key headers",
        pattern=(
            r"-----BEGIN (?:(?:RSA|EC|OPENSSH|DSA|ENCRYPTED) )?"
            r"PRIVATE KEY-----"
        ),
    ),
    CredentialFamily(
        family_id="credential_uri",
        description="URI user-info containing an embedded credential",
        pattern=(
            r"(?i)(?<![A-Za-z0-9])"
            r"[A-Za-z][A-Za-z0-9+.-]*://"
            r"[A-Za-z0-9._~%-]{1,64}:"
            r"[A-Za-z0-9._~!$&'()*+,;=:%-]{4,256}@"
        ),
    ),
)

_COMPILED_FAMILIES: tuple[tuple[CredentialFamily, re.Pattern[str]], ...] = (
    tuple((family, re.compile(family.pattern)) for family in CREDENTIAL_FAMILIES)
)
_SAFE_FIELD_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")


def _matching_family_ids(
    text: str,
    *,
    mapping_key: bool,
) -> tuple[str, ...]:
    return tuple(
        family.family_id
        for family, pattern in _COMPILED_FAMILIES
        if (mapping_key or not family.mapping_keys_only)
        and pattern.search(text) is not None
    )


def _safe_root_path(field: str) -> str:
    if _SAFE_FIELD_PATTERN.fullmatch(field) is None:
        return "$"
    if _matching_family_ids(field, mapping_key=False):
        return "$"
    return field


def _text_value(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("ascii", errors="ignore")
    return None


def scan_secret_material(
    value: object,
    *,
    field: str = "value",
) -> tuple[SecretFinding, ...]:
    """Find credential material without retaining raw keys or values."""

    root = _safe_root_path(field)
    findings: list[SecretFinding] = []
    seen_containers: set[int] = set()
    stack: list[tuple[object, str, bool]] = [(value, root, False)]

    while stack:
        current, path, mapping_key = stack.pop()
        text = _text_value(current)
        if text is not None:
            findings.extend(
                SecretFinding(family_id=family_id, path=path)
                for family_id in _matching_family_ids(
                    text,
                    mapping_key=mapping_key,
                )
            )
            continue

        if isinstance(current, Mapping):
            identity = id(current)
            if identity in seen_containers:
                continue
            seen_containers.add(identity)
            items = tuple(current.items())
            for index in range(len(items) - 1, -1, -1):
                key, child = items[index]
                stack.append((child, f"{path}.values[{index}]", False))
                stack.append((key, f"{path}.keys[{index}]", True))
            continue

        if isinstance(current, Sequence):
            identity = id(current)
            if identity in seen_containers:
                continue
            seen_containers.add(identity)
            for index in range(len(current) - 1, -1, -1):
                stack.append((current[index], f"{path}[{index}]", mapping_key))

    return tuple(findings)


def assert_no_secret_material(
    value: object,
    *,
    field: str = "value",
) -> None:
    """Fail closed with a safe error when credential material is present."""

    findings = scan_secret_material(value, field=field)
    if not findings:
        return
    first = findings[0]
    raise SecurityError(
        SecurityErrorCode.UNSAFE_PROJECTION,
        (
            "secret-like material detected at "
            f"{first.path} ({first.family_id})"
        ),
    )
