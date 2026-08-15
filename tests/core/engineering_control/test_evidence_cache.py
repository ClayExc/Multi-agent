from __future__ import annotations

from dataclasses import replace

import pytest
from flowpilot_engineering_control.errors import EngineeringControlError, ErrorCode
from flowpilot_engineering_control.evidence import (
    CacheKeyInput,
    CacheMissReason,
    CachePolicy,
    EnvironmentFingerprint,
    EvidenceCache,
    EvidenceKind,
)
from flowpilot_engineering_control.repository import RepositoryMapBuilder
from flowpilot_engineering_control.selection import CommandSpec

from .conftest import ExampleRepository


def _key_input(example_repository: ExampleRepository) -> CacheKeyInput:
    repository_map = RepositoryMapBuilder(example_repository.root).build()
    return CacheKeyInput.from_repository_map(
        command=CommandSpec(
            "targeted-tests",
            ("uv", "run", "--locked", "pytest", "-q", "tests/core"),
        ),
        repository_map=repository_map,
        contract_digest="sha256:" + "a" * 64,
        environment=EnvironmentFingerprint(
            os_name="test-os",
            architecture="x86_64",
            python_implementation="cpython",
            python_version="3.12.11",
        ),
        toolchain=(("pytest", "9.0.3"), ("uv", "0.8.0")),
    )


def _write_evidence(
    example_repository: ExampleRepository, value: str = "PASS\n"
) -> str:
    path = ".flowpilot-engineering/evidence/targeted.txt"
    example_repository.write(path, value)
    return path


def test_cache_hit_is_integrity_bound_and_idempotent(
    example_repository: ExampleRepository,
) -> None:
    key = _key_input(example_repository).build()
    evidence_path = _write_evidence(example_repository)
    cache = EvidenceCache(example_repository.root)
    head = example_repository.git("rev-parse", "HEAD")
    policy = CachePolicy(EvidenceKind.LOCAL_TEST)

    first_path = cache.record(
        key=key,
        producer_head=head,
        evidence_path=evidence_path,
        exit_code=0,
        policy=policy,
    )
    first_bytes = example_repository.root.joinpath(*first_path.split("/")).read_bytes()
    second_path = cache.record(
        key=key,
        producer_head=head,
        evidence_path=evidence_path,
        exit_code=0,
        policy=policy,
    )
    assert first_path == second_path
    assert example_repository.root.joinpath(*second_path.split("/")).read_bytes() == (
        first_bytes
    )
    decision = cache.check(
        record_path=first_path,
        expected_key=key,
        current_head=head,
        policy=policy,
    )
    assert decision.hit
    assert decision.reasons == ()


def test_failed_and_nonreusable_results_are_never_cached(
    example_repository: ExampleRepository,
) -> None:
    key = _key_input(example_repository).build()
    evidence_path = _write_evidence(example_repository, "FAIL\n")
    cache = EvidenceCache(example_repository.root)
    head = example_repository.git("rev-parse", "HEAD")

    with pytest.raises(EngineeringControlError) as failed:
        cache.record(
            key=key,
            producer_head=head,
            evidence_path=evidence_path,
            exit_code=1,
            policy=CachePolicy(EvidenceKind.LOCAL_TEST),
        )
    assert failed.value.code is ErrorCode.CACHE_FAILED_RESULT

    for kind in (
        EvidenceKind.ONLINE_PROVIDER,
        EvidenceKind.SECRET_SCAN,
        EvidenceKind.VULNERABILITY_QUERY,
        EvidenceKind.REAL_MIGRATION,
        EvidenceKind.DESTRUCTIVE_RECOVERY,
        EvidenceKind.SECURITY_REEXECUTE,
    ):
        with pytest.raises(EngineeringControlError) as denied:
            cache.record(
                key=key,
                producer_head=head,
                evidence_path=evidence_path,
                exit_code=0,
                policy=CachePolicy(kind),
            )
        assert denied.value.code is ErrorCode.CACHE_POLICY_DENIED


def test_cache_detects_record_and_evidence_tampering(
    example_repository: ExampleRepository,
) -> None:
    key = _key_input(example_repository).build()
    evidence_path = _write_evidence(example_repository)
    cache = EvidenceCache(example_repository.root)
    head = example_repository.git("rev-parse", "HEAD")
    policy = CachePolicy(EvidenceKind.LOCAL_TEST)
    record_path = cache.record(
        key=key,
        producer_head=head,
        evidence_path=evidence_path,
        exit_code=0,
        policy=policy,
    )
    record_file = example_repository.root.joinpath(*record_path.split("/"))
    original = record_file.read_bytes()
    record_file.write_bytes(original.replace(b'"reusable":true', b'"reusable":false'))
    decision = cache.check(
        record_path=record_path,
        expected_key=key,
        current_head=head,
        policy=policy,
    )
    assert decision.reasons == (CacheMissReason.RECORD_INTEGRITY,)

    record_file.write_bytes(original)
    example_repository.write(evidence_path, "TAMPERED\n")
    decision = cache.check(
        record_path=record_path,
        expected_key=key,
        current_head=head,
        policy=policy,
    )
    assert decision.reasons == (CacheMissReason.EVIDENCE_INTEGRITY,)


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("product_tree", CacheMissReason.PRODUCT_TREE_DRIFT),
        ("contract_tree", CacheMissReason.CONTRACT_TREE_DRIFT),
        ("migration_tree", CacheMissReason.MIGRATION_TREE_DRIFT),
        ("lock_hash", CacheMissReason.LOCK_DRIFT),
    ],
)
def test_cache_explains_protected_tree_drift(
    example_repository: ExampleRepository,
    field: str,
    reason: CacheMissReason,
) -> None:
    key_input = _key_input(example_repository)
    original_key = key_input.build()
    evidence_path = _write_evidence(example_repository)
    cache = EvidenceCache(example_repository.root)
    head = example_repository.git("rev-parse", "HEAD")
    policy = CachePolicy(EvidenceKind.LOCAL_TEST)
    record_path = cache.record(
        key=original_key,
        producer_head=head,
        evidence_path=evidence_path,
        exit_code=0,
        policy=policy,
    )
    changed_key = replace(key_input, **{field: "b" * 64}).build()
    decision = cache.check(
        record_path=record_path,
        expected_key=changed_key,
        current_head=head,
        policy=policy,
    )
    assert reason in decision.reasons


def test_cache_explains_environment_toolchain_and_argv_drift(
    example_repository: ExampleRepository,
) -> None:
    key_input = _key_input(example_repository)
    original_key = key_input.build()
    evidence_path = _write_evidence(example_repository)
    cache = EvidenceCache(example_repository.root)
    head = example_repository.git("rev-parse", "HEAD")
    policy = CachePolicy(EvidenceKind.LOCAL_TEST)
    record_path = cache.record(
        key=original_key,
        producer_head=head,
        evidence_path=evidence_path,
        exit_code=0,
        policy=policy,
    )
    environment_key = replace(
        key_input,
        environment=replace(key_input.environment, python_version="3.12.12"),
    ).build()
    toolchain_key = replace(
        key_input,
        toolchain=(("pytest", "9.0.4"), ("uv", "0.8.0")),
    ).build()
    argv_key = replace(
        key_input,
        command=CommandSpec("targeted-tests", ("python", "-c", "; | >")),
    ).build()
    contract_key = replace(
        key_input,
        contract_digest="sha256:" + "b" * 64,
    ).build()

    assert (
        CacheMissReason.ENVIRONMENT_DRIFT
        in cache.check(
            record_path=record_path,
            expected_key=environment_key,
            current_head=head,
            policy=policy,
        ).reasons
    )
    assert (
        CacheMissReason.TOOLCHAIN_DRIFT
        in cache.check(
            record_path=record_path,
            expected_key=toolchain_key,
            current_head=head,
            policy=policy,
        ).reasons
    )
    assert (
        CacheMissReason.COMMAND_DRIFT
        in cache.check(
            record_path=record_path,
            expected_key=argv_key,
            current_head=head,
            policy=policy,
        ).reasons
    )
    assert (
        CacheMissReason.CONTRACT_DIGEST_DRIFT
        in cache.check(
            record_path=record_path,
            expected_key=contract_key,
            current_head=head,
            policy=policy,
        ).reasons
    )


def test_cache_rejects_same_key_with_different_evidence(
    example_repository: ExampleRepository,
) -> None:
    key = _key_input(example_repository).build()
    evidence_path = _write_evidence(example_repository)
    cache = EvidenceCache(example_repository.root)
    head = example_repository.git("rev-parse", "HEAD")
    policy = CachePolicy(EvidenceKind.LOCAL_TEST)
    cache.record(
        key=key,
        producer_head=head,
        evidence_path=evidence_path,
        exit_code=0,
        policy=policy,
    )
    example_repository.write(evidence_path, "DIFFERENT\n")
    with pytest.raises(EngineeringControlError) as captured:
        cache.record(
            key=key,
            producer_head=head,
            evidence_path=evidence_path,
            exit_code=0,
            policy=policy,
        )
    assert captured.value.code is ErrorCode.CACHE_KEY_CONFLICT


def test_cache_rejects_untraceable_producer_head(
    example_repository: ExampleRepository,
) -> None:
    main_head = example_repository.git("rev-parse", "HEAD")
    example_repository.git("checkout", "-b", "side")
    example_repository.write("AGENTS.md", "side\n")
    side_head = example_repository.commit("side evidence producer")
    example_repository.git("checkout", "main")
    key = _key_input(example_repository).build()
    evidence_path = _write_evidence(example_repository)
    cache = EvidenceCache(example_repository.root)
    policy = CachePolicy(EvidenceKind.LOCAL_TEST)
    record_path = cache.record(
        key=key,
        producer_head=side_head,
        evidence_path=evidence_path,
        exit_code=0,
        policy=policy,
    )
    decision = cache.check(
        record_path=record_path,
        expected_key=key,
        current_head=main_head,
        policy=policy,
    )
    assert not decision.hit
    assert CacheMissReason.UNTRACEABLE_HEAD in decision.reasons


def test_cache_record_never_persists_command_argument_values(
    example_repository: ExampleRepository,
) -> None:
    key_input = _key_input(example_repository)
    secret = "SUPER_SECRET_TOKEN_VALUE"
    key = replace(
        key_input,
        command=CommandSpec("redaction-test", ("python", "-c", secret)),
    ).build()
    evidence_path = _write_evidence(example_repository)
    cache = EvidenceCache(example_repository.root)
    record_path = cache.record(
        key=key,
        producer_head=example_repository.git("rev-parse", "HEAD"),
        evidence_path=evidence_path,
        exit_code=0,
        policy=CachePolicy(EvidenceKind.LOCAL_TEST),
    )
    record_bytes = example_repository.root.joinpath(
        *record_path.split("/")
    ).read_bytes()
    assert secret.encode() not in record_bytes
