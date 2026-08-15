"""`flowpilot-eng` command-line interface."""

from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
from contextlib import suppress
from pathlib import Path

from flowpilot_engineering_control.capsule import (
    CapsuleBuilder,
    CapsuleRequest,
    EvidenceReference,
    ExpansionReason,
    ScopeExpansion,
)
from flowpilot_engineering_control.errors import EngineeringControlError, ErrorCode
from flowpilot_engineering_control.evidence import (
    CacheKeyInput,
    CachePolicy,
    EnvironmentFingerprint,
    EvidenceCache,
    EvidenceKind,
)
from flowpilot_engineering_control.paths import normalize_repo_path, path_is_within
from flowpilot_engineering_control.report import AttemptReportBuilder, ReadObservation
from flowpilot_engineering_control.repository import RepositoryMapBuilder
from flowpilot_engineering_control.selection import (
    CommandSpec,
    SelectionRequest,
    SelectionSignal,
    TestSelector,
)
from flowpilot_engineering_control.serialization import canonical_json_bytes

_COMMIT = re.compile(r"^[0-9a-f]{40}$")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="flowpilot-eng")
    parser.add_argument("--repo", default=".", help="repository root")
    commands = parser.add_subparsers(dest="command", required=True)

    map_parser = commands.add_parser("map")
    map_commands = map_parser.add_subparsers(dest="map_command", required=True)
    map_build = map_commands.add_parser("build")
    map_build.add_argument("--output")

    capsule_parser = commands.add_parser("capsule")
    capsule_commands = capsule_parser.add_subparsers(
        dest="capsule_command", required=True
    )
    capsule_build = capsule_commands.add_parser("build")
    _add_capsule_arguments(capsule_build)
    capsule_build.add_argument("--output")

    tests_parser = commands.add_parser("tests")
    tests_commands = tests_parser.add_subparsers(dest="tests_command", required=True)
    tests_select = tests_commands.add_parser("select")
    _add_capsule_arguments(tests_select)
    tests_select.add_argument(
        "--signal",
        action="append",
        choices=[signal.value for signal in SelectionSignal],
        default=[],
    )
    tests_select.add_argument("--output")

    evidence_parser = commands.add_parser("evidence")
    evidence_commands = evidence_parser.add_subparsers(
        dest="evidence_command", required=True
    )
    evidence_subparsers: dict[str, argparse.ArgumentParser] = {}
    for operation in ("record", "check"):
        evidence_command = evidence_commands.add_parser(operation)
        evidence_subparsers[operation] = evidence_command
        evidence_command.add_argument("--command-id", required=True)
        evidence_command.add_argument("--arg", action="append", required=True)
        evidence_command.add_argument("--contract-digest", required=True)
        evidence_command.add_argument("--toolchain", action="append", required=True)
        evidence_command.add_argument(
            "--kind",
            choices=[kind.value for kind in EvidenceKind],
            required=True,
        )
        evidence_command.add_argument("--output")
    evidence_subparsers["record"].add_argument("--evidence", required=True)
    evidence_subparsers["record"].add_argument("--exit-code", type=int, required=True)
    evidence_subparsers["record"].add_argument("--producer-head", default="HEAD")
    evidence_subparsers["check"].add_argument("--record", required=True)
    evidence_subparsers["check"].add_argument("--current-head", default="HEAD")

    attempt_parser = commands.add_parser("attempt")
    attempt_commands = attempt_parser.add_subparsers(
        dest="attempt_command", required=True
    )
    attempt_report = attempt_commands.add_parser("report")
    _add_capsule_arguments(attempt_report)
    attempt_report.add_argument(
        "--signal",
        action="append",
        choices=[signal.value for signal in SelectionSignal],
        default=[],
    )
    attempt_report.add_argument("--actual-read", action="append", default=[])
    attempt_report.add_argument("--selection-ms", type=int, required=True)
    attempt_report.add_argument("--output")
    return parser


def _add_capsule_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base", required=True)
    parser.add_argument("--target", default="HEAD")
    parser.add_argument("--owner", required=True)
    parser.add_argument("--work-package", required=True)
    parser.add_argument("--attempt", required=True)
    parser.add_argument("--risk", required=True)
    parser.add_argument("--contract-digest", required=True)
    parser.add_argument("--write-scope", action="append", default=[])
    parser.add_argument("--required-ref", action="append", default=[])
    parser.add_argument("--known-fact-ref", action="append", default=[])
    parser.add_argument("--do-not-recheck-ref", action="append", default=[])
    parser.add_argument("--expand", action="append", default=[])


def _reference(value: str) -> EvidenceReference:
    fields = value.split(":", 2)
    if len(fields) != 3:
        raise EngineeringControlError(ErrorCode.INVALID_PATH)
    reference_id, path, digest = fields
    if not reference_id or not re.fullmatch(r"[A-Za-z0-9_.\-/]+", reference_id):
        raise EngineeringControlError(ErrorCode.INVALID_PATH)
    return EvidenceReference(
        reference_id=reference_id,
        path=normalize_repo_path(path),
        sha256=digest,
    )


def _expansion(value: str) -> ScopeExpansion:
    fields = value.split(":", 2)
    if len(fields) != 3:
        raise EngineeringControlError(ErrorCode.INVALID_PATH)
    reason, authority, path = fields
    try:
        reason_code = ExpansionReason(reason)
    except ValueError as exc:
        raise EngineeringControlError(ErrorCode.INVALID_PATH) from exc
    if not authority or not re.fullmatch(r"[A-Za-z0-9_.\-/]+", authority):
        raise EngineeringControlError(ErrorCode.INVALID_PATH)
    return ScopeExpansion(
        reason=reason_code,
        paths=(normalize_repo_path(path),),
        authority=authority,
    )


def _toolchain(value: str) -> tuple[str, str]:
    fields = value.split("=", 1)
    if len(fields) != 2 or not all(fields):
        raise EngineeringControlError(ErrorCode.EVIDENCE_INVALID)
    if not all(re.fullmatch(r"[A-Za-z0-9_.\-+]+", field) for field in fields):
        raise EngineeringControlError(ErrorCode.EVIDENCE_INVALID)
    return fields[0], fields[1]


def _read_observation(value: str) -> ReadObservation:
    fields = value.split(":", 2)
    if len(fields) != 3:
        raise EngineeringControlError(ErrorCode.REPORT_INVALID)
    path, digest, raw_byte_count = fields
    try:
        byte_count = int(raw_byte_count)
    except ValueError as exc:
        raise EngineeringControlError(ErrorCode.REPORT_INVALID) from exc
    return ReadObservation(
        path=normalize_repo_path(path),
        sha256=digest,
        byte_count=byte_count,
    )


def _capsule_request(args: argparse.Namespace) -> CapsuleRequest:
    if not _COMMIT.fullmatch(args.base):
        raise EngineeringControlError(ErrorCode.INVALID_PATH)
    if args.target != "HEAD" and not _COMMIT.fullmatch(args.target):
        raise EngineeringControlError(ErrorCode.INVALID_PATH)
    return CapsuleRequest(
        base=args.base,
        target=args.target,
        owner=args.owner,
        work_package=args.work_package,
        attempt_id=args.attempt,
        risk_class=args.risk,
        contract_digest=args.contract_digest,
        write_scope=tuple(args.write_scope),
        required_refs=tuple(_reference(value) for value in args.required_ref),
        known_fact_refs=tuple(_reference(value) for value in args.known_fact_ref),
        do_not_recheck_refs=tuple(
            _reference(value) for value in args.do_not_recheck_ref
        ),
        expansions=tuple(_expansion(value) for value in args.expand),
    )


def _emit(root: Path, value: bytes, output: str | None) -> None:
    if output is None:
        sys.stdout.buffer.write(value)
        return
    relative = normalize_repo_path(output)
    if not path_is_within(relative, ".flowpilot-engineering"):
        raise EngineeringControlError(
            ErrorCode.OUTPUT_POLICY_VIOLATION,
            metadata={"path": relative},
        )
    destination = root.joinpath(*relative.split("/"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            delete=False,
        ) as handle:
            temporary_path = handle.name
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None:
            with suppress(FileNotFoundError):
                os.unlink(temporary_path)


def _execute(args: argparse.Namespace) -> None:
    root = Path(args.repo).resolve()
    if args.command == "map" and args.map_command == "build":
        repository_map = RepositoryMapBuilder(root).build()
        _emit(root, repository_map.to_bytes(), args.output)
        return
    if args.command == "capsule" and args.capsule_command == "build":
        repository_map = RepositoryMapBuilder(root).build()
        capsule = CapsuleBuilder(root, repository_map).build(_capsule_request(args))
        _emit(root, capsule.to_bytes(), args.output)
        return
    if args.command == "tests" and args.tests_command == "select":
        repository_map = RepositoryMapBuilder(root).build()
        capsule = CapsuleBuilder(root, repository_map).build(_capsule_request(args))
        plan = TestSelector(repository_map).select(
            SelectionRequest(
                capsule=capsule,
                fallback_signals=tuple(SelectionSignal(value) for value in args.signal),
            )
        )
        _emit(root, plan.to_bytes(), args.output)
        return
    if args.command == "evidence":
        repository_map = RepositoryMapBuilder(root).build()
        command = CommandSpec(args.command_id, tuple(args.arg))
        cache_key = CacheKeyInput.from_repository_map(
            command=command,
            repository_map=repository_map,
            contract_digest=args.contract_digest,
            environment=EnvironmentFingerprint.current(),
            toolchain=tuple(_toolchain(value) for value in args.toolchain),
        ).build()
        policy = CachePolicy(EvidenceKind(args.kind))
        cache = EvidenceCache(root)
        if args.evidence_command == "record":
            producer_head = (
                repository_map.git_head
                if args.producer_head == "HEAD"
                else args.producer_head
            )
            record_path = cache.record(
                key=cache_key,
                producer_head=producer_head,
                evidence_path=args.evidence,
                exit_code=args.exit_code,
                policy=policy,
            )
            _emit(
                root,
                canonical_json_bytes(
                    {
                        "cache_key": cache_key.to_record(),
                        "record_path": record_path,
                    }
                ),
                args.output,
            )
            return
        current_head = (
            repository_map.git_head
            if args.current_head == "HEAD"
            else args.current_head
        )
        decision = cache.check(
            record_path=args.record,
            expected_key=cache_key,
            current_head=current_head,
            policy=policy,
        )
        _emit(root, canonical_json_bytes(decision.to_record()), args.output)
        return
    if args.command == "attempt" and args.attempt_command == "report":
        repository_map = RepositoryMapBuilder(root).build()
        capsule = CapsuleBuilder(root, repository_map).build(_capsule_request(args))
        plan = TestSelector(repository_map).select(
            SelectionRequest(
                capsule=capsule,
                fallback_signals=tuple(SelectionSignal(value) for value in args.signal),
            )
        )
        report = AttemptReportBuilder.build(
            attempt_id=args.attempt,
            capsule=capsule,
            plan=plan,
            actual_reads=(
                tuple(_read_observation(value) for value in args.actual_read)
                if args.actual_read
                else None
            ),
            selection_compute_ms=args.selection_ms,
        )
        _emit(root, report.to_bytes(), args.output)
        return
    raise EngineeringControlError(ErrorCode.INVALID_PATH)


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        _execute(args)
    except EngineeringControlError as exc:
        payload = {
            "error": {
                "code": exc.code.value,
                "message": exc.safe_message,
                "metadata": exc.metadata,
            }
        }
        sys.stderr.buffer.write(canonical_json_bytes(payload))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
