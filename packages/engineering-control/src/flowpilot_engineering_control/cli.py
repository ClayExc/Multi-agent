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
from flowpilot_engineering_control.paths import normalize_repo_path, path_is_within
from flowpilot_engineering_control.repository import RepositoryMapBuilder
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
    capsule_build.add_argument("--base", required=True)
    capsule_build.add_argument("--target", default="HEAD")
    capsule_build.add_argument("--owner", required=True)
    capsule_build.add_argument("--work-package", required=True)
    capsule_build.add_argument("--attempt", required=True)
    capsule_build.add_argument("--risk", required=True)
    capsule_build.add_argument("--contract-digest", required=True)
    capsule_build.add_argument("--write-scope", action="append", default=[])
    capsule_build.add_argument("--required-ref", action="append", default=[])
    capsule_build.add_argument("--known-fact-ref", action="append", default=[])
    capsule_build.add_argument("--do-not-recheck-ref", action="append", default=[])
    capsule_build.add_argument("--expand", action="append", default=[])
    capsule_build.add_argument("--output")
    return parser


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
        if not _COMMIT.fullmatch(args.base):
            raise EngineeringControlError(ErrorCode.INVALID_PATH)
        if args.target != "HEAD" and not _COMMIT.fullmatch(args.target):
            raise EngineeringControlError(ErrorCode.INVALID_PATH)
        repository_map = RepositoryMapBuilder(root).build()
        request = CapsuleRequest(
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
        capsule = CapsuleBuilder(root, repository_map).build(request)
        _emit(root, capsule.to_bytes(), args.output)
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
