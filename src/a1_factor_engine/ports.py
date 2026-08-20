"""Async ports used by the graph.  Real database/API adapters can be added later."""

from __future__ import annotations

from typing import Protocol, Sequence

from .models import (
    ApprovalRecord,
    LockedResolution,
    MaterialClass,
    MaterialInterpretation,
    NormalizedActivity,
    ParameterEvidence,
    Recommendation,
    ReferenceFlowRecord,
    ResolutionRequest,
    ResolutionTrace,
    RetrievalIntent,
    RetrievalResult,
    SemanticAssessment,
    SourceRecord,
)


class MaterialUnderstandingPort(Protocol):
    async def interpret(self, request: ResolutionRequest) -> MaterialInterpretation: ...

    async def classify(self, activity: NormalizedActivity) -> MaterialClass: ...

    async def assess_candidate(
        self,
        activity: NormalizedActivity,
        source: SourceRecord,
        origin: str,
        material_class: MaterialClass | None = None,
    ) -> SemanticAssessment: ...


class FactorRepositoryPort(Protocol):
    async def search(self, intent: RetrievalIntent) -> RetrievalResult: ...


class ProxyRepositoryPort(Protocol):
    async def search(
        self, activity: NormalizedActivity, material_class: MaterialClass
    ) -> Sequence[SourceRecord]: ...


class ReferenceFlowRepositoryPort(Protocol):
    async def search(self, activity: NormalizedActivity) -> Sequence[ReferenceFlowRecord]: ...


class ProcessParameterRepositoryPort(Protocol):
    async def search(
        self, activity: NormalizedActivity, reference: SourceRecord
    ) -> Sequence[ParameterEvidence]: ...


class GradeSeriesRepositoryPort(Protocol):
    async def search(
        self, activity: NormalizedActivity, reference: SourceRecord
    ) -> Sequence[SourceRecord]: ...


class ResolutionStorePort(Protocol):
    async def has_resolution_run(self, request_id: str) -> bool: ...

    async def save_resolution_run(
        self, recommendation: Recommendation, trace: ResolutionTrace
    ) -> None: ...

    async def get_recommendation(self, request_id: str) -> Recommendation | None: ...

    async def save_trace(self, trace: ResolutionTrace) -> None: ...

    async def get_trace(self, request_id: str) -> ResolutionTrace | None: ...

    async def save_approval(self, approval: ApprovalRecord) -> None: ...

    async def get_approval(self, request_id: str, candidate_id: str) -> ApprovalRecord | None: ...

    async def save_locked(self, locked: LockedResolution) -> None: ...

    async def get_locked(self, request_id: str) -> LockedResolution | None: ...
