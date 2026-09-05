"""Async ports used by the graph.  Real database/API adapters can be added later."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

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


class ExternalSourceConnectorPort(Protocol):
    async def discover(self, intent: RetrievalIntent) -> Sequence[Mapping[str, Any]]: ...

    def health(self) -> Mapping[str, Any]: ...


class ExternalDocumentFetchPort(Protocol):
    async def fetch(self, reference: Mapping[str, Any]) -> Mapping[str, Any]: ...


class FactorEvidenceExtractorPort(Protocol):
    async def extract(
        self, document: Mapping[str, Any], intent: RetrievalIntent
    ) -> Sequence[SourceRecord]: ...


class ExternalCachePort(Protocol):
    async def get(self, key: str) -> Mapping[str, Any] | None: ...

    async def put(self, key: str, value: Mapping[str, Any]) -> None: ...


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

    async def save_approval(
        self,
        approval: ApprovalRecord,
        trace: ResolutionTrace,
        *,
        expected_recommendation_sha256: str,
        expected_trace_revision: int,
    ) -> ApprovalRecord: ...

    async def get_approval(self, request_id: str, candidate_id: str) -> ApprovalRecord | None: ...

    async def save_locked(
        self,
        locked: LockedResolution,
        trace: ResolutionTrace,
        *,
        expected_recommendation_sha256: str,
        expected_trace_revision: int,
    ) -> LockedResolution: ...

    async def get_locked(self, request_id: str) -> LockedResolution | None: ...
