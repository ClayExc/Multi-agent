from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
REALM_PATH = ROOT / "infra" / "keycloak" / "flowpilot-local-realm.json"
REALM: dict[str, Any] = json.loads(REALM_PATH.read_text(encoding="utf-8"))
REALM_TEXT = REALM_PATH.read_text(encoding="utf-8")
COMPOSE = (ROOT / "infra" / "compose" / "compose.yaml").read_text(
    encoding="utf-8"
)
ENV_EXAMPLE = (ROOT / ".env.example").read_text(encoding="utf-8")
PLACEHOLDER = re.compile(r"^\$\{[A-Z][A-Z0-9_]+\}$")


def _clients() -> dict[str, dict[str, Any]]:
    return {client["clientId"]: client for client in REALM["clients"]}


def _leaf_groups() -> dict[str, dict[str, Any]]:
    root = REALM["groups"]
    assert len(root) == 1 and root[0]["name"] == "tenants"
    result: dict[str, dict[str, Any]] = {}
    for tenant in root[0]["subGroups"]:
        for role_group in tenant["subGroups"]:
            path = f"/tenants/{tenant['name']}/{role_group['name']}"
            result[path] = role_group
    return result


def test_realm_is_local_bounded_and_brute_force_protected() -> None:
    assert REALM["realm"] == "flowpilot-local"
    assert REALM["enabled"] is True
    assert REALM["sslRequired"] == "external"
    assert REALM["registrationAllowed"] is False
    assert REALM["resetPasswordAllowed"] is False
    assert REALM["bruteForceProtected"] is True
    assert REALM["defaultSignatureAlgorithm"] == "RS256"
    assert REALM["revokeRefreshToken"] is True
    assert REALM["refreshTokenMaxReuse"] == 0
    assert 0 < REALM["accessTokenLifespan"] <= 300
    assert 0 < REALM["accessCodeLifespan"] <= 5
    assert 0 < REALM["ssoSessionIdleTimeout"] <= 900
    assert 0 < REALM["ssoSessionMaxLifespan"] <= 3600
    assert REALM["eventsEnabled"] is False
    assert REALM["adminEventsEnabled"] is False


def test_web_and_api_clients_fail_closed() -> None:
    clients = _clients()
    assert set(clients) == {
        "flowpilot-web",
        "flowpilot-api",
        "flowpilot-worker",
        "flowpilot-gateway",
    }
    web = clients["flowpilot-web"]
    assert web["publicClient"] is False
    assert web["clientAuthenticatorType"] == "client-secret"
    assert web["secret"] == "${KEYCLOAK_WEB_CLIENT_SECRET}"
    assert web["standardFlowEnabled"] is True
    assert web["implicitFlowEnabled"] is False
    assert web["directAccessGrantsEnabled"] is False
    assert web["serviceAccountsEnabled"] is False
    assert web["fullScopeAllowed"] is False
    assert web["attributes"]["pkce.code.challenge.method"] == "S256"
    assert web["defaultClientScopes"] == ["flowpilot-identity"]
    assert web["optionalClientScopes"] == []
    assert web["redirectUris"] == ["${FLOWPILOT_OIDC_REDIRECT_URI}"]
    assert web["webOrigins"] == ["${FLOWPILOT_WEB_ORIGIN}"]

    api = clients["flowpilot-api"]
    assert api["bearerOnly"] is True
    assert api["standardFlowEnabled"] is False
    assert api["implicitFlowEnabled"] is False
    assert api["directAccessGrantsEnabled"] is False
    assert api["serviceAccountsEnabled"] is False
    assert api["fullScopeAllowed"] is False


def test_service_clients_use_distinct_secret_audience_and_kind() -> None:
    clients = _clients()
    expectations = {
        "flowpilot-worker": (
            "${KEYCLOAK_WORKER_CLIENT_SECRET}",
            "mcp://flowpilot-gateway",
            "worker",
        ),
        "flowpilot-gateway": (
            "${KEYCLOAK_GATEWAY_CLIENT_SECRET}",
            "mcp://flowpilot-upstream",
            "gateway",
        ),
    }
    for client_id, (secret, audience, kind) in expectations.items():
        client = clients[client_id]
        assert client["publicClient"] is False
        assert client["bearerOnly"] is False
        assert client["standardFlowEnabled"] is False
        assert client["implicitFlowEnabled"] is False
        assert client["directAccessGrantsEnabled"] is False
        assert client["serviceAccountsEnabled"] is True
        assert client["fullScopeAllowed"] is False
        assert client["secret"] == secret
        assert client["defaultClientScopes"] == []
        assert client["optionalClientScopes"] == []
        mappers = {mapper["name"]: mapper for mapper in client["protocolMappers"]}
        audience_mapper = mappers[f"{kind}-audience"]
        assert (
            audience_mapper["config"]["included.custom.audience"] == audience
        )
        kind_mapper = mappers[f"{kind}-kind"]
        assert kind_mapper["config"]["claim.name"] == "workload_kind"
        assert kind_mapper["config"]["claim.value"] == kind


def test_two_tenants_have_user_and_approver_without_literal_passwords() -> None:
    groups = _leaf_groups()
    assert set(groups) == {
        "/tenants/tenant-a/users",
        "/tenants/tenant-a/approvers",
        "/tenants/tenant-b/users",
        "/tenants/tenant-b/approvers",
    }
    users = {user["username"]: user for user in REALM["users"]}
    assert set(users) == {
        "tenant-a-user",
        "tenant-a-approver",
        "tenant-b-user",
        "tenant-b-approver",
    }
    for tenant_id in ("tenant-a", "tenant-b"):
        for suffix in ("user", "approver"):
            user = users[f"{tenant_id}-{suffix}"]
            assert user["firstName"] == f"Tenant {tenant_id[-1].upper()}"
            assert user["lastName"] == suffix.title()
            assert user["attributes"]["tenant_id"] == [tenant_id]
            group_suffix = "users" if suffix == "user" else "approvers"
            group_path = f"/tenants/{tenant_id}/{group_suffix}"
            assert user["groups"] == [group_path]
            group = groups[group_path]
            assert group["attributes"]["tenant_id"] == [tenant_id]
            assert "flowpilot-user" in group["realmRoles"]
            assert ("flowpilot-approver" in group["realmRoles"]) is (
                suffix == "approver"
            )
            credential = user["credentials"]
            assert len(credential) == 1
            assert credential[0]["type"] == "password"
            assert credential[0]["temporary"] is False
            assert PLACEHOLDER.fullmatch(credential[0]["value"])


def test_realm_contains_only_environment_secret_placeholders() -> None:
    clients = _clients()
    assert PLACEHOLDER.fullmatch(clients["flowpilot-web"]["secret"])
    assert PLACEHOLDER.fullmatch(clients["flowpilot-worker"]["secret"])
    assert PLACEHOLDER.fullmatch(clients["flowpilot-gateway"]["secret"])
    for forbidden in (
        "local-dev-",
        "BEGIN PRIVATE KEY",
        "Bearer ",
        "eyJhbGci",
    ):
        assert forbidden not in REALM_TEXT


def test_compose_imports_realm_with_required_process_secrets() -> None:
    assert "--import-realm" in COMPOSE
    assert "../keycloak/flowpilot-local-realm.json:" in COMPOSE
    assert "/opt/keycloak/data/import/flowpilot-local-realm.json:ro" in COMPOSE
    assert "keycloak-data:/opt/keycloak/data" in COMPOSE
    assert "/health/ready" in COMPOSE
    assert "127.0.0.1/9000" in COMPOSE
    assert "9000:9000" not in COMPOSE
    required = {
        "FLOWPILOT_WEB_ORIGIN",
        "FLOWPILOT_OIDC_REDIRECT_URI",
        "KEYCLOAK_WEB_CLIENT_SECRET",
        "KEYCLOAK_WORKER_CLIENT_SECRET",
        "KEYCLOAK_GATEWAY_CLIENT_SECRET",
        "KEYCLOAK_TENANT_A_USER_PASSWORD",
        "KEYCLOAK_TENANT_A_APPROVER_PASSWORD",
        "KEYCLOAK_TENANT_B_USER_PASSWORD",
        "KEYCLOAK_TENANT_B_APPROVER_PASSWORD",
    }
    for variable in required:
        assert f"${{{variable}:?" in COMPOSE
        line = next(
            line for line in ENV_EXAMPLE.splitlines() if line.startswith(variable)
        )
        assert line.endswith("change-me") or line.startswith(
            ("FLOWPILOT_WEB_ORIGIN=", "FLOWPILOT_OIDC_REDIRECT_URI=")
        )
