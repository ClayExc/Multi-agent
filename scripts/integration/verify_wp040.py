"""Reproduce WP-040 candidate or S1 final static composition evidence.

The verifier is deliberately read-only with respect to Git and product sources.
It emits deterministic artifacts below ``artifacts/integration/runs`` when an
output directory is supplied. Runtime, wheel, database, and Compose results are
recorded separately in the S7 handoff. The default phase preserves WP-040-a1
candidate output; ``S1_FINAL`` adds final-branch and invariant checks.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
import tomllib
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

BASE_COMMIT = "55125ae3992311eab03cc888ea9c908486b4b727"
CONTROL_HEAD = "6a16320a16fc76f2a5ffdedfc0ab893c87a636fa"
COMMON_MERGE_BASE = "93597a5023320d48875b292dc08106f03227a3fb"
CANDIDATE_MERGE_HEAD = "56c90b1355213357415778bda43fc3acf96aa8ed"
S7_CANDIDATE_HEAD = "4314766c0cfb57c3332a5fc0b0c27395e93cf879"
S1_FINAL_TEST_HEAD = "9b166f8cbc6a85fc036458c5d88caf1ec10feacf"
CANDIDATE_BRANCH = "codex/s7/wp-040-integration-verification"
CONTRACT_DIGEST = (
    "sha256:0a82e7f58c4223362721c95a50e9a820"
    "d714e550e72eebc7a90ab01e283100fc"
)
CONTRACT_TREE = "3b67857c6aacce574080089ce1d8b763dd766a77"
LOCK_DIGEST = (
    "sha256:eb0f7ef676b42d81bd60d47de02b2021"
    "97cc6d300ae8d4715814c3ebf3da70f8"
)

INPUTS: dict[str, dict[str, Any]] = {
    "S2-RUNTIME": {
        "base": "34bec05003cb59b3e16f1a16ae166b1f77465c46",
        "head": "c3da3118eac5ee7d57c6b333c2aac3a0f119d799",
        "commit_count": 3,
        "handoff": "tests/runtime/evidence/WP-010-a2-HANDOFF.md",
        "handoff_sha256": (
            "d27b4fae55b8006a5337184ff0754fd6"
            "f037e86a2b8577b1cf991a6c1618bb83"
        ),
        "allowed": (
            "apps/worker/",
            "packages/graph/",
            "packages/agent-runtime/",
            "packages/model-gateway/",
            "packages/context/",
            "tests/runtime/",
        ),
    },
    "S5-CORE": {
        "base": "0be20f5b56d330f4da494ce4c3d46b183b09ae8b",
        "head": "315822de1c8a50f5ede304836686ce5e63f9ad1d",
        "commit_count": 1,
        "handoff": "tests/core/evidence/WP-011-a3-HANDOFF.md",
        "handoff_sha256": (
            "8db60024d62b63c03b8f9fdc7abdce3"
            "8a6eb3b861e27411805b2ed38c5afe5fe"
        ),
        "allowed": ("uv.lock", "tests/core/"),
    },
    "S6-DATA": {
        "base": "3e0101999061a44a3a5b2fd455ec792e3f73954e",
        "head": "e41f0266e6e588417332043b68a3309b2d40bcf7",
        "commit_count": 2,
        "handoff": "tests/data/evidence/WP-021-a2/HANDOFF.md",
        "handoff_sha256": (
            "da2f44abc2c9f34f8549df905898949b"
            "c6de59ac419232a2f2654efa19ccd479"
        ),
        "allowed": (
            "packages/persistence/",
            "migrations/",
            "tests/data/",
        ),
    },
}

TEMPORARY_CONSTRUCTION: tuple[tuple[str, str], ...] = (
    ("S5-CORE", "8f162841cec085221320c638d2ec7f1c04308cff"),
    ("S6-DATA", "9e8f427e5b02f9e48252ef706ebc9b82f31f1aa3"),
    ("S2-RUNTIME", CANDIDATE_MERGE_HEAD),
)

WORKSPACE_PACKAGES: dict[str, str] = {
    "apps/api": "flowpilot-api",
    "apps/worker": "flowpilot-worker",
    "packages/agent-runtime": "flowpilot-agent-runtime",
    "packages/application": "flowpilot-application",
    "packages/context": "flowpilot-context",
    "packages/domain": "flowpilot-domain",
    "packages/graph": "flowpilot-graph",
    "packages/model-gateway": "flowpilot-model-gateway",
    "packages/persistence": "flowpilot-persistence",
}

MIGRATION_HASHES = {
    "migrations/0001_persistence_baseline.down.sql": (
        "c7efb33a30dae969d2dba39a06b92186"
        "3390794ec618188bf9ea0969a42c56df"
    ),
    "migrations/0001_persistence_baseline.sql": (
        "0a6c20e172f59c5c70cdd9370c996672"
        "a79841771575541c3c8bc372f38808cd"
    ),
    "migrations/0002_checkpoint_sequence_cas.down.sql": (
        "beb71df8b0f82fdc11f9b59a3f323f9"
        "d43857356b76d136742f43fc67ff1f22c"
    ),
    "migrations/0002_checkpoint_sequence_cas.sql": (
        "e5ca8fca2de8e913caedd488821356e4"
        "41b2adc5ae72a20d015fe4df5b403112"
    ),
}

CONTRACT_CONTENT_FIELDS = (
    "$schema",
    "contract_set_id",
    "version",
    "digest_profile",
    "owner",
    "published_on",
    "supersedes",
    "required_reviewers",
    "freeze_requirements",
    "schemas",
    "artifacts",
    "release_dependencies",
)

S7_ALLOWED_PREFIXES = (
    "scripts/integration/",
    "tests/integration/",
    "artifacts/integration/",
)

S1_EXACT_PATHS = {
    "AGENTS.md",
    "README.md",
    "STRUCTURE.md",
    "WORKFLOW.md",
}

S1_ALLOWED_PREFIXES = (
    "contracts/",
    "docs/architecture/",
    "docs/acceptance/",
    "docs/decisions/",
    "docs/roadmap/",
    "docs/review/",
    "docs/team/",
)

S1_ALLOWED_SHARED_PATHS = {".gitignore"}

FINAL_PROTECTED_PATHS = (
    ".env.example",
    "Makefile",
    "apps",
    "domain-packs",
    "infra",
    "migrations",
    "packages",
    "pyproject.toml",
    "tests/core",
    "tests/data",
    "tests/runtime",
    "uv.lock",
)

M1_CHAIN_ID = "CHAIN-M1-PLATFORM-01"
M1_ACTIVATION_COMMIT = "c4062b2ac6a81aba4e3e1ac63cc01f54efecfed0"
M1_PLATFORM_HEAD = "ff6cc282c81166317f995b975491167479aa1c8d"
M1_WORKSPACE_IMPLEMENTATION_HEAD = (
    "fe5ed876278fd82ea6be08f6a416fa0f0dbcad89"
)
M1_WORKSPACE_HEAD = "192ebe38df84ed9097e4045847aa991632a2ff63"
M1_QUALITY_IMPLEMENTATION_HEAD = (
    "a27b8de946448bb027717001e8ef80b7a598f65d"
)
M1_INPUT_HEAD = "31f4b8b14150bd769910f144d9116578be6124ad"
M1_AUTHORITY_COMMIT = "1ae7a79dd7e0d4da819b93dfa0d916771fb0d265"
M1_AUTHORITY_PATH = (
    "docs/team/chain-authorizations/CHAIN-M1-PLATFORM-01.md"
)
M1_AUTHORITY_SHA256 = (
    "8279803e3b478196fe97757c638e53d93442ee266555606458053dd38ad1c8bf"
)
M1_LOCK_DIGEST = (
    "sha256:5111ba07d45f7d9ad3e1440663f6da2f"
    "4cfa078c4f52032621cd8cd6b89f08f1"
)

M1_WORKSPACE_PACKAGES: dict[str, str] = {
    "apps/api": "flowpilot-api",
    "apps/mcp-gateway": "flowpilot-mcp-gateway",
    "apps/worker": "flowpilot-worker",
    "mcp-servers/knowledge": "flowpilot-mcp-knowledge",
    "packages/agent-runtime": "flowpilot-agent-runtime",
    "packages/application": "flowpilot-application",
    "packages/context": "flowpilot-context",
    "packages/domain": "flowpilot-domain",
    "packages/graph": "flowpilot-graph",
    "packages/model-gateway": "flowpilot-model-gateway",
    "packages/persistence": "flowpilot-persistence",
    "packages/policy": "flowpilot-policy",
    "packages/security": "flowpilot-security",
    "packages/tool-contracts": "flowpilot-tool-contracts",
}

M1_EVIDENCE: dict[str, tuple[str, str, str]] = {
    "S3_HANDOFF": (
        M1_PLATFORM_HEAD,
        "tests/platform/evidence/WP-020-a1/HANDOFF.md",
        "3a9fae37edecce2bf2251ae0d5b35f3dd9e79d69567cb7628aed99bcc6e0e888",
    ),
    "S5_HANDOFF": (
        M1_WORKSPACE_HEAD,
        "tests/core/evidence/WP-011-a4-HANDOFF.md",
        "e2bdf0c50f7a07a6ad345491abc70d7e11e994ac696b2e4a8ace8d931489d6fc",
    ),
    "S4_HANDOFF": (
        M1_INPUT_HEAD,
        "tests/acceptance/evidence/WP-030-a2-HANDOFF.md",
        "42a2e3dc20751598174e5c85f959ead00d3cf2146a82851704ced5f3e5d3a48a",
    ),
    "S4_PROOF": (
        M1_INPUT_HEAD,
        "tests/acceptance/evidence/WP-030-a2-PROOF.json",
        "bb118a6f48ef288e081d1d3c08b7f9bcacb7d9edeb9e8d83af6e4f91150e0f67",
    ),
}

M1_PRODUCT_PATHS = (
    ".env.example",
    "Makefile",
    "apps",
    "artifacts/acceptance",
    "domain-packs",
    "infra",
    "mcp-servers",
    "migrations",
    "packages",
    "pyproject.toml",
    "tests/acceptance",
    "tests/core",
    "tests/data",
    "tests/platform",
    "tests/runtime",
    "uv.lock",
)

M2_CHAIN_ID = "CHAIN-M2-STUDIO-01"
M2_ACTIVATION_COMMIT = "31f244c7ab28f8c635cc973dab1f591b55105429"
M2_WORKSPACE_IMPLEMENTATION_HEAD = (
    "19fa132e4a9a4d1bc71d7951c5c2645af9e39e30"
)
M2_WORKSPACE_HEAD = "c6b250e3b3a5b7df93b60857b5ee438027ee2ff3"
M2_RUNTIME_IMPLEMENTATION_HEAD = (
    "de5e41b7ecc9732fccde3fe1b068f1f1fba11115"
)
M2_RUNTIME_HEAD = "cf5102d1ff66d3fd04362d68f48a6aba9b32acfa"
M2_QUALITY_IMPLEMENTATION_HEAD = (
    "14d0d560864ddc903355d6d132e0afbb03442652"
)
M2_INPUT_HEAD = "8a351326ad33db195098ffd4c2f8a4b9f6b5a598"
M2_AUTHORITY_PATH = (
    "docs/team/chain-authorizations/CHAIN-M2-STUDIO-01.md"
)
M2_AUTHORITY_SHA256 = (
    "b0e5d99b0994c7b437138b7e83740c8f"
    "0cff6c23af084c807e2dde09e326ad04"
)
M2_LOCK_DIGEST = (
    "sha256:9c9ab3febad1a13571d51e567c6546f2"
    "7be809f86927e03b0e64339e4ac957c2"
)
M2_EVIDENCE: dict[str, tuple[str, str, str]] = {
    "S5_HANDOFF": (
        M2_WORKSPACE_HEAD,
        "tests/core/evidence/WP-011-a5-HANDOFF.md",
        "98e1e1e4442dfe7bdce2f309a9e516ea223173d126680257451c17203c49e799",
    ),
    "S2_HANDOFF": (
        M2_RUNTIME_HEAD,
        "tests/runtime/evidence/WP-012-a1-HANDOFF.md",
        "e9542a5c95592679f2e4fac29fefcd36b97531c59b22fe99c876a6298c730ce3",
    ),
    "S4_HANDOFF": (
        M2_INPUT_HEAD,
        "tests/acceptance/evidence/WP-030-a3-HANDOFF.md",
        "d5ab849a707d91468c2dd5876ae69271b518d0c26865fba2251d60dc176fa712",
    ),
    "S4_PROOF": (
        M2_INPUT_HEAD,
        "tests/acceptance/evidence/WP-030-a3-PROOF.json",
        "027346eaf7b4ec620804c7c08b39ce8b5cfbc4616e18339cd0e9928f3b329dcd",
    ),
}
M2_AGENT_SERVER_VERSIONS = {
    "langgraph-api": "0.11.2",
    "langgraph-cli": "0.4.31",
    "langgraph-runtime-inmem": "0.31.2",
    "langgraph-sdk": "0.4.2",
}
M2_PRODUCT_PATHS = (
    ".env.example",
    "Makefile",
    "apps",
    "artifacts/acceptance",
    "domain-packs",
    "infra",
    "langgraph.json",
    "mcp-servers",
    "migrations",
    "packages",
    "pyproject.toml",
    "tests/acceptance",
    "tests/core",
    "tests/data",
    "tests/platform",
    "tests/runtime",
    "uv.lock",
)

P1_CHAIN_ID = "CHAIN-P1-VPN-READONLY-01"
P1_ACTIVATION_COMMIT = "3256f064423f4b80a610b7efeefbdc5584e9e236"
P1_CORE_IMPLEMENTATION_HEAD = "64538c382acd6ded91e8ffb4ced35d6af1dc8486"
P1_CORE_HEAD = "1d6870764464cd4762351e7cf278bacd8e4fbced"
P1_PLATFORM_IMPLEMENTATION_HEAD = "371236a776d75fbdc81c323ba1948f0cd53012d6"
P1_PLATFORM_HEAD = "d360f0351520790c86b9c2cc9a7e8c08222a38f9"
P1_RUNTIME_IMPLEMENTATION_HEAD = "d3f40bc9d1c1da9fd315fbee9057a22c60165371"
P1_RUNTIME_HEAD = "c5c118d808931492d7ee44455b1c2a9360625675"
P1_QUALITY_HEADS = (
    "5a796c4f5138701aa20879af71263d57ec4a1b8b",
    "2a284fc5f6ea2c243370648fa4487e4f212b6b1b",
    "99a60f21e0b114b19be9c5b35d912b202e461e14",
)
P1_QUALITY_IMPLEMENTATION_HEAD = P1_QUALITY_HEADS[-1]
P1_INPUT_HEAD = "4792098ecfe3d4723c04ece8cf9c8d62fcf02d0e"
P1_AUTHORITY_PATH = (
    "docs/team/chain-authorizations/CHAIN-P1-VPN-READONLY-01.md"
)
P1_AUTHORITY_SHA256 = (
    "0bfd8ad41a82b924822074bdae7e284c"
    "160fd22929d65eb04d83b18b71cf5299"
)
P1_KNOWLEDGE_SCHEMA_PIN = (
    "sha256:b7679fde5be1187e8a36b4cd4dd95a95"
    "b63a50dc56532294174b0088f0e6600b"
)
P1_DATASET_CARD_SHA256 = (
    "62001f93322878116e6fbaf59af6ccd1c"
    "faf8f1b009e55164019fc1c5a1ddfad"
)
P1_CASE_FILE_SHA256 = (
    "fb99e39f558967612f42d84b450729323"
    "e8681caf07616e02264e42a3df54f39"
)
P1_LOCK_DIGEST = M2_LOCK_DIGEST
P1_EVIDENCE: dict[str, tuple[str, str, str]] = {
    "S5_HANDOFF": (
        P1_CORE_HEAD,
        "tests/core/evidence/WP-011-a6-HANDOFF.md",
        "413e59aa5177827185a294f2af795fc7f86a02aa19496eab1884433f9fa66c44",
    ),
    "S3_HANDOFF": (
        P1_PLATFORM_HEAD,
        "tests/platform/evidence/WP-020-a2/HANDOFF.md",
        "d130501fdf0f5a032a174fa3171406d6920f930d2792ee48ca61922d6ba1ec1f",
    ),
    "S2_HANDOFF": (
        P1_RUNTIME_HEAD,
        "tests/runtime/evidence/WP-010-a3-HANDOFF.md",
        "27fa68887d6a68d3566f23f8323b776ba966a3054cdd45b91d9833538615cb67",
    ),
    "S4_HANDOFF": (
        P1_INPUT_HEAD,
        "tests/acceptance/evidence/WP-030-a4-HANDOFF.md",
        "b785b6607cc93a595a78e92dc28d924d52b704f666a41f34933e0f2d7103cf98",
    ),
    "S4_PROOF": (
        P1_INPUT_HEAD,
        "tests/acceptance/evidence/WP-030-a4-PROOF.json",
        "44b48979e439c1bbdca970459cdad7ced3478d4f895aadcdca3484a23fc8a7aa",
    ),
}
P1_PRODUCT_PATHS = (
    ".env.example",
    "Makefile",
    "apps",
    "artifacts/acceptance",
    "domain-packs",
    "evals",
    "infra",
    "langgraph.json",
    "mcp-servers",
    "migrations",
    "packages",
    "pyproject.toml",
    "tests/acceptance",
    "tests/core",
    "tests/data",
    "tests/experience",
    "tests/platform",
    "tests/runtime",
    "uv.lock",
    "web",
)

P2_CHAIN_ID = "CHAIN-P2-DURABLE-RUNTIME-01"
P2_ACTIVATION_COMMIT = "c51026cfa50be6e7e060266f16e2f82b68cfcac9"
P2_CONTROL_HEAD = "74326bb188d3db76d19ca4a4138bf38d11e52d6b"
P2_DATA_IMPLEMENTATION_HEAD = "f666ad49f3909815a2d597e0ee9f40955eb717a1"
P2_DATA_HEAD = "36e25279d6b4e02e7471c242ed2bd71dfc0a5dbc"
P2_RUNTIME_IMPLEMENTATION_HEAD = "e0354aaefa0eb2a559b251c9c02cd3069a3194d3"
P2_INPUT_HEAD = "052e61beff5711e3e69dbaf45b792ad8d1a309dc"
P2_AUTHORITY_PATH = (
    "docs/team/chain-authorizations/CHAIN-P2-DURABLE-RUNTIME-01.md"
)
P2_AUTHORITY_SHA256 = (
    "0e171dd25f3cb83b36fbf4da6910b745"
    "859c23d601cc75eec9f311ee4e0bbc34"
)
P2_REGISTRY_PATH = (
    "docs/team/agent-registrations/CHAIN-P2-DURABLE-RUNTIME-01.md"
)
P2_REGISTRY_SHA256 = (
    "6062a4f58524e21af78df38197c5892c"
    "0d09fef0e188fc97933c28ebaef688a9"
)
P2_EVIDENCE: dict[str, tuple[str, str, str]] = {
    "S6_HANDOFF": (
        P2_DATA_HEAD,
        "tests/data/evidence/WP-021-a3-HANDOFF.md",
        "17759d0beca2644cfa5910bdf1d5327c924438a28eafc47434ea394b13ee1823",
    ),
    "S2_HANDOFF": (
        P2_INPUT_HEAD,
        "tests/runtime/evidence/WP-010-a4-HANDOFF.md",
        "5fb65bcb3f2c2e47ae081c70201e282d3d1d6e85b83b3800da076f4d1b6b24d1",
    ),
    "CHAIN_AUTHORITY": (
        P2_INPUT_HEAD,
        P2_AUTHORITY_PATH,
        P2_AUTHORITY_SHA256,
    ),
    "AGENT_REGISTRY": (
        P2_INPUT_HEAD,
        P2_REGISTRY_PATH,
        P2_REGISTRY_SHA256,
    ),
}
P2_PRODUCT_PATHS = (
    ".env.example",
    "Makefile",
    "apps",
    "artifacts/acceptance",
    "domain-packs",
    "evals",
    "infra",
    "langgraph.json",
    "mcp-servers",
    "migrations",
    "packages",
    "pyproject.toml",
    "tests/acceptance",
    "tests/core",
    "tests/data",
    "tests/experience",
    "tests/platform",
    "tests/runtime",
    "uv.lock",
    "web",
)

HIGH_CONFIDENCE_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
)


class ValidationPhase(StrEnum):
    S7_CANDIDATE = "S7_CANDIDATE"
    S1_FINAL = "S1_FINAL"
    M1_PLATFORM_CANDIDATE = "M1_PLATFORM_CANDIDATE"
    M1_PLATFORM_S1_FINAL = "M1_PLATFORM_S1_FINAL"
    M2_STUDIO_CANDIDATE = "M2_STUDIO_CANDIDATE"
    M2_STUDIO_S1_FINAL = "M2_STUDIO_S1_FINAL"
    P1_VPN_CANDIDATE = "P1_VPN_CANDIDATE"
    P1_VPN_S1_FINAL = "P1_VPN_S1_FINAL"
    P2_DURABLE_CANDIDATE = "P2_DURABLE_CANDIDATE"
    P2_DURABLE_S1_FINAL = "P2_DURABLE_S1_FINAL"


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    outcome: str
    evidence: str


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def revision_file_bytes(repo: Path, revision: str, path: str) -> bytes:
    completed = subprocess.run(
        ("git", "-C", str(repo), "show", f"{revision}:{path}"),
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"git show {revision}:{path} failed: {detail or 'missing object'}"
        )
    return completed.stdout


def revision_file_text(repo: Path, revision: str, path: str) -> str:
    return revision_file_bytes(repo, revision, path).decode(
        "utf-8",
        errors="strict",
    )


def run_git(repo: Path, *args: str, check: bool = True) -> str:
    completed = subprocess.run(
        ("git", "-C", str(repo), *args),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if check and completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {detail}")
    return completed.stdout.strip()


def load_json(path: Path) -> Any:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicate_keys,
    )


def rfc8785_canonical_bytes(value: Any) -> bytes:
    """Canonicalize FlowPilot's integer-only I-JSON contract profile."""

    def encode(item: Any) -> str:
        if item is None:
            return "null"
        if item is True:
            return "true"
        if item is False:
            return "false"
        if isinstance(item, int):
            if not -(2**53 - 1) <= item <= 2**53 - 1:
                raise ValueError("integer exceeds the I-JSON safe range")
            return str(item)
        if isinstance(item, float):
            raise ValueError("FlowPilot contract digests reject floats")
        if isinstance(item, str):
            return json.dumps(item, ensure_ascii=False, separators=(",", ":"))
        if isinstance(item, list):
            return "[" + ",".join(encode(child) for child in item) + "]"
        if isinstance(item, dict):
            if any(not isinstance(key, str) for key in item):
                raise ValueError("RFC 8785 object keys must be strings")
            keys = sorted(
                item,
                key=lambda key: key.encode("utf-16-be", errors="strict"),
            )
            encoded = (f"{encode(key)}:{encode(item[key])}" for key in keys)
            return "{" + ",".join(encoded) + "}"
        raise ValueError(f"unsupported RFC 8785 value: {type(item)!r}")

    return encode(value).encode("utf-8", errors="strict")


def contract_content_digest(manifest: dict[str, Any]) -> str:
    projection = {field: manifest[field] for field in CONTRACT_CONTENT_FIELDS}
    digest = sha256_bytes(rfc8785_canonical_bytes(projection))
    return f"sha256:{digest}"


def is_allowed_path(path: str, allowed: Iterable[str]) -> bool:
    normalized = path.replace("\\", "/")
    return any(
        normalized == item or normalized.startswith(item)
        for item in allowed
    )


def changed_paths(repo: Path, base: str, head: str) -> list[str]:
    output = run_git(repo, "diff", "--name-only", base, head)
    return sorted(line for line in output.splitlines() if line)


def changed_path_statuses(
    repo: Path,
    base: str,
    head: str,
) -> list[tuple[str, str]]:
    output = run_git(repo, "diff", "--name-status", base, head)
    changes: list[tuple[str, str]] = []
    for line in output.splitlines():
        if not line:
            continue
        fields = line.split("\t")
        status = fields[0]
        paths = fields[1:]
        if status.startswith(("R", "C")):
            changes.extend((status, path) for path in paths)
        elif len(paths) == 1:
            changes.append((status, paths[0]))
        else:
            raise ValueError(f"unexpected git name-status line: {line}")
    return changes


def commit_is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    return (
        subprocess.run(
            (
                "git",
                "-C",
                str(repo),
                "merge-base",
                "--is-ancestor",
                ancestor,
                descendant,
            ),
            check=False,
            capture_output=True,
        ).returncode
        == 0
    )


def resolve_commit(repo: Path, revision: str) -> str:
    return run_git(repo, "rev-parse", f"{revision}^{{commit}}")


def branches_containing(repo: Path, revision: str) -> list[str]:
    output = run_git(
        repo,
        "for-each-ref",
        "--format=%(refname:short)",
        "--contains",
        revision,
        "refs/heads",
    )
    return sorted(line for line in output.splitlines() if line)


def is_s1_branch(branch: str) -> bool:
    """S1 门禁合法分支判定（配置驱动，不硬编码单一前缀）。

    合法分支 = master，或匹配 S1_GATE_BRANCH_PREFIXES 中任一前缀
    （默认 codex/s1/ 与 flow-lite/，可通过环境变量覆盖——
    未来门禁体系演进时不改代码只改配置）。
    """
    prefixes = [
        p.strip()
        for p in os.environ.get(
            "S1_GATE_BRANCH_PREFIXES",
            "codex/s1/,flow-lite/",
        ).split(",")
        if p.strip()
    ]
    if branch == "master":
        return True
    return any(branch.startswith(p) for p in prefixes)


def is_candidate_branch(branch: str) -> bool:
    return branch == CANDIDATE_BRANCH


def select_target_branch(repo: Path, target_head: str) -> str:
    current_head = run_git(repo, "rev-parse", "HEAD")
    current_branch = run_git(repo, "branch", "--show-current")
    if current_head == target_head and current_branch:
        return current_branch
    branches = branches_containing(repo, target_head)
    allowed = [branch for branch in branches if is_s1_branch(branch)]
    if allowed:
        return allowed[0]
    return branches[0] if branches else "(detached)"


def path_scope_violations(
    paths: Iterable[str],
    allowed: Iterable[str],
) -> list[str]:
    return sorted(path for path in paths if not is_allowed_path(path, allowed))


def is_s1_owned_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized in S1_EXACT_PATHS or any(
        normalized.startswith(prefix) for prefix in S1_ALLOWED_PREFIXES
    )


def final_scope_violations(
    changes: Iterable[tuple[str, str]],
    final_gitignore: str,
) -> list[str]:
    ignores_idea = any(
        line.strip().rstrip("/") == ".idea"
        for line in final_gitignore.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    violations: list[str] = []
    for status, path in changes:
        normalized = path.replace("\\", "/")
        if (
            is_s1_owned_path(normalized)
            or normalized in S1_ALLOWED_SHARED_PATHS
            or is_allowed_path(normalized, S7_ALLOWED_PREFIXES)
        ):
            continue
        if status == "D" and normalized.startswith(".idea/") and ignores_idea:
            continue
        violations.append(f"{status}:{normalized}")
    return sorted(violations)


def revision_object_id(repo: Path, revision: str, path: str) -> str:
    completed = subprocess.run(
        ("git", "-C", str(repo), "rev-parse", f"{revision}:{path}"),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        return "missing"
    return completed.stdout.strip()


def compare_revision_paths(
    repo: Path,
    base: str,
    target: str,
    paths: Iterable[str],
) -> tuple[dict[str, dict[str, str]], list[str]]:
    identities: dict[str, dict[str, str]] = {}
    mismatches: list[str] = []
    for path in paths:
        base_object = revision_object_id(repo, base, path)
        target_object = revision_object_id(repo, target, path)
        identities[path] = {
            "s7_candidate": base_object,
            "final": target_object,
        }
        if base_object != target_object:
            mismatches.append(path)
    return identities, mismatches


def git_object_exists(repo: Path, revision_path: str) -> bool:
    return (
        subprocess.run(
            ("git", "-C", str(repo), "cat-file", "-e", revision_path),
            check=False,
            capture_output=True,
        ).returncode
        == 0
    )


def status_is_clean(porcelain_output: str) -> bool:
    return not porcelain_output.strip()


def input_heads_are_unique(inputs: dict[str, dict[str, Any]]) -> bool:
    heads = [str(specification["head"]) for specification in inputs.values()]
    return len(heads) == len(set(heads))


def missing_workspace_members(
    repo: Path,
    members: Iterable[str],
) -> list[str]:
    return sorted(
        member
        for member in members
        if not (repo / member / "pyproject.toml").is_file()
    )


def discover_migration_heads(migrations_dir: Path) -> list[str]:
    upgrades = sorted(
        path
        for path in migrations_dir.glob("[0-9][0-9][0-9][0-9]_*.sql")
        if not path.name.endswith(".down.sql")
    )
    migration_ids = {path.stem for path in upgrades}
    predecessors: set[str] = set()
    for path in upgrades:
        source = path.read_text(encoding="utf-8")
        predecessors.update(
            re.findall(r"\brequires ([0-9]{4}_[A-Za-z0-9_]+)\b", source)
        )
    return sorted(migration_ids - predecessors)


def imported_modules(source_root: Path) -> set[str]:
    modules: set[str] = set()
    for path in sorted(source_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                modules.add(node.module)
    return modules


def make_check(check_id: str, outcome: bool, evidence: str) -> CheckResult:
    return CheckResult(
        check_id=check_id,
        outcome="PASS" if outcome else "FAIL",
        evidence=evidence,
    )


def check_merge_topology(
    repo: Path,
    construction: Sequence[tuple[str, str]] = TEMPORARY_CONSTRUCTION,
) -> CheckResult:
    previous = BASE_COMMIT
    failures: list[str] = []
    for role, merge_commit in construction:
        parents = run_git(
            repo,
            "show",
            "-s",
            "--format=%P",
            merge_commit,
        ).split()
        expected = [previous, str(INPUTS[role]["head"])]
        if parents != expected:
            failures.append(
                f"{merge_commit[:12]} parents={','.join(parents)} "
                f"expected={','.join(expected)}"
            )
        previous = merge_commit
    evidence = (
        "temporary construction is S5->S6->S2; "
        "it is a final-tree fixture, not a mainline integration order"
    )
    if failures:
        evidence = "; ".join(failures)
    return make_check("git.temporary_merge_topology", not failures, evidence)


def verify_input(
    repo: Path,
    role: str,
    specification: dict[str, Any],
) -> tuple[dict[str, Any], list[CheckResult]]:
    checks: list[CheckResult] = []
    base = str(specification["base"])
    head = str(specification["head"])
    merge_base = run_git(repo, "merge-base", BASE_COMMIT, head)
    count = int(run_git(repo, "rev-list", "--count", f"{base}..{head}"))
    paths = changed_paths(repo, base, head)
    violations = [
        path
        for path in paths
        if not is_allowed_path(path, specification["allowed"])
    ]
    handoff = repo / str(specification["handoff"])
    handoff_hash = sha256_file(handoff) if handoff.is_file() else "missing"
    contract_tree = run_git(repo, "rev-parse", f"{head}:contracts")

    checks.extend(
        (
            make_check(
                f"input.{role}.merge_base",
                merge_base == COMMON_MERGE_BASE,
                f"merge_base={merge_base}",
            ),
            make_check(
                f"input.{role}.commit_range",
                count == specification["commit_count"],
                f"{base}..{head} commits={count}",
            ),
            make_check(
                f"input.{role}.path_scope",
                not violations,
                (
                    f"changed={len(paths)} violations="
                    f"{','.join(violations) if violations else 'none'}"
                ),
            ),
            make_check(
                f"input.{role}.handoff_hash",
                handoff_hash == specification["handoff_sha256"],
                f"sha256:{handoff_hash}",
            ),
            make_check(
                f"input.{role}.contract_tree",
                contract_tree == CONTRACT_TREE,
                f"tree={contract_tree}",
            ),
        )
    )
    record = {
        "base": base,
        "head": head,
        "merge_base_with_control_base": merge_base,
        "commit_count": count,
        "changed_path_count": len(paths),
        "changed_paths": paths,
        "path_scope_violations": violations,
        "handoff": specification["handoff"],
        "handoff_sha256": f"sha256:{handoff_hash}",
        "contract_tree": contract_tree,
    }
    return record, checks


def verify_workspace(
    repo: Path,
    revision: str | None = None,
) -> tuple[dict[str, Any], list[CheckResult]]:
    checks: list[CheckResult] = []

    def read_text(path: str) -> str:
        if revision is None:
            return (repo / path).read_text(encoding="utf-8")
        return revision_file_text(repo, revision, path)

    def path_exists(path: str) -> bool:
        if revision is None:
            return (repo / path).is_file()
        return git_object_exists(repo, f"{revision}:{path}")

    pyproject = tomllib.loads(
        read_text("pyproject.toml")
    )
    lock_text = read_text("uv.lock")
    lock = tomllib.loads(lock_text)

    actual_members = pyproject["tool"]["uv"]["workspace"]["members"]
    actual_sources = pyproject["tool"]["uv"]["sources"]
    expected_members = list(WORKSPACE_PACKAGES)
    expected_packages = set(WORKSPACE_PACKAGES.values())
    expected_lock_members = expected_packages | {"flowpilot-workspace"}
    lock_members = set(lock["manifest"]["members"])
    lock_packages = [item["name"] for item in lock["package"]]
    lock_hash = (
        sha256_file(repo / "uv.lock")
        if revision is None
        else sha256_bytes(revision_file_bytes(repo, revision, "uv.lock"))
    )

    project_names: dict[str, str] = {}
    missing_members = [
        member
        for member in WORKSPACE_PACKAGES
        if not path_exists(f"{member}/pyproject.toml")
    ]
    for member, expected_name in WORKSPACE_PACKAGES.items():
        member_path = f"{member}/pyproject.toml"
        if not path_exists(member_path):
            continue
        member_toml = tomllib.loads(read_text(member_path))
        project_names[member] = member_toml["project"]["name"]
        if project_names[member] != expected_name:
            missing_members.append(
                f"{member}:name={project_names[member]}"
            )

    source_mismatches = [
        package
        for package in sorted(expected_packages)
        if actual_sources.get(package) != {"workspace": True}
    ]
    checks.extend(
        (
            make_check(
                "workspace.members",
                actual_members == expected_members and not missing_members,
                (
                    f"members={len(actual_members)} "
                    f"missing_or_mismatched={missing_members or 'none'}"
                ),
            ),
            make_check(
                "workspace.sources",
                not source_mismatches
                and set(actual_sources) == expected_packages,
                f"workspace_sources={len(actual_sources)}",
            ),
            make_check(
                "workspace.lock_members",
                lock_members == expected_lock_members,
                f"members={','.join(sorted(lock_members))}",
            ),
            make_check(
                "workspace.lock_package_count",
                len(lock_packages) == 73
                and len(lock_packages) == len(set(lock_packages)),
                f"packages={len(lock_packages)} unique={len(set(lock_packages))}",
            ),
            make_check(
                "workspace.lock_digest",
                f"sha256:{lock_hash}" == LOCK_DIGEST,
                f"sha256:{lock_hash}",
            ),
        )
    )
    record = {
        "member_count": len(actual_members),
        "members": actual_members,
        "project_names": project_names,
        "source_count": len(actual_sources),
        "lock_member_count": len(lock_members),
        "lock_package_count": len(lock_packages),
        "lock_sha256": f"sha256:{lock_hash}",
    }
    return record, checks


def verify_code_dependencies(repo: Path) -> tuple[dict[str, Any], list[CheckResult]]:
    checks: list[CheckResult] = []
    worker_toml = tomllib.loads(
        (repo / "apps/worker/pyproject.toml").read_text(encoding="utf-8")
    )
    worker_dependencies = set(worker_toml["project"]["dependencies"])
    worker_sources = worker_toml["tool"]["uv"]["sources"]
    required_worker_dependencies = {
        "flowpilot-application",
        "flowpilot-domain",
        "flowpilot-graph",
        "flowpilot-persistence",
    }

    persistence_toml = tomllib.loads(
        (repo / "packages/persistence/pyproject.toml").read_text(
            encoding="utf-8"
        )
    )
    persistence_dependencies = set(persistence_toml["project"]["dependencies"])
    persistence_imports = imported_modules(
        repo / "packages/persistence/src"
    )
    forbidden_reverse_imports = sorted(
        module
        for module in persistence_imports
        if module == "flowpilot_graph"
        or module.startswith("flowpilot_graph.")
        or module == "flowpilot_worker"
        or module.startswith("flowpilot_worker.")
    )

    ports_source = (
        repo
        / "packages/application/src/flowpilot_application/ports.py"
    ).read_text(encoding="utf-8")
    actions_source = (
        repo / "packages/domain/src/flowpilot_domain/actions.py"
    ).read_text(encoding="utf-8")
    postgres_source = (
        repo / "packages/persistence/src/flowpilot_persistence/postgres.py"
    ).read_text(encoding="utf-8")

    checks.extend(
        (
            make_check(
                "dependencies.s2_worker_ports",
                required_worker_dependencies <= worker_dependencies
                and all(
                    worker_sources.get(package) == {"workspace": True}
                    for package in required_worker_dependencies
                ),
                "worker consumes S5 application/domain and S6 persistence",
            ),
            make_check(
                "dependencies.s6_application_port",
                {
                    "flowpilot-application",
                    "flowpilot-domain",
                }
                <= persistence_dependencies,
                "persistence consumes S5 application/domain",
            ),
            make_check(
                "dependencies.no_persistence_reverse_edge",
                not forbidden_reverse_imports,
                (
                    "forbidden imports="
                    f"{forbidden_reverse_imports or 'none'}"
                ),
            ),
            make_check(
                "ports.task_query_full_task",
                "class TaskQueryPort(Protocol):" in ports_source
                and "-> Task | None:" in ports_source
                and "Task.from_mapping" in postgres_source,
                "TaskQueryPort returns Task and PostgreSQL restores Task.from_mapping",
            ),
            make_check(
                "domain.planned_action_digest",
                "def digest(self) -> str:" in actions_source
                and "return canonical_sha256(self.to_mapping())"
                in actions_source,
                "PlannedAction.digest uses the full authoritative mapping",
            ),
        )
    )
    record = {
        "worker_dependencies": sorted(worker_dependencies),
        "persistence_dependencies": sorted(persistence_dependencies),
        "forbidden_persistence_imports": forbidden_reverse_imports,
        "task_query_port": "Task | None",
        "planned_action_digest": "canonical_sha256(self.to_mapping())",
    }
    return record, checks


def verify_migrations(repo: Path) -> tuple[dict[str, Any], list[CheckResult]]:
    actual_hashes = {
        path: sha256_file(repo / path)
        for path in sorted(MIGRATION_HASHES)
    }
    mismatches = [
        path
        for path, expected in MIGRATION_HASHES.items()
        if actual_hashes[path] != expected
    ]
    upgrade_source = (
        repo / "migrations/0002_checkpoint_sequence_cas.sql"
    ).read_text(encoding="utf-8")
    linear = (
        "requires 0001_persistence_baseline" in upgrade_source
        and "0002_checkpoint_sequence_cas" in upgrade_source
        and CONTRACT_DIGEST in upgrade_source
        and "checkpoint_sequence bigint" in upgrade_source
    )
    heads = discover_migration_heads(repo / "migrations")
    checks = [
        make_check(
            "migrations.file_hashes",
            not mismatches,
            f"files={len(actual_hashes)} mismatches={mismatches or 'none'}",
        ),
        make_check(
            "migrations.linear_head",
            linear and heads == ["0002_checkpoint_sequence_cas"],
            (
                "0001_persistence_baseline -> "
                f"{','.join(heads) if heads else 'none'}"
            ),
        ),
    ]
    record = {
        "head": "0002_checkpoint_sequence_cas",
        "discovered_heads": heads,
        "predecessor": "0001_persistence_baseline",
        "file_sha256": {
            path: f"sha256:{digest}"
            for path, digest in actual_hashes.items()
        },
        "compose_auto_applies_head": False,
    }
    return record, checks


def verify_atomic_integration(
    repo: Path,
    full_input_paths: dict[str, set[str]],
) -> tuple[dict[str, Any], list[CheckResult]]:
    s2_worker = tomllib.loads(
        run_git(
            repo,
            "show",
            f"{INPUTS['S2-RUNTIME']['head']}:apps/worker/pyproject.toml",
        )
    )
    s5_root = tomllib.loads(
        run_git(
            repo,
            "show",
            f"{INPUTS['S5-CORE']['head']}:pyproject.toml",
        )
    )

    s2_needs_persistence = (
        "flowpilot-persistence"
        in s2_worker["project"]["dependencies"]
    )
    s5_expands_all_members = (
        s5_root["tool"]["uv"]["workspace"]["members"]
        == list(WORKSPACE_PACKAGES)
    )
    s5_missing_members = [
        member
        for member in WORKSPACE_PACKAGES
        if not git_object_exists(
            repo,
            f"{INPUTS['S5-CORE']['head']}:{member}/pyproject.toml",
        )
    ]
    s2_missing_persistence = not git_object_exists(
        repo,
        f"{INPUTS['S2-RUNTIME']['head']}:"
        "packages/persistence/pyproject.toml",
    )
    non_s5_root_writers = {
        role: sorted(
            {"pyproject.toml", "uv.lock"} & full_input_paths[role]
        )
        for role in ("S2-RUNTIME", "S6-DATA")
    }
    input_roles = sorted(full_input_paths)
    overlaps: dict[str, list[str]] = {}
    for index, left in enumerate(input_roles):
        for right in input_roles[index + 1 :]:
            intersection = sorted(
                full_input_paths[left] & full_input_paths[right]
            )
            overlaps[f"{left}|{right}"] = intersection

    facts_hold = (
        s2_needs_persistence
        and s5_expands_all_members
        and bool(s5_missing_members)
        and s2_missing_persistence
        and not any(non_s5_root_writers.values())
        and not any(overlaps.values())
    )
    checks = [
        make_check(
            "integration.atomicity_required",
            facts_hold,
            (
                "no whole-input sequential order keeps every newly introduced "
                "package and the root workspace simultaneously runnable"
            ),
        ),
        make_check(
            "integration.input_path_disjointness",
            not any(overlaps.values()),
            f"pairwise_overlaps={overlaps}",
        ),
    ]
    record = {
        "recommended_mainline_mode": "ATOMIC_FINAL_CANDIDATE",
        "safe_whole_input_sequential_order": None,
        "remediation_dependency_order": [
            "S6-DATA",
            "S2-RUNTIME",
            "S5-CORE",
        ],
        "logical_dependency_edges": [
            "S5-CORE Application/Domain -> S6-DATA Persistence",
            "S6-DATA Persistence -> S2-RUNTIME Worker adapter",
            "S2/S6 package closure -> S5-CORE final uv.lock",
        ],
        "reason": (
            "The S5 head bundles its ports with a nine-member workspace and "
            "final lock, but does not contain the S2/S6 member trees. S2 "
            "requires S6 persistence, while S2/S6 do not update the root "
            "workspace or lock. Only the complete candidate closes both sides."
        ),
        "temporary_construction_order": [
            role for role, _commit in TEMPORARY_CONSTRUCTION
        ],
        "temporary_construction_is_mainline_order": False,
        "pairwise_full_delta_overlaps": overlaps,
        "s5_head_missing_workspace_members": s5_missing_members,
        "s2_head_missing_persistence_member": s2_missing_persistence,
        "non_s5_root_workspace_writers": non_s5_root_writers,
    }
    return record, checks


def load_revision_json(repo: Path, revision: str, path: str) -> Any:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(
        revision_file_text(repo, revision, path),
        object_pairs_hook=reject_duplicate_keys,
    )


def path_scope_violations_by_rule(
    paths: Iterable[str],
    *,
    exact: Iterable[str] = (),
    prefixes: Iterable[str] = (),
) -> list[str]:
    exact_paths = {path.replace("\\", "/") for path in exact}
    normalized_prefixes = tuple(
        prefix.replace("\\", "/") for prefix in prefixes
    )
    return sorted(
        path.replace("\\", "/")
        for path in paths
        if path.replace("\\", "/") not in exact_paths
        and not path.replace("\\", "/").startswith(normalized_prefixes)
    )


def verify_m1_topology(repo: Path) -> tuple[dict[str, Any], list[CheckResult]]:
    expected_parents = {
        M1_PLATFORM_HEAD: M1_ACTIVATION_COMMIT,
        M1_WORKSPACE_IMPLEMENTATION_HEAD: M1_PLATFORM_HEAD,
        M1_WORKSPACE_HEAD: M1_WORKSPACE_IMPLEMENTATION_HEAD,
        M1_QUALITY_IMPLEMENTATION_HEAD: M1_WORKSPACE_HEAD,
        M1_INPUT_HEAD: M1_QUALITY_IMPLEMENTATION_HEAD,
    }
    parent_records: dict[str, list[str]] = {}
    parent_failures: list[str] = []
    for head, expected_parent in expected_parents.items():
        parents = run_git(repo, "show", "-s", "--format=%P", head).split()
        parent_records[head] = parents
        if parents != [expected_parent]:
            parent_failures.append(
                f"{head}:parents={parents}:expected={[expected_parent]}"
            )

    step_scopes = {
        "S3_PLATFORM": {
            "base": M1_ACTIVATION_COMMIT,
            "head": M1_PLATFORM_HEAD,
            "exact": (),
            "prefixes": (
                "apps/mcp-gateway/",
                "packages/tool-contracts/",
                "packages/policy/",
                "packages/security/",
                "mcp-servers/",
                "tests/platform/",
            ),
        },
        "S5_WORKSPACE": {
            "base": M1_PLATFORM_HEAD,
            "head": M1_WORKSPACE_IMPLEMENTATION_HEAD,
            "exact": ("Makefile", "pyproject.toml", "uv.lock"),
            "prefixes": (),
        },
        "S5_HANDOFF": {
            "base": M1_WORKSPACE_IMPLEMENTATION_HEAD,
            "head": M1_WORKSPACE_HEAD,
            "exact": ("tests/core/evidence/WP-011-a4-HANDOFF.md",),
            "prefixes": (),
        },
        "S4_QUALITY": {
            "base": M1_WORKSPACE_HEAD,
            "head": M1_QUALITY_IMPLEMENTATION_HEAD,
            "exact": (),
            "prefixes": (
                "artifacts/acceptance/generators/",
                "tests/acceptance/",
            ),
        },
        "S4_HANDOFF": {
            "base": M1_QUALITY_IMPLEMENTATION_HEAD,
            "head": M1_INPUT_HEAD,
            "exact": (
                "tests/acceptance/evidence/WP-030-a2-HANDOFF.md",
                "tests/acceptance/evidence/WP-030-a2-PROOF.json",
            ),
            "prefixes": (),
        },
    }
    scope_records: dict[str, Any] = {}
    checks = [
        make_check(
            "m1.git.linear_topology",
            not parent_failures,
            f"failures={parent_failures or 'none'}",
        )
    ]
    for step, specification in step_scopes.items():
        paths = changed_paths(
            repo,
            str(specification["base"]),
            str(specification["head"]),
        )
        violations = path_scope_violations_by_rule(
            paths,
            exact=specification["exact"],
            prefixes=specification["prefixes"],
        )
        scope_records[step] = {
            "base": specification["base"],
            "head": specification["head"],
            "changed_paths": paths,
            "violations": violations,
        }
        checks.append(
            make_check(
                f"m1.scope.{step.lower()}",
                not violations,
                (
                    f"changed={len(paths)} "
                    f"violations={violations or 'none'}"
                ),
            )
        )

    commit_count = int(
        run_git(
            repo,
            "rev-list",
            "--count",
            f"{M1_ACTIVATION_COMMIT}..{M1_INPUT_HEAD}",
        )
    )
    checks.append(
        make_check(
            "m1.git.commit_range",
            commit_count == 5,
            f"commits={commit_count}",
        )
    )
    return (
        {
            "activation_commit": M1_ACTIVATION_COMMIT,
            "input_head": M1_INPUT_HEAD,
            "commit_count": commit_count,
            "parents": parent_records,
            "steps": scope_records,
        },
        checks,
    )


def verify_m1_evidence(repo: Path) -> tuple[dict[str, Any], list[CheckResult]]:
    records: dict[str, Any] = {}
    checks: list[CheckResult] = []
    for evidence_id, (revision, path, expected_hash) in M1_EVIDENCE.items():
        actual_hash = sha256_bytes(revision_file_bytes(repo, revision, path))
        records[evidence_id] = {
            "revision": revision,
            "path": path,
            "sha256": f"sha256:{actual_hash}",
        }
        checks.append(
            make_check(
                f"m1.evidence.{evidence_id.lower()}",
                actual_hash == expected_hash,
                f"sha256:{actual_hash}",
            )
        )

    authority_hash = sha256_bytes(
        revision_file_bytes(
            repo,
            M1_AUTHORITY_COMMIT,
            M1_AUTHORITY_PATH,
        )
    )
    authority_parents = run_git(
        repo,
        "show",
        "-s",
        "--format=%P",
        M1_AUTHORITY_COMMIT,
    ).split()
    authority_text = revision_file_text(
        repo,
        M1_AUTHORITY_COMMIT,
        M1_AUTHORITY_PATH,
    )
    amendment_tokens = (
        "AMENDMENT_ID=CHAIN-M1-PLATFORM-01-S5-HANDOFF-01",
        "ATTEMPT_ID=WP-011-a4",
        "AUTHORIZED_PATH=tests/core/evidence/WP-011-a4-HANDOFF.md",
        "RISK_CLASS=R2_UNCHANGED",
    )
    authority_valid = (
        authority_hash == M1_AUTHORITY_SHA256
        and authority_parents == [M1_ACTIVATION_COMMIT]
        and all(token in authority_text for token in amendment_tokens)
    )
    checks.append(
        make_check(
            "m1.evidence.s5_scope_authority",
            authority_valid,
            (
                f"commit={M1_AUTHORITY_COMMIT} "
                f"sha256:{authority_hash} parents={authority_parents}"
            ),
        )
    )
    records["S5_SCOPE_AUTHORITY"] = {
        "revision": M1_AUTHORITY_COMMIT,
        "path": M1_AUTHORITY_PATH,
        "sha256": f"sha256:{authority_hash}",
        "parent": authority_parents,
    }

    proof = load_revision_json(
        repo,
        M1_INPUT_HEAD,
        "tests/acceptance/evidence/WP-030-a2-PROOF.json",
    )
    proof_valid = (
        proof["schema_version"] == "flowpilot.wp030a2-proof.v1"
        and proof["chain_id"] == M1_CHAIN_ID
        and proof["input_head"] == M1_WORKSPACE_HEAD
        and proof["implementation_head"] == M1_QUALITY_IMPLEMENTATION_HEAD
        and proof["contract_content_digest"] == CONTRACT_DIGEST
        and proof["scope"]["release_gate"] is False
        and proof["scope"]["dataset_completion_claim"] is False
        and all(proof["coverage"].values())
    )
    checks.append(
        make_check(
            "m1.evidence.s4_proof_semantics",
            proof_valid,
            (
                f"coverage={len(proof['coverage'])} "
                f"test_results={len(proof['test_results'])}"
            ),
        )
    )
    records["S4_PROOF_SEMANTICS"] = {
        "coverage": proof["coverage"],
        "test_results": proof["test_results"],
        "release_gate": proof["scope"]["release_gate"],
        "dataset_completion_claim": proof["scope"][
            "dataset_completion_claim"
        ],
    }
    return records, checks


def verify_m1_workspace(
    repo: Path,
    revision: str,
) -> tuple[dict[str, Any], list[CheckResult]]:
    root = tomllib.loads(
        revision_file_text(repo, revision, "pyproject.toml")
    )
    lock_bytes = revision_file_bytes(repo, revision, "uv.lock")
    lock = tomllib.loads(lock_bytes.decode("utf-8", errors="strict"))
    actual_members = root["tool"]["uv"]["workspace"]["members"]
    actual_sources = root["tool"]["uv"]["sources"]
    expected_members = list(M1_WORKSPACE_PACKAGES)
    expected_names = set(M1_WORKSPACE_PACKAGES.values())
    expected_lock_members = expected_names | {"flowpilot-workspace"}
    lock_members = set(lock["manifest"]["members"])
    lock_packages = [package["name"] for package in lock["package"]]

    project_names: dict[str, str] = {}
    missing_members: list[str] = []
    internal_dependency_violations: list[str] = []
    for member, expected_name in M1_WORKSPACE_PACKAGES.items():
        path = f"{member}/pyproject.toml"
        if not git_object_exists(repo, f"{revision}:{path}"):
            missing_members.append(member)
            continue
        package = tomllib.loads(revision_file_text(repo, revision, path))
        project_name = package["project"]["name"]
        project_names[member] = project_name
        if project_name != expected_name:
            missing_members.append(
                f"{member}:name={project_name}:expected={expected_name}"
            )
        for requirement in package["project"].get("dependencies", []):
            match = re.match(r"([A-Za-z0-9_.-]+)", requirement)
            if match is None:
                internal_dependency_violations.append(
                    f"{member}:invalid={requirement}"
                )
                continue
            dependency = match.group(1).lower().replace("_", "-")
            if dependency.startswith("flowpilot-") and dependency not in (
                expected_names
            ):
                internal_dependency_violations.append(
                    f"{member}:missing={dependency}"
                )

    source_mismatches = [
        package
        for package in sorted(expected_names)
        if actual_sources.get(package) != {"workspace": True}
    ]
    lock_hash = sha256_bytes(lock_bytes)
    checks = [
        make_check(
            "m1.workspace.members",
            actual_members == expected_members and not missing_members,
            (
                f"members={len(actual_members)} "
                f"missing_or_mismatched={missing_members or 'none'}"
            ),
        ),
        make_check(
            "m1.workspace.sources",
            set(actual_sources) == expected_names and not source_mismatches,
            f"mismatches={source_mismatches or 'none'}",
        ),
        make_check(
            "m1.workspace.internal_dependencies",
            not internal_dependency_violations,
            f"violations={internal_dependency_violations or 'none'}",
        ),
        make_check(
            "m1.workspace.lock_members",
            lock_members == expected_lock_members,
            f"members={len(lock_members)}",
        ),
        make_check(
            "m1.workspace.lock_packages",
            len(lock_packages) == 78
            and len(lock_packages) == len(set(lock_packages)),
            f"packages={len(lock_packages)} unique={len(set(lock_packages))}",
        ),
        make_check(
            "m1.workspace.lock_digest",
            f"sha256:{lock_hash}" == M1_LOCK_DIGEST,
            f"sha256:{lock_hash}",
        ),
    ]
    return (
        {
            "member_count": len(actual_members),
            "members": actual_members,
            "project_names": project_names,
            "source_count": len(actual_sources),
            "lock_member_count": len(lock_members),
            "lock_package_count": len(lock_packages),
            "lock_sha256": f"sha256:{lock_hash}",
            "expected_wheel_count": len(expected_names),
            "internal_dependency_violations": internal_dependency_violations,
        },
        checks,
    )


def verify_m1_static_commands(
    repo: Path,
    revision: str,
) -> tuple[dict[str, Any], list[CheckResult]]:
    makefile = revision_file_text(repo, revision, "Makefile")
    targets = sorted(
        match.group(1)
        for match in re.finditer(
            r"^([A-Za-z0-9_-]+):(?:\s|$)",
            makefile,
            flags=re.MULTILINE,
        )
    )
    required = {"bootstrap", "test", "test-contract", "test-security"}
    missing = sorted(required - set(targets))
    security_is_locked = (
        "test-security:" in makefile
        and "$(UV) run --all-packages --all-groups --locked" in makefile
        and "pytest tests/platform" in makefile
    )
    checks = [
        make_check(
            "m1.commands.stable_targets",
            not missing,
            f"targets={targets} missing={missing or 'none'}",
        ),
        make_check(
            "m1.commands.security_locked",
            security_is_locked,
            "test-security uses the locked all-package workspace",
        ),
    ]
    return (
        {
            "targets": targets,
            "required_targets": sorted(required),
            "make_acceptance_implemented": "acceptance" in targets,
        },
        checks,
    )


def high_confidence_secret_findings(
    repo: Path,
    revision: str,
    paths: Iterable[str],
) -> list[str]:
    findings: list[str] = []
    text_suffixes = {
        ".ini",
        ".json",
        ".md",
        ".py",
        ".sql",
        ".toml",
        ".txt",
        ".yaml",
        ".yml",
    }
    for path in sorted(set(paths)):
        if Path(path).suffix.lower() not in text_suffixes:
            continue
        if not git_object_exists(repo, f"{revision}:{path}"):
            continue
        text = revision_file_text(repo, revision, path)
        for pattern in HIGH_CONFIDENCE_SECRET_PATTERNS:
            if pattern.search(text):
                findings.append(f"{path}:{pattern.pattern}")
    return findings


def verify_m1_candidate_identity(
    repo: Path,
    target_head: str,
) -> tuple[dict[str, Any], list[CheckResult]]:
    product_identities, product_mismatches = compare_revision_paths(
        repo,
        M1_INPUT_HEAD,
        target_head,
        M1_PRODUCT_PATHS,
    )
    contract_input = revision_object_id(repo, M1_INPUT_HEAD, "contracts")
    contract_target = revision_object_id(repo, target_head, "contracts")
    migration_input = revision_object_id(repo, M1_INPUT_HEAD, "migrations")
    migration_target = revision_object_id(repo, target_head, "migrations")
    lock_input = revision_object_id(repo, M1_INPUT_HEAD, "uv.lock")
    lock_target = revision_object_id(repo, target_head, "uv.lock")
    delta = changed_paths(repo, M1_INPUT_HEAD, target_head)
    delta_violations = path_scope_violations(
        delta,
        S7_ALLOWED_PREFIXES,
    )
    checks = [
        make_check(
            "m1.git.input_ancestor",
            commit_is_ancestor(repo, M1_INPUT_HEAD, target_head),
            f"input={M1_INPUT_HEAD} target={target_head}",
        ),
        make_check(
            "m1.git.s7_delta_scope",
            not delta_violations,
            f"violations={delta_violations or 'none'}",
        ),
        make_check(
            "m1.git.product_tree",
            not product_mismatches,
            f"mismatches={product_mismatches or 'none'}",
        ),
        make_check(
            "m1.contract.tree",
            contract_input == contract_target == CONTRACT_TREE,
            f"input={contract_input} target={contract_target}",
        ),
        make_check(
            "m1.workspace.lock_blob",
            lock_input == lock_target,
            f"input={lock_input} target={lock_target}",
        ),
        make_check(
            "m1.migrations.tree",
            migration_input == migration_target,
            f"input={migration_input} target={migration_target}",
        ),
    ]
    return (
        {
            "target_head": target_head,
            "s7_delta": delta,
            "s7_delta_scope_violations": delta_violations,
            "product_path_identities": product_identities,
            "product_path_mismatches": product_mismatches,
            "contract_tree": {
                "input": contract_input,
                "target": contract_target,
            },
            "lock_blob": {"input": lock_input, "target": lock_target},
            "migration_tree": {
                "input": migration_input,
                "target": migration_target,
            },
        },
        checks,
    )


def build_m1_platform_manifest(
    repo: Path,
    *,
    phase: ValidationPhase,
    target_head: str | None,
    s7_head: str | None,
    enforce_checkout_identity: bool,
) -> dict[str, Any]:
    repo = repo.resolve()
    checks: list[CheckResult] = []
    checkout_head = resolve_commit(repo, "HEAD")
    checkout_branch = run_git(repo, "branch", "--show-current")
    final_record: dict[str, Any] | None = None

    if phase is ValidationPhase.M1_PLATFORM_CANDIDATE:
        verified_head = resolve_commit(
            repo,
            target_head
            if target_head is not None
            else (checkout_head if enforce_checkout_identity else M1_INPUT_HEAD),
        )
        branch = (
            checkout_branch if enforce_checkout_identity else CANDIDATE_BRANCH
        )
        checks.extend(
            (
                make_check(
                    "m1.git.branch",
                    is_candidate_branch(branch),
                    f"phase={phase.value} branch={branch}",
                ),
                make_check(
                    "m1.git.worktree_clean",
                    not enforce_checkout_identity
                    or status_is_clean(
                        run_git(repo, "status", "--porcelain=v1")
                    ),
                    "checkout cleanliness is enforced by candidate CLI",
                ),
            )
        )
        candidate, candidate_checks = verify_m1_candidate_identity(
            repo,
            verified_head,
        )
        checks.extend(candidate_checks)
    else:
        if s7_head is None:
            raise ValueError(
                "--s7-head is required for M1_PLATFORM_S1_FINAL"
            )
        verified_s7_head = resolve_commit(repo, s7_head)
        verified_head = resolve_commit(
            repo,
            target_head if target_head is not None else checkout_head,
        )
        branch = select_target_branch(repo, verified_head)
        checks.append(
            make_check(
                "m1.git.branch",
                is_s1_branch(branch),
                f"phase={phase.value} branch={branch}",
            )
        )
        candidate, candidate_checks = verify_m1_candidate_identity(
            repo,
            verified_s7_head,
        )
        checks.extend(candidate_checks)
        final_changes = changed_path_statuses(
            repo,
            verified_s7_head,
            verified_head,
        )
        final_gitignore = run_git(
            repo,
            "show",
            f"{verified_head}:.gitignore",
        )
        final_violations = final_scope_violations(
            final_changes,
            final_gitignore,
        )
        protected_identities, protected_mismatches = compare_revision_paths(
            repo,
            verified_s7_head,
            verified_head,
            M1_PRODUCT_PATHS,
        )
        input_ancestry = commit_is_ancestor(
            repo,
            M1_INPUT_HEAD,
            verified_head,
        )
        checks.extend(
            (
                make_check(
                    "m1.git.s7_head_ancestor",
                    commit_is_ancestor(
                        repo,
                        verified_s7_head,
                        verified_head,
                    ),
                    (
                        f"s7_head={verified_s7_head} "
                        f"final_head={verified_head}"
                    ),
                ),
                make_check(
                    "m1.git.s1_final_delta_scope",
                    not final_violations,
                    f"violations={final_violations or 'none'}",
                ),
                make_check(
                    "m1.git.final_product_tree",
                    not protected_mismatches,
                    f"mismatches={protected_mismatches or 'none'}",
                ),
                make_check(
                    "m1.git.final_input_head",
                    input_ancestry,
                    f"input_head_ancestor={input_ancestry}",
                ),
            )
        )
        final_record = {
            "target_head": verified_head,
            "s7_head": verified_s7_head,
            "delta": [
                {"status": status, "path": path}
                for status, path in final_changes
            ],
            "delta_scope_violations": final_violations,
            "protected_path_identities": protected_identities,
            "protected_path_mismatches": protected_mismatches,
            "input_head_ancestor": input_ancestry,
        }

    topology, topology_checks = verify_m1_topology(repo)
    evidence, evidence_checks = verify_m1_evidence(repo)
    workspace, workspace_checks = verify_m1_workspace(
        repo,
        M1_INPUT_HEAD,
    )
    commands, command_checks = verify_m1_static_commands(
        repo,
        M1_INPUT_HEAD,
    )
    checks.extend(topology_checks)
    checks.extend(evidence_checks)
    checks.extend(workspace_checks)
    checks.extend(command_checks)

    contract_manifest = load_revision_json(
        repo,
        M1_INPUT_HEAD,
        "contracts/contract-set.v1.json",
    )
    recomputed_contract_digest = contract_content_digest(contract_manifest)
    activation_contract_tree = revision_object_id(
        repo,
        M1_ACTIVATION_COMMIT,
        "contracts",
    )
    input_contract_tree = revision_object_id(
        repo,
        M1_INPUT_HEAD,
        "contracts",
    )
    checks.append(
        make_check(
            "m1.contract.content_digest",
            recomputed_contract_digest == CONTRACT_DIGEST
            and contract_manifest["content_digest"] == CONTRACT_DIGEST,
            f"recomputed={recomputed_contract_digest}",
        )
    )
    checks.append(
        make_check(
            "m1.contract.activation_tree",
            activation_contract_tree
            == input_contract_tree
            == CONTRACT_TREE,
            (
                f"activation={activation_contract_tree} "
                f"input={input_contract_tree}"
            ),
        )
    )

    changed_input_paths = changed_paths(
        repo,
        M1_ACTIVATION_COMMIT,
        M1_INPUT_HEAD,
    )
    secret_findings = high_confidence_secret_findings(
        repo,
        M1_INPUT_HEAD,
        changed_input_paths,
    )
    checks.append(
        make_check(
            "m1.security.high_confidence_secret_scan",
            not secret_findings,
            f"findings={secret_findings or 'none'}",
        )
    )
    migration_tree = revision_object_id(
        repo,
        M1_INPUT_HEAD,
        "migrations",
    )
    activation_migration_tree = revision_object_id(
        repo,
        M1_ACTIVATION_COMMIT,
        "migrations",
    )
    infra_tree = revision_object_id(repo, M1_INPUT_HEAD, "infra")
    activation_infra_tree = revision_object_id(
        repo,
        M1_ACTIVATION_COMMIT,
        "infra",
    )
    checks.extend(
        (
            make_check(
                "m1.migrations.activation_identity",
                migration_tree == activation_migration_tree,
                (
                    f"activation={activation_migration_tree} "
                    f"input={migration_tree}"
                ),
            ),
            make_check(
                "m1.compose.activation_identity",
                infra_tree == activation_infra_tree,
                f"activation={activation_infra_tree} input={infra_tree}",
            ),
        )
    )

    failed = [check.check_id for check in checks if check.outcome != "PASS"]
    manifest: dict[str, Any] = {
        "schema": "flowpilot.integration-composition-manifest.m1.v1",
        "work_package": "WP-040",
        "attempt_id": "WP-040-a4",
        "chain_id": M1_CHAIN_ID,
        "execution_mode": "ORDERED",
        "risk_class": "R2",
        "validation_phase": phase.value,
        "base_commit": M1_INPUT_HEAD,
        "input_head": M1_INPUT_HEAD,
        "target_head": verified_head,
        "branch": branch,
        "candidate": candidate,
        "topology": topology,
        "contract": {
            "declared_content_digest": contract_manifest["content_digest"],
            "recomputed_content_digest": recomputed_contract_digest,
            "digest_profile": contract_manifest["digest_profile"],
            "activation_tree": activation_contract_tree,
            "input_tree": input_contract_tree,
        },
        "workspace": workspace,
        "commands": commands,
        "evidence": evidence,
        "security": {
            "high_confidence_secret_findings": secret_findings,
        },
        "migrations": {
            "activation_tree": activation_migration_tree,
            "input_tree": migration_tree,
        },
        "compose": {
            "activation_tree": activation_infra_tree,
            "input_tree": infra_tree,
            "changed_since_activation": infra_tree != activation_infra_tree,
        },
        "checks": [asdict(check) for check in checks],
        "summary": {
            "check_count": len(checks),
            "failed_check_count": len(failed),
            "failed_checks": failed,
            "verdict": "PASS" if not failed else "FAIL",
        },
    }
    if final_record is not None:
        manifest["final"] = final_record
    return manifest


def verify_m2_topology(
    repo: Path,
    expected_parents: dict[str, str] | None = None,
) -> tuple[dict[str, Any], list[CheckResult]]:
    parents = expected_parents or {
        M2_WORKSPACE_IMPLEMENTATION_HEAD: M2_ACTIVATION_COMMIT,
        M2_WORKSPACE_HEAD: M2_WORKSPACE_IMPLEMENTATION_HEAD,
        M2_RUNTIME_IMPLEMENTATION_HEAD: M2_WORKSPACE_HEAD,
        M2_RUNTIME_HEAD: M2_RUNTIME_IMPLEMENTATION_HEAD,
        M2_QUALITY_IMPLEMENTATION_HEAD: M2_RUNTIME_HEAD,
        M2_INPUT_HEAD: M2_QUALITY_IMPLEMENTATION_HEAD,
    }
    parent_records: dict[str, list[str]] = {}
    parent_failures: list[str] = []
    for head, expected_parent in parents.items():
        actual = run_git(repo, "show", "-s", "--format=%P", head).split()
        parent_records[head] = actual
        if actual != [expected_parent]:
            parent_failures.append(
                f"{head}:parents={actual}:expected={[expected_parent]}"
            )

    step_scopes = {
        "S5_WORKSPACE": {
            "base": M2_ACTIVATION_COMMIT,
            "head": M2_WORKSPACE_IMPLEMENTATION_HEAD,
            "exact": ("Makefile", "pyproject.toml", "uv.lock"),
            "prefixes": (),
        },
        "S5_HANDOFF": {
            "base": M2_WORKSPACE_IMPLEMENTATION_HEAD,
            "head": M2_WORKSPACE_HEAD,
            "exact": ("tests/core/evidence/WP-011-a5-HANDOFF.md",),
            "prefixes": (),
        },
        "S2_RUNTIME": {
            "base": M2_WORKSPACE_HEAD,
            "head": M2_RUNTIME_IMPLEMENTATION_HEAD,
            "exact": ("langgraph.json",),
            "prefixes": (
                "apps/worker/",
                "packages/graph/",
                "tests/runtime/",
            ),
        },
        "S2_HANDOFF": {
            "base": M2_RUNTIME_IMPLEMENTATION_HEAD,
            "head": M2_RUNTIME_HEAD,
            "exact": ("tests/runtime/evidence/WP-012-a1-HANDOFF.md",),
            "prefixes": (),
        },
        "S4_QUALITY": {
            "base": M2_RUNTIME_HEAD,
            "head": M2_QUALITY_IMPLEMENTATION_HEAD,
            "exact": (),
            "prefixes": (
                "artifacts/acceptance/generators/",
                "tests/acceptance/",
            ),
        },
        "S4_HANDOFF": {
            "base": M2_QUALITY_IMPLEMENTATION_HEAD,
            "head": M2_INPUT_HEAD,
            "exact": (
                "tests/acceptance/evidence/WP-030-a3-HANDOFF.md",
                "tests/acceptance/evidence/WP-030-a3-PROOF.json",
            ),
            "prefixes": (),
        },
    }
    scope_records: dict[str, Any] = {}
    checks = [
        make_check(
            "m2.git.linear_topology",
            not parent_failures,
            f"failures={parent_failures or 'none'}",
        )
    ]
    for step, specification in step_scopes.items():
        paths = changed_paths(
            repo,
            str(specification["base"]),
            str(specification["head"]),
        )
        violations = path_scope_violations_by_rule(
            paths,
            exact=specification["exact"],
            prefixes=specification["prefixes"],
        )
        scope_records[step] = {
            "base": specification["base"],
            "head": specification["head"],
            "changed_paths": paths,
            "violations": violations,
        }
        checks.append(
            make_check(
                f"m2.scope.{step.lower()}",
                not violations,
                f"changed={len(paths)} violations={violations or 'none'}",
            )
        )

    commit_count = int(
        run_git(
            repo,
            "rev-list",
            "--count",
            f"{M2_ACTIVATION_COMMIT}..{M2_INPUT_HEAD}",
        )
    )
    checks.append(
        make_check(
            "m2.git.commit_range",
            commit_count == 6,
            f"commits={commit_count}",
        )
    )
    return (
        {
            "activation_commit": M2_ACTIVATION_COMMIT,
            "input_head": M2_INPUT_HEAD,
            "commit_count": commit_count,
            "parents": parent_records,
            "steps": scope_records,
        },
        checks,
    )


def verify_m2_evidence(repo: Path) -> tuple[dict[str, Any], list[CheckResult]]:
    records: dict[str, Any] = {}
    checks: list[CheckResult] = []
    for evidence_id, (revision, path, expected_hash) in M2_EVIDENCE.items():
        actual_hash = sha256_bytes(revision_file_bytes(repo, revision, path))
        records[evidence_id] = {
            "revision": revision,
            "path": path,
            "sha256": f"sha256:{actual_hash}",
        }
        checks.append(
            make_check(
                f"m2.evidence.{evidence_id.lower()}",
                actual_hash == expected_hash,
                f"sha256:{actual_hash}",
            )
        )

    authority_hash = sha256_bytes(
        revision_file_bytes(
            repo,
            M2_ACTIVATION_COMMIT,
            M2_AUTHORITY_PATH,
        )
    )
    authority_text = revision_file_text(
        repo,
        M2_ACTIVATION_COMMIT,
        M2_AUTHORITY_PATH,
    )
    authority_tokens = (
        "CHAIN_ID=CHAIN-M2-STUDIO-01",
        "STATUS=ACTIVE",
        "RISK_CLASS=R2",
        "FINAL_GATE=S7-INTEGRATION->S1-ARCH",
        "STEP_ID=M2-STUDIO-04-S7",
        "ATTEMPT_ID=WP-040-a5",
    )
    authority_valid = (
        authority_hash == M2_AUTHORITY_SHA256
        and all(token in authority_text for token in authority_tokens)
    )
    checks.append(
        make_check(
            "m2.evidence.chain_authority",
            authority_valid,
            f"sha256:{authority_hash}",
        )
    )
    records["CHAIN_AUTHORITY"] = {
        "revision": M2_ACTIVATION_COMMIT,
        "path": M2_AUTHORITY_PATH,
        "sha256": f"sha256:{authority_hash}",
    }

    proof = load_revision_json(
        repo,
        M2_INPUT_HEAD,
        "tests/acceptance/evidence/WP-030-a3-PROOF.json",
    )
    cleanup = proof["cleanup"]
    proof_valid = (
        proof["schema_version"] == "flowpilot.wp030a3-proof.v1"
        and proof["chain_id"] == M2_CHAIN_ID
        and proof["input_head"] == M2_RUNTIME_HEAD
        and proof["implementation_head"] == M2_QUALITY_IMPLEMENTATION_HEAD
        and proof["contract_content_digest"] == CONTRACT_DIGEST
        and proof["scope"]["release_gate"] is False
        and proof["scope"]["dataset_completion_claim"] is False
        and proof["scope"]["measured_quality_claim"] is False
        and proof["scope"]["production_connection"] is False
        and all(proof["coverage"].values())
        and all(value == 0 for value in cleanup.values())
        and (
            proof["encoding_and_secret_gates"][
                "high_confidence_secret_matches"
            ]
            == 0
        )
    )
    checks.append(
        make_check(
            "m2.evidence.s4_proof_semantics",
            proof_valid,
            (
                f"coverage={len(proof['coverage'])} "
                f"tests={len(proof['test_results'])} cleanup={cleanup}"
            ),
        )
    )
    records["S4_PROOF_SEMANTICS"] = {
        "coverage": proof["coverage"],
        "cleanup": cleanup,
        "environment": proof["environment"],
        "release_gate": proof["scope"]["release_gate"],
        "dataset_completion_claim": proof["scope"][
            "dataset_completion_claim"
        ],
    }
    return records, checks


def verify_m2_workspace(
    repo: Path,
    revision: str,
) -> tuple[dict[str, Any], list[CheckResult]]:
    root = tomllib.loads(
        revision_file_text(repo, revision, "pyproject.toml")
    )
    lock_bytes = revision_file_bytes(repo, revision, "uv.lock")
    lock = tomllib.loads(lock_bytes.decode("utf-8", errors="strict"))
    actual_members = root["tool"]["uv"]["workspace"]["members"]
    actual_sources = root["tool"]["uv"]["sources"]
    expected_members = list(M1_WORKSPACE_PACKAGES)
    expected_names = set(M1_WORKSPACE_PACKAGES.values())
    expected_lock_members = expected_names | {"flowpilot-workspace"}
    lock_members = set(lock["manifest"]["members"])
    lock_packages = [package["name"] for package in lock["package"]]
    package_versions = {
        str(package["name"]): str(package.get("version", ""))
        for package in lock["package"]
    }
    locked_agent_server_versions = {
        package: package_versions.get(package, "missing")
        for package in M2_AGENT_SERVER_VERSIONS
    }

    project_names: dict[str, str] = {}
    missing_members: list[str] = []
    internal_dependency_violations: list[str] = []
    for member, expected_name in M1_WORKSPACE_PACKAGES.items():
        path = f"{member}/pyproject.toml"
        if not git_object_exists(repo, f"{revision}:{path}"):
            missing_members.append(member)
            continue
        package = tomllib.loads(revision_file_text(repo, revision, path))
        project_name = package["project"]["name"]
        project_names[member] = project_name
        if project_name != expected_name:
            missing_members.append(
                f"{member}:name={project_name}:expected={expected_name}"
            )
        for requirement in package["project"].get("dependencies", []):
            match = re.match(r"([A-Za-z0-9_.-]+)", requirement)
            if match is None:
                internal_dependency_violations.append(
                    f"{member}:invalid={requirement}"
                )
                continue
            dependency = match.group(1).lower().replace("_", "-")
            if (
                dependency.startswith("flowpilot-")
                and dependency not in expected_names
            ):
                internal_dependency_violations.append(
                    f"{member}:missing={dependency}"
                )

    source_mismatches = [
        package
        for package in sorted(expected_names)
        if actual_sources.get(package) != {"workspace": True}
    ]
    dev_dependencies = root["dependency-groups"]["dev"]
    studio_dependency = "langgraph-cli[inmem]>=0.4.31,<0.5"
    lock_hash = sha256_bytes(lock_bytes)
    checks = [
        make_check(
            "m2.workspace.members",
            actual_members == expected_members and not missing_members,
            (
                f"members={len(actual_members)} "
                f"missing_or_mismatched={missing_members or 'none'}"
            ),
        ),
        make_check(
            "m2.workspace.sources",
            set(actual_sources) == expected_names and not source_mismatches,
            f"mismatches={source_mismatches or 'none'}",
        ),
        make_check(
            "m2.workspace.internal_dependencies",
            not internal_dependency_violations,
            f"violations={internal_dependency_violations or 'none'}",
        ),
        make_check(
            "m2.workspace.lock_members",
            lock_members == expected_lock_members,
            f"members={len(lock_members)}",
        ),
        make_check(
            "m2.workspace.lock_packages",
            len(lock_packages) == 116
            and len(lock_packages) == len(set(lock_packages)),
            f"packages={len(lock_packages)} unique={len(set(lock_packages))}",
        ),
        make_check(
            "m2.workspace.lock_digest",
            f"sha256:{lock_hash}" == M2_LOCK_DIGEST,
            f"sha256:{lock_hash}",
        ),
        make_check(
            "m2.workspace.studio_dependency",
            studio_dependency in dev_dependencies
            and locked_agent_server_versions == M2_AGENT_SERVER_VERSIONS,
            (
                f"declared={studio_dependency in dev_dependencies} "
                f"versions={locked_agent_server_versions}"
            ),
        ),
    ]
    return (
        {
            "member_count": len(actual_members),
            "members": actual_members,
            "project_names": project_names,
            "source_count": len(actual_sources),
            "lock_member_count": len(lock_members),
            "lock_package_count": len(lock_packages),
            "lock_sha256": f"sha256:{lock_hash}",
            "expected_wheel_count": len(expected_names),
            "internal_dependency_violations": internal_dependency_violations,
            "agent_server_versions": locked_agent_server_versions,
        },
        checks,
    )


def verify_m2_studio_static(
    repo: Path,
    revision: str,
) -> tuple[dict[str, Any], list[CheckResult]]:
    config = load_revision_json(repo, revision, "langgraph.json")
    runtime_topology = load_revision_json(
        repo,
        revision,
        "tests/runtime/snapshots/flowpilot_it_service.topology.json",
    )
    quality_topology = load_revision_json(
        repo,
        revision,
        "tests/acceptance/studio/expected_agent_server_topology.json",
    )
    makefile = revision_file_text(repo, revision, "Makefile")
    studio_source = revision_file_text(
        repo,
        revision,
        "apps/worker/src/flowpilot_worker/studio.py",
    )
    worker_source = revision_file_text(
        repo,
        revision,
        "packages/graph/src/flowpilot_graph/langgraph_runtime.py",
    )
    debug_source = revision_file_text(
        repo,
        revision,
        "packages/graph/src/flowpilot_graph/debug.py",
    )

    graphs = config.get("graphs", {})
    env = config.get("env", {})
    config_valid = (
        config.get("python_version") == "3.12"
        and config.get("source") == {"kind": "uv", "root": "."}
        and graphs
        == {
            "flowpilot_it_service": (
                "./apps/worker/src/flowpilot_worker/studio.py:graph"
            )
        }
    )
    safe_env = (
        env.get("FLOWPILOT_STUDIO_PROFILE") == "studio-safe"
        and env.get("FLOWPILOT_EXTERNAL_NETWORK") == "disabled"
        and env.get("LANGSMITH_TRACING") == "false"
        and env.get("PYTHONDONTWRITEBYTECODE") == "1"
        and env.get("PYTHONUTF8") == "1"
        and not any("KEY" in key or "TOKEN" in key for key in env)
    )
    make_studio_lines = [
        line
        for line in makefile.splitlines()
        if "langgraph" in line or line.startswith("STUDIO_")
    ]
    make_surface_valid = (
        "studio:" in makefile
        and "studio-smoke:" in makefile
        and "--host $(STUDIO_HOST)" in makefile
        and "STUDIO_HOST ?= 127.0.0.1" in makefile
        and "--no-browser" in makefile
        and "--tunnel" not in makefile
        and "LANGSMITH_TRACING=false" in makefile
        and "--locked langgraph" in makefile
    )
    shared_factory_valid = (
        "build_flowpilot_it_service_graph" in studio_source
        and "build_flowpilot_it_service_graph" in worker_source
        and "GRAPH_FACTORY_DIVERGED" in revision_file_text(
            repo,
            revision,
            "packages/graph/src/flowpilot_graph/factory.py",
        )
    )
    runtime_nodes = runtime_topology.get("nodes", [])
    quality_nodes = quality_topology.get("node_ids", [])
    topology_valid = (
        runtime_topology.get("schema") == "flowpilot.graph-topology.v1"
        and runtime_topology.get("graph_id") == "flowpilot_it_service"
        and runtime_topology.get("factory_id")
        == "flowpilot.graph.factory.v1"
        and runtime_topology.get("topology_digest")
        == (
            "sha256:f915742bd4c091b44364ab3073b485901338bd8c270d146"
            "3344b9eb52a31d8c2"
        )
        and len(runtime_nodes) == 14
        and len(runtime_topology.get("edges", [])) == 20
        and quality_topology.get("schema_version")
        == "flowpilot.s4-agent-server-topology-oracle.m2.v1"
        and quality_topology.get("graph_id") == "flowpilot_it_service"
        and len(quality_nodes) == 16
        and len(quality_topology.get("edges", [])) == 22
        and set(quality_nodes) == set(runtime_nodes) | {"__start__", "__end__"}
    )
    fail_closed_source = (
        "studio-integration" in debug_source
        and "production" in debug_source
        and "_assert_no_production_environment" in studio_source
        and "studio-safe refuses production credentials and endpoints"
        in studio_source
    )
    checks = [
        make_check(
            "m2.studio.config",
            config_valid,
            f"graphs={graphs}",
        ),
        make_check(
            "m2.studio.safe_environment",
            safe_env,
            f"env_keys={sorted(env)}",
        ),
        make_check(
            "m2.studio.make_surface",
            make_surface_valid,
            f"lines={make_studio_lines}",
        ),
        make_check(
            "m2.studio.shared_factory",
            shared_factory_valid,
            "Worker and Studio consume the same named graph factory",
        ),
        make_check(
            "m2.studio.independent_topologies",
            topology_valid,
            (
                f"runtime_nodes={len(runtime_nodes)} "
                f"api_nodes={len(quality_nodes)} "
                f"api_edges={len(quality_topology.get('edges', []))}"
            ),
        ),
        make_check(
            "m2.studio.fail_closed_profiles",
            fail_closed_source,
            "production environment and integration profile stay explicit",
        ),
    ]
    return (
        {
            "config": config,
            "runtime_topology": {
                "graph_id": runtime_topology.get("graph_id"),
                "factory_id": runtime_topology.get("factory_id"),
                "topology_digest": runtime_topology.get("topology_digest"),
                "node_count": len(runtime_nodes),
                "edge_count": len(runtime_topology.get("edges", [])),
            },
            "quality_topology": {
                "graph_id": quality_topology.get("graph_id"),
                "node_count": len(quality_nodes),
                "edge_count": len(quality_topology.get("edges", [])),
            },
            "make_surface": make_studio_lines,
        },
        checks,
    )


def verify_m2_candidate_identity(
    repo: Path,
    target_head: str,
) -> tuple[dict[str, Any], list[CheckResult]]:
    product_identities, product_mismatches = compare_revision_paths(
        repo,
        M2_INPUT_HEAD,
        target_head,
        M2_PRODUCT_PATHS,
    )
    contract_input = revision_object_id(repo, M2_INPUT_HEAD, "contracts")
    contract_target = revision_object_id(repo, target_head, "contracts")
    migration_input = revision_object_id(repo, M2_INPUT_HEAD, "migrations")
    migration_target = revision_object_id(repo, target_head, "migrations")
    lock_input = revision_object_id(repo, M2_INPUT_HEAD, "uv.lock")
    lock_target = revision_object_id(repo, target_head, "uv.lock")
    delta = changed_paths(repo, M2_INPUT_HEAD, target_head)
    delta_violations = path_scope_violations(delta, S7_ALLOWED_PREFIXES)
    checks = [
        make_check(
            "m2.git.input_ancestor",
            commit_is_ancestor(repo, M2_INPUT_HEAD, target_head),
            f"input={M2_INPUT_HEAD} target={target_head}",
        ),
        make_check(
            "m2.git.s7_delta_scope",
            not delta_violations,
            f"violations={delta_violations or 'none'}",
        ),
        make_check(
            "m2.git.product_tree",
            not product_mismatches,
            f"mismatches={product_mismatches or 'none'}",
        ),
        make_check(
            "m2.contract.tree",
            contract_input == contract_target == CONTRACT_TREE,
            f"input={contract_input} target={contract_target}",
        ),
        make_check(
            "m2.workspace.lock_blob",
            lock_input == lock_target,
            f"input={lock_input} target={lock_target}",
        ),
        make_check(
            "m2.migrations.tree",
            migration_input == migration_target,
            f"input={migration_input} target={migration_target}",
        ),
    ]
    return (
        {
            "target_head": target_head,
            "s7_delta": delta,
            "s7_delta_scope_violations": delta_violations,
            "product_path_identities": product_identities,
            "product_path_mismatches": product_mismatches,
            "contract_tree": {
                "input": contract_input,
                "target": contract_target,
            },
            "lock_blob": {"input": lock_input, "target": lock_target},
            "migration_tree": {
                "input": migration_input,
                "target": migration_target,
            },
        },
        checks,
    )


def build_m2_studio_manifest(
    repo: Path,
    *,
    phase: ValidationPhase,
    target_head: str | None,
    s7_head: str | None,
    enforce_checkout_identity: bool,
) -> dict[str, Any]:
    repo = repo.resolve()
    checks: list[CheckResult] = []
    checkout_head = resolve_commit(repo, "HEAD")
    checkout_branch = run_git(repo, "branch", "--show-current")
    final_record: dict[str, Any] | None = None

    if phase is ValidationPhase.M2_STUDIO_CANDIDATE:
        verified_head = resolve_commit(
            repo,
            target_head
            if target_head is not None
            else (checkout_head if enforce_checkout_identity else M2_INPUT_HEAD),
        )
        branch = (
            checkout_branch if enforce_checkout_identity else CANDIDATE_BRANCH
        )
        checks.extend(
            (
                make_check(
                    "m2.git.branch",
                    is_candidate_branch(branch),
                    f"phase={phase.value} branch={branch}",
                ),
                make_check(
                    "m2.git.worktree_clean",
                    not enforce_checkout_identity
                    or status_is_clean(
                        run_git(repo, "status", "--porcelain=v1")
                    ),
                    "checkout cleanliness is enforced by candidate CLI",
                ),
            )
        )
        candidate, candidate_checks = verify_m2_candidate_identity(
            repo,
            verified_head,
        )
        checks.extend(candidate_checks)
    else:
        if s7_head is None:
            raise ValueError("--s7-head is required for M2_STUDIO_S1_FINAL")
        verified_s7_head = resolve_commit(repo, s7_head)
        verified_head = resolve_commit(
            repo,
            target_head if target_head is not None else checkout_head,
        )
        branch = select_target_branch(repo, verified_head)
        checks.append(
            make_check(
                "m2.git.branch",
                is_s1_branch(branch),
                f"phase={phase.value} branch={branch}",
            )
        )
        candidate, candidate_checks = verify_m2_candidate_identity(
            repo,
            verified_s7_head,
        )
        checks.extend(candidate_checks)
        final_changes = changed_path_statuses(
            repo,
            verified_s7_head,
            verified_head,
        )
        final_gitignore = revision_file_text(
            repo,
            verified_head,
            ".gitignore",
        )
        final_violations = final_scope_violations(
            final_changes,
            final_gitignore,
        )
        protected_identities, protected_mismatches = compare_revision_paths(
            repo,
            verified_s7_head,
            verified_head,
            M2_PRODUCT_PATHS,
        )
        input_ancestry = {
            "S5-CORE": commit_is_ancestor(
                repo,
                M2_WORKSPACE_HEAD,
                verified_head,
            ),
            "S2-RUNTIME": commit_is_ancestor(
                repo,
                M2_RUNTIME_HEAD,
                verified_head,
            ),
            "S4-QUALITY": commit_is_ancestor(
                repo,
                M2_INPUT_HEAD,
                verified_head,
            ),
        }
        s7_ancestry = commit_is_ancestor(
            repo,
            verified_s7_head,
            verified_head,
        )
        checks.extend(
            (
                make_check(
                    "m2.git.s7_head_ancestor",
                    s7_ancestry,
                    (
                        f"s7_head={verified_s7_head} "
                        f"final_head={verified_head}"
                    ),
                ),
                make_check(
                    "m2.git.s1_final_delta_scope",
                    not final_violations,
                    f"violations={final_violations or 'none'}",
                ),
                make_check(
                    "m2.git.final_product_tree",
                    not protected_mismatches,
                    f"mismatches={protected_mismatches or 'none'}",
                ),
                make_check(
                    "m2.git.final_input_heads",
                    all(input_ancestry.values()),
                    f"ancestry={input_ancestry}",
                ),
            )
        )
        final_record = {
            "target_head": verified_head,
            "s7_head": verified_s7_head,
            "s7_head_ancestor": s7_ancestry,
            "delta": [
                {"status": status, "path": path}
                for status, path in final_changes
            ],
            "delta_scope_violations": final_violations,
            "protected_path_identities": protected_identities,
            "protected_path_mismatches": protected_mismatches,
            "input_head_ancestry": input_ancestry,
        }

    topology, topology_checks = verify_m2_topology(repo)
    evidence, evidence_checks = verify_m2_evidence(repo)
    workspace, workspace_checks = verify_m2_workspace(repo, M2_INPUT_HEAD)
    studio, studio_checks = verify_m2_studio_static(repo, M2_INPUT_HEAD)
    checks.extend(topology_checks)
    checks.extend(evidence_checks)
    checks.extend(workspace_checks)
    checks.extend(studio_checks)

    contract_manifest = load_revision_json(
        repo,
        M2_INPUT_HEAD,
        "contracts/contract-set.v1.json",
    )
    recomputed_contract_digest = contract_content_digest(contract_manifest)
    activation_contract_tree = revision_object_id(
        repo,
        M2_ACTIVATION_COMMIT,
        "contracts",
    )
    input_contract_tree = revision_object_id(
        repo,
        M2_INPUT_HEAD,
        "contracts",
    )
    checks.extend(
        (
            make_check(
                "m2.contract.content_digest",
                recomputed_contract_digest == CONTRACT_DIGEST
                and contract_manifest["content_digest"] == CONTRACT_DIGEST,
                f"recomputed={recomputed_contract_digest}",
            ),
            make_check(
                "m2.contract.activation_tree",
                activation_contract_tree
                == input_contract_tree
                == CONTRACT_TREE,
                (
                    f"activation={activation_contract_tree} "
                    f"input={input_contract_tree}"
                ),
            ),
        )
    )

    changed_input_paths = changed_paths(
        repo,
        M2_ACTIVATION_COMMIT,
        M2_INPUT_HEAD,
    )
    secret_findings = high_confidence_secret_findings(
        repo,
        M2_INPUT_HEAD,
        changed_input_paths,
    )
    checks.append(
        make_check(
            "m2.security.high_confidence_secret_scan",
            not secret_findings,
            f"findings={secret_findings or 'none'}",
        )
    )
    activation_migration_tree = revision_object_id(
        repo,
        M2_ACTIVATION_COMMIT,
        "migrations",
    )
    input_migration_tree = revision_object_id(
        repo,
        M2_INPUT_HEAD,
        "migrations",
    )
    activation_infra_tree = revision_object_id(
        repo,
        M2_ACTIVATION_COMMIT,
        "infra",
    )
    input_infra_tree = revision_object_id(repo, M2_INPUT_HEAD, "infra")
    checks.extend(
        (
            make_check(
                "m2.migrations.activation_identity",
                activation_migration_tree == input_migration_tree,
                (
                    f"activation={activation_migration_tree} "
                    f"input={input_migration_tree}"
                ),
            ),
            make_check(
                "m2.compose.activation_identity",
                activation_infra_tree == input_infra_tree,
                (
                    f"activation={activation_infra_tree} "
                    f"input={input_infra_tree}"
                ),
            ),
        )
    )

    failed = [check.check_id for check in checks if check.outcome != "PASS"]
    manifest: dict[str, Any] = {
        "schema": "flowpilot.integration-composition-manifest.m2-studio.v1",
        "work_package": "WP-040",
        "attempt_id": "WP-040-a5",
        "chain_id": M2_CHAIN_ID,
        "execution_mode": "ORDERED",
        "risk_class": "R2",
        "validation_phase": phase.value,
        "base_commit": M2_INPUT_HEAD,
        "input_heads": {
            "S5-CORE": M2_WORKSPACE_HEAD,
            "S2-RUNTIME": M2_RUNTIME_HEAD,
            "S4-QUALITY": M2_INPUT_HEAD,
        },
        "target_head": verified_head,
        "branch": branch,
        "candidate": candidate,
        "topology": topology,
        "contract": {
            "declared_content_digest": contract_manifest["content_digest"],
            "recomputed_content_digest": recomputed_contract_digest,
            "digest_profile": contract_manifest["digest_profile"],
            "activation_tree": activation_contract_tree,
            "input_tree": input_contract_tree,
        },
        "workspace": workspace,
        "studio": studio,
        "evidence": evidence,
        "security": {
            "high_confidence_secret_findings": secret_findings,
        },
        "migrations": {
            "activation_tree": activation_migration_tree,
            "input_tree": input_migration_tree,
        },
        "compose": {
            "activation_tree": activation_infra_tree,
            "input_tree": input_infra_tree,
            "changed_since_activation": (
                activation_infra_tree != input_infra_tree
            ),
        },
        "checks": [asdict(check) for check in checks],
        "summary": {
            "check_count": len(checks),
            "failed_check_count": len(failed),
            "failed_checks": failed,
            "verdict": "PASS" if not failed else "FAIL",
        },
    }
    if final_record is not None:
        manifest["final"] = final_record
    return manifest


def verify_p1_topology(
    repo: Path,
    expected_parents: dict[str, str] | None = None,
) -> tuple[dict[str, Any], list[CheckResult]]:
    parents = expected_parents or {
        P1_CORE_IMPLEMENTATION_HEAD: P1_ACTIVATION_COMMIT,
        P1_CORE_HEAD: P1_CORE_IMPLEMENTATION_HEAD,
        P1_PLATFORM_IMPLEMENTATION_HEAD: P1_CORE_HEAD,
        P1_PLATFORM_HEAD: P1_PLATFORM_IMPLEMENTATION_HEAD,
        P1_RUNTIME_IMPLEMENTATION_HEAD: P1_PLATFORM_HEAD,
        P1_RUNTIME_HEAD: P1_RUNTIME_IMPLEMENTATION_HEAD,
        P1_QUALITY_HEADS[0]: P1_RUNTIME_HEAD,
        P1_QUALITY_HEADS[1]: P1_QUALITY_HEADS[0],
        P1_QUALITY_HEADS[2]: P1_QUALITY_HEADS[1],
        P1_INPUT_HEAD: P1_QUALITY_HEADS[2],
    }
    parent_records: dict[str, list[str]] = {}
    parent_failures: list[str] = []
    for head, expected_parent in parents.items():
        actual = run_git(repo, "show", "-s", "--format=%P", head).split()
        parent_records[head] = actual
        if actual != [expected_parent]:
            parent_failures.append(
                f"{head}:parents={actual}:expected={[expected_parent]}"
            )

    step_scopes = {
        "S5_CORE": {
            "base": P1_ACTIVATION_COMMIT,
            "head": P1_CORE_IMPLEMENTATION_HEAD,
            "exact": (),
            "prefixes": (
                "apps/api/",
                "domain-packs/it-service/",
                "packages/application/",
                "packages/domain/",
                "tests/core/",
            ),
        },
        "S5_HANDOFF": {
            "base": P1_CORE_IMPLEMENTATION_HEAD,
            "head": P1_CORE_HEAD,
            "exact": ("tests/core/evidence/WP-011-a6-HANDOFF.md",),
            "prefixes": (),
        },
        "S3_PLATFORM": {
            "base": P1_CORE_HEAD,
            "head": P1_PLATFORM_IMPLEMENTATION_HEAD,
            "exact": (),
            "prefixes": (
                "apps/mcp-gateway/",
                "mcp-servers/",
                "packages/policy/",
                "packages/security/",
                "packages/tool-contracts/",
                "tests/platform/",
            ),
        },
        "S3_HANDOFF": {
            "base": P1_PLATFORM_IMPLEMENTATION_HEAD,
            "head": P1_PLATFORM_HEAD,
            "exact": ("tests/platform/evidence/WP-020-a2/HANDOFF.md",),
            "prefixes": (),
        },
        "S2_RUNTIME": {
            "base": P1_PLATFORM_HEAD,
            "head": P1_RUNTIME_IMPLEMENTATION_HEAD,
            "exact": ("langgraph.json",),
            "prefixes": (
                "apps/worker/",
                "packages/agent-runtime/",
                "packages/context/",
                "packages/graph/",
                "packages/model-gateway/",
                "tests/runtime/",
            ),
        },
        "S2_HANDOFF": {
            "base": P1_RUNTIME_IMPLEMENTATION_HEAD,
            "head": P1_RUNTIME_HEAD,
            "exact": ("tests/runtime/evidence/WP-010-a3-HANDOFF.md",),
            "prefixes": (),
        },
        "S4_QUALITY": {
            "base": P1_RUNTIME_HEAD,
            "head": P1_QUALITY_IMPLEMENTATION_HEAD,
            "exact": (),
            "prefixes": (
                "artifacts/acceptance/",
                "evals/",
                "packages/evaluation/",
                "packages/observability/",
                "packages/retrieval/",
                "tests/acceptance/",
                "tests/experience/",
                "web/",
            ),
        },
        "S4_HANDOFF": {
            "base": P1_QUALITY_IMPLEMENTATION_HEAD,
            "head": P1_INPUT_HEAD,
            "exact": (
                "tests/acceptance/evidence/WP-030-a4-HANDOFF.md",
                "tests/acceptance/evidence/WP-030-a4-PROOF.json",
            ),
            "prefixes": (),
        },
    }
    scope_records: dict[str, Any] = {}
    checks = [
        make_check(
            "p1.git.linear_topology",
            not parent_failures,
            f"failures={parent_failures or 'none'}",
        )
    ]
    for step, specification in step_scopes.items():
        paths = changed_paths(
            repo,
            str(specification["base"]),
            str(specification["head"]),
        )
        violations = path_scope_violations_by_rule(
            paths,
            exact=specification["exact"],
            prefixes=specification["prefixes"],
        )
        scope_records[step] = {
            "base": specification["base"],
            "head": specification["head"],
            "changed_paths": paths,
            "violations": violations,
        }
        checks.append(
            make_check(
                f"p1.scope.{step.lower()}",
                not violations,
                f"changed={len(paths)} violations={violations or 'none'}",
            )
        )

    commit_count = int(
        run_git(
            repo,
            "rev-list",
            "--count",
            f"{P1_ACTIVATION_COMMIT}..{P1_INPUT_HEAD}",
        )
    )
    checks.append(
        make_check(
            "p1.git.commit_range",
            commit_count == 10,
            f"commits={commit_count}",
        )
    )
    return (
        {
            "activation_commit": P1_ACTIVATION_COMMIT,
            "input_head": P1_INPUT_HEAD,
            "commit_count": commit_count,
            "parents": parent_records,
            "steps": scope_records,
        },
        checks,
    )


def _strict_revision_json(repo: Path, revision: str, path: str) -> Any:
    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(
        revision_file_text(repo, revision, path),
        object_pairs_hook=reject_duplicate_keys,
    )


def p1_dataset_violations(
    manifest: Any,
    case_document: Any,
    card_text: str,
) -> list[str]:
    violations: list[str] = []
    expected_manifest_fields = {
        "schema_version",
        "dataset_id",
        "version",
        "candidate_only",
        "case_count",
        "files",
    }
    if not isinstance(manifest, dict) or set(manifest) != expected_manifest_fields:
        return ["manifest.fields"]
    if manifest.get("candidate_only") is not True:
        violations.append("manifest.candidate_only")
    if manifest.get("case_count") != 20:
        violations.append("manifest.case_count")
    if manifest.get("files") != {
        "dataset-card.yaml": f"sha256:{P1_DATASET_CARD_SHA256}",
        "vpn-cases.json": f"sha256:{P1_CASE_FILE_SHA256}",
    }:
        violations.append("manifest.files")
    if not isinstance(case_document, dict):
        return violations + ["cases.document"]
    if set(case_document) != {
        "schema_version",
        "dataset_id",
        "version",
        "cases",
    }:
        violations.append("cases.fields")
    if (
        case_document.get("dataset_id") != manifest.get("dataset_id")
        or case_document.get("version") != manifest.get("version")
    ):
        violations.append("cases.identity")
    cases = case_document.get("cases")
    if not isinstance(cases, list) or len(cases) != 20:
        return violations + ["cases.count"]
    expected_ids = [f"vpn-p1-{index:03d}" for index in range(1, 21)]
    case_ids = [case.get("case_id") for case in cases if isinstance(case, dict)]
    scenarios = [case.get("scenario") for case in cases if isinstance(case, dict)]
    if len(case_ids) != 20 or case_ids != expected_ids:
        violations.append("cases.ids")
    if len(scenarios) != 20 or len(set(scenarios)) != 20:
        violations.append("cases.scenarios")
    case_fields = {
        "case_id",
        "suite",
        "category",
        "scenario",
        "assertions",
        "judge_scores",
        "expected",
    }
    expected_fields = {
        "task_status",
        "failure_code",
        "logical_knowledge_calls",
        "gateway_attempts",
        "result_ref",
        "citation_count",
    }
    if any(
        not isinstance(case, dict)
        or set(case) != case_fields
        or not isinstance(case.get("expected"), dict)
        or set(case["expected"]) != expected_fields
        for case in cases
    ):
        violations.append("cases.closed_fields")
    required_scenarios = {
        "missing_environment_resume_after_restart",
        "artifact_store_recovery",
        "duplicate_terminal_delivery",
        "wrong_tenant_request_reference",
        "wrong_tenant_knowledge_acl",
        "malicious_query_worker_rejected",
        "malicious_acl_query_adapter_rejected",
        "security_projection_and_judge_boundary",
    }
    if not required_scenarios.issubset(set(scenarios)):
        violations.append("cases.required_security_recovery_coverage")
    card_tokens = (
        "candidate_only: true",
        "release_eligible: false",
        "declared_case_count: 20",
        "denominator: all_declared_cases",
        "external_network: disabled",
        "pii: none",
        "secrets: none",
    )
    if not all(token in card_text for token in card_tokens):
        violations.append("dataset_card.boundaries")
    return sorted(set(violations))


def verify_p1_dataset(
    repo: Path,
) -> tuple[dict[str, Any], list[CheckResult]]:
    root = "evals/datasets/functional/vpn-readonly-p1"
    manifest = _strict_revision_json(
        repo,
        P1_INPUT_HEAD,
        f"{root}/manifest.json",
    )
    case_document = _strict_revision_json(
        repo,
        P1_INPUT_HEAD,
        f"{root}/vpn-cases.json",
    )
    card_bytes = revision_file_bytes(
        repo,
        P1_INPUT_HEAD,
        f"{root}/dataset-card.yaml",
    )
    case_bytes = revision_file_bytes(
        repo,
        P1_INPUT_HEAD,
        f"{root}/vpn-cases.json",
    )
    card_hash = sha256_bytes(card_bytes)
    case_hash = sha256_bytes(case_bytes)
    violations = p1_dataset_violations(
        manifest,
        case_document,
        card_bytes.decode("utf-8", errors="strict"),
    )
    cases = case_document["cases"]
    checks = [
        make_check(
            "p1.dataset.file_hashes",
            card_hash == P1_DATASET_CARD_SHA256
            and case_hash == P1_CASE_FILE_SHA256,
            f"card=sha256:{card_hash} cases=sha256:{case_hash}",
        ),
        make_check(
            "p1.dataset.closed_twenty_cases",
            not violations,
            f"violations={violations or 'none'}",
        ),
    ]
    return (
        {
            "dataset_id": manifest["dataset_id"],
            "version": manifest["version"],
            "candidate_only": manifest["candidate_only"],
            "case_count": len(cases),
            "case_ids": [case["case_id"] for case in cases],
            "scenarios": [case["scenario"] for case in cases],
            "dataset_card_sha256": f"sha256:{card_hash}",
            "case_file_sha256": f"sha256:{case_hash}",
            "violations": violations,
            "expected_by_case": {
                case["case_id"]: case["expected"] for case in cases
            },
        },
        checks,
    )


def verify_p1_evidence(
    repo: Path,
    dataset: dict[str, Any],
) -> tuple[dict[str, Any], list[CheckResult]]:
    records: dict[str, Any] = {}
    checks: list[CheckResult] = []
    for evidence_id, (revision, path, expected_hash) in P1_EVIDENCE.items():
        actual_hash = sha256_bytes(revision_file_bytes(repo, revision, path))
        records[evidence_id] = {
            "revision": revision,
            "path": path,
            "sha256": f"sha256:{actual_hash}",
        }
        checks.append(
            make_check(
                f"p1.evidence.{evidence_id.lower()}",
                actual_hash == expected_hash,
                f"sha256:{actual_hash}",
            )
        )

    authority_hash = sha256_bytes(
        revision_file_bytes(
            repo,
            P1_ACTIVATION_COMMIT,
            P1_AUTHORITY_PATH,
        )
    )
    authority_text = revision_file_text(
        repo,
        P1_ACTIVATION_COMMIT,
        P1_AUTHORITY_PATH,
    )
    authority_tokens = (
        "CHAIN_ID=CHAIN-P1-VPN-READONLY-01",
        "STATUS=ACTIVE",
        "RISK_CLASS=R2",
        "FINAL_GATE=S7-INTEGRATION->S1-ARCH",
        "STEP_ID=P1-VPN-05-S7",
        "ATTEMPT_ID=WP-040-a6",
        "GATE_LEVEL=RELEASE",
    )
    checks.append(
        make_check(
            "p1.evidence.chain_authority",
            authority_hash == P1_AUTHORITY_SHA256
            and all(token in authority_text for token in authority_tokens),
            f"sha256:{authority_hash}",
        )
    )
    records["CHAIN_AUTHORITY"] = {
        "revision": P1_ACTIVATION_COMMIT,
        "path": P1_AUTHORITY_PATH,
        "sha256": f"sha256:{authority_hash}",
    }

    proof = load_revision_json(
        repo,
        P1_INPUT_HEAD,
        "tests/acceptance/evidence/WP-030-a4-PROOF.json",
    )
    proof_results = proof.get("case_results", [])
    proof_by_case = {
        result.get("case_id"): result
        for result in proof_results
        if isinstance(result, dict)
    }
    projection_fields = (
        "task_status",
        "logical_knowledge_calls",
        "gateway_attempts",
        "result_ref",
        "citation_count",
    )
    projections_match = all(
        case_id in proof_by_case
        and proof_by_case[case_id].get("status") == "passed"
        and all(
            proof_by_case[case_id].get(field) == expected[field]
            for field in projection_fields
        )
        for case_id, expected in dataset["expected_by_case"].items()
    )
    aggregate = proof.get("aggregate", {})
    proof_dataset = proof.get("candidate_dataset", {})
    scope = proof.get("scope", {})
    proof_valid = (
        proof.get("schema_version") == "flowpilot.wp030a4-proof.v1"
        and proof.get("chain_id") == P1_CHAIN_ID
        and proof.get("input_head") == P1_RUNTIME_HEAD
        and proof.get("implementation_head") == P1_QUALITY_IMPLEMENTATION_HEAD
        and proof.get("contract_content_digest") == CONTRACT_DIGEST
        and proof.get("knowledge_schema_pin") == P1_KNOWLEDGE_SCHEMA_PIN
        and proof_dataset.get("candidate_only") is True
        and proof_dataset.get("release_eligible") is False
        and proof_dataset.get("case_count") == 20
        and proof_dataset.get("denominator_policy") == "all_declared_cases"
        and proof_dataset.get("dataset_card_hash")
        == f"sha256:{P1_DATASET_CARD_SHA256}"
        and proof_dataset.get("case_file_hash")
        == f"sha256:{P1_CASE_FILE_SHA256}"
        and aggregate
        == {
            "declared_case_count": 20,
            "result_count": 20,
            "passed": 20,
            "failed": 0,
            "skipped": 0,
            "quarantined": 0,
            "failure_count": 0,
            "gate_result": "pass",
            "report_state": "complete",
            "success_rate_reported": False,
        }
        and len(proof_results) == 20
        and len(proof_by_case) == 20
        and projections_match
        and all(proof.get("coverage", {}).values())
        and scope.get("release_gate") is False
        and scope.get("functional_120_complete") is False
        and scope.get("safety_fault_36_complete") is False
        and scope.get("production_connection") is False
        and scope.get("external_network") is False
        and scope.get("provider_usage") is False
        and scope.get("contract_change") is False
        and scope.get("shared_file_change") is False
        and proof.get("encoding_and_safety_gates", {}).get(
            "high_confidence_secret_matches"
        )
        == 0
        and proof.get("encoding_and_safety_gates", {}).get(
            "high_confidence_pii_matches"
        )
        == 0
    )
    checks.append(
        make_check(
            "p1.evidence.s4_proof_semantics",
            proof_valid,
            (
                f"cases={len(proof_results)} "
                f"projections_match={projections_match}"
            ),
        )
    )

    tenant_denials = (
        proof_by_case.get("vpn-p1-009", {}),
        proof_by_case.get("vpn-p1-010", {}),
    )
    cross_tenant_zero = all(
        result.get("task_status") == "FAILED"
        and result.get("logical_knowledge_calls") == 0
        and result.get("result_ref") == "absent"
        and result.get("citation_count") == 0
        for result in tenant_denials
    )
    checks.append(
        make_check(
            "p1.security.cross_tenant_successful_retrieval_zero",
            cross_tenant_zero,
            f"cases={[result.get('case_id') for result in tenant_denials]}",
        )
    )
    recovery_expectations = {
        "vpn-p1-003": (1, 1, "present"),
        "vpn-p1-006": (1, 2, "present"),
        "vpn-p1-007": (1, 1, "stable"),
    }
    recovery_single_call = all(
        proof_by_case.get(case_id, {}).get("logical_knowledge_calls")
        == expected[0]
        and proof_by_case.get(case_id, {}).get("gateway_attempts")
        == expected[1]
        and proof_by_case.get(case_id, {}).get("result_ref") == expected[2]
        for case_id, expected in recovery_expectations.items()
    )
    checks.append(
        make_check(
            "p1.recovery.no_duplicate_logical_knowledge_call",
            recovery_single_call,
            f"cases={sorted(recovery_expectations)}",
        )
    )
    records["S4_PROOF_SEMANTICS"] = {
        "declared_case_count": aggregate.get("declared_case_count"),
        "passed": aggregate.get("passed"),
        "failed": aggregate.get("failed"),
        "candidate_only": proof_dataset.get("candidate_only"),
        "release_eligible": proof_dataset.get("release_eligible"),
        "cross_tenant_successful_retrievals": 0 if cross_tenant_zero else None,
        "recovery_single_logical_call": recovery_single_call,
    }
    return records, checks


def _literal_module_bindings(source: str) -> dict[str, Any]:
    tree = ast.parse(source)
    bindings: dict[str, Any] = {}

    def evaluate(node: ast.AST) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name) and node.id in bindings:
            return bindings[node.id]
        if isinstance(node, ast.List):
            return [evaluate(item) for item in node.elts]
        if isinstance(node, ast.Tuple):
            return tuple(evaluate(item) for item in node.elts)
        if isinstance(node, ast.Dict):
            result: dict[Any, Any] = {}
            for key, value in zip(node.keys, node.values, strict=True):
                if key is None:
                    raise ValueError("dictionary expansion is not literal")
                result[evaluate(key)] = evaluate(value)
            return result
        raise ValueError(f"non-literal module binding: {ast.dump(node)}")

    for node in tree.body:
        target: ast.expr | None = None
        value: ast.expr | None = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            target = node.target
            value = node.value
        if not isinstance(target, ast.Name) or value is None:
            continue
        try:
            bindings[target.id] = evaluate(value)
        except ValueError:
            continue
    return bindings


def verify_p1_static_boundaries(
    repo: Path,
) -> tuple[dict[str, Any], list[CheckResult]]:
    knowledge_source = revision_file_text(
        repo,
        P1_INPUT_HEAD,
        "mcp-servers/knowledge/src/flowpilot_mcp_knowledge/server.py",
    )
    bindings = _literal_module_bindings(knowledge_source)
    schema_projection = {
        "name": bindings.get("TOOL_NAME"),
        "input_schema": bindings.get("INPUT_SCHEMA"),
        "output_schema": bindings.get("OUTPUT_SCHEMA"),
    }
    recomputed_pin = (
        "sha256:" + sha256_bytes(rfc8785_canonical_bytes(schema_projection))
    )
    declared_pin = bindings.get("KNOWLEDGE_SCHEMA_PIN")

    worker_paths = [
        path
        for path in run_git(
            repo,
            "ls-tree",
            "-r",
            "--name-only",
            P1_INPUT_HEAD,
            "apps/worker",
        ).splitlines()
        if path.endswith(".py")
    ]
    worker_sources = {
        path: revision_file_text(repo, P1_INPUT_HEAD, path)
        for path in worker_paths
    }
    forbidden_worker_tokens = (
        "flowpilot_mcp_knowledge",
        "KnowledgeMcpAdapter",
        "KnowledgeRecord",
    )
    bypass_findings = sorted(
        f"{path}:{token}"
        for path, source in worker_sources.items()
        for token in forbidden_worker_tokens
        if token in source
    )
    vpn_source = worker_sources[
        "apps/worker/src/flowpilot_worker/vpn.py"
    ]
    gateway_only = (
        not bypass_findings
        and "GatewayClientPort" in vpn_source
        and "GatewayCall" in vpn_source
        and "await self._gateway.execute(call)" in vpn_source
        and "interrupt(" in vpn_source
    )

    runtime_test = revision_file_text(
        repo,
        P1_INPUT_HEAD,
        "tests/runtime/integration/test_vpn_readonly_graph.py",
    )
    acceptance_test = revision_file_text(
        repo,
        P1_INPUT_HEAD,
        "tests/acceptance/vpn/test_vpn_readonly_candidate.py",
    )
    recovery_tokens = (
        "missing_environment",
        "restart",
        "logical_execution_count == 1",
        "RETRY_PENDING",
        "result_ref",
    )
    oracle_tokens = (
        "assert.tenant.cross_access_zero.v1",
        "all_declared_cases",
        "release_eligible",
        "test_vpn_judge_cannot_override_execution_or_deterministic_failures",
    )
    blackbox_source = revision_file_text(
        repo,
        P1_INPUT_HEAD,
        "tests/acceptance/vpn/blackbox.py",
    )
    checks = [
        make_check(
            "p1.knowledge.schema_hash",
            declared_pin == P1_KNOWLEDGE_SCHEMA_PIN
            and recomputed_pin == P1_KNOWLEDGE_SCHEMA_PIN,
            f"declared={declared_pin} recomputed={recomputed_pin}",
        ),
        make_check(
            "p1.runtime.knowledge_gateway_only",
            gateway_only,
            f"bypass_findings={bypass_findings or 'none'}",
        ),
        make_check(
            "p1.runtime.interrupt_recovery_tests",
            all(token in runtime_test for token in recovery_tokens),
            f"tokens={len(recovery_tokens)}",
        ),
        make_check(
            "p1.acceptance.security_oracle",
            all(
                token in acceptance_test or token in blackbox_source
                for token in oracle_tokens
            ),
            f"tokens={len(oracle_tokens)}",
        ),
    ]
    return (
        {
            "knowledge_schema_pin": {
                "declared": declared_pin,
                "recomputed": recomputed_pin,
            },
            "worker_python_paths": worker_paths,
            "knowledge_bypass_findings": bypass_findings,
            "recovery_test_tokens": list(recovery_tokens),
            "acceptance_oracle_tokens": list(oracle_tokens),
        },
        checks,
    )


def verify_p1_workspace(
    repo: Path,
) -> tuple[dict[str, Any], list[CheckResult]]:
    workspace, source_checks = verify_m2_workspace(repo, P1_INPUT_HEAD)
    checks = [
        CheckResult(
            check_id=check.check_id.replace("m2.", "p1.", 1),
            outcome=check.outcome,
            evidence=check.evidence,
        )
        for check in source_checks
    ]
    return workspace, checks


def verify_p1_candidate_identity(
    repo: Path,
    target_head: str,
) -> tuple[dict[str, Any], list[CheckResult]]:
    product_identities, product_mismatches = compare_revision_paths(
        repo,
        P1_INPUT_HEAD,
        target_head,
        P1_PRODUCT_PATHS,
    )
    contract_input = revision_object_id(repo, P1_INPUT_HEAD, "contracts")
    contract_target = revision_object_id(repo, target_head, "contracts")
    migration_input = revision_object_id(repo, P1_INPUT_HEAD, "migrations")
    migration_target = revision_object_id(repo, target_head, "migrations")
    lock_input = revision_object_id(repo, P1_INPUT_HEAD, "uv.lock")
    lock_target = revision_object_id(repo, target_head, "uv.lock")
    delta = changed_paths(repo, P1_INPUT_HEAD, target_head)
    delta_violations = path_scope_violations(delta, S7_ALLOWED_PREFIXES)
    checks = [
        make_check(
            "p1.git.input_ancestor",
            commit_is_ancestor(repo, P1_INPUT_HEAD, target_head),
            f"input={P1_INPUT_HEAD} target={target_head}",
        ),
        make_check(
            "p1.git.s7_delta_scope",
            not delta_violations,
            f"violations={delta_violations or 'none'}",
        ),
        make_check(
            "p1.git.product_tree",
            not product_mismatches,
            f"mismatches={product_mismatches or 'none'}",
        ),
        make_check(
            "p1.contract.tree",
            contract_input == contract_target == CONTRACT_TREE,
            f"input={contract_input} target={contract_target}",
        ),
        make_check(
            "p1.workspace.lock_blob",
            lock_input == lock_target,
            f"input={lock_input} target={lock_target}",
        ),
        make_check(
            "p1.migrations.tree",
            migration_input == migration_target,
            f"input={migration_input} target={migration_target}",
        ),
    ]
    return (
        {
            "target_head": target_head,
            "s7_delta": delta,
            "s7_delta_scope_violations": delta_violations,
            "product_path_identities": product_identities,
            "product_path_mismatches": product_mismatches,
            "contract_tree": {
                "input": contract_input,
                "target": contract_target,
            },
            "lock_blob": {"input": lock_input, "target": lock_target},
            "migration_tree": {
                "input": migration_input,
                "target": migration_target,
            },
        },
        checks,
    )


def build_p1_vpn_manifest(
    repo: Path,
    *,
    phase: ValidationPhase,
    target_head: str | None,
    s7_head: str | None,
    enforce_checkout_identity: bool,
) -> dict[str, Any]:
    repo = repo.resolve()
    checks: list[CheckResult] = []
    checkout_head = resolve_commit(repo, "HEAD")
    checkout_branch = run_git(repo, "branch", "--show-current")
    final_record: dict[str, Any] | None = None

    if phase is ValidationPhase.P1_VPN_CANDIDATE:
        verified_head = resolve_commit(
            repo,
            target_head
            if target_head is not None
            else (checkout_head if enforce_checkout_identity else P1_INPUT_HEAD),
        )
        branch = checkout_branch if enforce_checkout_identity else CANDIDATE_BRANCH
        checks.extend(
            (
                make_check(
                    "p1.git.branch",
                    is_candidate_branch(branch),
                    f"phase={phase.value} branch={branch}",
                ),
                make_check(
                    "p1.git.worktree_clean",
                    not enforce_checkout_identity
                    or status_is_clean(
                        run_git(repo, "status", "--porcelain=v1")
                    ),
                    "checkout cleanliness is enforced by candidate CLI",
                ),
            )
        )
        candidate, candidate_checks = verify_p1_candidate_identity(
            repo,
            verified_head,
        )
        checks.extend(candidate_checks)
    else:
        if s7_head is None:
            raise ValueError("--s7-head is required for P1_VPN_S1_FINAL")
        verified_s7_head = resolve_commit(repo, s7_head)
        verified_head = resolve_commit(
            repo,
            target_head if target_head is not None else checkout_head,
        )
        branch = select_target_branch(repo, verified_head)
        checks.append(
            make_check(
                "p1.git.branch",
                is_s1_branch(branch),
                f"phase={phase.value} branch={branch}",
            )
        )
        candidate, candidate_checks = verify_p1_candidate_identity(
            repo,
            verified_s7_head,
        )
        checks.extend(candidate_checks)
        final_changes = changed_path_statuses(
            repo,
            verified_s7_head,
            verified_head,
        )
        final_gitignore = revision_file_text(repo, verified_head, ".gitignore")
        final_violations = final_scope_violations(
            final_changes,
            final_gitignore,
        )
        protected_identities, protected_mismatches = compare_revision_paths(
            repo,
            verified_s7_head,
            verified_head,
            P1_PRODUCT_PATHS,
        )
        input_ancestry = {
            "S5-CORE": commit_is_ancestor(
                repo,
                P1_CORE_HEAD,
                verified_head,
            ),
            "S3-PLATFORM": commit_is_ancestor(
                repo,
                P1_PLATFORM_HEAD,
                verified_head,
            ),
            "S2-RUNTIME": commit_is_ancestor(
                repo,
                P1_RUNTIME_HEAD,
                verified_head,
            ),
            "S4-QUALITY": commit_is_ancestor(
                repo,
                P1_INPUT_HEAD,
                verified_head,
            ),
        }
        s7_ancestry = commit_is_ancestor(
            repo,
            verified_s7_head,
            verified_head,
        )
        checks.extend(
            (
                make_check(
                    "p1.git.s7_head_ancestor",
                    s7_ancestry,
                    (
                        f"s7_head={verified_s7_head} "
                        f"final_head={verified_head}"
                    ),
                ),
                make_check(
                    "p1.git.s1_final_delta_scope",
                    not final_violations,
                    f"violations={final_violations or 'none'}",
                ),
                make_check(
                    "p1.git.final_product_tree",
                    not protected_mismatches,
                    f"mismatches={protected_mismatches or 'none'}",
                ),
                make_check(
                    "p1.git.final_input_heads",
                    all(input_ancestry.values()),
                    f"ancestry={input_ancestry}",
                ),
            )
        )
        final_record = {
            "target_head": verified_head,
            "s7_head": verified_s7_head,
            "s7_head_ancestor": s7_ancestry,
            "delta": [
                {"status": status, "path": path}
                for status, path in final_changes
            ],
            "delta_scope_violations": final_violations,
            "protected_path_identities": protected_identities,
            "protected_path_mismatches": protected_mismatches,
            "input_head_ancestry": input_ancestry,
        }

    topology, topology_checks = verify_p1_topology(repo)
    dataset, dataset_checks = verify_p1_dataset(repo)
    evidence, evidence_checks = verify_p1_evidence(repo, dataset)
    workspace, workspace_checks = verify_p1_workspace(repo)
    boundaries, boundary_checks = verify_p1_static_boundaries(repo)
    checks.extend(topology_checks)
    checks.extend(dataset_checks)
    checks.extend(evidence_checks)
    checks.extend(workspace_checks)
    checks.extend(boundary_checks)

    contract_manifest = load_revision_json(
        repo,
        P1_INPUT_HEAD,
        "contracts/contract-set.v1.json",
    )
    recomputed_contract_digest = contract_content_digest(contract_manifest)
    activation_contract_tree = revision_object_id(
        repo,
        P1_ACTIVATION_COMMIT,
        "contracts",
    )
    input_contract_tree = revision_object_id(repo, P1_INPUT_HEAD, "contracts")
    checks.extend(
        (
            make_check(
                "p1.contract.content_digest",
                recomputed_contract_digest == CONTRACT_DIGEST
                and contract_manifest["content_digest"] == CONTRACT_DIGEST,
                f"recomputed={recomputed_contract_digest}",
            ),
            make_check(
                "p1.contract.activation_tree",
                activation_contract_tree == input_contract_tree == CONTRACT_TREE,
                (
                    f"activation={activation_contract_tree} "
                    f"input={input_contract_tree}"
                ),
            ),
        )
    )

    changed_input_paths = changed_paths(
        repo,
        P1_ACTIVATION_COMMIT,
        P1_INPUT_HEAD,
    )
    secret_findings = high_confidence_secret_findings(
        repo,
        P1_INPUT_HEAD,
        changed_input_paths,
    )
    checks.append(
        make_check(
            "p1.security.high_confidence_secret_scan",
            not secret_findings,
            f"findings={secret_findings or 'none'}",
        )
    )
    activation_migration_tree = revision_object_id(
        repo,
        P1_ACTIVATION_COMMIT,
        "migrations",
    )
    input_migration_tree = revision_object_id(repo, P1_INPUT_HEAD, "migrations")
    activation_infra_tree = revision_object_id(
        repo,
        P1_ACTIVATION_COMMIT,
        "infra",
    )
    input_infra_tree = revision_object_id(repo, P1_INPUT_HEAD, "infra")
    activation_lock_blob = revision_object_id(
        repo,
        P1_ACTIVATION_COMMIT,
        "uv.lock",
    )
    input_lock_blob = revision_object_id(repo, P1_INPUT_HEAD, "uv.lock")
    checks.extend(
        (
            make_check(
                "p1.workspace.activation_lock_identity",
                activation_lock_blob == input_lock_blob,
                f"activation={activation_lock_blob} input={input_lock_blob}",
            ),
            make_check(
                "p1.migrations.activation_identity",
                activation_migration_tree == input_migration_tree,
                (
                    f"activation={activation_migration_tree} "
                    f"input={input_migration_tree}"
                ),
            ),
            make_check(
                "p1.compose.activation_identity",
                activation_infra_tree == input_infra_tree,
                (
                    f"activation={activation_infra_tree} "
                    f"input={input_infra_tree}"
                ),
            ),
        )
    )

    failed = [check.check_id for check in checks if check.outcome != "PASS"]
    manifest: dict[str, Any] = {
        "schema": "flowpilot.integration-composition-manifest.p1-vpn.v1",
        "work_package": "WP-040",
        "attempt_id": "WP-040-a6",
        "chain_id": P1_CHAIN_ID,
        "execution_mode": "ORDERED",
        "risk_class": "R2",
        "validation_phase": phase.value,
        "base_commit": P1_INPUT_HEAD,
        "input_heads": {
            "S5-CORE": P1_CORE_HEAD,
            "S3-PLATFORM": P1_PLATFORM_HEAD,
            "S2-RUNTIME": P1_RUNTIME_HEAD,
            "S4-QUALITY": P1_INPUT_HEAD,
        },
        "target_head": verified_head,
        "branch": branch,
        "candidate": candidate,
        "topology": topology,
        "contract": {
            "declared_content_digest": contract_manifest["content_digest"],
            "recomputed_content_digest": recomputed_contract_digest,
            "digest_profile": contract_manifest["digest_profile"],
            "activation_tree": activation_contract_tree,
            "input_tree": input_contract_tree,
        },
        "workspace": workspace,
        "dataset": dataset,
        "boundaries": boundaries,
        "evidence": evidence,
        "security": {
            "high_confidence_secret_findings": secret_findings,
            "cross_tenant_successful_retrievals": evidence[
                "S4_PROOF_SEMANTICS"
            ]["cross_tenant_successful_retrievals"],
            "knowledge_bypass_findings": boundaries[
                "knowledge_bypass_findings"
            ],
        },
        "migrations": {
            "activation_tree": activation_migration_tree,
            "input_tree": input_migration_tree,
        },
        "compose": {
            "activation_tree": activation_infra_tree,
            "input_tree": input_infra_tree,
            "changed_since_activation": activation_infra_tree != input_infra_tree,
        },
        "checks": [asdict(check) for check in checks],
        "summary": {
            "check_count": len(checks),
            "failed_check_count": len(failed),
            "failed_checks": failed,
            "verdict": "PASS" if not failed else "FAIL",
        },
    }
    if final_record is not None:
        manifest["final"] = final_record
    return manifest


def verify_p2_topology(
    repo: Path,
    expected_parents: dict[str, str] | None = None,
) -> tuple[dict[str, Any], list[CheckResult]]:
    parents = expected_parents or {
        P2_CONTROL_HEAD: P2_ACTIVATION_COMMIT,
        P2_DATA_IMPLEMENTATION_HEAD: P2_CONTROL_HEAD,
        P2_DATA_HEAD: P2_DATA_IMPLEMENTATION_HEAD,
        P2_RUNTIME_IMPLEMENTATION_HEAD: P2_DATA_HEAD,
        P2_INPUT_HEAD: P2_RUNTIME_IMPLEMENTATION_HEAD,
    }
    parent_records: dict[str, list[str]] = {}
    parent_failures: list[str] = []
    for head, expected_parent in parents.items():
        actual = run_git(repo, "show", "-s", "--format=%P", head).split()
        parent_records[head] = actual
        if actual != [expected_parent]:
            parent_failures.append(
                f"{head}:parents={actual}:expected={[expected_parent]}"
            )

    step_scopes: dict[str, dict[str, Any]] = {
        "S1_CONTROL": {
            "base": P2_ACTIVATION_COMMIT,
            "head": P2_CONTROL_HEAD,
            "exact": ("AGENTS.md", "README.md"),
            "prefixes": ("docs/architecture/", "docs/team/"),
        },
        "S6_DATA": {
            "base": P2_CONTROL_HEAD,
            "head": P2_DATA_IMPLEMENTATION_HEAD,
            "exact": (),
            "prefixes": ("packages/persistence/", "tests/data/"),
        },
        "S6_HANDOFF": {
            "base": P2_DATA_IMPLEMENTATION_HEAD,
            "head": P2_DATA_HEAD,
            "exact": ("tests/data/evidence/WP-021-a3-HANDOFF.md",),
            "prefixes": (),
        },
        "S2_RUNTIME": {
            "base": P2_DATA_HEAD,
            "head": P2_RUNTIME_IMPLEMENTATION_HEAD,
            "exact": (),
            "prefixes": (
                "apps/worker/",
                "packages/graph/",
                "tests/runtime/",
            ),
        },
        "S2_HANDOFF": {
            "base": P2_RUNTIME_IMPLEMENTATION_HEAD,
            "head": P2_INPUT_HEAD,
            "exact": ("tests/runtime/evidence/WP-010-a4-HANDOFF.md",),
            "prefixes": (),
        },
    }
    scope_records: dict[str, Any] = {}
    checks = [
        make_check(
            "p2.git.linear_topology",
            not parent_failures,
            f"failures={parent_failures or 'none'}",
        )
    ]
    for step, specification in step_scopes.items():
        paths = changed_paths(
            repo,
            str(specification["base"]),
            str(specification["head"]),
        )
        violations = path_scope_violations_by_rule(
            paths,
            exact=specification["exact"],
            prefixes=specification["prefixes"],
        )
        scope_records[step] = {
            "base": specification["base"],
            "head": specification["head"],
            "changed_paths": paths,
            "violations": violations,
        }
        checks.append(
            make_check(
                f"p2.scope.{step.lower()}",
                not violations,
                f"changed={len(paths)} violations={violations or 'none'}",
            )
        )

    commit_count = int(
        run_git(
            repo,
            "rev-list",
            "--count",
            f"{P2_ACTIVATION_COMMIT}..{P2_INPUT_HEAD}",
        )
    )
    checks.append(
        make_check(
            "p2.git.commit_range",
            commit_count == 5,
            f"commits={commit_count}",
        )
    )
    return (
        {
            "activation_commit": P2_ACTIVATION_COMMIT,
            "control_head": P2_CONTROL_HEAD,
            "input_head": P2_INPUT_HEAD,
            "commit_count": commit_count,
            "parents": parent_records,
            "steps": scope_records,
        },
        checks,
    )


def verify_p2_evidence(
    repo: Path,
) -> tuple[dict[str, Any], list[CheckResult]]:
    records: dict[str, Any] = {}
    checks: list[CheckResult] = []
    for name, (revision, path, expected_hash) in P2_EVIDENCE.items():
        content = revision_file_bytes(repo, revision, path)
        observed_hash = sha256_bytes(content)
        text = content.decode("utf-8", errors="strict")
        records[name] = {
            "revision": revision,
            "path": path,
            "sha256": f"sha256:{observed_hash}",
        }
        checks.append(
            make_check(
                f"p2.evidence.{name.lower()}",
                observed_hash == expected_hash,
                f"sha256:{observed_hash}",
            )
        )
        if name.endswith("HANDOFF"):
            expected_attempt = (
                "WP-021-a3" if name == "S6_HANDOFF" else "WP-010-a4"
            )
            semantic_ok = all(
                marker in text
                for marker in (
                    "OUTCOME=PASS_HANDOFF",
                    f"ATTEMPT_ID={expected_attempt}",
                    f"CONTRACT_CONTENT_DIGEST={CONTRACT_DIGEST}",
                    "GATE=PASS",
                )
            )
            checks.append(
                make_check(
                    f"p2.evidence.{name.lower()}_semantics",
                    semantic_ok,
                    f"attempt={expected_attempt} pass_handoff={semantic_ok}",
                )
            )
    return records, checks


def verify_p2_static_boundaries(
    repo: Path,
) -> tuple[dict[str, Any], list[CheckResult]]:
    worker_paths = sorted(
        path
        for path in run_git(
            repo,
            "ls-tree",
            "-r",
            "--name-only",
            P2_INPUT_HEAD,
            "apps/worker/src",
        ).splitlines()
        if path.endswith(".py")
    )
    forbidden_imports = ("psycopg", "redis", "sqlalchemy")
    driver_bypass_findings: list[str] = []
    for path in worker_paths:
        source = revision_file_text(repo, P2_INPUT_HEAD, path)
        tree = ast.parse(source, filename=path)
        modules: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                modules.append(node.module)
        for module in modules:
            if module.split(".", 1)[0] in forbidden_imports:
                driver_bypass_findings.append(f"{path}:{module}")

    durable_source = revision_file_text(
        repo,
        P2_INPUT_HEAD,
        "apps/worker/src/flowpilot_worker/durable.py",
    )
    worker_persistence_source = revision_file_text(
        repo,
        P2_INPUT_HEAD,
        "apps/worker/src/flowpilot_worker/persistence.py",
    )
    postgres_source = revision_file_text(
        repo,
        P2_INPUT_HEAD,
        "packages/persistence/src/flowpilot_persistence/postgres.py",
    )
    recovery_source = revision_file_text(
        repo,
        P2_INPUT_HEAD,
        "packages/persistence/src/flowpilot_persistence/recovery.py",
    )
    redis_source = revision_file_text(
        repo,
        P2_INPUT_HEAD,
        "packages/persistence/src/flowpilot_persistence/redis_coordination.py",
    )
    typed_assembly = all(
        marker in durable_source
        for marker in (
            "DataUnitOfWorkFactory",
            "CoordinationRebuilder",
            "PersistenceCheckpointAdapter",
            "PersistenceLeaseAdapter",
            "control_checkpointer",
        )
    )
    explicit_control = (
        "if control_checkpointer is None" in durable_source
        and "InMemorySaver" not in durable_source
        and "InMemorySaver" not in worker_persistence_source
    )
    fenced_cas = all(
        marker in postgres_source
        for marker in (
            "run_generation = flowpilot.task_leases.run_generation + 1",
            "SET lease_token = 'released_' || lease_token",
            "checkpoint compare-and-swap sequence does not match",
            "PersistenceErrorCode.STALE_FENCE",
        )
    )
    tenant_rebuild = all(
        marker in recovery_source + redis_source
        for marker in (
            "a complete trusted tenant inventory is required",
            "runnable_signals",
            "rebuild_tenant",
            "tenant rebuild source contains another tenant",
        )
    )
    checks = [
        make_check(
            "p2.boundary.worker_no_driver_bypass",
            not driver_bypass_findings,
            f"findings={driver_bypass_findings or 'none'}",
        ),
        make_check(
            "p2.boundary.typed_durable_assembly",
            typed_assembly,
            f"typed_assembly={typed_assembly}",
        ),
        make_check(
            "p2.boundary.explicit_control_checkpointer",
            explicit_control,
            f"explicit_control={explicit_control}",
        ),
        make_check(
            "p2.boundary.fenced_checkpoint_cas",
            fenced_cas,
            f"fenced_cas={fenced_cas}",
        ),
        make_check(
            "p2.boundary.trusted_tenant_rebuild",
            tenant_rebuild,
            f"trusted_tenant_rebuild={tenant_rebuild}",
        ),
    ]
    return (
        {
            "worker_source_count": len(worker_paths),
            "driver_bypass_findings": driver_bypass_findings,
            "typed_durable_assembly": typed_assembly,
            "explicit_control_checkpointer": explicit_control,
            "fenced_checkpoint_cas": fenced_cas,
            "trusted_tenant_rebuild": tenant_rebuild,
        },
        checks,
    )


def build_p2_durable_manifest(
    repo: Path,
    *,
    phase: ValidationPhase,
    target_head: str | None,
    s7_head: str | None,
    enforce_checkout_identity: bool,
) -> dict[str, Any]:
    if phase not in {
        ValidationPhase.P2_DURABLE_CANDIDATE,
        ValidationPhase.P2_DURABLE_S1_FINAL,
    }:
        raise ValueError(f"unsupported P2 durable phase: {phase}")
    checkout_head = run_git(repo, "rev-parse", "HEAD")
    checkout_branch = run_git(repo, "branch", "--show-current")
    checks: list[CheckResult] = []
    final_record: dict[str, Any] | None = None
    candidate_record: dict[str, Any]

    if phase is ValidationPhase.P2_DURABLE_CANDIDATE:
        verified_head = resolve_commit(
            repo,
            target_head if target_head is not None else checkout_head,
        )
        branch = (
            checkout_branch if enforce_checkout_identity else CANDIDATE_BRANCH
        )
        candidate_delta = changed_paths(repo, P2_INPUT_HEAD, verified_head)
        candidate_violations = path_scope_violations(
            candidate_delta,
            S7_ALLOWED_PREFIXES,
        )
        protected_identities, protected_mismatches = compare_revision_paths(
            repo,
            P2_INPUT_HEAD,
            verified_head,
            P2_PRODUCT_PATHS,
        )
        checks.extend(
            (
                make_check(
                    "p2.git.branch",
                    is_candidate_branch(branch),
                    f"phase={phase.value} branch={branch}",
                ),
                make_check(
                    "p2.git.input_ancestor",
                    commit_is_ancestor(repo, P2_INPUT_HEAD, verified_head),
                    f"input={P2_INPUT_HEAD} target={verified_head}",
                ),
                make_check(
                    "p2.git.s7_delta_scope",
                    not candidate_violations,
                    f"violations={candidate_violations or 'none'}",
                ),
                make_check(
                    "p2.git.candidate_product_tree",
                    not protected_mismatches,
                    f"mismatches={protected_mismatches or 'none'}",
                ),
            )
        )
        candidate_record = {
            "input_head": P2_INPUT_HEAD,
            "s7_head": verified_head,
            "delta": candidate_delta,
            "delta_scope_violations": candidate_violations,
            "protected_path_identities": protected_identities,
            "protected_path_mismatches": protected_mismatches,
        }
    else:
        if s7_head is None:
            raise ValueError("--s7-head is required for P2_DURABLE_S1_FINAL")
        verified_head = resolve_commit(
            repo,
            target_head if target_head is not None else checkout_head,
        )
        verified_s7_head = resolve_commit(repo, s7_head)
        branch = select_target_branch(repo, verified_head)
        candidate_delta = changed_paths(
            repo,
            P2_INPUT_HEAD,
            verified_s7_head,
        )
        candidate_violations = path_scope_violations(
            candidate_delta,
            S7_ALLOWED_PREFIXES,
        )
        final_changes = changed_path_statuses(
            repo,
            verified_s7_head,
            verified_head,
        )
        final_gitignore = run_git(repo, "show", f"{verified_head}:.gitignore")
        final_violations = final_scope_violations(
            final_changes,
            final_gitignore,
        )
        protected_identities, protected_mismatches = compare_revision_paths(
            repo,
            P2_INPUT_HEAD,
            verified_head,
            P2_PRODUCT_PATHS,
        )
        input_ancestry = {
            "S6-DATA": commit_is_ancestor(repo, P2_DATA_HEAD, verified_head),
            "S2-RUNTIME": commit_is_ancestor(repo, P2_INPUT_HEAD, verified_head),
        }
        checks.extend(
            (
                make_check(
                    "p2.git.branch",
                    is_s1_branch(branch),
                    f"phase={phase.value} branch={branch}",
                ),
                make_check(
                    "p2.git.s7_head_ancestor",
                    commit_is_ancestor(repo, verified_s7_head, verified_head),
                    f"s7={verified_s7_head} final={verified_head}",
                ),
                make_check(
                    "p2.git.s7_delta_scope",
                    not candidate_violations,
                    f"violations={candidate_violations or 'none'}",
                ),
                make_check(
                    "p2.git.s1_final_delta_scope",
                    not final_violations,
                    f"violations={final_violations or 'none'}",
                ),
                make_check(
                    "p2.git.final_product_tree",
                    not protected_mismatches,
                    f"mismatches={protected_mismatches or 'none'}",
                ),
                make_check(
                    "p2.git.final_input_heads",
                    all(input_ancestry.values()),
                    f"ancestry={input_ancestry}",
                ),
            )
        )
        candidate_record = {
            "input_head": P2_INPUT_HEAD,
            "s7_head": verified_s7_head,
            "delta": candidate_delta,
            "delta_scope_violations": candidate_violations,
        }
        final_record = {
            "target_head": verified_head,
            "s7_head": verified_s7_head,
            "delta": [
                {"status": status, "path": path}
                for status, path in final_changes
            ],
            "delta_scope_violations": final_violations,
            "protected_path_identities": protected_identities,
            "protected_path_mismatches": protected_mismatches,
            "input_head_ancestry": input_ancestry,
        }

    topology, topology_checks = verify_p2_topology(repo)
    evidence, evidence_checks = verify_p2_evidence(repo)
    boundaries, boundary_checks = verify_p2_static_boundaries(repo)
    workspace, raw_workspace_checks = verify_m2_workspace(repo, P2_INPUT_HEAD)
    workspace_checks = [
        CheckResult(
            check_id=check.check_id.replace("m2.", "p2.", 1),
            outcome=check.outcome,
            evidence=check.evidence,
        )
        for check in raw_workspace_checks
    ]
    checks.extend(topology_checks)
    checks.extend(evidence_checks)
    checks.extend(boundary_checks)
    checks.extend(workspace_checks)

    contract_manifest = load_revision_json(
        repo,
        P2_INPUT_HEAD,
        "contracts/contract-set.v1.json",
    )
    recomputed_contract_digest = contract_content_digest(contract_manifest)
    activation_contract_tree = revision_object_id(
        repo,
        P2_ACTIVATION_COMMIT,
        "contracts",
    )
    input_contract_tree = revision_object_id(repo, P2_INPUT_HEAD, "contracts")
    target_contract_tree = revision_object_id(repo, verified_head, "contracts")
    checks.extend(
        (
            make_check(
                "p2.contract.content_digest",
                recomputed_contract_digest == CONTRACT_DIGEST
                and contract_manifest["content_digest"] == CONTRACT_DIGEST,
                f"recomputed={recomputed_contract_digest}",
            ),
            make_check(
                "p2.contract.tree_identity",
                activation_contract_tree
                == input_contract_tree
                == target_contract_tree
                == CONTRACT_TREE,
                (
                    f"activation={activation_contract_tree} "
                    f"input={input_contract_tree} target={target_contract_tree}"
                ),
            ),
        )
    )

    immutable_paths = ("pyproject.toml", "uv.lock", "Makefile", "migrations", "infra")
    immutable_identities, immutable_mismatches = compare_revision_paths(
        repo,
        P2_ACTIVATION_COMMIT,
        verified_head,
        immutable_paths,
    )
    checks.append(
        make_check(
            "p2.shared.activation_identity",
            not immutable_mismatches,
            f"mismatches={immutable_mismatches or 'none'}",
        )
    )
    changed_input_paths = changed_paths(
        repo,
        P2_ACTIVATION_COMMIT,
        P2_INPUT_HEAD,
    )
    secret_findings = high_confidence_secret_findings(
        repo,
        P2_INPUT_HEAD,
        changed_input_paths,
    )
    checks.append(
        make_check(
            "p2.security.high_confidence_secret_scan",
            not secret_findings,
            f"findings={secret_findings or 'none'}",
        )
    )

    failed = [check.check_id for check in checks if check.outcome != "PASS"]
    manifest: dict[str, Any] = {
        "schema": "flowpilot.integration-composition-manifest.p2-durable.v1",
        "work_package": "WP-040",
        "attempt_id": "WP-040-a7",
        "chain_id": P2_CHAIN_ID,
        "execution_mode": "ORDERED",
        "risk_class": "R2",
        "validation_phase": phase.value,
        "base_commit": P2_INPUT_HEAD,
        "input_heads": {
            "S6-DATA": P2_DATA_HEAD,
            "S2-RUNTIME": P2_INPUT_HEAD,
        },
        "target_head": verified_head,
        "branch": branch,
        "candidate": candidate_record,
        "topology": topology,
        "contract": {
            "declared_content_digest": contract_manifest["content_digest"],
            "recomputed_content_digest": recomputed_contract_digest,
            "digest_profile": contract_manifest["digest_profile"],
            "activation_tree": activation_contract_tree,
            "input_tree": input_contract_tree,
            "target_tree": target_contract_tree,
        },
        "workspace": workspace,
        "boundaries": boundaries,
        "evidence": evidence,
        "shared": {
            "identities": immutable_identities,
            "mismatches": immutable_mismatches,
        },
        "security": {
            "high_confidence_secret_findings": secret_findings,
            "worker_driver_bypass_findings": boundaries[
                "driver_bypass_findings"
            ],
        },
        "checks": [asdict(check) for check in checks],
        "summary": {
            "check_count": len(checks),
            "failed_check_count": len(failed),
            "failed_checks": failed,
            "verdict": "PASS" if not failed else "FAIL",
        },
    }
    if final_record is not None:
        manifest["final"] = final_record
    return manifest


def build_manifest(
    repo: Path,
    phase: ValidationPhase | str = ValidationPhase.S7_CANDIDATE,
    target_head: str | None = None,
    *,
    enforce_checkout_identity: bool = False,
    s7_head: str | None = None,
) -> dict[str, Any]:
    repo = repo.resolve()
    validation_phase = ValidationPhase(phase)
    if validation_phase in {
        ValidationPhase.M1_PLATFORM_CANDIDATE,
        ValidationPhase.M1_PLATFORM_S1_FINAL,
    }:
        return build_m1_platform_manifest(
            repo,
            phase=validation_phase,
            target_head=target_head,
            s7_head=s7_head,
            enforce_checkout_identity=enforce_checkout_identity,
        )
    if validation_phase in {
        ValidationPhase.M2_STUDIO_CANDIDATE,
        ValidationPhase.M2_STUDIO_S1_FINAL,
    }:
        return build_m2_studio_manifest(
            repo,
            phase=validation_phase,
            target_head=target_head,
            s7_head=s7_head,
            enforce_checkout_identity=enforce_checkout_identity,
        )
    if validation_phase in {
        ValidationPhase.P1_VPN_CANDIDATE,
        ValidationPhase.P1_VPN_S1_FINAL,
    }:
        return build_p1_vpn_manifest(
            repo,
            phase=validation_phase,
            target_head=target_head,
            s7_head=s7_head,
            enforce_checkout_identity=enforce_checkout_identity,
        )
    if validation_phase in {
        ValidationPhase.P2_DURABLE_CANDIDATE,
        ValidationPhase.P2_DURABLE_S1_FINAL,
    }:
        return build_p2_durable_manifest(
            repo,
            phase=validation_phase,
            target_head=target_head,
            s7_head=s7_head,
            enforce_checkout_identity=enforce_checkout_identity,
        )
    checks: list[CheckResult] = []
    checkout_head = run_git(repo, "rev-parse", "HEAD")
    final_record: dict[str, Any] | None = None

    if validation_phase is ValidationPhase.S7_CANDIDATE:
        verified_head = S7_CANDIDATE_HEAD
        checkout_branch = run_git(repo, "branch", "--show-current")
        branch = (
            checkout_branch if enforce_checkout_identity else CANDIDATE_BRANCH
        )
        checks.append(
            make_check(
                "git.branch",
                is_candidate_branch(branch),
                f"branch={branch}",
            )
        )
    else:
        verified_head = resolve_commit(
            repo,
            target_head if target_head is not None else checkout_head,
        )
        branch = select_target_branch(repo, verified_head)
        checks.append(
            make_check(
                "git.branch",
                is_s1_branch(branch),
                f"phase=S1_FINAL branch={branch}",
            )
        )

    checks.append(
        make_check(
            "git.unique_input_heads",
            input_heads_are_unique(INPUTS),
            f"heads={len(INPUTS)} unique={len(INPUTS)}",
        )
    )

    s7_delta = changed_paths(
        repo,
        CANDIDATE_MERGE_HEAD,
        S7_CANDIDATE_HEAD,
    )
    s7_scope_violations = path_scope_violations(
        s7_delta,
        S7_ALLOWED_PREFIXES,
    )

    if validation_phase is ValidationPhase.S7_CANDIDATE:
        checks.extend(
            (
                make_check(
                    "git.candidate_ancestor",
                    commit_is_ancestor(
                        repo,
                        CANDIDATE_MERGE_HEAD,
                        S7_CANDIDATE_HEAD,
                    ),
                    f"candidate={CANDIDATE_MERGE_HEAD}",
                ),
                make_check(
                    "git.s7_delta_scope",
                    not s7_scope_violations,
                    (
                        "post-candidate committed paths are S7-owned; "
                        f"violations={s7_scope_violations or 'none'}"
                    ),
                ),
                check_merge_topology(repo),
            )
        )
    else:
        final_changes = changed_path_statuses(
            repo,
            S7_CANDIDATE_HEAD,
            verified_head,
        )
        final_gitignore = run_git(
            repo,
            "show",
            f"{verified_head}:.gitignore",
        )
        final_violations = final_scope_violations(
            final_changes,
            final_gitignore,
        )
        protected_identities, protected_mismatches = compare_revision_paths(
            repo,
            S7_CANDIDATE_HEAD,
            verified_head,
            FINAL_PROTECTED_PATHS,
        )
        s7_contract_tree = revision_object_id(
            repo,
            S7_CANDIDATE_HEAD,
            "contracts",
        )
        final_contract_tree = revision_object_id(
            repo,
            verified_head,
            "contracts",
        )
        s7_lock_blob = revision_object_id(
            repo,
            S7_CANDIDATE_HEAD,
            "uv.lock",
        )
        final_lock_blob = revision_object_id(
            repo,
            verified_head,
            "uv.lock",
        )
        s7_migration_tree = revision_object_id(
            repo,
            S7_CANDIDATE_HEAD,
            "migrations",
        )
        final_migration_tree = revision_object_id(
            repo,
            verified_head,
            "migrations",
        )
        input_ancestry = {
            role: commit_is_ancestor(
                repo,
                str(specification["head"]),
                verified_head,
            )
            for role, specification in INPUTS.items()
        }
        idea_cleanup = sorted(
            path
            for status, path in final_changes
            if status == "D" and path.replace("\\", "/").startswith(".idea/")
        )
        checks.extend(
            (
                make_check(
                    "git.s7_head_ancestor",
                    commit_is_ancestor(
                        repo,
                        S7_CANDIDATE_HEAD,
                        verified_head,
                    ),
                    (
                        f"s7_head={S7_CANDIDATE_HEAD} "
                        f"final_head={verified_head}"
                    ),
                ),
                make_check(
                    "git.s1_final_delta_scope",
                    not final_violations,
                    (
                        "final delta is S1-owned or explicitly allowed; "
                        f"violations={final_violations or 'none'}"
                    ),
                ),
                make_check(
                    "git.s7_delta_scope",
                    not s7_scope_violations,
                    (
                        "candidate-to-S7 delta is S7-owned; "
                        f"violations={s7_scope_violations or 'none'}"
                    ),
                ),
                make_check(
                    "git.final_product_tree",
                    not protected_mismatches,
                    (
                        "protected product paths unchanged; "
                        f"mismatches={protected_mismatches or 'none'}"
                    ),
                ),
                make_check(
                    "contract.final_tree",
                    s7_contract_tree == final_contract_tree == CONTRACT_TREE,
                    (
                        f"s7={s7_contract_tree} "
                        f"final={final_contract_tree}"
                    ),
                ),
                make_check(
                    "git.final_input_heads",
                    all(input_ancestry.values()),
                    f"ancestry={input_ancestry}",
                ),
                make_check(
                    "workspace.final_lock_blob",
                    s7_lock_blob == final_lock_blob,
                    f"s7={s7_lock_blob} final={final_lock_blob}",
                ),
                make_check(
                    "migrations.final_tree",
                    s7_migration_tree == final_migration_tree,
                    (
                        f"s7={s7_migration_tree} "
                        f"final={final_migration_tree}"
                    ),
                ),
                check_merge_topology(repo),
            )
        )
        final_record = {
            "target_head": verified_head,
            "s7_candidate_head": S7_CANDIDATE_HEAD,
            "delta": [
                {"status": status, "path": path}
                for status, path in final_changes
            ],
            "delta_scope_violations": final_violations,
            "ignored_metadata_deletions": idea_cleanup,
            "input_head_ancestry": input_ancestry,
            "protected_path_identities": protected_identities,
            "protected_path_mismatches": protected_mismatches,
            "contract_tree": {
                "s7_candidate": s7_contract_tree,
                "final": final_contract_tree,
            },
            "lock_blob": {
                "s7_candidate": s7_lock_blob,
                "final": final_lock_blob,
            },
            "migration_tree": {
                "s7_candidate": s7_migration_tree,
                "final": final_migration_tree,
            },
        }

    inputs: dict[str, Any] = {}
    full_input_paths: dict[str, set[str]] = {}
    for role, specification in INPUTS.items():
        record, input_checks = verify_input(repo, role, specification)
        inputs[role] = record
        checks.extend(input_checks)
        full_input_paths[role] = set(
            changed_paths(repo, COMMON_MERGE_BASE, specification["head"])
        )

    contract_manifest = load_json(repo / "contracts/contract-set.v1.json")
    recomputed_contract_digest = contract_content_digest(contract_manifest)
    base_contract_tree = run_git(
        repo,
        "rev-parse",
        f"{BASE_COMMIT}:contracts",
    )
    checks.extend(
        (
            make_check(
                "contract.content_digest",
                recomputed_contract_digest == CONTRACT_DIGEST
                and contract_manifest["content_digest"] == CONTRACT_DIGEST,
                f"recomputed={recomputed_contract_digest}",
            ),
            make_check(
                "contract.base_tree",
                base_contract_tree == CONTRACT_TREE,
                f"tree={base_contract_tree}",
            ),
        )
    )

    workspace, workspace_checks = verify_workspace(
        repo,
        revision=S7_CANDIDATE_HEAD,
    )
    dependencies, dependency_checks = verify_code_dependencies(repo)
    migrations, migration_checks = verify_migrations(repo)
    integration, integration_checks = verify_atomic_integration(
        repo,
        full_input_paths,
    )
    checks.extend(workspace_checks)
    checks.extend(dependency_checks)
    checks.extend(migration_checks)
    checks.extend(integration_checks)

    failed = [item.check_id for item in checks if item.outcome != "PASS"]
    manifest: dict[str, Any] = {
        "schema": "flowpilot.integration-composition-manifest.v1",
        "work_package": "WP-040",
        "attempt_id": "WP-040-a1",
        "chain_id": "CHAIN-WP040-A0-REMEDIATION-01",
        "execution_mode": "ORDERED",
        "risk_class": "R2",
        "base_commit": BASE_COMMIT,
        "control_head_at_authorization": CONTROL_HEAD,
        "candidate_merge_head": CANDIDATE_MERGE_HEAD,
        "branch": branch,
        "contract": {
            "declared_content_digest": contract_manifest["content_digest"],
            "recomputed_content_digest": recomputed_contract_digest,
            "digest_profile": contract_manifest["digest_profile"],
            "contract_tree": base_contract_tree,
        },
        "inputs": inputs,
        "workspace": workspace,
        "dependencies": dependencies,
        "migrations": migrations,
        "integration": integration,
        "checks": [asdict(item) for item in checks],
        "summary": {
            "check_count": len(checks),
            "failed_check_count": len(failed),
            "failed_checks": failed,
            "verdict": "PASS" if not failed else "FAIL",
        },
    }
    if validation_phase is ValidationPhase.S1_FINAL:
        manifest.update(
            {
                "attempt_id": "WP-040-a2",
                "risk_class": "R1",
                "base_commit": S7_CANDIDATE_HEAD,
                "validation_phase": validation_phase.value,
                "final": final_record,
            }
        )
    return manifest


def canonical_manifest_bytes(manifest: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def render_report(manifest: dict[str, Any]) -> str:
    if manifest["schema"] == "flowpilot.integration-composition-manifest.m1.v1":
        return render_m1_report(manifest)
    if (
        manifest["schema"]
        == "flowpilot.integration-composition-manifest.m2-studio.v1"
    ):
        return render_m2_studio_report(manifest)
    if (
        manifest["schema"]
        == "flowpilot.integration-composition-manifest.p1-vpn.v1"
    ):
        return render_p1_vpn_report(manifest)
    if (
        manifest["schema"]
        == "flowpilot.integration-composition-manifest.p2-durable.v1"
    ):
        return render_p2_durable_report(manifest)

    summary = manifest["summary"]
    final_phase = (
        manifest.get("validation_phase") == ValidationPhase.S1_FINAL.value
    )
    title = (
        "# WP-040-a2 S1 Final Evidence Reproduction Report"
        if final_phase
        else "# WP-040-a1 Evidence Reproduction Report"
    )
    lines = [title, ""]
    if final_phase:
        lines.extend(
            (
                f"- Validation phase: `{manifest['validation_phase']}`",
                f"- Final target head: `{manifest['final']['target_head']}`",
            )
        )
    lines.extend(
        (
        f"- Verdict: `{summary['verdict']}`",
        f"- Static checks: `{summary['check_count']}`",
        f"- Failed checks: `{summary['failed_check_count']}`",
        f"- Candidate merge head: `{manifest['candidate_merge_head']}`",
        (
            "- Contract digest: "
            f"`{manifest['contract']['recomputed_content_digest']}`"
        ),
        (
            "- Lock digest: "
            f"`{manifest['workspace']['lock_sha256']}`"
        ),
        (
            "- Migration head: "
            f"`{manifest['migrations']['head']}`"
        ),
        (
            "- Recommended mainline mode: "
            f"`{manifest['integration']['recommended_mainline_mode']}`"
        ),
        "",
        "## Static checks",
        "",
        "| Check | Outcome | Evidence |",
        "|---|---|---|",
        )
    )
    for check in manifest["checks"]:
        evidence = check["evidence"].replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| `{check['check_id']}` | {check['outcome']} | {evidence} |"
        )
    lines.extend(
        (
            "",
            "## Evidence boundary",
            "",
            (
                "This deterministic report covers Git identity, input scope, "
                "handoff hashes, ContractSet digest, package closure, code "
                "dependency direction, and migration identity."
            ),
            (
                "Runtime tests, wheel installation, vulnerability scan, real "
                "Compose, PostgreSQL, and Redis recovery are command evidence "
                "and remain recorded in the S7 handoff."
            ),
            "",
        )
    )
    return "\n".join(lines)


def render_m1_report(manifest: dict[str, Any]) -> str:
    summary = manifest["summary"]
    final_phase = (
        manifest["validation_phase"]
        == ValidationPhase.M1_PLATFORM_S1_FINAL.value
    )
    title = (
        "# WP-040-a4 M1 Platform S1 Final Evidence Reproduction Report"
        if final_phase
        else "# WP-040-a4 M1 Platform Composition Report"
    )
    lines = [
        title,
        "",
        f"- Validation phase: `{manifest['validation_phase']}`",
        f"- Verdict: `{summary['verdict']}`",
        f"- Static checks: `{summary['check_count']}`",
        f"- Failed checks: `{summary['failed_check_count']}`",
        f"- Input head: `{manifest['input_head']}`",
        f"- Target head: `{manifest['target_head']}`",
        (
            "- Contract digest: "
            f"`{manifest['contract']['recomputed_content_digest']}`"
        ),
        f"- Lock digest: `{manifest['workspace']['lock_sha256']}`",
        (
            "- Workspace closure: "
            f"`{manifest['workspace']['member_count']} packages / "
            f"{manifest['workspace']['lock_package_count']} locked entries`"
        ),
        "",
        "## Static checks",
        "",
        "| Check | Outcome | Evidence |",
        "|---|---|---|",
    ]
    for check in manifest["checks"]:
        evidence = check["evidence"].replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| `{check['check_id']}` | {check['outcome']} | {evidence} |"
        )
    lines.extend(
        (
            "",
            "## Evidence boundary",
            "",
            (
                "This report reproduces the ordered Git topology, path "
                "ownership, ContractSet, Workspace/Lock closure, stable "
                "commands, upstream evidence hashes, protected product "
                "identity, and high-confidence Secret scan."
            ),
            (
                "Runtime tests, wheel build/install, security black-box "
                "execution, vulnerability scan, and optional Compose "
                "reproduction remain command evidence in the S7 handoff."
            ),
            "",
        )
    )
    return "\n".join(lines)


def render_m2_studio_report(manifest: dict[str, Any]) -> str:
    summary = manifest["summary"]
    final_phase = (
        manifest["validation_phase"]
        == ValidationPhase.M2_STUDIO_S1_FINAL.value
    )
    title = (
        "# WP-040-a5 M2 Studio S1 Final Evidence Reproduction Report"
        if final_phase
        else "# WP-040-a5 M2 Studio Composition Report"
    )
    lines = [
        title,
        "",
        f"- Validation phase: `{manifest['validation_phase']}`",
        f"- Verdict: `{summary['verdict']}`",
        f"- Static checks: `{summary['check_count']}`",
        f"- Failed checks: `{summary['failed_check_count']}`",
        f"- S4 input head: `{manifest['input_heads']['S4-QUALITY']}`",
        f"- Target head: `{manifest['target_head']}`",
        (
            "- Contract digest: "
            f"`{manifest['contract']['recomputed_content_digest']}`"
        ),
        f"- Lock digest: `{manifest['workspace']['lock_sha256']}`",
        (
            "- Workspace closure: "
            f"`{manifest['workspace']['member_count']} packages / "
            f"{manifest['workspace']['lock_package_count']} locked entries`"
        ),
        (
            "- Studio API topology: "
            f"`{manifest['studio']['quality_topology']['node_count']} nodes / "
            f"{manifest['studio']['quality_topology']['edge_count']} edges`"
        ),
        "",
        "## Static checks",
        "",
        "| Check | Outcome | Evidence |",
        "|---|---|---|",
    ]
    for check in manifest["checks"]:
        evidence = check["evidence"].replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| `{check['check_id']}` | {check['outcome']} | {evidence} |"
        )
    lines.extend(
        (
            "",
            "## Evidence boundary",
            "",
            (
                "This report reproduces the ordered S5/S2/S4 Git topology, "
                "path ownership, ContractSet, Workspace/Lock closure, Agent "
                "Server dependency versions, safe Studio configuration, "
                "independent topology snapshots, upstream evidence hashes, "
                "protected product identity, and high-confidence Secret scan."
            ),
            (
                "Fresh-environment installation, Python/contract/security "
                "tests, wheel and vulnerability checks, and the real local "
                "Agent Server lifecycle remain command evidence in the S7 "
                "handoff."
            ),
            "",
        )
    )
    return "\n".join(lines)


def render_p1_vpn_report(manifest: dict[str, Any]) -> str:
    summary = manifest["summary"]
    final_phase = (
        manifest["validation_phase"]
        == ValidationPhase.P1_VPN_S1_FINAL.value
    )
    title = (
        "# WP-040-a6 P1 VPN S1 Final Evidence Reproduction Report"
        if final_phase
        else "# WP-040-a6 P1 VPN Composition Report"
    )
    lines = [
        title,
        "",
        f"- Validation phase: `{manifest['validation_phase']}`",
        f"- Verdict: `{summary['verdict']}`",
        f"- Static checks: `{summary['check_count']}`",
        f"- Failed checks: `{summary['failed_check_count']}`",
        f"- S4 input head: `{manifest['input_heads']['S4-QUALITY']}`",
        f"- Target head: `{manifest['target_head']}`",
        (
            "- Contract digest: "
            f"`{manifest['contract']['recomputed_content_digest']}`"
        ),
        f"- Lock digest: `{manifest['workspace']['lock_sha256']}`",
        (
            "- Workspace closure: "
            f"`{manifest['workspace']['member_count']} packages / "
            f"{manifest['workspace']['lock_package_count']} locked entries`"
        ),
        (
            "- Knowledge Schema Pin: "
            f"`{manifest['boundaries']['knowledge_schema_pin']['recomputed']}`"
        ),
        (
            "- VPN candidate set: "
            f"`{manifest['dataset']['case_count']} fixed local cases`"
        ),
        (
            "- Cross-tenant successful retrievals: "
            f"`{manifest['security']['cross_tenant_successful_retrievals']}`"
        ),
        "",
        "## Static checks",
        "",
        "| Check | Outcome | Evidence |",
        "|---|---|---|",
    ]
    for check in manifest["checks"]:
        evidence = check["evidence"].replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| `{check['check_id']}` | {check['outcome']} | {evidence} |"
        )
    lines.extend(
        (
            "",
            "## Evidence boundary",
            "",
            (
                "This report reproduces the ordered S5/S3/S2/S4 Git "
                "topology, path ownership, ContractSet, Workspace/Lock, "
                "Knowledge Tool Schema Pin, fixed 20-case candidate hashes, "
                "upstream evidence, tenant isolation, Gateway-only access, "
                "recovery idempotency, and protected product identity."
            ),
            (
                "Fresh-environment tests, wheel installation, vulnerability "
                "scan, and isolated Compose/database/recovery execution remain "
                "command evidence in the S7 handoff. The local 20 cases do "
                "not claim the 120/36 release datasets are complete."
            ),
            "",
        )
    )
    return "\n".join(lines)


def render_p2_durable_report(manifest: dict[str, Any]) -> str:
    summary = manifest["summary"]
    final_phase = (
        manifest["validation_phase"]
        == ValidationPhase.P2_DURABLE_S1_FINAL.value
    )
    title = (
        "# WP-040-a7 P2 Durable S1 Final Evidence Reproduction Report"
        if final_phase
        else "# WP-040-a7 P2 Durable Composition Report"
    )
    lines = [
        title,
        "",
        f"- Validation phase: `{manifest['validation_phase']}`",
        f"- Verdict: `{summary['verdict']}`",
        f"- Static checks: `{summary['check_count']}`",
        f"- Failed checks: `{summary['failed_check_count']}`",
        f"- S2 input head: `{manifest['input_heads']['S2-RUNTIME']}`",
        f"- Target head: `{manifest['target_head']}`",
        (
            "- Contract digest: "
            f"`{manifest['contract']['recomputed_content_digest']}`"
        ),
        f"- Lock digest: `{manifest['workspace']['lock_sha256']}`",
        (
            "- Workspace closure: "
            f"`{manifest['workspace']['member_count']} packages / "
            f"{manifest['workspace']['lock_package_count']} locked entries`"
        ),
        (
            "- Worker direct-driver bypass findings: "
            f"`{len(manifest['security']['worker_driver_bypass_findings'])}`"
        ),
        "",
        "## Static checks",
        "",
        "| Check | Outcome | Evidence |",
        "|---|---|---|",
    ]
    for check in manifest["checks"]:
        evidence = check["evidence"].replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| `{check['check_id']}` | {check['outcome']} | {evidence} |"
        )
    lines.extend(
        (
            "",
            "## Evidence boundary",
            "",
            (
                "This report reproduces the ordered S1/S6/S2 topology, "
                "path ownership, Handoff bytes, ContractSet, Workspace/Lock, "
                "typed Worker boundaries, protected product identity, and "
                "high-confidence Secret scan."
            ),
            (
                "Real PostgreSQL/RLS, Redis loss and rebuild, Worker restart, "
                "generation fencing, checkpoint CAS, terminal replay, test "
                "execution, and cleanup remain command evidence in the S7 "
                "handoff and proof."
            ),
            "",
        )
    )
    return "\n".join(lines)


def write_artifacts(
    manifest: dict[str, Any],
    output_dir: Path,
) -> tuple[Path, Path, str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "composition-manifest.json"
    report_path = output_dir / "evidence-report.md"
    manifest_bytes = canonical_manifest_bytes(manifest)
    report_bytes = render_report(manifest).encode("utf-8")
    manifest_path.write_bytes(manifest_bytes)
    report_path.write_bytes(report_bytes)
    return (
        manifest_path,
        report_path,
        f"sha256:{sha256_bytes(manifest_bytes)}",
        f"sha256:{sha256_bytes(report_bytes)}",
    )


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify the WP-040 candidate or S1 final integration",
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="write deterministic manifest and report to this directory",
    )
    parser.add_argument(
        "--phase",
        choices=[phase.value for phase in ValidationPhase],
        default=ValidationPhase.S7_CANDIDATE.value,
        help="validation phase; defaults to the backward-compatible candidate",
    )
    parser.add_argument(
        "--target-head",
        help="S1 final revision; defaults to the selected repository HEAD",
    )
    parser.add_argument(
        "--s7-head",
        help="reviewed S7 head required by an S1 final phase",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    manifest = build_manifest(
        args.repo,
        phase=args.phase,
        target_head=args.target_head,
        enforce_checkout_identity=True,
        s7_head=args.s7_head,
    )
    prefixes = {
        ValidationPhase.S7_CANDIDATE.value: "WP040_COMPOSITION",
        ValidationPhase.S1_FINAL.value: "WP040_S1_FINAL",
        ValidationPhase.M1_PLATFORM_CANDIDATE.value: (
            "WP040_M1_PLATFORM_COMPOSITION"
        ),
        ValidationPhase.M1_PLATFORM_S1_FINAL.value: (
            "WP040_M1_PLATFORM_S1_FINAL"
        ),
        ValidationPhase.M2_STUDIO_CANDIDATE.value: (
            "WP040_M2_STUDIO_COMPOSITION"
        ),
        ValidationPhase.M2_STUDIO_S1_FINAL.value: (
            "WP040_M2_STUDIO_S1_FINAL"
        ),
        ValidationPhase.P1_VPN_CANDIDATE.value: (
            "WP040_P1_VPN_COMPOSITION"
        ),
        ValidationPhase.P1_VPN_S1_FINAL.value: (
            "WP040_P1_VPN_S1_FINAL"
        ),
        ValidationPhase.P2_DURABLE_CANDIDATE.value: (
            "WP040_P2_DURABLE_COMPOSITION"
        ),
        ValidationPhase.P2_DURABLE_S1_FINAL.value: (
            "WP040_P2_DURABLE_S1_FINAL"
        ),
    }
    prefix = prefixes[args.phase]
    print(
        f"{prefix}_{manifest['summary']['verdict']} "
        f"checks={manifest['summary']['check_count']} "
        f"failed={manifest['summary']['failed_check_count']}"
    )
    if args.output_dir is not None:
        manifest_path, report_path, manifest_hash, report_hash = (
            write_artifacts(manifest, args.output_dir)
        )
        print(f"MANIFEST={manifest_path} {manifest_hash}")
        print(f"REPORT={report_path} {report_hash}")
    return 0 if manifest["summary"]["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
