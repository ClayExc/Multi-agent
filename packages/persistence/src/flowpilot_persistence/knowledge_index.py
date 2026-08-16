from __future__ import annotations

# ruff: noqa: E501
import hashlib
import math
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from flowpilot_domain import AclPrincipal, DataClassification

from .postgres import _TenantTransaction

EMBEDDING_DIMENSION = 384
EMBEDDING_MODEL = "flowpilot-hash-embedding"
EMBEDDING_VERSION = "m10.v1"
SCORE_INPUT_VERSION = "flowpilot-hybrid-score-input.m10.v1"
_TOKEN = re.compile(r"\w+", re.UNICODE)


class DeterministicEmbeddingPort(Protocol):
    model: str
    version: str
    dimension: int

    async def embed(self, text: str) -> tuple[float, ...]: ...


class HashEmbeddingAdapter:
    """Local deterministic feature hashing; never retains or emits input text."""

    model = EMBEDDING_MODEL
    version = EMBEDDING_VERSION
    dimension = EMBEDDING_DIMENSION

    async def embed(self, text: str) -> tuple[float, ...]:
        values = [0.0] * self.dimension
        for token in _TOKEN.findall(text.casefold()):
            digest = hashlib.sha256(token.encode()).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimension
            values[bucket] += -1.0 if digest[4] & 1 else 1.0
        norm = math.sqrt(sum(value * value for value in values))
        if norm == 0:
            return tuple(values)
        return tuple(value / norm for value in values)


@dataclass(frozen=True, slots=True)
class KnowledgeCandidateQuery:
    tenant_id: str
    purpose: str
    principals: tuple[AclPrincipal, ...]
    classification_ceiling: DataClassification
    query_text: str
    query_vector: tuple[float, ...]
    observed_at: datetime
    limit: int = 20

    def __post_init__(self) -> None:
        if len(self.query_vector) != EMBEDDING_DIMENSION:
            raise ValueError("knowledge query vector dimension is invalid")
        if not 1 <= self.limit <= 100:
            raise ValueError("knowledge candidate limit is invalid")


@dataclass(frozen=True, slots=True)
class KnowledgeCandidate:
    tenant_id: str
    document_id: str
    document_version: int
    section_id: str
    content_ref: str
    content_hash: str
    data_classification: DataClassification
    vector_distance: float
    keyword_rank: float
    score_input_version: str = SCORE_INPUT_VERSION

    @property
    def stable_sort_key(self) -> tuple[str, int, str]:
        return self.document_id, self.document_version, self.section_id


def _vector_literal(vector: tuple[float, ...]) -> str:
    if len(vector) != EMBEDDING_DIMENSION or any(not math.isfinite(v) for v in vector):
        raise ValueError("embedding vector is invalid")
    return "[" + ",".join(format(value, ".9g") for value in vector) + "]"


class PostgresKnowledgeIndexer:
    def __init__(self, transaction: _TenantTransaction) -> None:
        self._transaction = transaction

    async def index_next(
        self, tenant_id: str, embedding: DeterministicEmbeddingPort
    ) -> bool:
        await self._transaction.bind(tenant_id)
        if (
            embedding.dimension != EMBEDDING_DIMENSION
            or embedding.model != EMBEDDING_MODEL
            or embedding.version != EMBEDDING_VERSION
        ):
            raise ValueError("embedding adapter version is not supported")
        row = await self._transaction.connection.fetch_one(
            """SELECT j.job_id,j.document_id,j.document_version,j.document_revision,
                      j.content_hash,j.operation,b.content_body,v.content_ref
               FROM flowpilot.knowledge_index_jobs j
               LEFT JOIN flowpilot.knowledge_content_bodies b
                 ON (b.tenant_id,b.document_id,b.document_version)=
                    (j.tenant_id,j.document_id,j.document_version)
               JOIN flowpilot.knowledge_document_versions v
                 ON (v.tenant_id,v.document_id,v.document_version)=
                    (j.tenant_id,j.document_id,j.document_version)
               WHERE j.tenant_id=%(tenant_id)s AND j.index_state IN ('pending','stale')
               ORDER BY j.requested_at,j.job_id FOR UPDATE OF j SKIP LOCKED LIMIT 1""",
            {"tenant_id": tenant_id},
        )
        if row is None:
            return False
        if row["operation"] == "remove":
            await self._transaction.connection.execute(
                """DELETE FROM flowpilot.knowledge_sections
                   WHERE tenant_id=%(tenant_id)s AND document_id=%(document_id)s""",
                {"tenant_id": tenant_id, "document_id": row["document_id"]},
            )
            state = "removed"
        else:
            body = row.get("content_body")
            if not isinstance(body, str) or not body:
                await self._mark_failed(
                    tenant_id, str(row["job_id"]), "CONTENT_UNAVAILABLE"
                )
                return True
            vector = await embedding.embed(body)
            affected = await self._transaction.connection.execute(
                """INSERT INTO flowpilot.knowledge_sections
                   (tenant_id,document_id,document_version,section_id,section_ordinal,
                    content_ref,content_hash,safe_metadata,search_vector,embedding,
                    embedding_model,embedding_version)
                   VALUES (%(tenant_id)s,%(document_id)s,%(document_version)s,'root',0,
                           %(content_ref)s,%(content_hash)s,'{}'::jsonb,
                           to_tsvector('simple',%(body)s),%(embedding)s::flowpilot.vector,
                           %(model)s,%(version)s)
                   ON CONFLICT (tenant_id,document_id,document_version,section_id)
                   DO UPDATE SET search_vector=EXCLUDED.search_vector,
                     embedding=EXCLUDED.embedding,embedding_model=EXCLUDED.embedding_model,
                     embedding_version=EXCLUDED.embedding_version
                   WHERE flowpilot.knowledge_sections.content_hash=EXCLUDED.content_hash""",
                {
                    "tenant_id": tenant_id,
                    "document_id": row["document_id"],
                    "document_version": row["document_version"],
                    "content_ref": row["content_ref"],
                    "content_hash": row["content_hash"],
                    "body": body,
                    "embedding": _vector_literal(vector),
                    "model": embedding.model,
                    "version": embedding.version,
                },
            )
            if affected != 1:
                await self._mark_failed(
                    tenant_id, str(row["job_id"]), "INDEX_CONTENT_CONFLICT"
                )
                return True
            state = "ready"
        await self._transaction.connection.execute(
            """UPDATE flowpilot.knowledge_index_jobs SET index_state=%(state)s,
                      indexed_at=transaction_timestamp(),failure_code=NULL
               WHERE tenant_id=%(tenant_id)s AND job_id=%(job_id)s""",
            {"tenant_id": tenant_id, "job_id": row["job_id"], "state": state},
        )
        return True

    async def _mark_failed(self, tenant_id: str, job_id: str, code: str) -> None:
        await self._transaction.connection.execute(
            """UPDATE flowpilot.knowledge_index_jobs SET index_state='failed',
                      failure_code=%(code)s,indexed_at=transaction_timestamp()
               WHERE tenant_id=%(tenant_id)s AND job_id=%(job_id)s""",
            {"tenant_id": tenant_id, "job_id": job_id, "code": code},
        )

    async def mark_all_stale(self, tenant_id: str) -> int:
        """Schedule a PostgreSQL-fact rebuild without mutating document facts."""
        await self._transaction.bind(tenant_id)
        return await self._transaction.connection.execute(
            """UPDATE flowpilot.knowledge_index_jobs
               SET index_state='stale',indexed_at=NULL
               WHERE tenant_id=%(tenant_id)s AND index_state IN ('ready','failed')""",
            {"tenant_id": tenant_id},
        )


class PostgresKnowledgeCandidateRepository:
    def __init__(self, transaction: _TenantTransaction) -> None:
        self._transaction = transaction

    async def candidates(
        self, query: KnowledgeCandidateQuery
    ) -> tuple[KnowledgeCandidate, ...]:
        await self._transaction.bind(query.tenant_id)
        principal_bindings = [
            f"{principal.principal_type.value}:{principal.principal_id}"
            for principal in query.principals
        ]
        rows = await self._transaction.connection.fetch_all(
            """SELECT s.tenant_id,s.document_id,s.document_version,s.section_id,
                      s.content_ref,s.content_hash,v.data_classification,
                      (s.embedding OPERATOR(flowpilot.<=>)
                       %(vector)s::flowpilot.vector) AS vector_distance,
                      ts_rank_cd(s.search_vector,plainto_tsquery('simple',%(query)s)) AS keyword_rank
               FROM flowpilot.knowledge_sections s
               JOIN flowpilot.knowledge_document_versions v
                 ON (v.tenant_id,v.document_id,v.document_version)=
                    (s.tenant_id,s.document_id,s.document_version)
               JOIN flowpilot.knowledge_documents d
                 ON (d.tenant_id,d.document_id)=(s.tenant_id,s.document_id)
               WHERE s.tenant_id=%(tenant_id)s AND d.lifecycle='active'
                 AND v.effective_at<=%(observed_at)s
                 AND (v.expires_at IS NULL OR v.expires_at>%(observed_at)s)
                 AND v.acl->'allowed_purposes' ? %(purpose)s
                 AND ((v.acl->>'tenant_wide')::boolean OR EXISTS(
                     SELECT 1 FROM jsonb_array_elements(v.acl->'principals') p
                     WHERE concat(p->>'principal_type',':',p->>'principal_id')=ANY(%(principals)s)))
                 AND CASE v.data_classification WHEN 'public' THEN 0 WHEN 'internal' THEN 1
                     WHEN 'confidential' THEN 2 WHEN 'restricted' THEN 3 ELSE 99 END
                     <=%(classification_rank)s
                 AND s.embedding_model=%(model)s AND s.embedding_version=%(version)s
               ORDER BY vector_distance ASC,keyword_rank DESC,
                        s.document_id,s.document_version,s.section_id LIMIT %(limit)s""",
            {
                "tenant_id": query.tenant_id,
                "vector": _vector_literal(query.query_vector),
                "query": query.query_text,
                "observed_at": query.observed_at,
                "purpose": query.purpose,
                "principals": principal_bindings,
                "classification_rank": {
                    DataClassification.PUBLIC: 0,
                    DataClassification.INTERNAL: 1,
                    DataClassification.CONFIDENTIAL: 2,
                    DataClassification.RESTRICTED: 3,
                }[query.classification_ceiling],
                "model": EMBEDDING_MODEL,
                "version": EMBEDDING_VERSION,
                "limit": query.limit,
            },
        )
        return tuple(
            KnowledgeCandidate(
                tenant_id=str(row["tenant_id"]),
                document_id=str(row["document_id"]),
                document_version=int(row["document_version"]),
                section_id=str(row["section_id"]),
                content_ref=str(row["content_ref"]),
                content_hash=str(row["content_hash"]),
                data_classification=DataClassification(str(row["data_classification"])),
                vector_distance=float(row["vector_distance"]),
                keyword_rank=float(row["keyword_rank"]),
            )
            for row in rows
        )
