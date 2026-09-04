"""Contract oracle independent of CarbonFactorResolver runtime decisions."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any

from .contracts import (
    BOUNDARY_COMPATIBILITY,
    SOURCE_PRIORITY,
    SOURCE_QUALITY_ADMISSION,
    SUBJECT_COMPATIBILITY,
    UNIT_DIMENSIONS,
    ExpectedDecision,
)


def normalize_label(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", value)


def _aliases(record: Mapping[str, Any]) -> set[str]:
    return {
        normalize_label(str(value))
        for value in (record["name"], *record.get("aliases", ()))
        if str(value).strip()
    }


def _has_valid_provenance(record: Mapping[str, Any]) -> bool:
    digest = record.get("source_document_sha256")
    return (
        isinstance(digest, str)
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
        and bool(record.get("source_document_locator"))
    )


def _dimension(unit: object) -> str | None:
    return UNIT_DIMENSIONS.get(str(unit))


def derive_expectation(
    request: Mapping[str, Any], records: Sequence[Mapping[str, Any]]
) -> ExpectedDecision:
    """Derive a decision from explicit contracts, never from runtime helpers."""

    name = normalize_label(str(request.get("material_name", "")))
    semantic_matches = [record for record in records if name in _aliases(record)]
    all_ids = tuple(sorted(str(record["source_id"]) for record in records))
    semantic_ids = tuple(sorted(str(record["source_id"]) for record in semantic_matches))
    if not semantic_matches:
        return ExpectedDecision(
            status="unresolved",
            forbidden_source_ids=all_ids,
            reason_codes=("CATALOG_COVERAGE_GAP",),
        )

    process = request.get("production_process")
    form = request.get("product_form")
    if len(semantic_matches) > 1:
        processes = {record.get("production_process") for record in semantic_matches}
        forms = {record.get("product_form") for record in semantic_matches}
        years = {record.get("year") for record in semantic_matches}
        if len(processes - {None}) > 1 and process is None:
            return ExpectedDecision(
                status="more_input_needed",
                reference_only_source_ids=semantic_ids,
                reason_codes=("PROCESS_REQUIRED",),
            )
        if len(forms - {None}) > 1 and form is None:
            return ExpectedDecision(
                status="more_input_needed",
                reference_only_source_ids=semantic_ids,
                reason_codes=("PRODUCT_FORM_REQUIRED",),
            )
        if len(years - {None}) > 1 and request.get("year") is None:
            return ExpectedDecision(
                status="more_input_needed",
                reference_only_source_ids=semantic_ids,
                reason_codes=("YEAR_REQUIRED",),
            )

    dimension = _dimension(request.get("target_factor_unit") or request.get("quantity_unit"))
    known_record_dimensions = {_dimension(record.get("primary_unit")) for record in semantic_matches}
    if dimension is None or dimension not in known_record_dimensions:
        return ExpectedDecision(
            status="unresolved",
            forbidden_source_ids=semantic_ids,
            reason_codes=("UNIT_DIMENSION_MISMATCH",),
        )

    request_boundary = str(request.get("boundary", ""))
    request_subject = str(request.get("subject_type", ""))
    qualified: list[Mapping[str, Any]] = []
    reference_only: list[Mapping[str, Any]] = []
    failure_codes: set[str] = set()
    for record in semantic_matches:
        if _dimension(record.get("primary_unit")) != dimension:
            failure_codes.add("UNIT_DIMENSION_MISMATCH")
            continue
        record_boundary = str(record.get("boundary", ""))
        if not BOUNDARY_COMPATIBILITY.get(request_boundary, {}).get(record_boundary, False):
            failure_codes.add("BOUNDARY_MISMATCH")
            continue
        record_subject = str(record.get("subject_type", ""))
        if not SUBJECT_COMPATIBILITY.get(request_subject, {}).get(record_subject, False):
            failure_codes.add("SUBJECT_MISMATCH")
            continue
        if process is not None and record.get("production_process") not in (None, process):
            failure_codes.add("PROCESS_MISMATCH")
            continue
        if form is not None and record.get("product_form") not in (None, form):
            failure_codes.add("PRODUCT_FORM_MISMATCH")
            continue
        if request.get("geography") and record.get("geography") not in (None, request["geography"]):
            failure_codes.add("GEOGRAPHY_MISMATCH")
            continue
        if request.get("year") and record.get("year") not in (None, request["year"]):
            failure_codes.add("YEAR_MISMATCH")
            continue
        quality_ok = SOURCE_QUALITY_ADMISSION.get(str(record.get("source_quality_status")), False)
        eligible = bool(record.get("admission_eligible")) and record.get("document_status") == "PUBLISHED"
        if not _has_valid_provenance(record) or not quality_ok or not eligible:
            reference_only.append(record)
            failure_codes.add("PROVENANCE_NOT_ADMISSIBLE")
            continue
        qualified.append(record)

    if not qualified:
        references = tuple(sorted(str(record["source_id"]) for record in reference_only))
        status = "reference_review_required" if references else "unresolved"
        return ExpectedDecision(
            status=status,
            forbidden_source_ids=semantic_ids,
            reference_only_source_ids=references,
            reason_codes=tuple(sorted(failure_codes)) or ("NO_QUALIFIED_CANDIDATE",),
        )

    qualified.sort(
        key=lambda record: (
            -SOURCE_PRIORITY[str(record["source_tier"])],
            str(record["source_id"]),
        )
    )
    top = str(qualified[0]["source_id"])
    acceptable = tuple(str(record["source_id"]) for record in qualified)
    qualified_set = set(acceptable)
    forbidden = tuple(sorted(source_id for source_id in all_ids if source_id not in qualified_set))
    return ExpectedDecision(
        status="recommendation_ready",
        acceptable_source_ids=acceptable,
        forbidden_source_ids=forbidden,
        reference_only_source_ids=tuple(
            sorted(str(record["source_id"]) for record in reference_only)
        ),
        approval_allowed=True,
        expected_top_1=top,
    )
