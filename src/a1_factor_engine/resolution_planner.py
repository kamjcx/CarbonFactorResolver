"""Deterministic, dependency-ordered resolution planning."""

from __future__ import annotations

from .models import GapType, ResolutionGap, ResolutionPlan, RouterType

STEP_FOR_GAP = {
    GapType.UNIT_SCALE: RouterType.UNIT_SCALE,
    GapType.REFERENCE_FLOW: RouterType.REFERENCE_FLOW,
    GapType.PROCESS_VARIANT: RouterType.PROCESS_VARIANT,
    GapType.GRADE_COMPOSITION: RouterType.GRADE_COMPOSITION,
    GapType.MATERIAL_ABSENT: RouterType.CLASS_AWARE_PROXY,
}

STEP_ORDER = (
    RouterType.UNIT_SCALE,
    RouterType.REFERENCE_FLOW,
    RouterType.PROCESS_VARIANT,
    RouterType.GRADE_COMPOSITION,
    RouterType.CLASS_AWARE_PROXY,
)


def build_resolution_plan(
    candidate_id: str, gaps: tuple[ResolutionGap, ...]
) -> ResolutionPlan:
    requested = {STEP_FOR_GAP[gap.gap_type] for gap in gaps if gap.gap_type in STEP_FOR_GAP}
    steps = tuple(step for step in STEP_ORDER if step in requested)
    return ResolutionPlan(
        plan_id=f"plan:{candidate_id}",
        candidate_id=candidate_id,
        gap_ids=tuple(gap.gap_id for gap in gaps),
        steps=steps,
    )
