"""Framework-independent typed graph runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Generic, TypeVar

from .models import (
    AccountingAssignment,
    AuditEvent,
    Candidate,
    CandidateAdmission,
    CandidateExclusion,
    CandidateQualification,
    DerivedFactorCandidate,
    GapType,
    LinkAttempt,
    MaterialClass,
    NormalizedActivity,
    ParameterEvidence,
    PipelineFunnel,
    ProvisionalOption,
    QualificationDiagnostic,
    RecallObservation,
    Recommendation,
    RecordConversionDiagnostic,
    ReferenceFlowRecord,
    RequestGap,
    RequestResolutionPlan,
    ResolutionGap,
    ResolutionPlan,
    ResolutionRequest,
    ResolutionTrace,
    ResolutionType,
    ResultTier,
    RetrievalDiagnostic,
    SemanticIndexAnchor,
    SourceRecord,
    TransformationStep,
    resolution_request_fingerprint,
)


def candidate_hard_rejection_reasons(candidate: Candidate) -> tuple[str, ...]:
    """Return candidate-local reasons that can never be overridden by approval."""

    reasons: list[str] = []
    if candidate.resolution_type == ResolutionType.UNADJUSTED_PROCESS_PROXY or any(
        gap.gap_type == GapType.PROCESS_VARIANT for gap in candidate.gaps
    ):
        reasons.append("unresolved_process_variant_requires_process_model")
    return tuple(dict.fromkeys(reasons))


def candidate_rejection_reasons(candidate: Candidate, state: "GraphState") -> tuple[str, ...]:
    """Return hard blocks plus soft review gates for ordinary recommendation."""

    reasons = list(candidate_hard_rejection_reasons(candidate))
    if candidate.result_tier == ResultTier.REFERENCE_ONLY:
        reasons.append("reference_only_candidate_requires_explicit_review")
    return tuple(dict.fromkeys(reasons))


def candidate_is_sufficient(candidate: Candidate, state: "GraphState") -> bool:
    """Shared hard eligibility gate used by routers and Top-K status."""
    return not candidate_rejection_reasons(candidate, state)


class Stage(str, Enum):
    INPUT = "input"
    VALIDATE = "validate"
    NORMALIZE = "normalize"
    LOCAL_RETRIEVAL = "local_retrieval"
    LOCAL_EVALUATE = "local_evaluate"
    EXTERNAL_DISCOVERY = "external_discovery"
    EXTERNAL_FETCH = "external_fetch"
    EVIDENCE_EXTRACTION = "evidence_extraction"
    EXTERNAL_QUALIFICATION = "external_qualification"
    EXTERNAL_CANDIDATE = "external_candidate"
    GAP_ANALYSIS = "gap_analysis"
    RESOLUTION_PLANNER = "resolution_planner"
    UNIT_SCALE_RESOLUTION = "unit_scale_resolution"
    REFERENCE_FLOW_RESOLUTION = "reference_flow_resolution"
    PROCESS_VARIANT_RESOLUTION = "process_variant_resolution"
    GRADE_COMPOSITION_RESOLUTION = "grade_composition_resolution"
    MATERIAL_RESOLUTION = "material_resolution"
    PROXY_RESOLUTION = "proxy_resolution"
    PROXY_EVALUATE = "proxy_evaluate"
    RE_EVALUATE = "re_evaluate"
    CANDIDATE_POOL = "candidate_pool"
    RANK = "rank"
    TOP_K = "top_k"
    TERMINAL = "terminal"


@dataclass(slots=True)
class GraphState:
    request: ResolutionRequest
    stage: Stage = Stage.INPUT
    normalized: NormalizedActivity | None = None
    material_class: MaterialClass | None = None
    local_records: tuple[SourceRecord, ...] = ()
    raw_related_hits: tuple[SourceRecord, ...] = ()
    recall_observations: tuple[RecallObservation, ...] = ()
    qualifications: tuple[CandidateQualification, ...] = ()
    qualification_diagnostics: tuple[QualificationDiagnostic, ...] = ()
    candidate_admissions: tuple[CandidateAdmission, ...] = ()
    request_gaps: tuple[RequestGap, ...] = ()
    provisional_options: tuple[ProvisionalOption, ...] = ()
    request_resolution_plan: RequestResolutionPlan | None = None
    proxy_records: tuple[SourceRecord, ...] = ()
    external_records: tuple[SourceRecord, ...] = ()
    local_candidates: tuple[Candidate, ...] = ()
    proxy_candidates: tuple[Candidate, ...] = ()
    external_candidates: tuple[Candidate, ...] = ()
    resolution_candidates: tuple[Candidate, ...] = ()
    gaps: dict[str, tuple[ResolutionGap, ...]] = field(default_factory=dict)
    resolution_plans: dict[str, ResolutionPlan] = field(default_factory=dict)
    reference_flow_records: tuple[ReferenceFlowRecord, ...] = ()
    parameter_evidence: list[ParameterEvidence] = field(default_factory=list)
    accounting_assignments: list[AccountingAssignment] = field(default_factory=list)
    transformation_steps: list[TransformationStep] = field(default_factory=list)
    derived_candidates: list[DerivedFactorCandidate] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    required_fields: tuple[str, ...] = ()
    excluded_candidates: list[CandidateExclusion] = field(default_factory=list)
    candidate_pool: tuple[Candidate, ...] = ()
    ranked_candidates: tuple[Candidate, ...] = ()
    link_attempts: list[LinkAttempt] = field(default_factory=list)
    semantic_index_anchor: SemanticIndexAnchor | None = None
    retrieval_diagnostics: tuple[RetrievalDiagnostic, ...] = ()
    conversion_diagnostics: tuple[RecordConversionDiagnostic, ...] = ()
    pipeline_funnel: PipelineFunnel = field(default_factory=PipelineFunnel)
    recommendation: Recommendation | None = None
    events: list[AuditEvent] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    trace: ResolutionTrace = field(init=False)

    def __post_init__(self) -> None:
        raw_fingerprint = resolution_request_fingerprint(self.request)
        self.trace = ResolutionTrace(
            trace_id=f"trace:{self.request.request_id}",
            request_id=self.request.request_id,
            request_fingerprint=raw_fingerprint,
            raw_request_fingerprint=raw_fingerprint,
        )

    def event(self, stage: Stage, message: str, details: dict | None = None) -> None:
        self.events.append(AuditEvent(stage=stage.value, message=message))
        self.trace.append(stage.value, message, details)


StateT = TypeVar("StateT")


class Node(Generic[StateT]):
    name: str = "node"

    async def run(self, state: StateT) -> StateT:
        raise NotImplementedError


class Router:
    """Bounded routing policy; each insufficiency branch is visited once."""

    @staticmethod
    def after_proxy(state: GraphState) -> Stage:
        return Stage.CANDIDATE_POOL
