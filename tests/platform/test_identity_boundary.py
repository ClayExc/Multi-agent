from __future__ import annotations

import asyncio
import hashlib
from base64 import urlsafe_b64encode
from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from typing import cast

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from factories import (
    AGENT_ID,
    AGENT_PRINCIPAL,
    AGENT_VERSION,
    AUDIENCE,
    NOW,
    OTHER_TENANT,
    PURPOSE,
    TENANT,
    make_fixture,
)
from flowpilot_domain import AssuranceLevel, DataClassification, ToolOperation
from flowpilot_mcp_gateway import GatewayIngress, GatewayIngressRequest
from flowpilot_security import (
    AuthenticatedWorkload,
    InMemorySecurityContextSource,
    OidcAudiencePolicy,
    OidcIdentityAdapter,
    RefreshLineageState,
    SecurityContextReference,
    SecurityError,
    SecurityErrorCode,
    SecurityVerifier,
    TrustedContextMapper,
    TrustedContextMappingPolicy,
    UserClaimPolicy,
    VerifiedUserIdentity,
    WorkloadClaimPolicy,
    WorkloadRegistration,
    oidc_nonce_digest,
)

ISSUER = "https://identity.local/realms/flowpilot"
USER_AUDIENCE = "flowpilot-api"
USER_PARTY = "flowpilot-web"
USER_ID_AUDIENCE = USER_PARTY
WORKLOAD_PARTY = "flowpilot-worker"
USER_KID = "user-signing-2026-08"
USER_ID_KID = "user-id-signing-2026-08"
WORKLOAD_KID = "workload-signing-2026-08"
USER_NONCE = "nonce-7dd4d503a3ac4cb4"
SUBJECT = "user-alice"


def _rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


USER_KEY = _rsa_key()
WORKLOAD_KEY = _rsa_key()
ROTATED_KEY = _rsa_key()


def _jwk(
    key: rsa.RSAPrivateKey,
    *,
    kid: str,
    algorithm: str = "RS256",
) -> dict[str, object]:
    result = jwt.algorithms.RSAAlgorithm.to_jwk(
        key.public_key(),
        as_dict=True,
    )
    assert isinstance(result, dict)
    return {
        **result,
        "kid": kid,
        "alg": algorithm,
        "use": "sig",
        "key_ops": ["verify"],
    }


class FakeJwksSource:
    def __init__(
        self,
        current: Mapping[str, Mapping[str, object]],
        *,
        refreshed: Mapping[str, Mapping[str, object]] | None = None,
    ) -> None:
        self.current = dict(current)
        self.refreshed = dict(refreshed or current)
        self.calls: list[tuple[str, str, bool]] = []
        self.available = True

    async def resolve(
        self,
        *,
        issuer: str,
        key_id: str,
        force_refresh: bool,
    ) -> Mapping[str, object] | None:
        self.calls.append((issuer, key_id, force_refresh))
        if not self.available:
            raise RuntimeError("simulated private JWKS failure")
        if issuer != ISSUER:
            return None
        keys = self.refreshed if force_refresh else self.current
        return keys.get(key_id)


class FakeNonceGuard:
    def __init__(self, issued: frozenset[str] = frozenset()) -> None:
        self.issued = set(issued)
        self.consumed: set[str] = set()
        self.calls: list[tuple[str, datetime]] = []
        self.available = True

    async def consume(self, *, nonce_hash: str, expires_at: datetime) -> bool:
        if not self.available:
            raise RuntimeError("simulated private nonce failure")
        self.calls.append((nonce_hash, expires_at))
        if nonce_hash not in self.issued or nonce_hash in self.consumed:
            return False
        self.consumed.add(nonce_hash)
        return True


class FakeRefreshLineageGuard:
    def __init__(self) -> None:
        self.states: dict[str, RefreshLineageState] = {}
        self.seen_token_hashes: set[str] = set()
        self.seen_token_id_hashes: set[str] = set()
        self.calls: list[tuple[str, int, int]] = []
        self.available = True
        self._lock = asyncio.Lock()

    async def establish(self, *, initial: RefreshLineageState) -> bool:
        if not self.available:
            raise RuntimeError("simulated private lineage failure")
        async with self._lock:
            self.calls.append(("establish", 0, initial.generation))
            if (
                initial.generation != 1
                or initial.session_identity_hash in self.states
                or initial.access_token_hash in self.seen_token_hashes
                or initial.access_token_id_hash in self.seen_token_id_hashes
            ):
                return False
            self.states[initial.session_identity_hash] = initial
            self.seen_token_hashes.add(initial.access_token_hash)
            self.seen_token_id_hashes.add(initial.access_token_id_hash)
            return True

    async def compare_and_swap(
        self,
        *,
        expected: RefreshLineageState,
        replacement: RefreshLineageState,
    ) -> bool:
        if not self.available:
            raise RuntimeError("simulated private lineage failure")
        async with self._lock:
            self.calls.append(
                ("compare_and_swap", expected.generation, replacement.generation)
            )
            current = self.states.get(expected.session_identity_hash)
            if (
                current != expected
                or replacement.session_identity_hash
                != expected.session_identity_hash
                or replacement.generation != expected.generation + 1
                or replacement.issued_at < expected.issued_at
                or replacement.access_token_hash in self.seen_token_hashes
                or replacement.access_token_id_hash in self.seen_token_id_hashes
            ):
                return False
            self.states[expected.session_identity_hash] = replacement
            self.seen_token_hashes.add(replacement.access_token_hash)
            self.seen_token_id_hashes.add(replacement.access_token_id_hash)
            return True


def _user_policy() -> UserClaimPolicy:
    return UserClaimPolicy(
        token=OidcAudiencePolicy(
            issuer=ISSUER,
            audience=USER_AUDIENCE,
            authorized_parties=frozenset({USER_PARTY}),
        ),
        tenant_mapping={
            "external-alpha": TENANT,
            "external-bravo": OTHER_TENANT,
        },
        role_mapping={
            "flowpilot-requester": "requester",
            "vpn-users": "group:vpn-users",
        },
        scope_mapping={
            "openid": "identity:read",
            "tasks:read": "tasks:read",
        },
        assurance_mapping={"urn:flowpilot:loa:high": AssuranceLevel.HIGH},
        id_token=OidcAudiencePolicy(
            issuer=ISSUER,
            audience=USER_ID_AUDIENCE,
            authorized_parties=frozenset({USER_PARTY}),
            allowed_algorithms=frozenset({"RS256", "RS384"}),
        ),
    )


def _workload_policy() -> WorkloadClaimPolicy:
    return WorkloadClaimPolicy(
        token=OidcAudiencePolicy(
            issuer=ISSUER,
            audience=AUDIENCE,
            authorized_parties=frozenset({WORKLOAD_PARTY}),
        ),
        registrations=(
            WorkloadRegistration(
                issuer=ISSUER,
                authorized_party=WORKLOAD_PARTY,
                subject_id="service-account-flowpilot-worker",
                agent_id=AGENT_ID,
                agent_version=AGENT_VERSION,
                principal_ref=AGENT_PRINCIPAL,
                tenant_ids=frozenset({TENANT}),
                purposes=frozenset({PURPOSE}),
                allowed_tools=frozenset({"knowledge.search.v1"}),
            ),
        ),
    )


def _adapter(
    *,
    jwks: FakeJwksSource | None = None,
    nonces: FakeNonceGuard | None = None,
    refresh_lineage: FakeRefreshLineageGuard | None = None,
) -> tuple[OidcIdentityAdapter, FakeJwksSource, FakeNonceGuard]:
    selected_jwks = jwks or FakeJwksSource(
        {
            USER_KID: _jwk(USER_KEY, kid=USER_KID),
            USER_ID_KID: _jwk(
                USER_KEY,
                kid=USER_ID_KID,
                algorithm="RS384",
            ),
            WORKLOAD_KID: _jwk(WORKLOAD_KEY, kid=WORKLOAD_KID),
        }
    )
    selected_nonces = nonces or FakeNonceGuard(
        frozenset(
            {
                oidc_nonce_digest(
                    issuer=ISSUER,
                    authorized_party=USER_PARTY,
                    nonce=USER_NONCE,
                )
            }
        )
    )
    selected_refresh_lineage = refresh_lineage or FakeRefreshLineageGuard()
    return (
        OidcIdentityAdapter(
            jwks=selected_jwks,
            nonces=selected_nonces,
            users=_user_policy(),
            workloads=_workload_policy(),
            refresh_lineage=selected_refresh_lineage,
        ),
        selected_jwks,
        selected_nonces,
    )


def _base_user_claims() -> dict[str, object]:
    return {
        "iss": ISSUER,
        "aud": USER_AUDIENCE,
        "azp": USER_PARTY,
        "sub": SUBJECT,
        "iat": int((NOW - timedelta(minutes=1)).timestamp()),
        "nbf": int((NOW - timedelta(minutes=1)).timestamp()),
        "exp": int((NOW + timedelta(minutes=10)).timestamp()),
        "nonce": USER_NONCE,
        "tenant_id": "external-alpha",
        "realm_access": {
            "roles": ["flowpilot-requester", "vpn-users"],
        },
        "scope": "openid tasks:read",
        "acr": "urn:flowpilot:loa:high",
        "sid": "keycloak-session-alpha",
        "jti": "access-token-initial",
    }


def _base_workload_claims() -> dict[str, object]:
    return {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "azp": WORKLOAD_PARTY,
        "sub": "service-account-flowpilot-worker",
        "iat": int((NOW - timedelta(minutes=1)).timestamp()),
        "nbf": int((NOW - timedelta(minutes=1)).timestamp()),
        "exp": int((NOW + timedelta(minutes=10)).timestamp()),
    }


def _token(
    claims: Mapping[str, object],
    *,
    key: rsa.RSAPrivateKey = USER_KEY,
    kid: str = USER_KID,
    algorithm: str = "RS256",
) -> str:
    return jwt.encode(dict(claims), key, algorithm=algorithm, headers={"kid": kid})


def _at_hash(token: str, *, algorithm: str = "RS384") -> str:
    digest_factory = {"RS256": hashlib.sha256, "RS384": hashlib.sha384}[algorithm]
    digest = digest_factory(token.encode("ascii")).digest()
    return urlsafe_b64encode(digest[: len(digest) // 2]).rstrip(b"=").decode(
        "ascii"
    )


def _base_id_claims(
    access_token: str,
    *,
    include_nonce: bool = True,
) -> dict[str, object]:
    claims: dict[str, object] = {
        "iss": ISSUER,
        "aud": USER_ID_AUDIENCE,
        "azp": USER_PARTY,
        "sub": SUBJECT,
        "iat": int((NOW - timedelta(minutes=1)).timestamp()),
        "nbf": int((NOW - timedelta(minutes=1)).timestamp()),
        "exp": int((NOW + timedelta(minutes=10)).timestamp()),
        "sid": "keycloak-session-alpha",
        "at_hash": _at_hash(access_token),
    }
    if include_nonce:
        claims["nonce"] = USER_NONCE
    return claims


def _id_token(claims: Mapping[str, object]) -> str:
    return _token(
        claims,
        kid=USER_ID_KID,
        algorithm="RS384",
    )


@pytest.mark.asyncio
async def test_user_token_maps_to_revocable_trusted_context_without_raw_token() -> None:
    adapter, _, nonce_guard = _adapter()
    token = _token(_base_user_claims())

    identity = await adapter.verify_user_token(
        token,
        expected_nonce=USER_NONCE,
        now=NOW,
    )
    mapper = TrustedContextMapper(
        TrustedContextMappingPolicy(
            allowed_purposes=frozenset({PURPOSE}),
            data_classification_ceiling=DataClassification.CONFIDENTIAL,
            maximum_ttl_seconds=900,
        )
    )
    trusted = mapper.map_user(
        identity=identity,
        reference=SecurityContextReference(
            context_id="secctx_m8alpha001",
            context_ref="security-context://tenant-alpha/user-alice/m8",
        ),
        purpose=PURPOSE,
        now=NOW,
        ttl_seconds=600,
    )

    assert identity.tenant_id == TENANT
    assert identity.roles == frozenset({"requester", "group:vpn-users"})
    assert identity.scopes == frozenset({"identity:read", "tasks:read"})
    assert identity.token_hash.startswith("sha256:")
    assert identity.refresh_lineage is None
    assert trusted.context.tenant_id == TENANT
    assert trusted.context.subject_id == SUBJECT
    assert trusted.context.purpose == PURPOSE
    assert trusted.context.context_hash.startswith("sha256:")
    assert token not in repr(identity)
    assert token not in repr(trusted)
    assert USER_NONCE not in repr(nonce_guard.calls)

    source = InMemorySecurityContextSource()
    await source.store(trusted)
    resolved = await source.resolve(trusted.context.context_ref)
    assert (
        SecurityVerifier().verify_context(
            presented=trusted.context,
            trusted=resolved,
            now=NOW,
        )
        == trusted.context
    )
    await source.revoke(
        trusted.context.context_ref,
        revoked_at=NOW + timedelta(seconds=1),
        reason_code="USER_SESSION_REVOKED",
    )
    with pytest.raises(SecurityError) as raised:
        SecurityVerifier().verify_context(
            presented=trusted.context,
            trusted=await source.resolve(trusted.context.context_ref),
            now=NOW + timedelta(seconds=2),
        )
    assert raised.value.code is SecurityErrorCode.CONTEXT_NOT_ACTIVE


@pytest.mark.asyncio
async def test_callback_token_pair_uses_standard_id_and_access_semantics() -> None:
    lineage_guard = FakeRefreshLineageGuard()
    adapter, _, nonce_guard = _adapter(refresh_lineage=lineage_guard)
    access_claims = _base_user_claims()
    access_claims.pop("nonce")
    access_token = _token(access_claims)
    id_token = _id_token(
        {
            **_base_id_claims(access_token),
            "tenant_id": "external-bravo",
            "realm_access": {"roles": ["realm-administrator"]},
            "scope": "untrusted:id-token-scope",
        }
    )

    identity = await adapter.verify_user_token_pair(
        id_token=id_token,
        access_token=access_token,
        expected_nonce=USER_NONCE,
        now=NOW,
    )

    expected_hash = "sha256:" + hashlib.sha256(
        access_token.encode("utf-8")
    ).hexdigest()
    assert identity.tenant_id == TENANT
    assert identity.roles == frozenset({"requester", "group:vpn-users"})
    assert identity.scopes == frozenset({"identity:read", "tasks:read"})
    assert identity.token_hash == expected_hash
    assert identity.refresh_lineage is not None
    assert identity.refresh_lineage.generation == 1
    assert (
        lineage_guard.states[identity.refresh_lineage.session_identity_hash]
        == identity.refresh_lineage
    )
    assert len(nonce_guard.calls) == 1
    assert id_token not in repr(identity)
    assert access_token not in repr(identity)
    assert "access-token-initial" not in repr(identity)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    [
        "missing_id",
        "missing_access",
        "token_swap",
        "id_signature",
        "id_issuer",
        "id_audience",
        "id_azp",
        "access_signature",
        "access_issuer",
        "access_audience",
        "access_azp",
        "subject",
        "session",
        "at_hash",
        "missing_jti",
    ],
)
async def test_callback_token_pair_rejects_swap_and_binding_failures(
    mutation: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    adapter, _, _ = _adapter()
    access_claims = _base_user_claims()
    access_claims.pop("nonce")
    id_claims: dict[str, object]
    access_key = USER_KEY
    id_key = USER_KEY
    if mutation == "access_issuer":
        access_claims["iss"] = "https://attacker.invalid/realm"
    elif mutation == "access_audience":
        access_claims["aud"] = "attacker-api"
    elif mutation == "access_azp":
        access_claims["azp"] = "attacker-browser"
    elif mutation == "missing_jti":
        access_claims.pop("jti")
    access_token = _token(access_claims)
    id_claims = _base_id_claims(access_token)
    if mutation == "id_issuer":
        id_claims["iss"] = "https://attacker.invalid/realm"
    elif mutation == "id_audience":
        id_claims["aud"] = "attacker-browser"
    elif mutation == "id_azp":
        id_claims["azp"] = "attacker-browser"
    elif mutation == "subject":
        id_claims["sub"] = "user-mallory"
    elif mutation == "session":
        id_claims["sid"] = "keycloak-session-mallory"
    elif mutation == "at_hash":
        id_claims["at_hash"] = _at_hash("different-access-token")
    if mutation == "access_signature":
        access_key = ROTATED_KEY
        access_token = _token(access_claims, key=access_key)
        id_claims = _base_id_claims(access_token)
    if mutation == "id_signature":
        id_key = ROTATED_KEY
    id_token = _token(
        id_claims,
        key=id_key,
        kid=USER_ID_KID,
        algorithm="RS384",
    )
    presented_id = id_token
    presented_access = access_token
    if mutation == "missing_id":
        presented_id = ""
    elif mutation == "missing_access":
        presented_access = ""
    elif mutation == "token_swap":
        presented_id, presented_access = access_token, id_token

    with pytest.raises(SecurityError) as rejected:
        await adapter.verify_user_token_pair(
            id_token=presented_id,
            access_token=presented_access,
            expected_nonce=USER_NONCE,
            now=NOW,
        )

    assert rejected.value.code in {
        SecurityErrorCode.IDENTITY_CLAIMS_INVALID,
        SecurityErrorCode.IDENTITY_TOKEN_INVALID,
        SecurityErrorCode.NONCE_REPLAY,
    }
    combined = str(rejected.value) + repr(rejected.value) + caplog.text
    assert id_token not in combined
    assert access_token not in combined


@pytest.mark.asyncio
async def test_callback_nonce_is_wrong_or_single_use() -> None:
    adapter, _, nonce_guard = _adapter()
    access_claims = _base_user_claims()
    access_claims.pop("nonce")
    access_token = _token(access_claims)
    id_token = _id_token(_base_id_claims(access_token))

    with pytest.raises(SecurityError) as wrong:
        await adapter.verify_user_token_pair(
            id_token=id_token,
            access_token=access_token,
            expected_nonce="wrong-server-nonce",
            now=NOW,
        )
    assert wrong.value.code is SecurityErrorCode.NONCE_REPLAY
    assert nonce_guard.calls == []

    await adapter.verify_user_token_pair(
        id_token=id_token,
        access_token=access_token,
        expected_nonce=USER_NONCE,
        now=NOW,
    )
    with pytest.raises(SecurityError) as replay:
        await adapter.verify_user_token_pair(
            id_token=id_token,
            access_token=access_token,
            expected_nonce=USER_NONCE,
            now=NOW,
        )
    assert replay.value.code is SecurityErrorCode.NONCE_REPLAY
    assert len(nonce_guard.calls) == 2


@pytest.mark.asyncio
async def test_refresh_rotates_access_identity_without_consuming_login_nonce() -> None:
    lineage_guard = FakeRefreshLineageGuard()
    adapter, _, nonce_guard = _adapter(refresh_lineage=lineage_guard)
    initial_claims = _base_user_claims()
    initial_claims.pop("nonce")
    initial_access = _token(initial_claims)
    initial = await adapter.verify_user_token_pair(
        id_token=_id_token(_base_id_claims(initial_access)),
        access_token=initial_access,
        expected_nonce=USER_NONCE,
        now=NOW,
    )
    refreshed_claims = {
        **initial_claims,
        "jti": "access-token-refresh-same-second",
        "exp": int((NOW + timedelta(minutes=20)).timestamp()),
        "realm_access": {"roles": ["vpn-users"]},
        "scope": "openid",
        "acr": "urn:flowpilot:loa:high",
    }
    refreshed_access = _token(refreshed_claims)

    refreshed = await adapter.verify_user_refresh(
        access_token=refreshed_access,
        previous_identity=initial,
        now=NOW + timedelta(seconds=2),
    )

    assert refreshed.subject_id == initial.subject_id
    assert refreshed.tenant_id == initial.tenant_id
    assert refreshed.session_id_hash == initial.session_id_hash
    assert refreshed.roles == frozenset({"group:vpn-users"})
    assert refreshed.scopes == frozenset({"identity:read"})
    assert refreshed.expires_at > initial.expires_at
    assert refreshed.token_hash != initial.token_hash
    assert refreshed.issued_at == initial.issued_at
    assert refreshed.refresh_lineage is not None
    assert refreshed.refresh_lineage.generation == 2
    assert (
        lineage_guard.states[refreshed.refresh_lineage.session_identity_hash]
        == refreshed.refresh_lineage
    )
    assert len(nonce_guard.calls) == 1


@pytest.mark.asyncio
async def test_refresh_id_token_binds_access_and_does_not_reuse_nonce() -> None:
    adapter, _, nonce_guard = _adapter()
    initial_claims = _base_user_claims()
    initial_claims.pop("nonce")
    initial_access = _token(initial_claims)
    initial = await adapter.verify_user_token_pair(
        id_token=_id_token(_base_id_claims(initial_access)),
        access_token=initial_access,
        expected_nonce=USER_NONCE,
        now=NOW,
    )
    refreshed_claims = {
        **initial_claims,
        "jti": "access-token-refresh-with-id",
        "iat": int((NOW + timedelta(seconds=2)).timestamp()),
        "nbf": int((NOW + timedelta(seconds=2)).timestamp()),
        "exp": int((NOW + timedelta(minutes=20)).timestamp()),
    }
    refreshed_access = _token(refreshed_claims)
    refreshed_id = _id_token(
        _base_id_claims(refreshed_access, include_nonce=False)
    )

    refreshed = await adapter.verify_user_refresh(
        access_token=refreshed_access,
        id_token=refreshed_id,
        previous_identity=initial,
        now=NOW + timedelta(seconds=3),
    )

    assert refreshed.token_hash != initial.token_hash
    assert len(nonce_guard.calls) == 1

    reused_nonce_id = _id_token(_base_id_claims(refreshed_access))
    with pytest.raises(SecurityError) as nonce_reuse:
        await adapter.verify_user_refresh(
            access_token=refreshed_access,
            id_token=reused_nonce_id,
            previous_identity=initial,
            now=NOW + timedelta(seconds=3),
        )
    assert nonce_reuse.value.code is SecurityErrorCode.IDENTITY_TOKEN_INVALID
    assert len(nonce_guard.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("sub", "user-mallory"),
        ("tenant_id", "external-bravo"),
        ("sid", "keycloak-session-mallory"),
    ],
)
async def test_refresh_rejects_cross_identity_tenant_or_session(
    field: str,
    value: str,
) -> None:
    adapter, _, _ = _adapter()
    initial_claims = _base_user_claims()
    initial_claims.pop("nonce")
    initial_access = _token(initial_claims)
    initial = await adapter.verify_user_token_pair(
        id_token=_id_token(_base_id_claims(initial_access)),
        access_token=initial_access,
        expected_nonce=USER_NONCE,
        now=NOW,
    )
    refreshed_claims = {
        **initial_claims,
        "jti": "access-token-refresh-cross-identity",
        field: value,
        "iat": int((NOW + timedelta(seconds=1)).timestamp()),
        "nbf": int((NOW + timedelta(seconds=1)).timestamp()),
        "exp": int((NOW + timedelta(minutes=20)).timestamp()),
    }
    refreshed_access = _token(refreshed_claims)

    with pytest.raises(SecurityError) as rejected:
        await adapter.verify_user_refresh(
            access_token=refreshed_access,
            previous_identity=initial,
            now=NOW + timedelta(seconds=2),
        )

    assert rejected.value.code is SecurityErrorCode.IDENTITY_TOKEN_INVALID
    assert refreshed_access not in str(rejected.value)


@pytest.mark.asyncio
async def test_refresh_rejects_current_and_historical_access_tokens() -> None:
    lineage_guard = FakeRefreshLineageGuard()
    adapter, _, _ = _adapter(refresh_lineage=lineage_guard)
    initial_claims = _base_user_claims()
    initial_claims.pop("nonce")
    initial_access = _token(initial_claims)
    initial = await adapter.verify_user_token_pair(
        id_token=_id_token(_base_id_claims(initial_access)),
        access_token=initial_access,
        expected_nonce=USER_NONCE,
        now=NOW,
    )
    next_claims = {
        **initial_claims,
        "jti": "access-token-refresh-current",
        "exp": int((NOW + timedelta(minutes=20)).timestamp()),
    }
    next_access = _token(next_claims)
    current = await adapter.verify_user_refresh(
        access_token=next_access,
        previous_identity=initial,
        now=NOW + timedelta(seconds=2),
    )
    assert current.issued_at == initial.issued_at
    assert current.refresh_lineage is not None
    lineage_key = current.refresh_lineage.session_identity_hash
    authoritative = lineage_guard.states[lineage_key]

    for historical in (next_access, initial_access):
        with pytest.raises(SecurityError) as rejected:
            await adapter.verify_user_refresh(
                access_token=historical,
                previous_identity=current,
                now=NOW + timedelta(seconds=2),
            )
        assert rejected.value.code is SecurityErrorCode.IDENTITY_TOKEN_INVALID
        assert historical not in str(rejected.value)
        assert lineage_guard.states[lineage_key] == authoritative


@pytest.mark.asyncio
async def test_concurrent_same_second_refresh_advances_lineage_once() -> None:
    lineage_guard = FakeRefreshLineageGuard()
    adapter, _, _ = _adapter(refresh_lineage=lineage_guard)
    initial_claims = _base_user_claims()
    initial_claims.pop("nonce")
    initial_access = _token(initial_claims)
    initial = await adapter.verify_user_token_pair(
        id_token=_id_token(_base_id_claims(initial_access)),
        access_token=initial_access,
        expected_nonce=USER_NONCE,
        now=NOW,
    )
    first_claims = {
        **initial_claims,
        "jti": "access-token-concurrent-first",
        "exp": int((NOW + timedelta(minutes=20)).timestamp()),
    }
    second_claims = {
        **initial_claims,
        "jti": "access-token-concurrent-second",
        "exp": int((NOW + timedelta(minutes=21)).timestamp()),
    }
    first_access = _token(first_claims)
    second_access = _token(second_claims)

    results = await asyncio.gather(
        adapter.verify_user_refresh(
            access_token=first_access,
            previous_identity=initial,
            now=NOW + timedelta(seconds=1),
        ),
        adapter.verify_user_refresh(
            access_token=second_access,
            previous_identity=initial,
            now=NOW + timedelta(seconds=1),
        ),
        return_exceptions=True,
    )

    successes = [item for item in results if isinstance(item, VerifiedUserIdentity)]
    failures = [item for item in results if isinstance(item, SecurityError)]
    assert len(successes) == 1
    assert len(failures) == 1
    assert failures[0].code is SecurityErrorCode.IDENTITY_TOKEN_INVALID
    winner = successes[0]
    assert winner.refresh_lineage is not None
    assert winner.refresh_lineage.generation == 2
    assert (
        lineage_guard.states[winner.refresh_lineage.session_identity_hash]
        == winner.refresh_lineage
    )
    combined = str(failures[0]) + repr(failures[0])
    assert first_access not in combined
    assert second_access not in combined


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mutation",
    [
        "old_generation",
        "wrong_current_hash",
        "reused_jti",
        "missing_jti",
        "iat_rollback",
    ],
)
async def test_refresh_lineage_cas_rejects_stale_or_replayed_inputs_without_advance(
    mutation: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    lineage_guard = FakeRefreshLineageGuard()
    adapter, _, _ = _adapter(refresh_lineage=lineage_guard)
    initial_claims = _base_user_claims()
    initial_claims.pop("nonce")
    initial_access = _token(initial_claims)
    initial = await adapter.verify_user_token_pair(
        id_token=_id_token(_base_id_claims(initial_access)),
        access_token=initial_access,
        expected_nonce=USER_NONCE,
        now=NOW,
    )
    current_claims = {
        **initial_claims,
        "jti": "access-token-lineage-current",
        "exp": int((NOW + timedelta(minutes=20)).timestamp()),
    }
    current_access = _token(current_claims)
    current = await adapter.verify_user_refresh(
        access_token=current_access,
        previous_identity=initial,
        now=NOW + timedelta(seconds=1),
    )
    assert current.refresh_lineage is not None
    lineage_key = current.refresh_lineage.session_identity_hash
    authoritative = lineage_guard.states[lineage_key]
    previous = current
    candidate_claims = {
        **current_claims,
        "jti": "access-token-lineage-candidate",
        "exp": int((NOW + timedelta(minutes=30)).timestamp()),
    }
    if mutation == "old_generation":
        stale = replace(current.refresh_lineage, generation=1)
        previous = replace(current, refresh_lineage=stale)
    elif mutation == "wrong_current_hash":
        wrong_hash = "sha256:" + "0" * 64
        wrong = replace(current.refresh_lineage, access_token_hash=wrong_hash)
        previous = replace(current, token_hash=wrong_hash, refresh_lineage=wrong)
    elif mutation == "reused_jti":
        candidate_claims["jti"] = current_claims["jti"]
    elif mutation == "missing_jti":
        candidate_claims.pop("jti")
    elif mutation == "iat_rollback":
        candidate_claims["iat"] = int((NOW - timedelta(minutes=2)).timestamp())
        candidate_claims["nbf"] = int((NOW - timedelta(minutes=2)).timestamp())
    candidate_access = _token(candidate_claims)

    with pytest.raises(SecurityError) as rejected:
        await adapter.verify_user_refresh(
            access_token=candidate_access,
            previous_identity=previous,
            now=NOW + timedelta(seconds=2),
        )

    combined = str(rejected.value) + repr(rejected.value) + caplog.text
    assert rejected.value.code in {
        SecurityErrorCode.IDENTITY_CLAIMS_INVALID,
        SecurityErrorCode.IDENTITY_TOKEN_INVALID,
    }
    assert lineage_guard.states[lineage_key] == authoritative
    assert candidate_access not in combined
    assert current_access not in combined


@pytest.mark.asyncio
async def test_refresh_lineage_guard_failure_is_closed_and_does_not_leak_tokens(
    caplog: pytest.LogCaptureFixture,
) -> None:
    callback_guard = FakeRefreshLineageGuard()
    callback_guard.available = False
    callback_adapter, _, _ = _adapter(refresh_lineage=callback_guard)
    initial_claims = _base_user_claims()
    initial_claims.pop("nonce")
    initial_access = _token(initial_claims)
    id_token = _id_token(_base_id_claims(initial_access))

    with pytest.raises(SecurityError) as callback_rejected:
        await callback_adapter.verify_user_token_pair(
            id_token=id_token,
            access_token=initial_access,
            expected_nonce=USER_NONCE,
            now=NOW,
        )
    assert callback_rejected.value.code is SecurityErrorCode.IDENTITY_SOURCE_UNAVAILABLE
    assert callback_guard.states == {}

    refresh_guard = FakeRefreshLineageGuard()
    refresh_adapter, _, _ = _adapter(refresh_lineage=refresh_guard)
    initial = await refresh_adapter.verify_user_token_pair(
        id_token=id_token,
        access_token=initial_access,
        expected_nonce=USER_NONCE,
        now=NOW,
    )
    assert initial.refresh_lineage is not None
    lineage_key = initial.refresh_lineage.session_identity_hash
    authoritative = refresh_guard.states[lineage_key]
    refresh_guard.available = False
    refreshed_claims = {
        **initial_claims,
        "jti": "access-token-lineage-unavailable",
        "exp": int((NOW + timedelta(minutes=20)).timestamp()),
    }
    refreshed_access = _token(refreshed_claims)

    with pytest.raises(SecurityError) as refresh_rejected:
        await refresh_adapter.verify_user_refresh(
            access_token=refreshed_access,
            previous_identity=initial,
            now=NOW + timedelta(seconds=1),
        )
    combined = (
        str(callback_rejected.value)
        + repr(callback_rejected.value)
        + str(refresh_rejected.value)
        + repr(refresh_rejected.value)
        + caplog.text
    )
    assert refresh_rejected.value.code is SecurityErrorCode.IDENTITY_SOURCE_UNAVAILABLE
    assert refresh_guard.states[lineage_key] == authoritative
    assert id_token not in combined
    assert initial_access not in combined
    assert refreshed_access not in combined


@pytest.mark.asyncio
async def test_refresh_id_token_rejects_wrong_at_hash_without_token_leakage(
    caplog: pytest.LogCaptureFixture,
) -> None:
    adapter, _, _ = _adapter()
    initial_claims = _base_user_claims()
    initial_claims.pop("nonce")
    initial_access = _token(initial_claims)
    initial = await adapter.verify_user_token_pair(
        id_token=_id_token(_base_id_claims(initial_access)),
        access_token=initial_access,
        expected_nonce=USER_NONCE,
        now=NOW,
    )
    refreshed_claims = {
        **initial_claims,
        "jti": "access-token-refresh-bad-at-hash",
        "iat": int((NOW + timedelta(seconds=1)).timestamp()),
        "nbf": int((NOW + timedelta(seconds=1)).timestamp()),
        "exp": int((NOW + timedelta(minutes=20)).timestamp()),
    }
    refreshed_access = _token(refreshed_claims)
    bad_id_claims = _base_id_claims(refreshed_access, include_nonce=False)
    bad_id_claims["at_hash"] = _at_hash(initial_access)
    refreshed_id = _id_token(bad_id_claims)

    with pytest.raises(SecurityError) as rejected:
        await adapter.verify_user_refresh(
            access_token=refreshed_access,
            id_token=refreshed_id,
            previous_identity=initial,
            now=NOW + timedelta(seconds=2),
        )

    combined = str(rejected.value) + repr(rejected.value) + caplog.text
    assert rejected.value.code is SecurityErrorCode.IDENTITY_TOKEN_INVALID
    assert refreshed_access not in combined
    assert refreshed_id not in combined


@pytest.mark.asyncio
async def test_workload_token_uses_server_registration_before_gateway_policy() -> None:
    adapter, _, _ = _adapter()
    claims = {
        **_base_workload_claims(),
        "tenant_ids": ["tenant-attacker"],
        "purposes": ["arbitrary-browser-purpose"],
        "allowed_tools": ["ticket.update.v1"],
        "agent_id": "attacker-selected-agent",
    }
    token = _token(claims, key=WORKLOAD_KEY, kid=WORKLOAD_KID)
    workload = await adapter.verify_workload_token(token, now=NOW)

    assert workload.tenant_ids == frozenset({TENANT})
    assert workload.purposes == frozenset({PURPOSE})
    assert workload.allowed_tools == frozenset({"knowledge.search.v1"})
    assert workload.agent_id == AGENT_ID
    assert workload.issuer == ISSUER
    assert workload.authorized_party == WORKLOAD_PARTY
    assert workload.credential_hash is not None
    assert token not in repr(workload)

    fixture = make_fixture(operation=ToolOperation.READ)
    execution = await fixture.gateway.execute(
        fixture.replace_invocation(workload=workload)
    )

    assert execution.result.status.value == "verified"
    assert fixture.context_source.resolution_count == 1
    assert fixture.adapter.invocation_count == 1
    assert token not in repr(execution)


@pytest.mark.asyncio
async def test_production_ingress_authenticates_bearer_before_internal_invocation(
) -> None:
    adapter, _, _ = _adapter()
    fixture = make_fixture(operation=ToolOperation.READ)
    ingress = GatewayIngress(
        core=fixture.gateway,
        workload_tokens=adapter,
        clock=lambda: NOW,
    )
    request = GatewayIngressRequest(
        request=fixture.invocation.request,
        thread_id=fixture.invocation.thread_id,
        run_id=fixture.invocation.run_id,
        correlation_id=fixture.invocation.correlation_id,
    )
    token = _token(
        _base_workload_claims(),
        key=WORKLOAD_KEY,
        kid=WORKLOAD_KID,
    )

    execution = await ingress.execute(request, workload_bearer=token)

    assert execution.result.status.value == "verified"
    assert fixture.context_source.resolution_count == 1
    assert fixture.adapter.invocation_count == 1
    assert token not in repr(request)
    assert token not in repr(ingress)
    assert token not in repr(execution)


@pytest.mark.asyncio
async def test_workload_registration_rejects_same_client_with_wrong_subject() -> None:
    adapter, _, _ = _adapter()
    token = _token(
        {**_base_workload_claims(), "sub": SUBJECT},
        key=WORKLOAD_KEY,
        kid=WORKLOAD_KID,
    )
    fixture = make_fixture(operation=ToolOperation.READ)
    ingress = GatewayIngress(
        core=fixture.gateway,
        workload_tokens=adapter,
        clock=lambda: NOW,
    )
    request = GatewayIngressRequest(
        request=fixture.invocation.request,
        thread_id=fixture.invocation.thread_id,
        run_id=fixture.invocation.run_id,
        correlation_id=fixture.invocation.correlation_id,
    )

    with pytest.raises(SecurityError) as rejected:
        await ingress.execute(request, workload_bearer=token)

    assert rejected.value.code is SecurityErrorCode.WORKLOAD_UNTRUSTED
    assert fixture.context_source.resolution_count == 0
    assert fixture.policy_source.resolve_count == 0
    assert fixture.adapter.invocation_count == 0
    assert token not in str(rejected.value)


@pytest.mark.asyncio
async def test_user_token_cannot_be_used_as_gateway_workload_identity() -> None:
    adapter, _, _ = _adapter()
    user_token = _token(_base_user_claims())
    identity = await adapter.verify_user_token(
        user_token,
        expected_nonce=USER_NONCE,
        now=NOW,
    )

    with pytest.raises(SecurityError) as wrong_audience:
        await adapter.verify_workload_token(user_token, now=NOW)
    assert wrong_audience.value.code is SecurityErrorCode.IDENTITY_TOKEN_INVALID
    assert user_token not in str(wrong_audience.value)
    assert user_token not in repr(wrong_audience.value)

    fixture = make_fixture(operation=ToolOperation.READ)
    with pytest.raises(SecurityError) as direct_user:
        replace(
            fixture.invocation,
            workload=cast(AuthenticatedWorkload, identity),
        )
    assert direct_user.value.code is SecurityErrorCode.USER_TOKEN_FORBIDDEN
    assert fixture.adapter.invocation_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("overrides", "expected_code"),
    [
        (
            {"iss": "https://attacker.invalid/realm"},
            SecurityErrorCode.IDENTITY_TOKEN_INVALID,
        ),
        ({"aud": "attacker-api"}, SecurityErrorCode.IDENTITY_TOKEN_INVALID),
        ({"azp": "attacker-browser"}, SecurityErrorCode.IDENTITY_TOKEN_INVALID),
        (
            {"exp": int((NOW - timedelta(seconds=1)).timestamp())},
            SecurityErrorCode.IDENTITY_EXPIRED,
        ),
        (
            {"nbf": int((NOW + timedelta(seconds=1)).timestamp())},
            SecurityErrorCode.IDENTITY_EXPIRED,
        ),
        (
            {"iat": int((NOW + timedelta(seconds=1)).timestamp())},
            SecurityErrorCode.IDENTITY_EXPIRED,
        ),
    ],
)
async def test_user_token_rejects_untrusted_identity_and_time_claims(
    overrides: Mapping[str, object],
    expected_code: SecurityErrorCode,
) -> None:
    adapter, _, nonce_guard = _adapter()
    token = _token({**_base_user_claims(), **overrides})

    with pytest.raises(SecurityError) as raised:
        await adapter.verify_user_token(
            token,
            expected_nonce=USER_NONCE,
            now=NOW,
        )

    assert raised.value.code is expected_code
    assert token not in str(raised.value)
    assert token not in repr(raised.value)
    assert nonce_guard.calls == []


@pytest.mark.asyncio
async def test_algorithm_signature_and_jwks_failures_are_closed_and_safe() -> None:
    adapter, jwks, nonce_guard = _adapter()
    claims = _base_user_claims()
    symmetric = jwt.encode(
        claims,
        "local-test-only-signing-value-32-bytes-minimum",
        algorithm="HS256",
        headers={"kid": USER_KID},
    )
    wrong_signature = _token(claims, key=ROTATED_KEY)
    missing_kid = jwt.encode(claims, USER_KEY, algorithm="RS256")

    for token in (symmetric, wrong_signature, missing_kid):
        with pytest.raises(SecurityError) as raised:
            await adapter.verify_user_token(
                token,
                expected_nonce=USER_NONCE,
                now=NOW,
            )
        assert raised.value.code is SecurityErrorCode.IDENTITY_TOKEN_INVALID
        assert token not in str(raised.value)
        assert token not in repr(raised.value)
    assert nonce_guard.calls == []
    jwks.available = False
    unavailable = _token(claims)
    with pytest.raises(SecurityError) as source_error:
        await adapter.verify_user_token(
            unavailable,
            expected_nonce=USER_NONCE,
            now=NOW,
        )
    assert source_error.value.code is SecurityErrorCode.IDENTITY_SOURCE_UNAVAILABLE
    assert "simulated private" not in str(source_error.value)
    assert unavailable not in str(source_error.value)


@pytest.mark.asyncio
async def test_jwks_signature_rotation_forces_one_refresh() -> None:
    stale = _jwk(USER_KEY, kid=USER_KID)
    rotated = _jwk(ROTATED_KEY, kid=USER_KID)
    jwks = FakeJwksSource(
        {USER_KID: stale},
        refreshed={USER_KID: rotated},
    )
    adapter, _, _ = _adapter(jwks=jwks)
    token = _token(_base_user_claims(), key=ROTATED_KEY)

    identity = await adapter.verify_user_token(
        token,
        expected_nonce=USER_NONCE,
        now=NOW,
    )

    assert identity.subject_id == SUBJECT
    assert jwks.calls == [
        (ISSUER, USER_KID, False),
        (ISSUER, USER_KID, True),
    ]


@pytest.mark.asyncio
async def test_nonce_is_single_use_across_distinct_tokens() -> None:
    adapter, _, nonce_guard = _adapter()
    first = _token(_base_user_claims())
    second = _token(
        {
            **_base_user_claims(),
            "sid": "another-keycloak-session",
            "iat": int((NOW - timedelta(seconds=30)).timestamp()),
        }
    )

    await adapter.verify_user_token(first, expected_nonce=USER_NONCE, now=NOW)
    with pytest.raises(SecurityError) as replay:
        await adapter.verify_user_token(second, expected_nonce=USER_NONCE, now=NOW)

    assert replay.value.code is SecurityErrorCode.NONCE_REPLAY
    assert len(nonce_guard.calls) == 2
    assert nonce_guard.calls[0][0] == nonce_guard.calls[1][0]
    assert USER_NONCE not in repr(nonce_guard.calls)


@pytest.mark.asyncio
async def test_wrong_nonce_and_nonce_source_failure_are_closed_and_safe(
    caplog: pytest.LogCaptureFixture,
) -> None:
    adapter, _, nonce_guard = _adapter()
    token = _token(_base_user_claims())

    with pytest.raises(SecurityError) as mismatch:
        await adapter.verify_user_token(
            token,
            expected_nonce="nonce-that-does-not-match",
            now=NOW,
        )
    assert mismatch.value.code is SecurityErrorCode.NONCE_REPLAY
    assert nonce_guard.calls == []

    nonce_guard.available = False
    with pytest.raises(SecurityError) as unavailable:
        await adapter.verify_user_token(
            token,
            expected_nonce=USER_NONCE,
            now=NOW,
        )
    assert unavailable.value.code is SecurityErrorCode.IDENTITY_SOURCE_UNAVAILABLE
    combined_output = str(unavailable.value) + repr(unavailable.value) + caplog.text
    assert token not in combined_output
    assert USER_NONCE not in combined_output
    assert "simulated private" not in combined_output


@pytest.mark.asyncio
async def test_nonce_guard_rejects_browser_supplied_unissued_nonce() -> None:
    unissued_nonce = "nonce-browser-selected-value"
    adapter, _, nonce_guard = _adapter(nonces=FakeNonceGuard())
    token = _token({**_base_user_claims(), "nonce": unissued_nonce})

    with pytest.raises(SecurityError) as rejected:
        await adapter.verify_user_token(
            token,
            expected_nonce=unissued_nonce,
            now=NOW,
        )

    assert rejected.value.code is SecurityErrorCode.NONCE_REPLAY
    assert len(nonce_guard.calls) == 1
    assert unissued_nonce not in repr(nonce_guard.calls)
    assert token not in str(rejected.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "claim_update",
    [
        {"tenant_id": "external-attacker"},
        {"realm_access": {"roles": ["realm-administrator"]}},
    ],
)
async def test_unknown_tenant_or_role_consumes_server_nonce_before_rejection(
    claim_update: Mapping[str, object],
) -> None:
    adapter, _, nonce_guard = _adapter()
    token = _token({**_base_user_claims(), **claim_update})

    with pytest.raises(SecurityError) as raised:
        await adapter.verify_user_token(
            token,
            expected_nonce=USER_NONCE,
            now=NOW,
        )

    assert raised.value.code is SecurityErrorCode.IDENTITY_MAPPING_DENIED
    assert len(nonce_guard.calls) == 1
    with pytest.raises(SecurityError) as replay:
        await adapter.verify_user_token(
            token,
            expected_nonce=USER_NONCE,
            now=NOW,
        )
    assert replay.value.code is SecurityErrorCode.NONCE_REPLAY


@pytest.mark.asyncio
async def test_browser_claims_cannot_override_server_purpose_or_classification(
) -> None:
    adapter, _, _ = _adapter()
    token = _token(
        {
            **_base_user_claims(),
            "purpose": "break-glass-administration",
            "data_classification_ceiling": "restricted",
            "context_ref": "security-context://attacker/forged",
            "agent_id": "attacker-agent",
        }
    )
    identity = await adapter.verify_user_token(
        token,
        expected_nonce=USER_NONCE,
        now=NOW,
    )
    mapper = TrustedContextMapper(
        TrustedContextMappingPolicy(
            allowed_purposes=frozenset({PURPOSE}),
            data_classification_ceiling=DataClassification.INTERNAL,
            maximum_ttl_seconds=300,
        )
    )

    trusted = mapper.map_user(
        identity=identity,
        reference=SecurityContextReference(
            context_id="secctx_m8server01",
            context_ref="security-context://server-issued/m8-alpha",
        ),
        purpose=PURPOSE,
        now=NOW,
        ttl_seconds=300,
    )

    assert trusted.context.purpose == PURPOSE
    assert trusted.context.data_classification_ceiling is DataClassification.INTERNAL
    assert trusted.context.context_ref == "security-context://server-issued/m8-alpha"
    assert "attacker" not in repr(trusted)


@pytest.mark.asyncio
async def test_gateway_re_resolves_and_rejects_revoked_context_before_side_effects(
) -> None:
    fixture = make_fixture(operation=ToolOperation.READ)
    fixture.context_source.active = False

    execution = await fixture.gateway.execute(fixture.invocation)

    assert execution.result.error_code == SecurityErrorCode.CONTEXT_NOT_ACTIVE.value
    assert fixture.context_source.resolution_count == 1
    assert fixture.adapter.invocation_count == 0
    assert fixture.policy_source.resolve_count == 0
    assert fixture.credentials.issue_count == 0


def test_identity_configuration_rejects_symmetric_algorithms_and_incomplete_registry(
) -> None:
    with pytest.raises(ValueError, match="asymmetric"):
        OidcAudiencePolicy(
            issuer=ISSUER,
            audience=USER_AUDIENCE,
            authorized_parties=frozenset({USER_PARTY}),
            allowed_algorithms=frozenset({"HS256"}),
        )

    with pytest.raises(ValueError, match="registrations"):
        WorkloadClaimPolicy(
            token=OidcAudiencePolicy(
                issuer=ISSUER,
                audience=AUDIENCE,
                authorized_parties=frozenset({WORKLOAD_PARTY}),
            ),
            registrations=(),
        )


def test_verified_identity_types_never_accept_raw_credential_evidence() -> None:
    with pytest.raises(ValueError, match="sha256"):
        RefreshLineageState(
            session_identity_hash="raw-session-identity",
            access_token_hash="raw-access-token",
            access_token_id_hash="raw-jti",
            issued_at=NOW,
            generation=1,
        )

    with pytest.raises(ValueError, match="sha256"):
        VerifiedUserIdentity(
            issuer=ISSUER,
            subject_id=SUBJECT,
            tenant_id=TENANT,
            authorized_party=USER_PARTY,
            roles=frozenset({"requester"}),
            scopes=frozenset({"tasks:read"}),
            assurance_level=AssuranceLevel.HIGH,
            session_id_hash="keycloak-session-raw",
            token_hash="raw-token-value",
            issued_at=NOW,
            expires_at=NOW + timedelta(minutes=5),
        )


def test_attested_workload_requires_complete_strict_oidc_evidence() -> None:
    common = {
        "agent_id": AGENT_ID,
        "agent_version": AGENT_VERSION,
        "principal_ref": AGENT_PRINCIPAL,
        "audience": AUDIENCE,
        "tenant_ids": frozenset({TENANT}),
        "purposes": frozenset({PURPOSE}),
        "allowed_tools": frozenset({"knowledge.search.v1"}),
        "issued_at": NOW - timedelta(minutes=1),
        "expires_at": NOW + timedelta(minutes=5),
    }
    with pytest.raises(ValueError, match="complete OIDC evidence"):
        AuthenticatedWorkload(**common, attested=True)
    with pytest.raises(ValueError, match="lowercase sha256"):
        AuthenticatedWorkload(
            **common,
            attested=True,
            issuer=ISSUER,
            authorized_party=WORKLOAD_PARTY,
            subject_id="service-account-flowpilot-worker",
            credential_hash="sha256:raw-workload-token",
        )


@pytest.mark.asyncio
async def test_context_snapshot_rejects_role_tampering_before_gateway_policy() -> None:
    adapter, _, _ = _adapter()
    identity = await adapter.verify_user_token(
        _token(_base_user_claims()),
        expected_nonce=USER_NONCE,
        now=NOW,
    )
    trusted = TrustedContextMapper(
        TrustedContextMappingPolicy(
            allowed_purposes=frozenset({PURPOSE}),
            data_classification_ceiling=DataClassification.CONFIDENTIAL,
            maximum_ttl_seconds=300,
        )
    ).map_user(
        identity=identity,
        reference=SecurityContextReference(
            context_id="secctx_m8tamper01",
            context_ref="security-context://server-issued/m8-tamper",
        ),
        purpose=PURPOSE,
        now=NOW,
        ttl_seconds=300,
    )
    tampered = replace(trusted, roles=trusted.roles | {"administrator"})

    with pytest.raises(SecurityError) as rejected:
        SecurityVerifier().verify_context(
            presented=trusted.context,
            trusted=tampered,
            now=NOW,
        )

    assert rejected.value.code is SecurityErrorCode.CONTEXT_UNTRUSTED
