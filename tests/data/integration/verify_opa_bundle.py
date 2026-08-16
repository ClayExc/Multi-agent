from __future__ import annotations

import hashlib
import json
import os

import httpx


def decision(base_url: str, input_document: dict[str, object]) -> list[object]:
    response = httpx.post(
        f"{base_url.rstrip('/')}/v1/data/flowpilot/authz/decisions",
        json={"input": input_document},
        timeout=10,
    )
    response.raise_for_status()
    payload = response.json()
    result = payload.get("result")
    if not isinstance(result, list):
        raise RuntimeError("OPA returned no closed decision list")
    return result


def outcome(results: list[object]) -> str:
    if len(results) != 1 or not isinstance(results[0], dict):
        raise RuntimeError("OPA returned a non-closed decision shape")
    value = results[0].get("decision")
    if not isinstance(value, str):
        raise RuntimeError("OPA decision outcome is invalid")
    return value


def main() -> None:
    base_url = os.environ["FLOWPILOT_TEST_OPA_URL"]
    deny = decision(base_url, {})
    wrong_tenant = decision(
        base_url,
        {
            "risk_level": "low",
            "context": {"tenant_id": "tenant-a"},
            "action": {"tenant_id": "tenant-b"},
        },
    )
    allow = decision(
        base_url,
        {
            "risk_level": "low",
            "context": {"tenant_id": "tenant-a"},
            "action": {"tenant_id": "tenant-a"},
        },
    )
    if outcome(deny) != "deny":
        raise RuntimeError("OPA default was not deny")
    if outcome(wrong_tenant) != "deny":
        raise RuntimeError("OPA allowed a cross-tenant input")
    if outcome(allow) != "allow":
        raise RuntimeError("OPA rejected the exact low-risk tenant binding")
    shape = json.dumps(
        [sorted(item) for item in (deny[0], allow[0]) if isinstance(item, dict)],
        separators=(",", ":"),
    ).encode()
    print(
        "OPA_BUNDLE_OK default_deny=1 cross_tenant_allow=0 exact_allow=1 "
        f"shape_digest=sha256:{hashlib.sha256(shape).hexdigest()}"
    )


if __name__ == "__main__":
    main()
