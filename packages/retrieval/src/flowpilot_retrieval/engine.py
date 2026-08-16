from __future__ import annotations

import math
import re
from dataclasses import dataclass

from flowpilot_application import KnowledgeCitationResolution
from flowpilot_domain import DataClassification, StableCitation
from flowpilot_persistence import (
    DeterministicEmbeddingPort,
    KnowledgeCandidate,
    KnowledgeCandidateQuery,
)
from flowpilot_persistence.knowledge_index import (
    EMBEDDING_DIMENSION,
    EMBEDDING_MODEL,
    EMBEDDING_VERSION,
    SCORE_INPUT_VERSION,
)

from .errors import RetrievalError, RetrievalErrorCode
from .models import (
    HybridRankingPolicy,
    RetrievalDiagnostics,
    RetrievalHit,
    RetrievalRequest,
    RetrievalResult,
)
from .ports import KnowledgeCandidatePort, KnowledgeCitationVerificationPort

_CONTENT_REF = re.compile(r"^knowledge-content://[a-f0-9]{64}$")
_CLASSIFICATION_RANK = {
    DataClassification.PUBLIC: 0,
    DataClassification.INTERNAL: 1,
    DataClassification.CONFIDENTIAL: 2,
    DataClassification.RESTRICTED: 3,
}


@dataclass(frozen=True, slots=True)
class _RankedCandidate:
    candidate: KnowledgeCandidate
    citation: StableCitation
    score: float
    vector_score: float
    keyword_score: float

    @property
    def order_key(self) -> tuple[float, float, float, str, int, str]:
        return (
            -self.score,
            self.candidate.vector_distance,
            -self.keyword_score,
            *self.candidate.stable_sort_key,
        )


class HybridRetrievalEngine:
    """Deterministic ranking over candidates already filtered by trusted storage."""

    def __init__(
        self,
        *,
        embedding: DeterministicEmbeddingPort,
        candidates: KnowledgeCandidatePort,
        citations: KnowledgeCitationVerificationPort,
        policy: HybridRankingPolicy | None = None,
    ) -> None:
        self._embedding = embedding
        self._candidates = candidates
        self._citations = citations
        self._policy = policy or HybridRankingPolicy()

    async def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        self._validate_request_binding(request)
        self._validate_embedding_version()
        vector = await self._embed(request.query_text)
        query = KnowledgeCandidateQuery(
            tenant_id=request.context.tenant_id,
            purpose=request.context.purpose,
            principals=request.principals,
            classification_ceiling=request.action_classification_ceiling,
            query_text=request.query_text,
            query_vector=vector,
            observed_at=request.observed_at,
            limit=request.candidate_limit,
        )
        raw_candidates = await self._load_candidates(query)
        ranked = self._rank_and_deduplicate(raw_candidates, request)
        eligible = tuple(
            item for item in ranked if item.score >= self._policy.minimum_score
        )
        selected = eligible[: request.result_limit]
        hits = await self._revalidate(request, selected)
        diagnostics = RetrievalDiagnostics(
            ranking_version=self._policy.version,
            score_input_version=SCORE_INPUT_VERSION,
            embedding_model=EMBEDDING_MODEL,
            embedding_version=EMBEDDING_VERSION,
            candidate_count=len(raw_candidates),
            deduplicated_count=len(ranked),
            threshold_eligible_count=len(eligible),
            verified_count=len(hits),
        )
        return RetrievalResult(hits=hits, diagnostics=diagnostics)

    def _validate_request_binding(self, request: RetrievalRequest) -> None:
        context = request.context
        security_context = context.security_context
        if (
            context.tenant_id != security_context.tenant_id
            or context.purpose != security_context.purpose
            or _CLASSIFICATION_RANK[request.action_classification_ceiling]
            > _CLASSIFICATION_RANK[
                security_context.data_classification_ceiling
            ]
        ):
            raise RetrievalError(RetrievalErrorCode.SECURITY_BINDING_MISMATCH)
        if not (
            security_context.issued_at
            <= request.observed_at
            < security_context.expires_at
        ):
            raise RetrievalError(RetrievalErrorCode.SECURITY_CONTEXT_UNAVAILABLE)

    def _validate_embedding_version(self) -> None:
        if (
            self._embedding.model != EMBEDDING_MODEL
            or self._embedding.version != EMBEDDING_VERSION
            or self._embedding.dimension != EMBEDDING_DIMENSION
        ):
            raise RetrievalError(RetrievalErrorCode.EMBEDDING_VERSION_UNSUPPORTED)

    async def _embed(self, query_text: str) -> tuple[float, ...]:
        try:
            vector = await self._embedding.embed(query_text)
        except Exception:
            raise RetrievalError(RetrievalErrorCode.EMBEDDING_FAILED) from None
        if (
            not isinstance(vector, tuple)
            or len(vector) != EMBEDDING_DIMENSION
            or any(
                not isinstance(value, float | int) or not math.isfinite(value)
                for value in vector
            )
        ):
            raise RetrievalError(RetrievalErrorCode.EMBEDDING_FAILED)
        return tuple(float(value) for value in vector)

    async def _load_candidates(
        self, query: KnowledgeCandidateQuery
    ) -> tuple[KnowledgeCandidate, ...]:
        try:
            candidates = await self._candidates.candidates(query)
        except Exception:
            raise RetrievalError(RetrievalErrorCode.CANDIDATE_SOURCE_FAILED) from None
        if (
            not isinstance(candidates, tuple)
            or len(candidates) > query.limit
            or any(
            not isinstance(item, KnowledgeCandidate) for item in candidates
            )
        ):
            raise RetrievalError(RetrievalErrorCode.CANDIDATE_PROTOCOL_VIOLATION)
        return candidates

    def _rank_and_deduplicate(
        self,
        candidates: tuple[KnowledgeCandidate, ...],
        request: RetrievalRequest,
    ) -> tuple[_RankedCandidate, ...]:
        exact: dict[tuple[str, int, str], KnowledgeCandidate] = {}
        ranked: list[_RankedCandidate] = []
        ceiling = request.action_classification_ceiling
        for candidate in candidates:
            self._validate_candidate(candidate, request.context.tenant_id, ceiling)
            existing = exact.get(candidate.stable_sort_key)
            if existing is not None:
                if existing != candidate:
                    raise RetrievalError(
                        RetrievalErrorCode.CANDIDATE_PROTOCOL_VIOLATION
                    )
                continue
            exact[candidate.stable_sort_key] = candidate
            ranked.append(self._score(candidate))

        # One section per exact document version prevents chunk multiplicity from
        # crowding out other evidence while preserving the version in the citation.
        per_version: dict[tuple[str, int], _RankedCandidate] = {}
        for item in sorted(ranked, key=lambda value: value.order_key):
            key = (item.candidate.document_id, item.candidate.document_version)
            per_version.setdefault(key, item)
        return tuple(sorted(per_version.values(), key=lambda value: value.order_key))

    def _validate_candidate(
        self,
        candidate: KnowledgeCandidate,
        tenant_id: str,
        ceiling: DataClassification,
    ) -> None:
        if candidate.tenant_id != tenant_id:
            raise RetrievalError(RetrievalErrorCode.CANDIDATE_PROTOCOL_VIOLATION)
        if candidate.score_input_version != SCORE_INPUT_VERSION:
            raise RetrievalError(RetrievalErrorCode.CANDIDATE_PROTOCOL_VIOLATION)
        if (
            not isinstance(candidate.vector_distance, float | int)
            or not math.isfinite(candidate.vector_distance)
            or candidate.vector_distance < 0.0
            or not isinstance(candidate.keyword_rank, float | int)
            or not math.isfinite(candidate.keyword_rank)
            or candidate.keyword_rank < 0.0
        ):
            raise RetrievalError(RetrievalErrorCode.CANDIDATE_PROTOCOL_VIOLATION)
        if not isinstance(candidate.content_ref, str) or not _CONTENT_REF.fullmatch(
            candidate.content_ref
        ):
            raise RetrievalError(RetrievalErrorCode.CANDIDATE_PROTOCOL_VIOLATION)
        if not isinstance(candidate.data_classification, DataClassification):
            raise RetrievalError(RetrievalErrorCode.CANDIDATE_PROTOCOL_VIOLATION)
        if _CLASSIFICATION_RANK[candidate.data_classification] > _CLASSIFICATION_RANK[
            ceiling
        ]:
            raise RetrievalError(RetrievalErrorCode.CANDIDATE_PROTOCOL_VIOLATION)
        try:
            StableCitation(
                tenant_id=candidate.tenant_id,
                document_id=candidate.document_id,
                document_version=candidate.document_version,
                section_id=candidate.section_id,
                content_hash=candidate.content_hash,
            )
        except Exception:
            raise RetrievalError(
                RetrievalErrorCode.CANDIDATE_PROTOCOL_VIOLATION
            ) from None

    def _score(self, candidate: KnowledgeCandidate) -> _RankedCandidate:
        vector_score = 1.0 / (1.0 + float(candidate.vector_distance))
        keyword_rank = float(candidate.keyword_rank)
        keyword_score = keyword_rank / (1.0 + keyword_rank)
        score = round(
            self._policy.vector_weight * vector_score
            + self._policy.keyword_weight * keyword_score,
            12,
        )
        citation = StableCitation(
            tenant_id=candidate.tenant_id,
            document_id=candidate.document_id,
            document_version=candidate.document_version,
            section_id=candidate.section_id,
            content_hash=candidate.content_hash,
        )
        return _RankedCandidate(
            candidate=candidate,
            citation=citation,
            score=score,
            vector_score=round(vector_score, 12),
            keyword_score=round(keyword_score, 12),
        )

    async def _revalidate(
        self,
        request: RetrievalRequest,
        selected: tuple[_RankedCandidate, ...],
    ) -> tuple[RetrievalHit, ...]:
        hits: list[RetrievalHit] = []
        for item in selected:
            try:
                resolution = await self._citations.resolve_citation(
                    request.context,
                    item.citation,
                    action_classification_ceiling=(
                        request.action_classification_ceiling
                    ),
                )
            except Exception:
                raise RetrievalError(
                    RetrievalErrorCode.REFERENCE_REVALIDATION_FAILED
                ) from None
            if not isinstance(resolution, KnowledgeCitationResolution) or (
                resolution.citation != item.citation
                or resolution.content_ref != item.candidate.content_ref
                or resolution.data_classification
                is not item.candidate.data_classification
            ):
                raise RetrievalError(
                    RetrievalErrorCode.REFERENCE_REVALIDATION_FAILED
                )
            hits.append(
                RetrievalHit(
                    citation=item.citation,
                    content_ref=resolution.content_ref,
                    data_classification=resolution.data_classification,
                    content_excerpt=resolution.content_excerpt,
                    score=item.score,
                    vector_score=item.vector_score,
                    keyword_score=item.keyword_score,
                    ranking_version=self._policy.version,
                    score_input_version=item.candidate.score_input_version,
                )
            )
        return tuple(hits)
