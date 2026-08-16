package flowpilot.authz

import rego.v1

default decisions := [{
    "decision": "deny",
    "reason_codes": ["LOCAL_POLICY_DEFAULT_DENY"],
    "obligations": [],
    "approval_requirements": null,
}]

decisions := [{
    "decision": "allow",
    "reason_codes": ["LOCAL_POLICY_LOW_RISK_TENANT_BOUND"],
    "obligations": [],
    "approval_requirements": null,
}] if {
    input.risk_level == "low"
    input.context.tenant_id == input.action.tenant_id
}
