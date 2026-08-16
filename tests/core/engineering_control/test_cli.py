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


def _capsule_args(example_repository: ExampleRepository) -> list[str]:
    return [
        "--base",
        example_repository.git("rev-parse", "HEAD"),
        "--owner",
        "S5-CORE",
        "--work-package",
        "WP-092",
        "--attempt",
        "WP-092-test",
        "--risk",
        "R2",
        "--contract-digest",
        "sha256:" + "a" * 64,
        "--write-scope",
        "packages/engineering-control/**",
    ]


def test_cli_select_and_attempt_report_are_nonempty_and_deterministic(
    example_repository: ExampleRepository,
    capfd: object,
) -> None:
    select_args = [
        "--repo",
        str(example_repository.root),
        "tests",
        "select",
        *_capsule_args(example_repository),
    ]
    assert main(select_args) == 0
    first = capfd.readouterr().out  # type: ignore[attr-defined]
    assert main(select_args) == 0
    second = capfd.readouterr().out  # type: ignore[attr-defined]
    assert first == second
    plan = json.loads(first)
    assert plan["tier"] == "FULL"
    assert plan["commands"]

    report_args = [
        "--repo",
        str(example_repository.root),
        "attempt",
        "report",
        *_capsule_args(example_repository),
        "--selection-ms",
        "5",
    ]
    assert main(report_args) == 0
    report = json.loads(capfd.readouterr().out)  # type: ignore[attr-defined]
    assert report["actual_read"] is None
    assert report["estimated_usage"]["tokens"] >= 0


def test_cli_targeted_plan_uses_workspace_python_module_runner(
    example_repository: ExampleRepository,
    capfd: object,
) -> None:
    base = example_repository.git("rev-parse", "HEAD")
    example_repository.write(
        "packages/engineering-control/src/flowpilot_engineering_control/private.py",
        "VALUE = 'changed'\n",
    )
    example_repository.commit("targeted cli selection")

    assert (
        main(
            [
                "--repo",
                str(example_repository.root),
                "tests",
                "select",
                "--base",
                base,
                "--owner",
                "S5-CORE",
                "--work-package",
                "WP-092",
                "--attempt",
                "WP-092-test",
                "--risk",
                "R2",
                "--contract-digest",
                "sha256:" + "a" * 64,
                "--write-scope",
                "packages/engineering-control/**",
            ]
        )
        == 0
    )
    plan = json.loads(capfd.readouterr().out)  # type: ignore[attr-defined]
    assert plan["tier"] == "TARGETED"
    assert plan["commands"][0]["argv"] == [
        "uv",
        "run",
        "--all-packages",
        "--all-groups",
        "--locked",
        "python",
        "-B",
        "-m",
        "pytest",
        "-q",
        "tests/core/engineering_control",
    ]


def test_cli_evidence_record_and_check_round_trip(
    example_repository: ExampleRepository,
    capfd: object,
) -> None:
    evidence_path = ".flowpilot-engineering/evidence/cli.txt"
    example_repository.write(evidence_path, "PASS\n")
    common = [
        "--command-id",
        "cli-round-trip",
        "--arg",
        "python",
        "--arg",
        "; | > $(literal)",
        "--contract-digest",
        "sha256:" + "a" * 64,
        "--toolchain",
        "python=3.12.11",
        "--kind",
        "local_test",
    ]
    assert (
        main(
            [
                "--repo",
                str(example_repository.root),
                "evidence",
                "record",
                *common,
                "--evidence",
                evidence_path,
                "--exit-code",
                "0",
            ]
        )
        == 0
    )
    record = json.loads(capfd.readouterr().out)  # type: ignore[attr-defined]
    assert "; | > $(literal)" not in json.dumps(record)
    assert (
        main(
            [
                "--repo",
                str(example_repository.root),
                "evidence",
                "check",
                *common,
                "--record",
                record["record_path"],
            ]
        )
        == 0
    )
    decision = json.loads(capfd.readouterr().out)  # type: ignore[attr-defined]
    assert decision == {
        "hit": True,
        "reasons": [],
        "record_sha256": decision["record_sha256"],
    }
