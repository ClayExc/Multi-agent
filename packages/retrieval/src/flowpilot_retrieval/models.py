from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import UTC, datetime

from flowpilot_application import KnowledgeRequestContext
from flowpilot_domain import AclPrincipal, DataClassification, StableCitation

HYBRID_RANKING_VERSION = "flowpilot.hybrid-ranking.m10.v1"
DEFAULT_VECTOR_WEIGHT = 0.7
DEFAULT_KEYWORD_WEIGHT = 0.3
DEFAULT_MINIMUM_SCORE = 0.35


@dataclass(frozen=True, slots=True)
class HybridRankingPolicy:
    version: str = HYBRID_RANKING_VERSION
    vector_weight: float = DEFAULT_VECTOR_WEIGHT
    keyword_weight: float = DEFAULT_KEYWORD_WEIGHT
    minimum_score: float = DEFAULT_MINIMUM_SCORE

    def __post_init__(self) -> None:
        if self.version != HYBRID_RANKING_VERSION:
            raise ValueError("retrieval ranking version is not supported")
        values = (self.vector_weight, self.keyword_weight, self.minimum_score)
        if any(not math.isfinite(value) for value in values):
            raise ValueError("retrieval ranking policy contains a non-finite value")
        if self.vector_weight < 0 or self.keyword_weight < 0:
            raise ValueError("retrieval ranking weights must not be negative")
        if not math.isclose(
            self.vector_weight + self.keyword_weight,
            1.0,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise ValueError("retrieval ranking weights must sum to one")
        if not 0.0 <= self.minimum_score <= 1.0:
            raise ValueError("retrieval minimum score is outside the supported range")


@dataclass(frozen=True, slots=True)
class RetrievalRequest:
    """Trusted retrieval input. Query text is deliberately excluded from repr."""

    context: KnowledgeRequestContext
    principals: tuple[AclPrincipal, ...]
    query_text: str = field(repr=False)
    observed_at: datetime
    candidate_limit: int = 50
    result_limit: int = 10

    def __post_init__(self) -> None:
        if not isinstance(self.context, KnowledgeRequestContext):
            raise ValueError("retrieval context is invalid")
        if not isinstance(self.principals, tuple) or any(
            not isinstance(item, AclPrincipal) for item in self.principals
        ):
            raise ValueError("retrieval principals are invalid")
        if len(self.principals) != len(set(self.principals)):
            raise ValueError("retrieval principals must be unique")
        object.__setattr__(self, "principals", tuple(sorted(self.principals)))
        if not isinstance(self.query_text, str) or not self.query_text.strip():
            raise ValueError("retrieval query must not be empty")
        if len(self.query_text.encode("utf-8")) > 16 * 1024:
            raise ValueError("retrieval query exceeds the supported size")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("retrieval observed_at must be timezone-aware")
        object.__setattr__(self, "observed_at", self.observed_at.astimezone(UTC))
        if not 1 <= self.candidate_limit <= 100:
            raise ValueError("retrieval candidate limit is invalid")
        if not 1 <= self.result_limit <= self.candidate_limit:
            raise ValueError("retrieval result limit is invalid")


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    citation: StableCitation
    content_ref: str
    data_classification: DataClassification
    score: float
    vector_score: float
    keyword_score: float
    ranking_version: str
    score_input_version: str


@dataclass(frozen=True, slots=True)
class RetrievalDiagnostics:
    ranking_version: str
    score_input_version: str
    embedding_model: str
    embedding_version: str
    candidate_count: int
    deduplicated_count: int
    threshold_eligible_count: int
    verified_count: int

    def safe_mapping(self) -> dict[str, str | int]:
        return {
            "ranking_version": self.ranking_version,
            "score_input_version": self.score_input_version,
            "embedding_model": self.embedding_model,
            "embedding_version": self.embedding_version,
            "candidate_count": self.candidate_count,
            "deduplicated_count": self.deduplicated_count,
            "threshold_eligible_count": self.threshold_eligible_count,
            "verified_count": self.verified_count,
        }


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    hits: tuple[RetrievalHit, ...]
    diagnostics: RetrievalDiagnostics
