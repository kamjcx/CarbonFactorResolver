"""Explicit-denominator metrics and deterministic Bad Case attribution."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

KNOWN_REASON_CODES = frozenset({
    "ADMISSION_REJECTED",
    "CATALOG_FACTOR_UNIT_INVALID",
    "CONFLICTING_DUPLICATE_SOURCE_ID",
    "UNIT_CONVERSION_EVIDENCE_REQUIRED",
    "UNIT_DIMENSION_MISMATCH",
    "UNIT_SYNTAX_UNSUPPORTED",
    "SOURCE_DOCUMENT_HASH_REQUIRED",
    "PROCESS_REQUIRED",
    "PRODUCT_FORM_REQUIRED",
    "GEOGRAPHY_REQUIRED",
    "YEAR_REQUIRED",
})

BAD_CASE_CATEGORIES = frozenset({
    "QUERY_AMBIGUITY",
    "CATALOG_COVERAGE_GAP",
    "ALIAS_OR_ENTITY_FAILURE",
    "RETRIEVAL_FAILURE",
    "RANKING_FAILURE",
    "UNIT_QUALIFICATION_FAILURE",
    "BOUNDARY_FAILURE",
    "SUBJECT_FAILURE",
    "PROVENANCE_FAILURE",
    "BENCHMARK_LABEL_DISAGREEMENT",
    "EXPLANATION_OR_UI_FAILURE",
})


@dataclass(frozen=True, slots=True)
class MetricValue:
    numerator: int
    denominator: int
    rate: float | None

    @classmethod
    def of(cls, numerator: int, denominator: int) -> MetricValue:
        if numerator < 0 or denominator < 0 or numerator > denominator:
            raise ValueError("metric counts must satisfy 0 <= numerator <= denominator")
        return cls(numerator, denominator, numerator / denominator if denominator else None)

    def to_dict(self) -> dict[str, int | float | None]:
        return asdict(self)


def _expectation(row: Mapping[str, Any]) -> Mapping[str, Any]:
    value = row.get("expectation", {})
    return value if isinstance(value, Mapping) else {}


def _observation(row: Mapping[str, Any]) -> Mapping[str, Any]:
    value = row.get("observation", {})
    return value if isinstance(value, Mapping) else {}


def _strings(value: object) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    return ()


def _selectable_ids(row: Mapping[str, Any]) -> tuple[str, ...]:
    observed = _observation(row)
    return tuple(dict.fromkeys((
        *_strings(observed.get("primary_ids")),
        *_strings(observed.get("reviewable_ids")),
    )))


def _forbidden_escape(row: Mapping[str, Any]) -> bool:
    forbidden = set(_strings(_expectation(row).get("forbidden_ids")))
    return bool(forbidden & set(_selectable_ids(row)))


def _metric(
    rows: Sequence[Mapping[str, Any]],
    predicate: Callable[[Mapping[str, Any]], bool],
    success: Callable[[Mapping[str, Any]], bool],
) -> MetricValue:
    eligible = [row for row in rows if predicate(row)]
    return MetricValue.of(sum(bool(success(row)) for row in eligible), len(eligible))


def aggregate_metrics(
    rows: Sequence[Mapping[str, Any]],
    *,
    relation_results: Mapping[str, bool] | None = None,
) -> dict[str, Any]:
    """Aggregate requested metrics without hiding empty denominators."""

    relation_results = relation_results or {}

    def direct(row: Mapping[str, Any]) -> bool:
        return _expectation(row).get("decision") == "direct"

    def acceptable(row: Mapping[str, Any]) -> set[str]:
        return set(_strings(_expectation(row).get("acceptable_ids")))

    def top_ids(row: Mapping[str, Any]) -> tuple[str, ...]:
        return _strings(_observation(row).get("primary_ids"))

    direct_top1 = _metric(
        rows, direct,
        lambda row: bool(top_ids(row) and top_ids(row)[0] in acceptable(row)),
    )
    recall_at_5 = _metric(
        rows,
        lambda row: bool(acceptable(row)),
        lambda row: bool(acceptable(row) & set(_selectable_ids(row)[:5])),
    )
    forbidden = MetricValue.of(
        sum(_forbidden_escape(row) for row in rows), len(rows)
    )
    abstention = _metric(
        rows,
        lambda row: _expectation(row).get("decision") == "abstain",
        lambda row: not _selectable_ids(row)
        and _observation(row).get("status") not in {
            "error", "recommendation_ready", "reference_review_required"
        },
    )
    more_input = _metric(
        rows,
        lambda row: _expectation(row).get("decision") == "more_input",
        lambda row: _observation(row).get("status") == "more_input_needed",
    )
    unnecessary = _metric(
        rows,
        lambda row: _expectation(row).get("decision") != "more_input",
        lambda row: _observation(row).get("status") == "more_input_needed",
    )

    def violation(axis: str) -> MetricValue:
        scoped = [row for row in rows if _expectation(row).get("safety_axis") == axis]
        return MetricValue.of(sum(_forbidden_escape(row) for row in scoped), len(scoped))

    proxy = _metric(
        rows,
        lambda row: bool(_expectation(row).get("requires_proxy_disclosure")),
        lambda row: bool(_observation(row).get("proxy_disclosed")),
    )
    evidence = _metric(
        rows,
        lambda row: bool(_selectable_ids(row)),
        lambda row: bool(_observation(row).get("evidence_complete")),
    )
    replay = MetricValue.of(
        sum(bool(value) for value in relation_results.values()), len(relation_results)
    )
    http_rows = [row for row in rows if _observation(row).get("http_status") is not None]
    http_500 = MetricValue.of(
        sum(int(_observation(row).get("http_status", 0)) >= 500 for row in http_rows),
        len(http_rows),
    )
    unknown_reasons = sorted({
        reason
        for row in rows
        for reason in _strings(_observation(row).get("reason_codes"))
        if reason not in KNOWN_REASON_CODES
    })
    errors = sum(bool(_observation(row).get("error")) for row in rows)

    metrics: dict[str, Any] = {
        "direct_recommendation_top1": direct_top1.to_dict(),
        "recall_at_5": recall_at_5.to_dict(),
        "forbidden_candidate_escape": forbidden.to_dict(),
        "abstention_correctness": abstention.to_dict(),
        "more_input_recall": more_input.to_dict(),
        "unnecessary_question_rate": unnecessary.to_dict(),
        "boundary_violation": violation("boundary").to_dict(),
        "subject_violation": violation("subject").to_dict(),
        "unit_violation": violation("unit").to_dict(),
        "proxy_disclosure": proxy.to_dict(),
        "evidence_metadata_completeness": evidence.to_dict(),
        "deterministic_replay": replay.to_dict(),
        "unhandled_http_500": http_500.to_dict(),
        "harness_error_count": errors,
        "unknown_reason_codes": unknown_reasons,
        "case_count": len(rows),
    }
    hard_gate_results = {
        "direct_top1_at_least_90_percent": bool(direct_top1.rate is not None and direct_top1.rate >= 0.90),
        "recall_at_5_at_least_95_percent": bool(recall_at_5.rate is not None and recall_at_5.rate >= 0.95),
        "abstention_at_least_90_percent": bool(abstention.rate is not None and abstention.rate >= 0.90),
        "more_input_at_least_90_percent": bool(more_input.rate is not None and more_input.rate >= 0.90),
        "zero_forbidden_escape": forbidden.numerator == 0,
        "zero_boundary_violation": metrics["boundary_violation"]["numerator"] == 0,
        "zero_subject_violation": metrics["subject_violation"]["numerator"] == 0,
        "zero_unit_violation": metrics["unit_violation"]["numerator"] == 0,
        "evidence_metadata_complete": bool(evidence.rate is not None and evidence.rate == 1.0),
        "deterministic_replay_100_percent": replay.denominator > 0 and replay.numerator == replay.denominator,
        "zero_unhandled_http_500": http_500.denominator > 0 and http_500.numerator == 0,
        "zero_harness_errors": errors == 0,
        "zero_unknown_reason_codes": not unknown_reasons,
    }
    metrics["hard_gate_results"] = hard_gate_results
    metrics["hard_gates_pass"] = all(hard_gate_results.values())
    return metrics


def classify_bad_case(row: Mapping[str, Any]) -> str | None:
    """Return one stable attribution category for a failed generated case."""

    if row.get("passed") is True:
        return None
    expected = _expectation(row)
    observed = _observation(row)
    axis = str(expected.get("safety_axis") or "")
    category = str(row.get("category") or "")
    if axis == "provenance":
        return "PROVENANCE_FAILURE"
    if axis == "boundary":
        return "BOUNDARY_FAILURE"
    if axis == "subject":
        return "SUBJECT_FAILURE"
    if axis == "unit":
        return "UNIT_QUALIFICATION_FAILURE"
    if expected.get("decision") == "more_input":
        return "QUERY_AMBIGUITY"
    if "alias" in category or "typo" in category or "entity" in category:
        return "ALIAS_OR_ENTITY_FAILURE"
    acceptable = set(_strings(expected.get("acceptable_ids")))
    selected = _selectable_ids(row)
    if acceptable and not (acceptable & set(selected)):
        return "RETRIEVAL_FAILURE" if not selected else "RANKING_FAILURE"
    if _forbidden_escape(row):
        return "RANKING_FAILURE"
    if observed.get("error") or not observed.get("trace_complete", True):
        return "EXPLANATION_OR_UI_FAILURE"
    if expected.get("decision") == "abstain":
        return "CATALOG_COVERAGE_GAP"
    return "BENCHMARK_LABEL_DISAGREEMENT"


def bad_cases(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    found = []
    for row in rows:
        category = classify_bad_case(row)
        if category is None:
            continue
        if category not in BAD_CASE_CATEGORIES:
            raise ValueError(f"unknown Bad Case category: {category}")
        found.append({"bad_case_category": category, **dict(row)})
    return found
