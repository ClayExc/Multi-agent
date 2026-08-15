from __future__ import annotations

import json

from flowpilot_engineering_control.cli import main

from .conftest import ExampleRepository


def test_cli_map_build_emits_canonical_json(
    example_repository: ExampleRepository,
    capfd: object,
) -> None:
    assert main(["--repo", str(example_repository.root), "map", "build"]) == 0
    captured = capfd.readouterr()  # type: ignore[attr-defined]
    payload = json.loads(captured.out)
    assert payload["schema_version"] == "flowpilot.repository-map.v1"
    assert payload["map_sha256"]
    assert "fixture-secret-that-must-not-leak" not in captured.out


def test_cli_rejects_revision_injection_without_running_git(
    example_repository: ExampleRepository,
    capfd: object,
) -> None:
    exit_code = main(
        [
            "--repo",
            str(example_repository.root),
            "capsule",
            "build",
            "--base",
            "HEAD;touch-pwned",
            "--owner",
            "S5-CORE",
            "--work-package",
            "WP-091",
            "--attempt",
            "WP-091-test",
            "--risk",
            "R2",
            "--contract-digest",
            "sha256:" + "a" * 64,
            "--write-scope",
            "packages/engineering-control/**",
        ]
    )
    captured = capfd.readouterr()  # type: ignore[attr-defined]
    assert exit_code == 2
    assert json.loads(captured.err)["error"]["code"] == "ENG_INVALID_PATH"
    assert "touch-pwned" not in captured.err
    assert not (example_repository.root / "pwned").exists()


def test_cli_output_must_use_local_engineering_directory(
    example_repository: ExampleRepository,
    capfd: object,
) -> None:
    exit_code = main(
        [
            "--repo",
            str(example_repository.root),
            "map",
            "build",
            "--output",
            "repository-map.json",
        ]
    )
    captured = capfd.readouterr()  # type: ignore[attr-defined]
    assert exit_code == 2
    assert json.loads(captured.err)["error"]["code"] == ("ENG_OUTPUT_POLICY_VIOLATION")
    assert not (example_repository.root / "repository-map.json").exists()
