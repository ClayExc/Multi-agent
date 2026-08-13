from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from fastapi import FastAPI
from flowpilot_domain import AssuranceLevel, DataClassification
from flowpilot_security import (
    InMemorySecurityContextSource,
    OidcAudiencePolicy,
    OidcIdentityAdapter,
    TrustedContextMapper,
    TrustedContextMappingPolicy,
    UserClaimPolicy,
    WorkloadClaimPolicy,
    WorkloadRegistration,
)

from .app import create_app
from .keycloak import KeycloakOidcConfig, KeycloakOidcProvider
from .oidc import (
    InMemoryOidcSessionStore,
    OidcApiSecurityBundle,
    OidcBffConfig,
    compose_oidc_api_security,
)

_REQUIRED_ENV = (
    "FLOWPILOT_OIDC_ISSUER",
    "FLOWPILOT_OIDC_CLIENT_ID",
    "KEYCLOAK_WEB_CLIENT_SECRET",
    "FLOWPILOT_OIDC_REDIRECT_URI",
    "FLOWPILOT_OIDC_ALLOW_INSECURE_LOOPBACK",
)
_OPTIONAL_ENV = (
    "FLOWPILOT_OIDC_TIMEOUT_SECONDS",
    "FLOWPILOT_OIDC_MAX_RESPONSE_BYTES",
    "FLOWPILOT_OIDC_POST_LOGIN_REDIRECT",
    "FLOWPILOT_OIDC_PURPOSE",
)


@dataclass(frozen=True, slots=True, repr=False)
class LocalKeycloakSettings:
    issuer: str
    client_id: str
    client_secret: str
    redirect_uri: str
    allow_insecure_loopback: bool
    timeout_seconds: float = 5.0
    max_response_bytes: int = 131072
    post_login_redirect: str = "/"
    purpose: str = "it_support"

    def __post_init__(self) -> None:
        KeycloakOidcConfig(
            issuer=self.issuer,
            client_id=self.client_id,
            client_secret=self.client_secret,
            redirect_uri=self.redirect_uri,
            allow_insecure_loopback=self.allow_insecure_loopback,
            timeout_seconds=self.timeout_seconds,
            max_response_bytes=self.max_response_bytes,
        )
        OidcBffConfig(
            issuer=self.issuer.rstrip("/"),
            authorized_party=self.client_id,
            redirect_uri=self.redirect_uri,
            post_login_redirect=self.post_login_redirect,
            purpose=self.purpose,
            allow_insecure_loopback_provider=self.allow_insecure_loopback,
        )

    def __repr__(self) -> str:
        return (
            "LocalKeycloakSettings(issuer="
            f"{self.issuer!r}, client_id={self.client_id!r}, "
            "client_secret=<redacted>, "
            f"redirect_uri={self.redirect_uri!r}, "
            f"allow_insecure_loopback={self.allow_insecure_loopback!r}, "
            f"timeout_seconds={self.timeout_seconds!r}, "
            f"max_response_bytes={self.max_response_bytes!r}, "
            f"post_login_redirect={self.post_login_redirect!r}, "
            f"purpose={self.purpose!r})"
        )

    @classmethod
    def from_mapping(
        cls,
        values: Mapping[str, str],
    ) -> LocalKeycloakSettings | None:
        relevant = _REQUIRED_ENV + _OPTIONAL_ENV
        if not any(key in values for key in relevant):
            return None
        if any(not values.get(key, "").strip() for key in _REQUIRED_ENV):
            raise ValueError("OIDC environment configuration is incomplete")
        try:
            allow_loopback = _parse_bool(
                values["FLOWPILOT_OIDC_ALLOW_INSECURE_LOOPBACK"]
            )
            timeout = float(values.get("FLOWPILOT_OIDC_TIMEOUT_SECONDS", "5"))
            maximum = int(values.get("FLOWPILOT_OIDC_MAX_RESPONSE_BYTES", "131072"))
            return cls(
                issuer=values["FLOWPILOT_OIDC_ISSUER"].strip(),
                client_id=values["FLOWPILOT_OIDC_CLIENT_ID"].strip(),
                client_secret=values["KEYCLOAK_WEB_CLIENT_SECRET"],
                redirect_uri=values["FLOWPILOT_OIDC_REDIRECT_URI"].strip(),
                allow_insecure_loopback=allow_loopback,
                timeout_seconds=timeout,
                max_response_bytes=maximum,
                post_login_redirect=values.get(
                    "FLOWPILOT_OIDC_POST_LOGIN_REDIRECT",
                    "/",
                ).strip(),
                purpose=values.get("FLOWPILOT_OIDC_PURPOSE", "it_support").strip(),
            )
        except (KeyError, TypeError, ValueError):
            raise ValueError("OIDC environment configuration is invalid") from None


def compose_local_keycloak_oidc(
    settings: LocalKeycloakSettings,
    *,
    clock: Callable[[], datetime] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> OidcApiSecurityBundle:
    """Compose the local single-process Keycloak identity boundary.

    The returned BFF and request-security adapter share one session/context
    authority. Callers must inject both members of this bundle together.
    """

    effective_clock = clock or _utc_now
    issuer = settings.issuer.rstrip("/")
    provider = KeycloakOidcProvider(
        KeycloakOidcConfig(
            issuer=issuer,
            client_id=settings.client_id,
            client_secret=settings.client_secret,
            redirect_uri=settings.redirect_uri,
            allow_insecure_loopback=settings.allow_insecure_loopback,
            timeout_seconds=settings.timeout_seconds,
            max_response_bytes=settings.max_response_bytes,
        ),
        transport=transport,
    )
    sessions = InMemoryOidcSessionStore(clock=effective_clock)
    contexts = InMemorySecurityContextSource()
    verifier = OidcIdentityAdapter(
        jwks=provider,
        nonces=sessions,
        refresh_lineage=sessions,
        users=_local_user_policy(issuer, settings.client_id),
        workloads=_local_workload_policy(issuer),
    )
    mapper = TrustedContextMapper(
        TrustedContextMappingPolicy(
            allowed_purposes=frozenset({settings.purpose}),
            data_classification_ceiling=DataClassification.RESTRICTED,
            maximum_ttl_seconds=3600,
        )
    )
    return compose_oidc_api_security(
        provider=provider,
        token_verifier=verifier,
        context_mapper=mapper,
        contexts=contexts,
        sessions=sessions,
        config=OidcBffConfig(
            issuer=issuer,
            authorized_party=settings.client_id,
            redirect_uri=settings.redirect_uri,
            post_login_redirect=settings.post_login_redirect,
            purpose=settings.purpose,
            allow_insecure_loopback_provider=settings.allow_insecure_loopback,
        ),
        clock=effective_clock,
    )


def create_local_keycloak_app(
    settings: LocalKeycloakSettings,
    *,
    clock: Callable[[], datetime] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    bundle = compose_local_keycloak_oidc(
        settings,
        clock=clock,
        transport=transport,
    )
    return create_app(
        request_security=bundle.request_security,
        oidc_bff=bundle.bff,
    )


def create_default_app(
    values: Mapping[str, str] | None = None,
    *,
    clock: Callable[[], datetime] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    settings = LocalKeycloakSettings.from_mapping(
        os.environ if values is None else values
    )
    if settings is None:
        return create_app()
    return create_local_keycloak_app(settings, clock=clock, transport=transport)


def _local_user_policy(issuer: str, client_id: str) -> UserClaimPolicy:
    return UserClaimPolicy(
        token=OidcAudiencePolicy(
            issuer=issuer,
            audience="flowpilot-api",
            authorized_parties=frozenset({client_id}),
            clock_skew_seconds=30,
        ),
        id_token=OidcAudiencePolicy(
            issuer=issuer,
            audience=client_id,
            authorized_parties=frozenset({client_id}),
            clock_skew_seconds=30,
        ),
        tenant_mapping={"tenant-a": "tenant-a", "tenant-b": "tenant-b"},
        roles_claim=("groups",),
        role_mapping={
            "/tenants/tenant-a/users": "requester",
            "/tenants/tenant-a/approvers": "approver",
            "/tenants/tenant-b/users": "requester",
            "/tenants/tenant-b/approvers": "approver",
        },
        scope_mapping={
            "openid": "identity:read",
            "flowpilot-identity": "identity:read",
        },
        assurance_mapping={
            "0": AssuranceLevel.LOW,
            "1": AssuranceLevel.SUBSTANTIAL,
        },
    )


def _local_workload_policy(issuer: str) -> WorkloadClaimPolicy:
    return WorkloadClaimPolicy(
        token=OidcAudiencePolicy(
            issuer=issuer,
            audience="flowpilot-api",
            authorized_parties=frozenset({"flowpilot-worker"}),
            clock_skew_seconds=30,
        ),
        registrations=(
            WorkloadRegistration(
                issuer=issuer,
                authorized_party="flowpilot-worker",
                subject_id="service-account-flowpilot-worker",
                agent_id="flowpilot-worker",
                agent_version="local",
                principal_ref="workload://flowpilot-worker/local",
                tenant_ids=frozenset({"tenant-a", "tenant-b"}),
                purposes=frozenset({"it_support"}),
                allowed_tools=frozenset({"knowledge.search.v1"}),
            ),
        ),
    )


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError("invalid boolean")


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)
