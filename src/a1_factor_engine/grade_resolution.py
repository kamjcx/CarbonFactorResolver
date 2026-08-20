"""Deterministic same-series interpolation and nearest-grade fallback."""

from __future__ import annotations

import re

from .derived_factor import derive_candidate
from .models import (
    Candidate,
    NormalizedActivity,
    ResolutionType,
    RouterType,
    SourceRecord,
    TransformationStep,
)
from .units import convert_factor


def extract_grade(value: str | None) -> float | None:
    match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*%", value or "")
    if not match:
        return None
    result = float(match.group(1))
    return result if 0 < result <= 100 else None


def _record_grade(record: SourceRecord) -> float | None:
    raw = record.metadata.get("grade")
    if raw:
        try:
            value = float(raw)
            if 0 < value <= 100:
                return value
        except ValueError:
            pass
    return extract_grade(record.composition) or extract_grade(record.material_name)


def resolve_grade(
    activity: NormalizedActivity,
    candidate: Candidate,
    series: tuple[SourceRecord, ...],
) -> Candidate:
    target = extract_grade(activity.composition) or extract_grade(activity.canonical_name)
    anchors = []
    for record in (candidate.source, *series):
        grade = _record_grade(record)
        if grade is None:
            continue
        if record.provider != candidate.source.provider:
            continue
        if record.boundary != candidate.source.boundary or record.production_process != candidate.source.production_process:
            continue
        anchors.append((grade, record))
    if target is not None:
        lower = max((item for item in anchors if item[0] <= target), default=None, key=lambda item: item[0])
        upper = min((item for item in anchors if item[0] >= target), default=None, key=lambda item: item[0])
        if lower and upper and lower[0] != upper[0]:
            low_grade, low = lower
            high_grade, high = upper
            low_factor = convert_factor(low.factor_value, low.factor_unit, candidate.factor_unit)
            high_factor = convert_factor(high.factor_value, high.factor_unit, candidate.factor_unit)
            ratio = (target - low_grade) / (high_grade - low_grade)
            output = low_factor + ratio * (high_factor - low_factor)
            step = TransformationStep(
                step_id=f"grade:{candidate.candidate_id}:interpolate",
                router_type=RouterType.GRADE_COMPOSITION,
                method="BOUNDED_SAME_SERIES_INTERPOLATION",
                input_source_ids=(low.source_id, high.source_id),
                parameter_ids=(),
                formula_id="grade.linear_interpolation_same_series/v1",
                formula_expression="EF_target = EF_low + (grade_target-grade_low)/(grade_high-grade_low)*(EF_high-EF_low)",
                input_values={
                    "grade_low": low_grade,
                    "factor_low": low_factor,
                    "grade_high": high_grade,
                    "factor_high": high_factor,
                    "grade_target": target,
                },
                output_value=output,
                output_unit=candidate.factor_unit,
                assumptions=("anchors belong to the same source, boundary and process series",),
            )
            return derive_candidate(
                candidate,
                candidate_id=f"{candidate.candidate_id}:grade-{target:g}-interpolated",
                resolution_type=ResolutionType.GRADE_INTERPOLATED,
                factor_value=output,
                steps=(step,),
                base_source_ids=(low.source_id, high.source_id),
                reasons=(f"bounded interpolation between {low_grade:g}% and {high_grade:g}% same-series anchors",),
                assumptions=step.assumptions,
            )

    source_grade = _record_grade(candidate.source)
    difference = "unknown"
    if target is not None and source_grade is not None:
        difference = f"{target - source_grade:+g} percentage points"
    return derive_candidate(
        candidate,
        candidate_id=f"{candidate.candidate_id}:grade-proxy",
        resolution_type=ResolutionType.GRADE_PROXY,
        reasons=("retained the nearest available grade without changing its factor",),
        limitations=(f"target-to-source grade difference: {difference}; no supported adjustment basis",),
        assumptions=("nearest grade is used unchanged",),
    )
