from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from flowpilot_application import KnowledgeCitationResolution, KnowledgeRequestContext
from flowpilot_domain import (
    AclPrincipal,
    AclPrincipalType,
    ActorType,
    AssuranceLevel,
    AuthenticationMethod,
    AuthenticationRef,
    DataClassification,
    SecurityContextRef,
    StableCitation,
)
from flowpilot_persistence import (
    HashEmbeddingAdapter,
    KnowledgeCandidate,
    KnowledgeCandidateQuery,
)
from flowpilot_persistence.knowledge_index import (
    EMBEDDING_DIMENSION,
    EMBEDDING_MODEL,
    EMBEDDING_VERSION,
    SCORE_INPUT_VERSION,
)
from flowpilot_retrieval import (
    HybridRankingPolicy,
    HybridRetrievalEngine,
    RetrievalError,
    RetrievalErrorCode,
    RetrievalRequest,
)

NOW = datetime(2026, 8, 16, 8, 0, tzinfo=UTC)
TENANT = "tenant-alpha"
PURPOSE = "incident-resolution"
CONTENT_HASH = "sha256:" + "a" * 64
CONTENT_REF = "knowledge-content://" + "b" * 64
PRINCIPAL = AclPrincipal(AclPrincipalType.SUBJECT, "user-alpha")


@dataclass(slots=True)
class FakeEmbedding:
    model: str = EMBEDDING_MODEL
    version: str = EMBEDDING_VERSION
    dimension: int = EMBEDDING_DIMENSION
    output: tuple[float, ...] = field(
        default_factory=lambda: (0.0,) * EMBEDDING_DIMENSION
    )
    failure: Exception | None = None
    calls: int = 0

    async def embed(self, text: str) -> tuple[float, ...]:
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        return self.output


@dataclass(slots=True)
class FakeCandidatePort:
    items: object = ()
    failure: Exception | None = None
    queries: list[KnowledgeCandidateQuery] = field(default_factory=list)

    async def candidates(
        self, query: KnowledgeCandidateQuery
    ) -> tuple[KnowledgeCandidate, ...]:
        self.queries.append(query)
        if self.failure is not None:
            raise self.failure
        return cast(tuple[KnowledgeCandidate, ...], self.items)


@dataclass(slots=True)
class FakeCitationVerifier:
    overrides: dict[StableCitation, KnowledgeCitationResolution] = field(
        default_factory=dict
    )
    failure: Exception | None = None
    calls: list[StableCitation] = field(default_factory=list)

    async def resolve_citation(
        self,
        context: KnowledgeRequestContext,
        citation: StableCitation,
    ) -> KnowledgeCitationResolution:
        self.calls.append(citation)
        if self.failure is not None:
            raise self.failure
        return self.overrides.get(
            citation,
            KnowledgeCitationResolution(
                citation=citation,
                content_ref=CONTENT_REF,
                data_classification=DataClassification.INTERNAL,
            ),
        )


def _security_context(
    *,
    tenant_id: str = TENANT,
    purpose: str = PURPOSE,
    issued_at: datetime = NOW - timedelta(hours=1),
    expires_at: datetime = NOW + timedelta(hours=1),
) -> SecurityContextRef:
    return SecurityContextRef(
        context_id="secctx_abcdefgh",
        context_ref="security-context://safe",
        context_hash="sha256:" + "c" * 64,
        tenant_id=tenant_id,
        subject_id="user-alpha",
        subject_type=ActorType.USER,
        purpose=purpose,
        authentication=AuthenticationRef(
            method=AuthenticationMethod.OIDC,
            assurance_level=AssuranceLevel.HIGH,
        ),
        data_classification_ceiling=DataClassification.CONFIDENTIAL,
        issued_at=issued_at,
        expires_at=expires_at,
    )


def _request(
    *,
    context_tenant: str = TENANT,
    context_purpose: str = PURPOSE,
    security_context: SecurityContextRef | None = None,
    query_text: str = "vpn credential recovery",
    observed_at: datetime = NOW,
    candidate_limit: int = 50,
    result_limit: int = 10,
) -> RetrievalRequest:
    return RetrievalRequest(
        context=KnowledgeRequestContext(
            tenant_id=context_tenant,
            purpose=context_purpose,
            security_context=security_context or _security_context(),
        ),
        principals=(PRINCIPAL,),
        query_text=query_text,
        observed_at=observed_at,
        candidate_limit=candidate_limit,
        result_limit=result_limit,
    )


def _candidate(
    *,
    tenant_id: str = TENANT,
    document_id: str = "doc_abcdefgh",
    document_version: int = 1,
    section_id: str = "section-1",
    content_ref: str = CONTENT_REF,
    content_hash: str = CONTENT_HASH,
    data_classification: DataClassification = DataClassification.INTERNAL,
    vector_distance: float = 0.2,
    keyword_rank: float = 1.0,
    score_input_version: str = SCORE_INPUT_VERSION,
) -> KnowledgeCandidate:
    return KnowledgeCandidate(
        tenant_id=tenant_id,
        document_id=document_id,
        document_version=document_version,
        section_id=section_id,
        content_ref=content_ref,
        content_hash=content_hash,
        data_classification=data_classification,
        vector_distance=vector_distance,
        keyword_rank=keyword_rank,
        score_input_version=score_input_version,
    )


def _engine(
    *,
    embedding: FakeEmbedding | None = None,
    candidates: FakeCandidatePort | None = None,
    verifier: FakeCitationVerifier | None = None,
    policy: HybridRankingPolicy | None = None,
) -> tuple[
    HybridRetrievalEngine,
    FakeEmbedding,
    FakeCandidatePort,
    FakeCitationVerifier,
]:
    embedding = embedding or FakeEmbedding()
    candidates = candidates or FakeCandidatePort()
    verifier = verifier or FakeCitationVerifier()
    return (
        HybridRetrievalEngine(
            embedding=embedding,
            candidates=candidates,
            citations=verifier,
            policy=policy,
        ),
        embedding,
        candidates,
        verifier,
    )


@pytest.mark.asyncio
async def test_hybrid_ranking_builds_authorized_query_and_safe_diagnostics() -> None:
    lower_vector = _candidate(
        document_id="doc_vector01",
        vector_distance=0.1,
        keyword_rank=0.0,
    )
    stronger_hybrid = _candidate(
        document_id="doc_hybrid01",
        vector_distance=0.4,
        keyword_rank=3.0,
    )
    port = FakeCandidatePort(items=(lower_vector, stronger_hybrid))
    engine, embedding, _, verifier = _engine(candidates=port)

    result = await engine.retrieve(_request())

    assert [hit.citation.document_id for hit in result.hits] == [
        "doc_hybrid01",
        "doc_vector01",
    ]
    assert embedding.calls == 1
    assert len(verifier.calls) == 2
    query = port.queries[0]
    assert query.tenant_id == TENANT
    assert query.purpose == PURPOSE
    assert query.principals == (PRINCIPAL,)
    assert query.classification_ceiling is DataClassification.CONFIDENTIAL
    assert query.observed_at == NOW
    assert len(query.query_vector) == EMBEDDING_DIMENSION
    assert result.diagnostics.safe_mapping() == {
        "ranking_version": "flowpilot.hybrid-ranking.m10.v1",
        "score_input_version": SCORE_INPUT_VERSION,
        "embedding_model": EMBEDDING_MODEL,
        "embedding_version": EMBEDDING_VERSION,
        "candidate_count": 2,
        "deduplicated_count": 2,
        "threshold_eligible_count": 2,
        "verified_count": 2,
    }


@pytest.mark.asyncio
async def test_exact_duplicates_collapse_and_equal_scores_use_stable_key() -> None:
    later = _candidate(document_id="doc_bbbbbbbb")
    earlier = _candidate(document_id="doc_aaaaaaaa")
    engine, _, _, _ = _engine(
        candidates=FakeCandidatePort(items=(later, earlier, later))
    )

    result = await engine.retrieve(_request())

    assert [hit.citation.document_id for hit in result.hits] == [
        "doc_aaaaaaaa",
        "doc_bbbbbbbb",
    ]
    assert result.diagnostics.candidate_count == 3
    assert result.diagnostics.deduplicated_count == 2


@pytest.mark.asyncio
async def test_same_query_and_configuration_replay_byte_stable_scores() -> None:
    port = FakeCandidatePort(items=(_candidate(),))
    verifier = FakeCitationVerifier()
    engine = HybridRetrievalEngine(
        embedding=HashEmbeddingAdapter(),
        candidates=port,
        citations=verifier,
    )

    first = await engine.retrieve(_request())
    second = await engine.retrieve(_request())

    assert first == second
    assert port.queries[0].query_vector == port.queries[1].query_vector
    assert first.hits[0].score == 0.733333333333


@pytest.mark.asyncio
async def test_document_version_dedup_keeps_best_section_per_exact_version() -> None:
    items = (
        _candidate(document_version=1, section_id="weak", vector_distance=2.0),
        _candidate(document_version=1, section_id="strong", vector_distance=0.1),
        _candidate(document_version=2, section_id="new", vector_distance=0.2),
    )
    engine, _, _, _ = _engine(candidates=FakeCandidatePort(items=items))

    result = await engine.retrieve(_request())

    actual = [
        (hit.citation.document_version, hit.citation.section_id)
        for hit in result.hits
    ]
    assert actual == [
        (1, "strong"),
        (2, "new"),
    ]
    assert result.diagnostics.deduplicated_count == 2


@pytest.mark.asyncio
async def test_low_relevance_and_empty_candidates_return_explicit_no_evidence() -> None:
    policy = HybridRankingPolicy(minimum_score=0.8)
    verifier = FakeCitationVerifier()
    engine, _, _, _ = _engine(
        candidates=FakeCandidatePort(items=(_candidate(vector_distance=10.0),)),
        verifier=verifier,
        policy=policy,
    )

    low_result = await engine.retrieve(_request())
    empty_engine, _, _, empty_verifier = _engine()
    empty_result = await empty_engine.retrieve(_request())

    assert low_result.hits == ()
    assert low_result.diagnostics.threshold_eligible_count == 0
    assert verifier.calls == []
    assert empty_result.hits == ()
    assert empty_result.diagnostics.candidate_count == 0
    assert empty_verifier.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "candidate",
    [
        _candidate(tenant_id="tenant-other"),
        _candidate(data_classification=DataClassification.RESTRICTED),
        _candidate(score_input_version="flowpilot-hybrid-score-input.other"),
        _candidate(content_ref="knowledge-content://not-opaque"),
        _candidate(content_hash="not-a-hash"),
        _candidate(vector_distance=math.nan),
        _candidate(vector_distance=-0.1),
        _candidate(keyword_rank=math.inf),
        _candidate(keyword_rank=-0.1),
    ],
)
async def test_candidate_metadata_protocol_violations_fail_closed(
    candidate: KnowledgeCandidate,
) -> None:
    engine, _, _, verifier = _engine(
        candidates=FakeCandidatePort(items=(candidate,))
    )

    with pytest.raises(RetrievalError) as caught:
        await engine.retrieve(_request())

    assert caught.value.code is RetrievalErrorCode.CANDIDATE_PROTOCOL_VIOLATION
    assert verifier.calls == []


@pytest.mark.asyncio
async def test_conflicting_duplicate_version_section_fails_closed() -> None:
    candidate = _candidate()
    conflict = replace(candidate, keyword_rank=2.0)
    engine, _, _, verifier = _engine(
        candidates=FakeCandidatePort(items=(candidate, conflict))
    )

    with pytest.raises(RetrievalError) as caught:
        await engine.retrieve(_request())

    assert caught.value.code is RetrievalErrorCode.CANDIDATE_PROTOCOL_VIOLATION
    assert verifier.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "retrieval_request",
    [
        _request(context_tenant="tenant-forged"),
        _request(context_purpose="forged-purpose"),
    ],
)
async def test_context_binding_mismatch_fails_before_embedding(
    retrieval_request: RetrievalRequest,
) -> None:
    engine, embedding, port, _ = _engine()

    with pytest.raises(RetrievalError) as caught:
        await engine.retrieve(retrieval_request)

    assert caught.value.code is RetrievalErrorCode.SECURITY_BINDING_MISMATCH
    assert embedding.calls == 0
    assert port.queries == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "observed_at",
    [NOW - timedelta(hours=2), NOW + timedelta(hours=1)],
)
async def test_expired_or_not_yet_valid_context_fails_before_embedding(
    observed_at: datetime,
) -> None:
    engine, embedding, port, _ = _engine()

    with pytest.raises(RetrievalError) as caught:
        await engine.retrieve(_request(observed_at=observed_at))

    assert caught.value.code is RetrievalErrorCode.SECURITY_CONTEXT_UNAVAILABLE
    assert embedding.calls == 0
    assert port.queries == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "embedding",
    [
        FakeEmbedding(model="other-model"),
        FakeEmbedding(version="m10.other"),
        FakeEmbedding(dimension=128),
    ],
)
async def test_embedding_identity_mismatch_fails_before_query(
    embedding: FakeEmbedding,
) -> None:
    engine, _, port, _ = _engine(embedding=embedding)

    with pytest.raises(RetrievalError) as caught:
        await engine.retrieve(_request())

    assert caught.value.code is RetrievalErrorCode.EMBEDDING_VERSION_UNSUPPORTED
    assert embedding.calls == 0
    assert port.queries == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "embedding",
    [
        FakeEmbedding(output=(0.0,) * (EMBEDDING_DIMENSION - 1)),
        FakeEmbedding(output=(math.nan,) + (0.0,) * (EMBEDDING_DIMENSION - 1)),
        FakeEmbedding(failure=RuntimeError("raw query body must not escape")),
    ],
)
async def test_embedding_failures_are_mapped_to_stable_error(
    embedding: FakeEmbedding,
) -> None:
    engine, _, port, _ = _engine(embedding=embedding)

    with pytest.raises(RetrievalError) as caught:
        await engine.retrieve(_request())

    assert caught.value.code is RetrievalErrorCode.EMBEDDING_FAILED
    assert str(caught.value) == "RETRIEVAL_EMBEDDING_FAILED"
    assert port.queries == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "port",
    [
        FakeCandidatePort(items=[]),
        FakeCandidatePort(failure=RuntimeError("database secret must not escape")),
    ],
)
async def test_candidate_port_failures_are_mapped_to_stable_error(
    port: FakeCandidatePort,
) -> None:
    engine, _, _, _ = _engine(candidates=port)

    with pytest.raises(RetrievalError) as caught:
        await engine.retrieve(_request())

    expected = (
        RetrievalErrorCode.CANDIDATE_SOURCE_FAILED
        if port.failure is not None
        else RetrievalErrorCode.CANDIDATE_PROTOCOL_VIOLATION
    )
    assert caught.value.code is expected
    assert "secret" not in str(caught.value).casefold()


@pytest.mark.asyncio
async def test_candidate_port_cannot_expand_the_authorized_query_limit() -> None:
    port = FakeCandidatePort(
        items=(
            _candidate(document_id="doc_aaaaaaaa"),
            _candidate(document_id="doc_bbbbbbbb"),
        )
    )
    engine, _, _, verifier = _engine(candidates=port)

    with pytest.raises(RetrievalError) as caught:
        await engine.retrieve(_request(candidate_limit=1, result_limit=1))

    assert caught.value.code is RetrievalErrorCode.CANDIDATE_PROTOCOL_VIOLATION
    assert verifier.calls == []


@pytest.mark.asyncio
async def test_expired_revoked_or_missing_reference_is_a_stable_failure() -> None:
    verifier = FakeCitationVerifier(
        failure=RuntimeError("retired document title must not escape")
    )
    engine, _, _, _ = _engine(
        candidates=FakeCandidatePort(items=(_candidate(),)),
        verifier=verifier,
    )

    with pytest.raises(RetrievalError) as caught:
        await engine.retrieve(_request())

    assert caught.value.code is RetrievalErrorCode.REFERENCE_REVALIDATION_FAILED
    assert str(caught.value) == "RETRIEVAL_REFERENCE_REVALIDATION_FAILED"
    assert len(verifier.calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mismatch", ["version", "hash", "content_ref", "classification"]
)
async def test_reference_revalidation_must_match_exact_candidate(
    mismatch: str,
) -> None:
    candidate = _candidate()
    citation = StableCitation(
        tenant_id=TENANT,
        document_id=candidate.document_id,
        document_version=candidate.document_version,
        section_id=candidate.section_id,
        content_hash=candidate.content_hash,
    )
    wrong_citation = citation
    content_ref = CONTENT_REF
    classification = DataClassification.INTERNAL
    if mismatch == "version":
        wrong_citation = replace(citation, document_version=2)
    elif mismatch == "hash":
        wrong_citation = replace(citation, content_hash="sha256:" + "d" * 64)
    elif mismatch == "content_ref":
        content_ref = "knowledge-content://" + "e" * 64
    else:
        classification = DataClassification.PUBLIC
    verifier = FakeCitationVerifier(
        overrides={
            citation: KnowledgeCitationResolution(
                citation=wrong_citation,
                content_ref=content_ref,
                data_classification=classification,
            )
        }
    )
    engine, _, _, _ = _engine(
        candidates=FakeCandidatePort(items=(candidate,)),
        verifier=verifier,
    )

    with pytest.raises(RetrievalError) as caught:
        await engine.retrieve(_request())

    assert caught.value.code is RetrievalErrorCode.REFERENCE_REVALIDATION_FAILED


@pytest.mark.asyncio
async def test_query_and_failure_content_stay_out_of_result_and_error() -> None:
    canary = "secret-query-canary-6e3a"
    engine, _, _, _ = _engine(
        candidates=FakeCandidatePort(
            failure=RuntimeError(f"upstream leaked {canary}")
        )
    )
    request = _request(query_text=canary)

    assert canary not in repr(request)
    with pytest.raises(RetrievalError) as caught:
        await engine.retrieve(request)

    assert canary not in str(caught.value)
    assert canary not in repr(caught.value)


@pytest.mark.parametrize(
    "policy",
    [
        {"vector_weight": 0.8, "keyword_weight": 0.3},
        {"vector_weight": -0.1, "keyword_weight": 1.1},
        {"minimum_score": math.nan},
        {"minimum_score": 1.1},
        {"version": "flowpilot.hybrid-ranking.other"},
    ],
)
def test_ranking_policy_rejects_unversioned_or_invalid_configuration(
    policy: dict[str, object],
) -> None:
    with pytest.raises(ValueError):
        HybridRankingPolicy(**policy)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "changes",
    [
        {"query_text": "   "},
        {"observed_at": datetime(2026, 8, 16, 8, 0)},
        {"candidate_limit": 0},
        {"candidate_limit": 101},
        {"candidate_limit": 2, "result_limit": 3},
    ],
)
def test_request_rejects_invalid_shape(changes: dict[str, object]) -> None:
    arguments: dict[str, object] = {
        "context": KnowledgeRequestContext(
            tenant_id=TENANT,
            purpose=PURPOSE,
            security_context=_security_context(),
        ),
        "principals": (PRINCIPAL,),
        "query_text": "safe query",
        "observed_at": NOW,
        "candidate_limit": 50,
        "result_limit": 10,
    }
    arguments.update(changes)
    with pytest.raises(ValueError):
        RetrievalRequest(**arguments)  # type: ignore[arg-type]
