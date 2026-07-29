from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from flowpilot_application import (
    ApplicationError,
    DomainPackRegistry,
    ErrorCode,
    load_domain_pack,
)
from flowpilot_domain import CommandType, RiskLevel

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
IT_SERVICE_PACK = REPOSITORY_ROOT / "domain-packs" / "it-service"


def test_it_service_pack_loads_validated_minimal_fixture() -> None:
    definition = load_domain_pack(IT_SERVICE_PACK)

    assert definition.manifest.domain_id == "it-service"
    assert definition.manifest.version == "0.1.0"
    assert definition.intents[0].id == "vpn_support"
    assert definition.intents[0].allowed_command_types == (
        CommandType.CREATE,
        CommandType.SUBMIT_MESSAGE,
    )
    assert definition.required_fields == {"vpn_support": ("environment",)}
    assert definition.risk_rules[0].risk_level is RiskLevel.LOW
    assert definition.fixtures[0].expected_intent == "vpn_support"
    definition.fixtures[0].command.assert_digest()
    definition.fixtures[0].command.assert_security_binding()


def test_domain_pack_registry_is_versioned_and_rejects_duplicates() -> None:
    definition = load_domain_pack(IT_SERVICE_PACK)
    registry = DomainPackRegistry()

    registry.register(definition)

    assert registry.get("it-service", "0.1.0") is definition
    with pytest.raises(ApplicationError) as duplicate:
        registry.register(definition)
    with pytest.raises(ApplicationError) as missing:
        registry.get("it-service", "9.9.9")

    assert duplicate.value.code is ErrorCode.DOMAIN_PACK_CONFLICT
    assert missing.value.code is ErrorCode.DOMAIN_PACK_NOT_FOUND


def test_domain_pack_boundary_contains_no_executable_python() -> None:
    files = {
        path.relative_to(IT_SERVICE_PACK).as_posix()
        for path in IT_SERVICE_PACK.rglob("*")
        if path.is_file()
    }

    assert files == {
        "evals/minimal-vpn-request.json",
        "intents.yaml",
        "manifest.yaml",
        "required-fields.yaml",
        "risk-rules.yaml",
    }
    assert not any(path.suffix == ".py" for path in IT_SERVICE_PACK.rglob("*"))


def test_domain_pack_reference_cannot_escape_pack_root(tmp_path: Path) -> None:
    candidate = tmp_path / "it-service"
    shutil.copytree(IT_SERVICE_PACK, candidate)
    manifest = (candidate / "manifest.yaml").read_text(encoding="utf-8")
    (candidate / "manifest.yaml").write_text(
        manifest.replace("intents.yaml", "../outside.yaml"),
        encoding="utf-8",
    )
    (tmp_path / "outside.yaml").write_text(
        "schema_version: flowpilot.domain-pack.intents.v1\nintents: []\n",
        encoding="utf-8",
    )

    with pytest.raises(ApplicationError) as captured:
        load_domain_pack(candidate)

    assert captured.value.code is ErrorCode.DOMAIN_PACK_INVALID
    assert "escapes" in captured.value.safe_message


def test_domain_pack_yaml_aliases_are_rejected(tmp_path: Path) -> None:
    candidate = tmp_path / "it-service"
    shutil.copytree(IT_SERVICE_PACK, candidate)
    (candidate / "intents.yaml").write_text(
        "\n".join(
            (
                "schema_version: flowpilot.domain-pack.intents.v1",
                "intents:",
                "  - &vpn",
                "    id: vpn_support",
                "    description: VPN support",
                "    allowed_command_types: [task.create.v1]",
                "  - *vpn",
            )
        ),
        encoding="utf-8",
    )

    with pytest.raises(ApplicationError) as captured:
        load_domain_pack(candidate)

    assert captured.value.code is ErrorCode.DOMAIN_PACK_INVALID
    assert "aliases" in captured.value.safe_message


def test_domain_pack_duplicate_yaml_keys_are_rejected(tmp_path: Path) -> None:
    candidate = tmp_path / "it-service"
    shutil.copytree(IT_SERVICE_PACK, candidate)
    with (candidate / "manifest.yaml").open("a", encoding="utf-8") as manifest:
        manifest.write("display_name: Conflicting Name\n")

    with pytest.raises(ApplicationError) as captured:
        load_domain_pack(candidate)

    assert captured.value.code is ErrorCode.DOMAIN_PACK_INVALID
    assert "unique" in captured.value.safe_message


def test_domain_pack_exact_schema_rejects_unknown_fields(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "it-service"
    shutil.copytree(IT_SERVICE_PACK, candidate)
    with (candidate / "manifest.yaml").open("a", encoding="utf-8") as manifest:
        manifest.write("executable: flowpilot_plugin.py\n")

    with pytest.raises(ApplicationError) as captured:
        load_domain_pack(candidate)

    assert captured.value.code is ErrorCode.DOMAIN_PACK_INVALID
    assert "fields" in captured.value.safe_message
