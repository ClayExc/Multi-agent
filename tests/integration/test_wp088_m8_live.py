from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_live_identity_result_is_fail_closed() -> None:
    result = json.loads(
        (ROOT / "tests/integration/evidence/WP-088-a1-PROOF.json").read_text()
    )["end_to_end_live"]
    assert {
        key: result[key]
        for key in (
            "code_pkce_callbacks",
            "opaque_cookie_sessions",
            "same_second_refreshes",
            "concurrent_refresh_successes",
            "concurrent_refresh_rejections",
            "logout_successes",
            "revoked_session_rejections",
            "cross_tenant_successful_reads",
            "model_calls",
            "tool_calls",
        )
    } == {
        "code_pkce_callbacks": 1,
        "opaque_cookie_sessions": 1,
        "same_second_refreshes": 1,
        "concurrent_refresh_successes": 1,
        "concurrent_refresh_rejections": 1,
        "logout_successes": 1,
        "revoked_session_rejections": 1,
        "cross_tenant_successful_reads": 0,
        "model_calls": 0,
        "tool_calls": 0,
    }


def test_live_crypto_result_uses_real_jwks_and_rejects_every_negative() -> None:
    result = json.loads(
        (ROOT / "tests/integration/evidence/WP-088-a1-PROOF.json").read_text()
    )["signed_token_live_crypto"]
    assert result["valid_pairs"] == 1
    assert result["raw_token_output_count"] == 0
    assert all(
        result[name] == 1
        for name in (
            "wrong_nonce_rejections",
            "nonce_replay_rejections",
            "token_swap_rejections",
            "wrong_audience_rejections",
            "tenant_mapping_rejections",
            "role_mapping_rejections",
        )
    )


def test_durable_verifier_injects_mandatory_production_validator() -> None:
    path = ROOT / "scripts/integration/verify_durable_recovery.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    builds = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "build_durable_runtime"
    ]
    assert len(builds) == 3
    assert all(
        any(item.arg == "security_contexts" for item in call.keywords)
        for call in builds
    )
    source = path.read_text(encoding="utf-8")
    assert "RuntimeSecurityContextValidator(" in source
    assert "PostgresSecurityContextSource(" in source
    assert "Noop" not in source
