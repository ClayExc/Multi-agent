# FlowPilot Security

This package verifies that a public `SecurityContextRef` matches a currently
trusted server-side identity record and that the authenticated workload
principal matches the declared Agent.

It never accepts tenant, role, audience, or credential claims from model
output. Capability credentials are represented by opaque, audience-bound,
short-lived handles; raw tokens are not returned by this package and are
forbidden from lifecycle, Audit, Security, and debug projections.
