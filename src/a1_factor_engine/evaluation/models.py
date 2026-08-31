"""Immutable public models for FactorBench V1."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

SCHEMA_VERSION = "factorbench/v1"


def _tuple_of_strings(value: object, field_name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field_name} must be an array of strings")
    return tuple(value)


@dataclass(frozen=True, slots=True)
class FactorBenchCase:
    """One frozen, public-synthetic FactorBench input and its expectations."""

    schema_version: str
    case_id: str
    tags: tuple[str, ...]
    request: Mapping[str, Any]
    catalog_fixture: str
    expected_identity: str | None
    expected_status: str
    expected_top_ids: tuple[str, ...] = ()
    expected_required_choices: tuple[str, ...] = ()
    expected_hard_exclusions: tuple[str, ...] = ()
    expected_trace_stages: tuple[str, ...] = ()
    external_fixture: str | None = None

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ValueError(f"unsupported FactorBench schema: {self.schema_version!r}")
        if not self.case_id.strip():
            raise ValueError("case_id is required")
        if not self.catalog_fixture.strip():
            raise ValueError("catalog_fixture is required")
        if not self.expected_status.strip():
            raise ValueError("expected_status is required")
        if not isinstance(self.request, Mapping):
            raise ValueError("request must be an object")
        object.__setattr__(self, "request", MappingProxyType(dict(self.request)))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "FactorBenchCase":
        required = {
            "schema_version", "case_id", "tags", "request", "catalog_fixture",
            "expected_identity", "expected_status", "expected_top_ids",
            "expected_required_choices", "expected_hard_exclusions", "expected_trace_stages",
        }
        missing = sorted(required - value.keys())
        if missing:
            raise ValueError(f"FactorBench case lacks frozen fields: {', '.join(missing)}")
        return cls(
            schema_version=str(value["schema_version"]),
            case_id=str(value["case_id"]),
            tags=_tuple_of_strings(value["tags"], "tags"),
            request=dict(value["request"]),
            catalog_fixture=str(value["catalog_fixture"]),
            external_fixture=(
                str(value["external_fixture"]) if value.get("external_fixture") is not None else None
            ),
            expected_identity=(
                str(value["expected_identity"]) if value["expected_identity"] is not None else None
            ),
            expected_status=str(value["expected_status"]),
            expected_top_ids=_tuple_of_strings(value["expected_top_ids"], "expected_top_ids"),
            expected_required_choices=_tuple_of_strings(
                value["expected_required_choices"], "expected_required_choices"
            ),
            expected_hard_exclusions=_tuple_of_strings(
                value["expected_hard_exclusions"], "expected_hard_exclusions"
            ),
            expected_trace_stages=_tuple_of_strings(
                value["expected_trace_stages"], "expected_trace_stages"
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        result = {
            "schema_version": self.schema_version,
            "case_id": self.case_id,
            "tags": list(self.tags),
            "request": dict(self.request),
            "catalog_fixture": self.catalog_fixture,
            "expected_identity": self.expected_identity,
            "expected_status": self.expected_status,
            "expected_top_ids": list(self.expected_top_ids),
            "expected_required_choices": list(self.expected_required_choices),
            "expected_hard_exclusions": list(self.expected_hard_exclusions),
            "expected_trace_stages": list(self.expected_trace_stages),
        }
        if self.external_fixture is not None:
            result["external_fixture"] = self.external_fixture
        return result


@dataclass(frozen=True, slots=True)
class FactorBenchCaseResult:
    case_id: str
    tags: tuple[str, ...]
    expected_identity: str | None
    observed_identity: str | None
    expected_status: str
    observed_status: str
    expected_top_ids: tuple[str, ...]
    observed_top_ids: tuple[str, ...]
    expected_required_choices: tuple[str, ...]
    observed_required_choices: tuple[str, ...]
    expected_hard_exclusions: tuple[str, ...]
    observed_trace_stages: tuple[str, ...]
    missing_trace_stages: tuple[str, ...]
    evidence_coverage: float
    latency_ms: float
    used_external_fixture: bool = False
    error: str | None = None

    @property
    def reciprocal_rank(self) -> float:
        relevant = set(self.expected_top_ids)
        return next((1.0 / rank for rank, item in enumerate(self.observed_top_ids, 1) if item in relevant), 0.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "tags": list(self.tags),
            "expected_identity": self.expected_identity,
            "observed_identity": self.observed_identity,
            "expected_status": self.expected_status,
            "observed_status": self.observed_status,
            "expected_top_ids": list(self.expected_top_ids),
            "observed_top_ids": list(self.observed_top_ids),
            "expected_required_choices": list(self.expected_required_choices),
            "observed_required_choices": list(self.observed_required_choices),
            "expected_hard_exclusions": list(self.expected_hard_exclusions),
            "observed_trace_stages": list(self.observed_trace_stages),
            "missing_trace_stages": list(self.missing_trace_stages),
            "evidence_coverage": self.evidence_coverage,
            "latency_ms": self.latency_ms,
            "used_external_fixture": self.used_external_fixture,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class FactorBenchMetrics:
    entity_accuracy: float
    recall_at_1: float
    recall_at_3: float
    recall_at_5: float
    mrr: float
    confusable_false_positive_rate: float
    qualified_candidate_precision: float
    evidence_completeness: float
    correct_more_input: float
    correct_abstention: float
    external_retrieval_success: float
    p50_latency_ms: float
    p95_latency_ms: float
    case_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_accuracy": self.entity_accuracy,
            "recall_at_1": self.recall_at_1,
            "recall_at_3": self.recall_at_3,
            "recall_at_5": self.recall_at_5,
            "mrr": self.mrr,
            "confusable_false_positive_rate": self.confusable_false_positive_rate,
            "qualified_candidate_precision": self.qualified_candidate_precision,
            "evidence_completeness": self.evidence_completeness,
            "correct_more_input": self.correct_more_input,
            "correct_abstention": self.correct_abstention,
            "external_retrieval_success": self.external_retrieval_success,
            "p50_latency_ms": self.p50_latency_ms,
            "p95_latency_ms": self.p95_latency_ms,
            "case_count": self.case_count,
        }


@dataclass(frozen=True, slots=True)
class FactorBenchRun:
    schema_version: str
    run_id: str
    git_sha: str | None
    package_version: str
    dataset_sha256: str
    registry_version: str
    registry_sha256: str
    catalog_anchors: tuple[Mapping[str, Any], ...]
    semantic_index_anchors: tuple[Mapping[str, Any], ...]
    energy_anchors: tuple[Mapping[str, Any], ...]
    external_hashes: Mapping[str, str]
    results: tuple[FactorBenchCaseResult, ...]
    aggregates: FactorBenchMetrics
    baseline_comparison: Mapping[str, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "git_sha": self.git_sha,
            "package_version": self.package_version,
            "dataset_sha256": self.dataset_sha256,
            "registry_version": self.registry_version,
            "registry_sha256": self.registry_sha256,
            "catalog_anchors": [dict(value) for value in self.catalog_anchors],
            "semantic_index_anchors": [dict(value) for value in self.semantic_index_anchors],
            "energy_anchors": [dict(value) for value in self.energy_anchors],
            "external_hashes": dict(self.external_hashes),
            "results": [value.to_dict() for value in self.results],
            "aggregates": self.aggregates.to_dict(),
            "baseline_comparison": (
                dict(self.baseline_comparison) if self.baseline_comparison is not None else None
            ),
        }
