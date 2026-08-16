from __future__ import annotations

import json
from pathlib import Path

from flowpilot_policy import PolicyBundle

ROOT = Path(__file__).resolve().parents[3]
COMPOSE = (ROOT / "infra/compose/compose.yaml").read_text(encoding="utf-8")
ENVIRONMENT = (ROOT / ".env.example").read_text(encoding="utf-8")
BUNDLE = ROOT / "infra/opa/bundle"


def _bundle() -> PolicyBundle:
    return PolicyBundle.create(
        version="policy-m9-local-v1",
        modules={
            "flowpilot/authz.rego": (BUNDLE / "flowpilot/authz.rego").read_text(
                encoding="utf-8"
            )
        },
        data=json.loads((BUNDLE / "data.json").read_text(encoding="utf-8")),
    )


def test_fixed_bundle_is_versioned_digestible_and_default_deny() -> None:
    manifest = json.loads((BUNDLE / ".manifest").read_text(encoding="utf-8"))
    bundle = _bundle()
    bundle.assert_integrity()
    assert manifest["revision"] == bundle.version
    assert manifest["roots"] == ["flowpilot"]
    assert bundle.digest.startswith("sha256:")
    source = dict(bundle.modules)["flowpilot/authz.rego"]
    assert "default decisions" in source
    assert "LOCAL_POLICY_DEFAULT_DENY" in source
    assert "input.context.tenant_id == input.action.tenant_id" in source


def test_compose_mounts_bundle_and_complete_migration_chain_read_only() -> None:
    assert "005-governance-audit-query.sql:ro" in COMPOSE
    assert COMPOSE.index("004-security-context-rls-binding.sql:ro") < COMPOSE.index(
        "005-governance-audit-query.sql:ro"
    )
    assert "../opa/bundle:/bundle:ro" in COMPOSE
    assert "--bundle" in COMPOSE
    assert "data.flowpilot.authz.decisions" in COMPOSE
    assert "condition: service_completed_successfully" in COMPOSE
    assert "sha256sum -c" in COMPOSE


def test_governance_cursor_secret_has_no_usable_default() -> None:
    lines = {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in ENVIRONMENT.splitlines()
        if line and not line.startswith("#") and "=" in line
    }
    assert lines["FLOWPILOT_GOVERNANCE_CURSOR_HMAC_SECRET"] == ""
    assert "environment: FLOWPILOT_GOVERNANCE_CURSOR_HMAC_SECRET" in COMPOSE
    assert "/run/secrets/governance_cursor_hmac" in COMPOSE
    assert "-ge 32" in COMPOSE
