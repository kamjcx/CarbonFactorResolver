"""A1 Factor Resolution Engine orchestration and approval workflow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from .adapters import (
    DeterministicMaterialUnderstanding,
    InMemoryResolutionStore,
    NullFactorRepository,
    NullGradeSeriesRepository,
    NullProcessParameterRepository,
    NullProxyRepository,
    NullReferenceFlowRepository,
)
from .derived_factor import expected_total_emissions
from .graph import GraphState, Router, Stage, candidate_hard_rejection_reasons
from .material_registry import (
    DEFAULT_MATERIAL_REGISTRY,
    MaterialRuleSuggestionPort,
    MaterialSemanticRegistryPort,
    NullMaterialRuleSuggestion,
)
from .models import (
    ApprovalMode,
    ApprovalRecord,
    ApprovalStatus,
    Candidate,
    CandidateOrigin,
    GapType,
    LockedResolution,
    Recommendation,
    RequestGap,
    RequestGapType,
    RequestResolutionPlan,
    ResolutionRequest,
    ResolutionStatus,
    ResolutionTrace,
    ResultTier,
    RouterType,
)
from .nodes import (
    CandidatePoolNode,
    GapAnalysisNode,
    GradeCompositionResolutionNode,
    LocalEvaluateNode,
    LocalRetrievalNode,
    MaterialResolutionNode,
    NormalizeNode,
    ProcessVariantResolutionNode,
    ProxyEvaluateNode,
    ProxyResolutionNode,
    RankNode,
    ReEvaluateNode,
    ReferenceFlowResolutionNode,
    ResolutionPlannerNode,
    TopKNode,
    UnitScaleResolutionNode,
    ValidateNode,
    evaluate_records,
)
from .ports import (
    ExternalSourceConnectorPort,
    FactorEvidenceExtractorPort,
    FactorRepositoryPort,
    GradeSeriesRepositoryPort,
    MaterialUnderstandingPort,
    ProcessParameterRepositoryPort,
    ProxyRepositoryPort,
    ReferenceFlowRepositoryPort,
    ResolutionStorePort,
)


@dataclass
class A1ResolutionGraph:
    """Explicit graph with typed state, nodes and bounded routers."""

    local_retrieval: FactorRepositoryPort
    proxy_retrieval: ProxyRepositoryPort
    understanding: MaterialUnderstandingPort
    reference_flows: ReferenceFlowRepositoryPort
    process_parameters: ProcessParameterRepositoryPort
    grade_series: GradeSeriesRepositoryPort
    material_registry: MaterialSemanticRegistryPort = DEFAULT_MATERIAL_REGISTRY
    rule_suggestions: MaterialRuleSuggestionPort = NullMaterialRuleSuggestion()
    external_connectors: Sequence[ExternalSourceConnectorPort] = ()
    external_extractor: FactorEvidenceExtractorPort | None = None

    def __post_init__(self) -> None:
        self.validate = ValidateNode()
        self.normalize = NormalizeNode(self.understanding, self.material_registry, self.rule_suggestions)
        self.local = LocalRetrievalNode(self.local_retrieval)
        self.local_evaluate = LocalEvaluateNode(self.understanding, self.material_registry)
        self.gap_analysis = GapAnalysisNode()
        self.planner = ResolutionPlannerNode()
        self.unit_scale = UnitScaleResolutionNode()
        self.reference_flow = ReferenceFlowResolutionNode(self.reference_flows)
        self.process_variant = ProcessVariantResolutionNode(self.process_parameters)
        self.grade_composition = GradeCompositionResolutionNode(self.grade_series, self.material_registry)
        self.material = MaterialResolutionNode(self.understanding)
        self.proxy = ProxyResolutionNode(self.proxy_retrieval)
        self.proxy_evaluate = ProxyEvaluateNode(self.understanding, self.material_registry)
        self.re_evaluate = ReEvaluateNode()
        self.pool = CandidatePoolNode()
        self.rank = RankNode()
        self.top_k = TopKNode()

    @staticmethod
    def _technical_order(candidate: Candidate) -> tuple[RouterType, ...]:
        aliases = {
            "process": RouterType.PROCESS_VARIANT,
            "grade": RouterType.GRADE_COMPOSITION,
        }
        preferred = tuple(
            aliases[item]
            for item in (
                part.strip().casefold()
                for part in candidate.source.metadata.get("resolution_order", "").split(",")
            )
            if item in aliases
        )
        return tuple(dict.fromkeys((*preferred, RouterType.PROCESS_VARIANT, RouterType.GRADE_COMPOSITION)))

    async def _resolve_current_candidates(self, state: GraphState) -> None:
        """Run each candidate's finite plan once, preserving declared Grade/Process dependencies."""

        await self.unit_scale.run(state)
        await self.reference_flow.run(state)
        resolved: list[Candidate] = []
        for candidate in state.resolution_candidates:
            state.resolution_candidates = (candidate,)
            for router in self._technical_order(candidate):
                if router == RouterType.PROCESS_VARIANT:
                    await self.process_variant.run(state)
                elif router == RouterType.GRADE_COMPOSITION:
                    await self.grade_composition.run(state)
            resolved.extend(state.resolution_candidates)
        state.resolution_candidates = tuple(resolved)

    async def _discover_external(self, state: GraphState) -> None:
        if not self.external_connectors or self.external_extractor is None or state.normalized is None:
            return
        intent = state.normalized.retrieval_intent
        if intent is None:
            return
        records = []
        for connector in self.external_connectors:
            try:
                references = await connector.discover(intent)
            except Exception as exc:
                state.event(Stage.EXTERNAL_DISCOVERY, "external connector discovery unavailable", {
                    "connector": type(connector).__name__,
                    "reference_count": 0,
                    "source_ids": (),
                    "reason_code": type(exc).__name__,
                })
                continue
            state.event(Stage.EXTERNAL_DISCOVERY, "external connector discovery completed", {
                "connector": type(connector).__name__, "reference_count": len(references),
                "source_ids": tuple(str(item.get("source_id", "")) for item in references),
            })
            fetch = getattr(connector, "fetch", None)
            if fetch is None:
                continue
            for reference in references:
                try:
                    document = await fetch(reference)
                    state.event(Stage.EXTERNAL_FETCH, "external evidence document fetched", {
                        "source_id": str(reference.get("source_id", "")),
                        "content_sha256": str(document.get("content_sha256", "")),
                    })
                    extracted = await self.external_extractor.extract(document, intent)
                    records.extend(extracted)
                except Exception as exc:
                    state.event(Stage.EXTERNAL_FETCH, "external evidence rejected", {
                        "source_id": str(reference.get("source_id", "")),
                        "reason_code": type(exc).__name__,
                    })
        state.external_records = tuple(records)
        state.event(Stage.EVIDENCE_EXTRACTION, "external evidence extraction completed", {
            "record_count": len(records),
            "source_ids": tuple(record.source_id for record in records),
        })
        if records:
            candidates, exclusions = await evaluate_records(
                state.normalized, records, CandidateOrigin.EXTERNAL,
                self.understanding, registry=self.material_registry,
            )
            state.external_candidates = candidates
            state.excluded_candidates.extend(exclusions)
            identity = state.normalized.identity_resolution
            if identity and identity.selected_product_entity_id is None:
                product_routes = {
                    "mat.product.primary_aluminium": "primary",
                    "mat.product.secondary_aluminium": "secondary",
                }
                process_routes = {
                    "primary aluminium production": "primary",
                    "secondary aluminium production": "secondary",
                }
                variants = tuple(dict.fromkeys(
                    product_routes.get(item.source.metadata.get("product_entity_id", ""))
                    or process_routes.get((item.source.production_process or "").casefold())
                    for item in candidates
                    if (
                        product_routes.get(item.source.metadata.get("product_entity_id", ""))
                        or process_routes.get((item.source.production_process or "").casefold())
                    )
                ))
                if len(variants) > 1 and not any(gap.field == "route" for gap in state.request_gaps):
                    route_gap = RequestGap(
                        gap_id=f"{state.request.request_id}:route",
                        gap_type=RequestGapType.INPUT_SPECIFICATION,
                        field="route",
                        reason=(
                            "the generic material identity has multiple product-route variants; "
                            "select a route before choosing a factor"
                        ),
                        required=True,
                        options=variants + ("unknown",),
                    )
                    state.request_gaps = tuple((*state.request_gaps, route_gap))
                    state.required_fields = tuple(dict.fromkeys((*state.required_fields, "route")))
                    state.request_resolution_plan = RequestResolutionPlan(
                        request_id=state.request.request_id,
                        gaps=state.request_gaps,
                        next_question=route_gap,
                        provisional_options=state.provisional_options,
                    )
            state.event(Stage.EXTERNAL_QUALIFICATION, "external records qualified", {
                "qualified_count": len(candidates),
                "excluded": tuple({"source_id": item.source_id, "reasons": item.reasons} for item in exclusions),
            })
            state.event(Stage.EXTERNAL_CANDIDATE, "external candidates entered existing resolution graph", {
                "candidate_ids": tuple(item.candidate_id for item in candidates),
            })

    async def run(self, request: ResolutionRequest) -> GraphState:
        state = GraphState(request=request)
        await self.validate.run(state)
        await self.normalize.run(state)
        if state.normalized is None:
            state.recommendation = Recommendation(
                request_id=request.request_id,
                status=ResolutionStatus.ERROR,
                message="input could not be normalized; correct the quantity or unit and retry",
                trace=state.trace,
            )
            state.stage = Stage.TERMINAL
            return state

        await self.local.run(state)
        await self.local_evaluate.run(state)
        if state.request_gaps:
            # Discovery is evidence, not selection. A broad request such as
            # generic aluminium must still show available route variants while
            # the terminal decision remains MORE_INPUT_NEEDED.
            await self._discover_external(state)
        if state.request_gaps and state.resolution_candidates:
            # A broad family request cannot silently choose a subtype record;
            # retain its raw/qualification evidence and ask the smallest
            # identity question first.
            state.resolution_candidates = ()
            state.local_candidates = ()
        if state.request_gaps and not state.resolution_candidates:
            state.required_fields = tuple(gap.field for gap in state.request_gaps)
            state.event(
                Stage.LOCAL_EVALUATE,
                "request specification is incomplete; returning more-input options before proxy resolution",
                {
                    "decision": "more_input",
                    "required_choice": {
                        "field": state.request_gaps[0].field,
                        "options": state.request_gaps[0].options,
                    },
                    "provisional_options": tuple({
                        "option_type": option.option_type,
                        "not_selected_because": option.not_selected_because,
                    } for option in state.provisional_options),
                },
            )
        await self.gap_analysis.run(state)
        await self.planner.run(state)

        if state.resolution_candidates:
            state.event(Stage.LOCAL_EVALUATE, "local candidates passed to solve-first resolution", {
                "decision": "resolve_local_gaps",
                "plans": tuple(plan.to_dict() for plan in state.resolution_plans.values()),
            })
            await self._resolve_current_candidates(state)
        elif not state.request_gaps:
            state.event(Stage.LOCAL_EVALUATE, "no local candidate recalled; no evaluable candidates after qualification; class-aware proxy is the final fallback", {
                "decision": "enter_proxy",
                "reason": "formal local and bounded related-candidate retrieval produced no evaluable candidates after record qualification",
            })

        if not state.resolution_candidates and not state.request_gaps:
            await self._discover_external(state)
            if state.external_candidates:
                state.resolution_candidates = state.external_candidates
                await self.gap_analysis.run(state)
                await self.planner.run(state)
                await self._resolve_current_candidates(state)

        needs_class_proxy = not state.required_fields and not state.external_candidates and (
            not state.resolution_candidates or any(
                any(gap.gap_type == GapType.MATERIAL_ABSENT for gap in candidate.gaps)
                for candidate in state.resolution_candidates
            )
        )
        if needs_class_proxy:
            # Material class is intentionally late, after same-material resolution.
            await self.material.run(state)
            await self.proxy.run(state)
            await self.proxy_evaluate.run(state)
            if state.proxy_candidates:
                local_resolved = state.resolution_candidates
                local_candidates = state.local_candidates
                state.resolution_candidates = state.proxy_candidates
                state.proxy_candidates = ()
                await self.gap_analysis.run(state)
                await self.planner.run(state)
                await self._resolve_current_candidates(state)
                state.proxy_candidates = state.resolution_candidates
                state.resolution_candidates = local_resolved
                state.local_candidates = local_candidates
        await self.re_evaluate.run(state)
        if Router.after_proxy(state) == Stage.CANDIDATE_POOL:
            await self.pool.run(state)
        await self.rank.run(state)
        await self.top_k.run(state)
        return state


class A1FactorResolutionEngine:
    """Public facade for resolution and human approval/locking."""

    def __init__(
        self,
        *,
        local_retrieval: FactorRepositoryPort | None = None,
        proxy_retrieval: ProxyRepositoryPort | None = None,
        understanding: MaterialUnderstandingPort | None = None,
        reference_flows: ReferenceFlowRepositoryPort | None = None,
        process_parameters: ProcessParameterRepositoryPort | None = None,
        grade_series: GradeSeriesRepositoryPort | None = None,
        material_registry: MaterialSemanticRegistryPort | None = None,
        rule_suggestions: MaterialRuleSuggestionPort | None = None,
        external_connectors: Sequence[ExternalSourceConnectorPort] = (),
        external_extractor: FactorEvidenceExtractorPort | None = None,
        store: ResolutionStorePort | None = None,
    ) -> None:
        self.store = store or InMemoryResolutionStore()
        self.graph = A1ResolutionGraph(
            local_retrieval or NullFactorRepository(),
            proxy_retrieval or NullProxyRepository(),
            understanding or DeterministicMaterialUnderstanding(),
            reference_flows or NullReferenceFlowRepository(),
            process_parameters or NullProcessParameterRepository(),
            grade_series or NullGradeSeriesRepository(),
            material_registry or DEFAULT_MATERIAL_REGISTRY,
            rule_suggestions or NullMaterialRuleSuggestion(),
            external_connectors,
            external_extractor,
        )

    async def resolve(self, request: ResolutionRequest | Mapping[str, object]) -> Recommendation:
        if isinstance(request, Mapping):
            request = ResolutionRequest.from_mapping(request)
        if await self.store.has_resolution_run(request.request_id):
            raise ValueError(f"duplicate request_id: {request.request_id}")
        state = await self.graph.run(request)
        assert state.recommendation is not None
        await self.store.save_resolution_run(state.recommendation, state.trace)
        return state.recommendation

    async def state(self, request_id: str) -> Recommendation | None:
        return await self.store.get_recommendation(request_id)

    async def trace(self, request_id: str) -> ResolutionTrace | None:
        return await self.store.get_trace(request_id)

    async def approve(
        self, request_id: str, candidate_id: str, reviewer: str, note: str = "",
        mode: ApprovalMode | str = ApprovalMode.STANDARD,
    ) -> ApprovalRecord:
        recommendation = await self.store.get_recommendation(request_id)
        if recommendation is None:
            raise KeyError(f"unknown request: {request_id}")
        if recommendation.status not in {
            ResolutionStatus.RECOMMENDATION_READY,
            ResolutionStatus.REFERENCE_REVIEW_REQUIRED,
        }:
            raise ValueError("only a recommendation-ready or reference-review resolution can be approved")
        mode = ApprovalMode(mode)
        candidate = next((
            c for c in recommendation.candidates if c.candidate_id == candidate_id
        ), None)
        reviewable = next((
            c for c in recommendation.reviewable_candidates
            if c.candidate_id == candidate_id
        ), None)
        if candidate is None and reviewable is not None:
            if mode != ApprovalMode.REFERENCE_OVERRIDE:
                raise ValueError(
                    "reviewable candidates require reference_override mode and cannot "
                    "enter ordinary approval"
                )
            candidate = reviewable
        if candidate is None:
            raise KeyError(f"candidate not found: {candidate_id}")
        hard_rejections = candidate_hard_rejection_reasons(candidate)
        if hard_rejections:
            raise ValueError(
                "candidate is hard-blocked and cannot be approved: "
                + ", ".join(hard_rejections)
            )
        if (
            recommendation.status == ResolutionStatus.REFERENCE_REVIEW_REQUIRED
            and mode != ApprovalMode.REFERENCE_OVERRIDE
        ):
            raise ValueError("reference-review resolutions require reference_override mode")
        if candidate.result_tier == ResultTier.REFERENCE_ONLY:
            if mode != ApprovalMode.REFERENCE_OVERRIDE or not note.strip():
                raise ValueError("REFERENCE_ONLY candidates require reference_override mode and a non-empty reason")
        elif candidate.result_tier == ResultTier.USABLE_WITH_ASSUMPTIONS and mode == ApprovalMode.STANDARD:
            raise ValueError("USABLE_WITH_ASSUMPTIONS candidates require assumption_acceptance mode")
        existing_approval = await self.store.get_approval(request_id, candidate_id)
        if existing_approval is not None and existing_approval.status == ApprovalStatus.REJECTED:
            raise ValueError("rejected candidate cannot be approved in the same resolution run")
        approval = ApprovalRecord(request_id, candidate_id, reviewer, ApprovalStatus.APPROVED, note, mode=mode)
        await self.store.save_approval(approval)
        await self._append_trace(request_id, "human_approval", "candidate approved", {
            "candidate_id": candidate_id, "reviewer": reviewer, "note": note, "approval_mode": mode.value,
        })
        return approval

    async def reject(self, request_id: str, candidate_id: str, reviewer: str, note: str = "") -> ApprovalRecord:
        recommendation = await self.store.get_recommendation(request_id)
        if recommendation is None:
            raise KeyError(f"unknown request: {request_id}")
        candidate = next((
            c for c in (
                *recommendation.candidates, *recommendation.reviewable_candidates
            )
            if c.candidate_id == candidate_id
        ), None)
        if candidate is None:
            raise KeyError(f"candidate not found: {candidate_id}")
        approval = ApprovalRecord(request_id, candidate_id, reviewer, ApprovalStatus.REJECTED, note)
        await self.store.save_approval(approval)
        await self._append_trace(request_id, "human_approval", "candidate rejected", {
            "candidate_id": candidate_id, "reviewer": reviewer, "note": note,
        })
        return approval

    async def lock(self, request_id: str, candidate_id: str, reviewer: str) -> LockedResolution:
        existing = await self.store.get_locked(request_id)
        if existing is not None:
            if existing.candidate.candidate_id != candidate_id:
                raise ValueError("resolution is already locked and immutable")
            return existing
        approval = await self.store.get_approval(request_id, candidate_id)
        if approval is None or approval.status != ApprovalStatus.APPROVED:
            raise ValueError("candidate must be approved before locking")
        recommendation = await self.store.get_recommendation(request_id)
        if recommendation is None:
            raise KeyError(f"unknown request: {request_id}")
        candidate = next((
            c for c in (
                *recommendation.candidates, *recommendation.reviewable_candidates
            )
            if c.candidate_id == candidate_id
        ), None)
        if candidate is None:
            raise KeyError(f"candidate not found: {candidate_id}")
        hard_rejections = candidate_hard_rejection_reasons(candidate)
        if hard_rejections:
            raise ValueError(
                "candidate is hard-blocked and cannot be locked: "
                + ", ".join(hard_rejections)
            )
        if candidate.result_tier == ResultTier.REFERENCE_ONLY and approval.mode != ApprovalMode.REFERENCE_OVERRIDE:
            raise ValueError("REFERENCE_ONLY candidate requires reference_override approval")
        if candidate.result_tier == ResultTier.USABLE_WITH_ASSUMPTIONS and approval.mode == ApprovalMode.STANDARD:
            raise ValueError("candidate assumptions must be explicitly accepted before locking")
        expected_total = expected_total_emissions(candidate)
        if expected_total is not None:
            observed_total = candidate.total_emissions_kgco2e
            tolerance = max(1e-9, abs(expected_total) * 1e-9)
            if observed_total is None or abs(observed_total - expected_total) > tolerance:
                raise ValueError(
                    "candidate total emissions are inconsistent with factor value and resolved quantity"
                )
        locked = LockedResolution(
            request_id=request_id,
            candidate=candidate,
            reviewer=reviewer,
            approval=ApprovalRecord(
                request_id, candidate_id, approval.reviewer, ApprovalStatus.LOCKED, approval.note, approval.created_at,
                approval.mode,
            ),
        )
        await self.store.save_locked(locked)
        await self._append_trace(request_id, "lock", "approved factor result locked", {
            "candidate_id": candidate_id,
            "reviewer": reviewer,
            "locked_result_is_immutable": True,
            "trace_remains_appendable": True,
            "result_tier": candidate.result_tier.value,
            "approval_mode": approval.mode.value,
            "accepted_assumptions": candidate.assumptions,
            "override_reason": approval.note if approval.mode == ApprovalMode.REFERENCE_OVERRIDE else None,
            "unresolved_warnings": candidate.warnings,
        })
        return locked

    async def locked(self, request_id: str) -> LockedResolution | None:
        return await self.store.get_locked(request_id)

    async def compare_traces(self, before_request_id: str, after_request_id: str) -> dict[str, object]:
        """Explain why equivalent requests differ across catalogue versions."""
        before = await self.store.get_trace(before_request_id)
        after = await self.store.get_trace(after_request_id)
        if before is None or after is None:
            raise KeyError("both resolution traces must exist")
        before_fingerprint = before.normalized_business_fingerprint or before.request_fingerprint
        after_fingerprint = after.normalized_business_fingerprint or after.request_fingerprint
        if before_fingerprint != after_fingerprint:
            raise ValueError("trace comparison requires equivalent business requests")

        before_hits = self._trace_ids(before, "local_retrieval", "records", "source_id")
        after_hits = self._trace_ids(after, "local_retrieval", "records", "source_id")
        before_ranking = self._trace_ids(before, "rank", "ranking", "candidate_id")
        after_ranking = self._trace_ids(after, "rank", "ranking", "candidate_id")
        before_excluded = self._trace_ids(before, "top_k", "excluded", "source_id")
        after_excluded = self._trace_ids(after, "top_k", "excluded", "source_id")
        before_anchor = before.database_anchor
        after_anchor = after.database_anchor
        database_changed = (
            before_anchor is None or after_anchor is None or before_anchor.identity != after_anchor.identity
        )
        explanations: list[str] = []
        if database_changed:
            explanations.append("formal factor database anchor changed")
        if before_hits != after_hits:
            explanations.append("local retrieval hit set changed")
        if before_excluded != after_excluded:
            explanations.append("candidate exclusion set changed")
        if before_ranking != after_ranking:
            explanations.append("deterministic candidate ranking changed")
        if not explanations:
            explanations.append("no result-driving trace difference detected")
        return {
            "same_request": True,
            "request_fingerprint": before_fingerprint,
            "raw_request_fingerprint_before": before.raw_request_fingerprint or before.request_fingerprint,
            "raw_request_fingerprint_after": after.raw_request_fingerprint or after.request_fingerprint,
            "database_changed": database_changed,
            "before_database": before_anchor.to_dict() if before_anchor else None,
            "after_database": after_anchor.to_dict() if after_anchor else None,
            "local_hits_added": tuple(sorted(set(after_hits) - set(before_hits))),
            "local_hits_removed": tuple(sorted(set(before_hits) - set(after_hits))),
            "excluded_before": before_excluded,
            "excluded_after": after_excluded,
            "ranking_before": before_ranking,
            "ranking_after": after_ranking,
            "explanations": tuple(explanations),
        }

    async def _append_trace(
        self, request_id: str, stage: str, message: str, details: Mapping[str, object]
    ) -> None:
        trace = await self.store.get_trace(request_id)
        if trace is None:
            raise KeyError(f"trace not found: {request_id}")
        trace.append(stage, message, details)
        await self.store.save_trace(trace)

    @staticmethod
    def _trace_ids(
        trace: ResolutionTrace, stage: str, collection_key: str, id_key: str
    ) -> tuple[str, ...]:
        entry = trace.latest(stage)
        if entry is None:
            return ()
        values = entry.details.get(collection_key, ())
        if not isinstance(values, (list, tuple)):
            return ()
        return tuple(
            str(item.get(id_key)) for item in values
            if isinstance(item, Mapping) and item.get(id_key)
        )
