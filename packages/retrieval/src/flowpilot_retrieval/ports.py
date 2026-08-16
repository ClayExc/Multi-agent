from __future__ import annotations

from typing import Protocol

from flowpilot_application import KnowledgeCitationResolution, KnowledgeRequestContext
from flowpilot_domain import DataClassification, StableCitation
from flowpilot_persistence import KnowledgeCandidate, KnowledgeCandidateQuery


class KnowledgeCandidatePort(Protocol):
    async def candidates(
        self, query: KnowledgeCandidateQuery
    ) -> tuple[KnowledgeCandidate, ...]: ...


class KnowledgeCitationVerificationPort(Protocol):
    async def resolve_citation(
        self,
        context: KnowledgeRequestContext,
        citation: StableCitation,
        *,
        action_classification_ceiling: DataClassification,
    ) -> KnowledgeCitationResolution: ...
