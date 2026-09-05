"""Strict JSON contracts for the public HTTP data plane.

This module belongs to the optional ``api`` dependency surface.  Domain
validation remains authoritative after a request DTO is converted into a
``ResolutionRequest``; the DTO prevents JSON coercion and shape ambiguity from
reaching that boundary.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from pydantic.json_schema import SkipJsonSchema

from .models import (
    CandidateOrigin,
    FactorKind,
    FactorSourceType,
    FactorSubjectType,
    FollowUp,
    ResolutionStatus,
    ResolutionType,
    ResultTier,
    SourceQualityStatus,
)
from .serialization import to_jsonable

NonEmptyText = Annotated[
    str,
    StringConstraints(strict=True, strip_whitespace=True, min_length=1),
]
PositiveFiniteFloat = Annotated[
    float,
    Field(strict=True, gt=0, allow_inf_nan=False),
]
StrictYear = Annotated[int, Field(strict=True, gt=0, lt=3000)]
StrictTopK = Annotated[int, Field(strict=True, ge=1, le=50)]
OptionalNonEmptyText = NonEmptyText | SkipJsonSchema[None]
OptionalStrictYear = StrictYear | SkipJsonSchema[None]


class _StrictRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True)


class UnitConversionEvidenceDTO(_StrictRequestModel):
    evidence_id: NonEmptyText
    version: NonEmptyText
    source_canonical_unit: NonEmptyText
    target_canonical_unit: NonEmptyText
    multiplier: PositiveFiniteFloat


class ResolutionRequestDTO(_StrictRequestModel):
    """Production HTTP request; debug-only controls are intentionally absent."""

    material_name: NonEmptyText
    quantity: PositiveFiniteFloat
    quantity_unit: NonEmptyText = "kg"
    geography: OptionalNonEmptyText = None
    year: OptionalStrictYear = None
    product_form: OptionalNonEmptyText = None
    composition: OptionalNonEmptyText = None
    production_process: OptionalNonEmptyText = None
    subject_type: FactorSubjectType = FactorSubjectType.UNKNOWN
    boundary: NonEmptyText = "cradle-to-gate"
    target_factor_unit: OptionalNonEmptyText = None
    unit_conversion_evidence: UnitConversionEvidenceDTO | SkipJsonSchema[None] = None
    top_k: StrictTopK = 3
    request_id: OptionalNonEmptyText = None

    @model_validator(mode="before")
    @classmethod
    def reject_explicit_null_fields(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            null_fields = sorted(str(key) for key, item in value.items() if item is None)
            if null_fields:
                raise ValueError(
                    "explicit null is not allowed; omit optional fields instead: "
                    + ", ".join(null_fields)
                )
        return value

    def to_domain_mapping(self) -> dict[str, object]:
        """Return the explicitly admitted fields for independent domain validation."""

        return self.model_dump(mode="python", exclude_none=True)


class PublicErrorDetailDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reason_code: str
    message: str


class PublicErrorEnvelopeDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    api_version: str
    request_id: str
    correlation_id: str
    error: PublicErrorDetailDTO
    # Compatibility alias retained for API v1 clients.
    detail: PublicErrorDetailDTO


class PublicReadinessErrorEnvelopeDTO(PublicErrorEnvelopeDTO):
    """Closed 503 contract with the bounded readiness counters returned at runtime."""

    required_total: int
    required_unavailable: int
    optional_unavailable: int


class PublicSourceEvidenceDTO(BaseModel):
    """Public evidence summary; locators and arbitrary source metadata are excluded."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str
    source_type: FactorSourceType
    provider: str
    material_name: str
    factor_kind: FactorKind
    subject_type: FactorSubjectType
    geography: str | None = None
    year: int | None = None
    boundary: str | None = None
    boundary_modules: tuple[str, ...] = ()
    indicator: str | None = None
    declared_product: str | None = None
    source_quality_status: SourceQualityStatus
    admission_eligible: bool
    citation: str = ""
    excerpt: str = ""
    source_document_sha256: str | None = None
    page: str | None = None
    table: str | None = None
    row: str | None = None
    content_sha256: str


class PublicCandidateDTO(BaseModel):
    """Selectable or reference-only candidate summary for external review."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str
    origin: CandidateOrigin
    factor_value: float
    factor_unit: str
    score: float
    resolution_type: ResolutionType
    result_tier: ResultTier
    reasons: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    evidence_coverage: float
    evidence_gaps: tuple[str, ...] = ()
    proxy_material: str | None = None
    proxy_class: str | None = None
    source: PublicSourceEvidenceDTO
    content_sha256: str


class PublicConfidenceDTO(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    value: float
    level: str
    top_score: float
    score_margin: float
    evidence_coverage: float
    rationale: tuple[str, ...] = ()


class PublicRecommendationDTO(BaseModel):
    """Whitelist-only recommendation returned by production resolve/read/replay."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    status: ResolutionStatus
    follow_up: FollowUp | None = None
    message: str = ""
    confidence: PublicConfidenceDTO | None = None
    resolution_strength: PublicConfidenceDTO | None = None
    candidates: tuple[PublicCandidateDTO, ...] = ()
    reviewable_candidates: tuple[PublicCandidateDTO, ...] = ()
    questions: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    content_sha256: str | None = None


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _text(value: Any) -> str:
    converted = to_jsonable(value)
    return "" if converted is None else str(converted)


def _optional_text(value: Any) -> str | None:
    converted = to_jsonable(value)
    return None if converted is None else str(converted)


def _text_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, Sequence):
        raise TypeError("public sequence field must be a sequence")
    return tuple(_text(item) for item in value)


def _source_evidence(source: Any) -> PublicSourceEvidenceDTO:
    return PublicSourceEvidenceDTO(
        source_id=_text(_field(source, "source_id")),
        source_type=_field(source, "source_type"),
        provider=_text(_field(source, "provider")),
        material_name=_text(_field(source, "material_name")),
        factor_kind=_field(source, "factor_kind"),
        subject_type=_field(source, "subject_type"),
        geography=_optional_text(_field(source, "geography")),
        year=_field(source, "year"),
        boundary=_optional_text(_field(source, "boundary")),
        boundary_modules=_text_tuple(_field(source, "boundary_modules", ())),
        indicator=_optional_text(_field(source, "indicator")),
        declared_product=_optional_text(_field(source, "declared_product")),
        source_quality_status=_field(source, "source_quality_status"),
        admission_eligible=_field(source, "admission_eligible"),
        citation=_text(_field(source, "citation", "")),
        excerpt=_text(_field(source, "excerpt", "")),
        source_document_sha256=_optional_text(_field(source, "source_document_sha256")),
        page=_field(source, "page"),
        table=_optional_text(_field(source, "table")),
        row=_optional_text(_field(source, "row")),
        content_sha256=_text(_field(source, "content_sha256")),
    )


def _candidate(candidate: Any) -> PublicCandidateDTO:
    return PublicCandidateDTO(
        candidate_id=_text(_field(candidate, "candidate_id")),
        origin=_field(candidate, "origin"),
        factor_value=_field(candidate, "factor_value"),
        factor_unit=_text(_field(candidate, "factor_unit")),
        score=_field(candidate, "score"),
        resolution_type=_field(candidate, "resolution_type"),
        result_tier=_field(candidate, "result_tier"),
        reasons=_text_tuple(_field(candidate, "reasons", ())),
        limitations=_text_tuple(_field(candidate, "limitations", ())),
        assumptions=_text_tuple(_field(candidate, "assumptions", ())),
        warnings=_text_tuple(_field(candidate, "warnings", ())),
        evidence_coverage=_field(candidate, "evidence_coverage"),
        evidence_gaps=_text_tuple(_field(candidate, "evidence_gaps", ())),
        proxy_material=_optional_text(_field(candidate, "proxy_material")),
        proxy_class=_optional_text(_field(candidate, "proxy_class")),
        source=_source_evidence(_field(candidate, "source")),
        content_sha256=_text(_field(candidate, "content_sha256")),
    )


def _confidence(value: Any) -> PublicConfidenceDTO | None:
    if value is None:
        return None
    return PublicConfidenceDTO(
        value=_field(value, "value"),
        level=_text(_field(value, "level")),
        top_score=_field(value, "top_score"),
        score_margin=_field(value, "score_margin"),
        evidence_coverage=_field(value, "evidence_coverage"),
        rationale=_text_tuple(_field(value, "rationale", ())),
    )


def public_recommendation_dto(
    recommendation: Any,
    *,
    request_id: str | None = None,
) -> PublicRecommendationDTO:
    """Construct the public response from an allowlist, never a recursive domain dump."""

    public_request_id = request_id or _text(_field(recommendation, "request_id"))
    return PublicRecommendationDTO(
        request_id=public_request_id,
        status=_field(recommendation, "status"),
        follow_up=_field(recommendation, "follow_up"),
        message=_text(_field(recommendation, "message", "")),
        confidence=_confidence(_field(recommendation, "confidence")),
        resolution_strength=_confidence(_field(recommendation, "resolution_strength")),
        candidates=tuple(_candidate(item) for item in _field(recommendation, "candidates", ())),
        reviewable_candidates=tuple(
            _candidate(item) for item in _field(recommendation, "reviewable_candidates", ())
        ),
        questions=_text_tuple(_field(recommendation, "questions", ())),
        reason_codes=_text_tuple(_field(recommendation, "reason_codes", ())),
        content_sha256=_optional_text(_field(recommendation, "content_sha256")),
    )


__all__ = [
    "PublicErrorEnvelopeDTO",
    "PublicReadinessErrorEnvelopeDTO",
    "PublicRecommendationDTO",
    "ResolutionRequestDTO",
    "UnitConversionEvidenceDTO",
    "public_recommendation_dto",
]
