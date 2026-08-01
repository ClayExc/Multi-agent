"""Fix up synthetic fixture digests so the data is self-consistent.

Computes and back-fills:
- planned-action digest -> approvals.v1.json action_digest and
  events.v1.json task.approval.required.v1 payload action_digest
- command idempotency_key and command_digest for commands.v1.json
- file sha256 entries in manifest.json

Digest semantics mirror flowpilot_domain.canonical.canonical_sha256
(RFC 8785 canonical JSON + SHA-256). This script is an authoring helper
for the web fixture set; run it with the workspace interpreter:

    uv run --frozen python web/tools/fixup_fixtures.py

It rewrites the fixture files in place (deterministic output).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parents[1]
FIXTURES = WEB / "fixtures"


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_hex(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def load(name: str) -> dict:
    with (FIXTURES / name).open(encoding="utf-8") as handle:
        return json.load(handle)


def dump(name: str, data: dict) -> None:
    path = FIXTURES / name
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    planned = load("planned-actions.v1.json")["planned_actions"]
    approvals = load("approvals.v1.json")
    events = load("events.v1.json")
    commands = load("commands.v1.json")

    digests_by_action: dict[str, str] = {}
    for action in planned:
        digests_by_action[action["action_id"]] = sha256_hex(action)

    digests_by_approval: dict[str, str] = {}
    for approval in approvals["approvals"]:
        digest = digests_by_action[approval["action_id"]]
        digests_by_approval[approval["approval_id"]] = digest
        approval["action_digest"] = digest
    dump("approvals.v1.json", approvals)

    for event in events["events"]:
        if event["event_type"] != "task.approval.required.v1":
            continue
        approval_id = event["payload"]["approval_id"]
        event["payload"]["action_digest"] = digests_by_approval[approval_id]
    dump("events.v1.json", events)

    for command in commands["commands"]:
        digest_projection = {
            "command_type": command["command_type"],
            "tenant_id": command["tenant_id"],
            "task_id": command["task_id"],
            "actor": command["actor"],
            "expected_task_version": command["expected_task_version"],
            "payload": command["payload"],
        }
        command["command_digest"] = sha256_hex(digest_projection)
        command["idempotency_key"] = sha256_hex(
            {
                "command_type": command["command_type"],
                "tenant_id": command["tenant_id"],
                "task_id": command["task_id"],
                "payload": command["payload"],
            }
        )
    dump("commands.v1.json", commands)

    manifest = load("manifest.json")
    for name in sorted(manifest["entries"]):
        raw = (FIXTURES / name).read_bytes()
        manifest["entries"][name]["sha256"] = (
            "sha256:" + hashlib.sha256(raw).hexdigest()
        )
    dump("manifest.json", manifest)

    print(
        "fixed up "
        f"{len(planned)} planned actions, {len(approvals['approvals'])} "
        f"approvals, {len(commands['commands'])} commands"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
