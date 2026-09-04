"""Deterministic FactorBench V1 loader, runner, and metric implementation."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import subprocess
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any

from a1_factor_engine.adapters import HttpCatalogFactorRepository
from a1_factor_engine.engine import A1FactorResolutionEngine
from a1_factor_engine.material_registry import DEFAULT_MATERIAL_REGISTRY
from a1_factor_engine.models import Recommendation, ResolutionStatus

from .models import (
    SCHEMA_VERSION,
    FactorBenchCase,
    FactorBenchCaseResult,
    FactorBenchMetrics,
    FactorBenchRun,
)

EngineFactory = Callable[
    [HttpCatalogFactorRepository, FactorBenchCase, Mapping[str, Any] | None],
    A1FactorResolutionEngine,
]


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_cases(path: str | Path) -> tuple[FactorBenchCase, ...]:
    target = Path(path)
    cases: list[FactorBenchCase] = []
    for line_number, line in enumerate(target.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid FactorBench JSONL at line {line_number}: {exc.msg}") from exc
        if not isinstance(value, Mapping):
            raise ValueError(f"FactorBench line {line_number} must be an object")
        cases.append(FactorBenchCase.from_mapping(value))
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("FactorBench case_id values must be unique")
    return tuple(cases)


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * percentile + 0.5)))
    return ordered[index]


def aggregate_metrics(results: Sequence[FactorBenchCaseResult]) -> FactorBenchMetrics:
    entity_cases = [item for item in results if item.expected_identity is not None]
    retrieval_cases = [item for item in results if item.expected_top_ids]

    def recalled(item: FactorBenchCaseResult, k: int) -> float:
        return float(bool(set(item.expected_top_ids) & set(item.observed_top_ids[:k])))

    confusable = [item for item in results if item.expected_hard_exclusions or "confusable" in item.tags]
    false_positive_count = sum(
        bool(set(item.expected_hard_exclusions) & set(item.observed_top_ids)) for item in confusable
    )
    candidate_count = sum(len(item.observed_top_ids) for item in retrieval_cases)
    qualified_count = sum(
        len(set(item.observed_top_ids) & set(item.expected_top_ids)) for item in retrieval_cases
    )
    more_input = [
        item for item in results
        if item.expected_status == ResolutionStatus.MORE_INPUT_NEEDED.value or "more_input" in item.tags
    ]
    abstentions = [
        item for item in results
        if "abstention" in item.tags or (
            not item.expected_top_ids and item.expected_status != ResolutionStatus.MORE_INPUT_NEEDED.value
        )
    ]
    external = [item for item in results if item.used_external_fixture]
    latencies = [item.latency_ms for item in results]
    return FactorBenchMetrics(
        entity_accuracy=_mean([
            float(item.observed_identity == item.expected_identity) for item in entity_cases
        ]),
        recall_at_1=_mean([recalled(item, 1) for item in retrieval_cases]),
        recall_at_3=_mean([recalled(item, 3) for item in retrieval_cases]),
        recall_at_5=_mean([recalled(item, 5) for item in retrieval_cases]),
        mrr=_mean([item.reciprocal_rank for item in retrieval_cases]),
        confusable_false_positive_rate=(false_positive_count / len(confusable) if confusable else 0.0),
        qualified_candidate_precision=(qualified_count / candidate_count if candidate_count else 0.0),
        evidence_completeness=_mean([item.evidence_coverage for item in retrieval_cases]),
        correct_more_input=_mean([
            float(
                item.observed_status == ResolutionStatus.MORE_INPUT_NEEDED.value
                and set(item.expected_required_choices) <= set(item.observed_required_choices)
            )
            for item in more_input
        ]),
        correct_abstention=_mean([
            float(item.observed_status == item.expected_status and not item.observed_top_ids)
            for item in abstentions
        ]),
        external_retrieval_success=_mean([
            float(item.observed_status == item.expected_status and bool(
                set(item.expected_top_ids) & set(item.observed_top_ids)
            )) for item in external
        ]),
        p50_latency_ms=median(latencies) if latencies else 0.0,
        p95_latency_ms=_percentile(latencies, 0.95),
        case_count=len(results),
    )


def compare_runs(
    baseline: FactorBenchRun | Mapping[str, Any],
    candidate: FactorBenchRun | Mapping[str, Any],
) -> dict[str, float]:
    """Return candidate-minus-baseline aggregate deltas for shared numeric metrics."""
    def metrics(value: FactorBenchRun | Mapping[str, Any]) -> Mapping[str, Any]:
        if isinstance(value, FactorBenchRun):
            return value.aggregates.to_dict()
        raw = value.get("aggregates", value)
        if not isinstance(raw, Mapping):
            raise ValueError("run must contain aggregate metrics")
        return raw

    before, after = metrics(baseline), metrics(candidate)
    return {
        key: float(value) - float(before[key])
        for key, value in after.items()
        if key != "case_count" and key in before
    }


def _required_choices(value: object) -> tuple[str, ...]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if key in {"field", "choice", "id", "value"} and isinstance(nested, str):
                found.append(nested)
            else:
                found.extend(_required_choices(nested))
    elif isinstance(value, (list, tuple)):
        for nested in value:
            found.extend(_required_choices(nested))
    elif isinstance(value, str):
        found.append(value)
    return tuple(dict.fromkeys(found))


def _identity(recommendation: Recommendation) -> str | None:
    if recommendation.trace is None:
        return None
    normalized = recommendation.trace.latest("normalize")
    if normalized is None:
        return None
    identity = normalized.details.get("material_identity")
    if not isinstance(identity, Mapping):
        identity = normalized.details.get("identity_resolution")
    if not isinstance(identity, Mapping):
        return None
    selected = identity.get("base_entity_id") or identity.get("selected_base_entity_id")
    return str(selected) if selected else None


def _default_engine(
    repository: HttpCatalogFactorRepository,
    _case: FactorBenchCase,
    external_fixture: Mapping[str, Any] | None,
) -> A1FactorResolutionEngine:
    if external_fixture is not None:
        from a1_factor_engine.external_connectors import (
            FixtureExternalConnector,
            StructuredEPDEvidenceExtractor,
        )

        return A1FactorResolutionEngine(
            local_retrieval=repository,
            external_connectors=(FixtureExternalConnector(str(external_fixture["__fixture_path__"])),),
            external_extractor=StructuredEPDEvidenceExtractor(),
        )
    return A1FactorResolutionEngine(local_retrieval=repository)


class FactorBenchRunner:
    def __init__(
        self,
        dataset_path: str | Path,
        *,
        fixture_root: str | Path | None = None,
        engine_factory: EngineFactory | None = None,
        timer: Callable[[], float] = perf_counter,
    ) -> None:
        self.dataset_path = Path(dataset_path)
        self.fixture_root = Path(fixture_root) if fixture_root is not None else self.dataset_path.parent.parent / "fixtures" / "catalog"
        self.engine_factory = engine_factory or _default_engine
        self.timer = timer

    async def run(self, baseline: FactorBenchRun | Mapping[str, Any] | None = None) -> FactorBenchRun:
        cases = load_cases(self.dataset_path)
        if len(cases) < 40:
            raise ValueError("FactorBench V1 requires at least 40 cases")
        results: list[FactorBenchCaseResult] = []
        catalog_anchors: dict[str, Mapping[str, Any]] = {}
        semantic_anchors: dict[str, Mapping[str, Any]] = {}
        energy_anchors: dict[str, Mapping[str, Any]] = {}
        external_hashes: dict[str, str] = {}
        payload_cache: dict[Path, Mapping[str, Any]] = {}

        for case in cases:
            fixture_path = self.fixture_root / case.catalog_fixture
            if fixture_path not in payload_cache:
                payload = json.loads(fixture_path.read_text(encoding="utf-8"))
                if not isinstance(payload, Mapping):
                    raise ValueError(f"catalog fixture must be an object: {fixture_path}")
                payload_cache[fixture_path] = payload
            payload = payload_cache[fixture_path]
            database = payload.get("database")
            expected_sha = str(database.get("sha256")) if isinstance(database, Mapping) else None

            def fetch_fixture(
                _endpoint: str, fixture_payload: Mapping[str, Any] = payload
            ) -> Mapping[str, Any]:
                return fixture_payload

            repository = HttpCatalogFactorRepository(
                endpoint=f"fixture://{fixture_path.name}",
                expected_sha256=expected_sha,
                fetch_json=fetch_fixture,
            )
            external_fixture = None
            if case.external_fixture:
                external_path = self.fixture_root.parent / "external" / case.external_fixture
                raw_external = external_path.read_bytes()
                external_hashes[case.external_fixture] = _sha256(raw_external)
                loaded_external = json.loads(raw_external)
                if not isinstance(loaded_external, Mapping):
                    raise ValueError(f"external fixture must be an object: {external_path}")
                external_fixture = dict(loaded_external)
                external_fixture["__fixture_path__"] = str(external_path)
            engine = self.engine_factory(repository, case, external_fixture)
            request = dict(case.request)
            request["request_id"] = f"factorbench:{case.case_id}"
            start = self.timer()
            try:
                recommendation = await engine.resolve(request)
                elapsed = max(0.0, (self.timer() - start) * 1000.0)
                result = self._result(case, recommendation, elapsed)
                if recommendation.trace is not None:
                    explanation = recommendation.trace.explain()
                    catalog = explanation.get("database_version")
                    semantic = explanation.get("semantic_index")
                    for anchor, target in ((catalog, catalog_anchors), (semantic, semantic_anchors)):
                        if isinstance(anchor, Mapping):
                            stable_anchor = {
                                key: value for key, value in anchor.items() if key != "observed_at"
                            }
                            key = json.dumps(stable_anchor, sort_keys=True, default=str)
                            target[key] = stable_anchor
                    for anchor in explanation.get("parameter_databases", ()):
                        if isinstance(anchor, Mapping):
                            key = json.dumps(dict(anchor), sort_keys=True, default=str)
                            energy_anchors[key] = dict(anchor)
            except Exception as exc:  # one bad case must remain visible in a complete benchmark run
                elapsed = max(0.0, (self.timer() - start) * 1000.0)
                result = FactorBenchCaseResult(
                    case_id=case.case_id, tags=case.tags,
                    expected_identity=case.expected_identity, observed_identity=None,
                    expected_status=case.expected_status, observed_status=ResolutionStatus.ERROR.value,
                    expected_top_ids=case.expected_top_ids, observed_top_ids=(),
                    expected_required_choices=case.expected_required_choices,
                    observed_required_choices=(),
                    expected_hard_exclusions=case.expected_hard_exclusions,
                    observed_trace_stages=(), missing_trace_stages=case.expected_trace_stages,
                    expected_reason_codes=case.expected_reason_codes,
                    observed_reason_codes=(),
                    evidence_coverage=0.0, latency_ms=elapsed,
                    used_external_fixture=external_fixture is not None,
                    error=f"{type(exc).__name__}: {exc}",
                )
            results.append(result)

        metrics = aggregate_metrics(results)
        dataset_sha = _sha256(self.dataset_path.read_bytes())
        package_version = self._package_version()
        git_sha = self._git_sha()
        run_identity = json.dumps({
            "dataset_sha256": dataset_sha,
            "git_sha": git_sha,
            "package_version": package_version,
            "registry_version": DEFAULT_MATERIAL_REGISTRY.version,
            "registry_sha256": DEFAULT_MATERIAL_REGISTRY.sha256,
            "catalog_anchors": sorted(catalog_anchors),
            "semantic_index_anchors": sorted(semantic_anchors),
            "external_hashes": external_hashes,
        }, sort_keys=True, separators=(",", ":"))
        run = FactorBenchRun(
            schema_version=SCHEMA_VERSION,
            run_id=f"factorbench-v1:{_sha256(run_identity.encode('utf-8'))[:16]}",
            git_sha=git_sha,
            package_version=package_version,
            dataset_sha256=dataset_sha,
            registry_version=DEFAULT_MATERIAL_REGISTRY.version,
            registry_sha256=DEFAULT_MATERIAL_REGISTRY.sha256,
            catalog_anchors=tuple(catalog_anchors.values()),
            semantic_index_anchors=tuple(semantic_anchors.values()),
            energy_anchors=tuple(energy_anchors.values()),
            external_hashes=external_hashes,
            results=tuple(results),
            aggregates=metrics,
            baseline_comparison=None,
        )
        if baseline is None:
            return run
        return replace(run, baseline_comparison=compare_runs(baseline, run))

    @staticmethod
    def _result(case: FactorBenchCase, recommendation: Recommendation, latency_ms: float) -> FactorBenchCaseResult:
        candidates = (*recommendation.candidates, *recommendation.reviewable_candidates)
        top_ids = tuple(dict.fromkeys(candidate.source.source_id for candidate in candidates))
        trace_stages = tuple(entry.stage for entry in recommendation.trace.entries) if recommendation.trace else ()
        explanation = recommendation.trace.explain() if recommendation.trace else {}
        choices = _required_choices(explanation.get("required_choice"))
        coverage = 0.0
        if candidates:
            source = candidates[0].source
            evidence_fields = (
                source.source_id,
                source.provider,
                source.locator,
                source.factor_unit,
                source.factor_kind.value,
                source.indicator,
                source.declared_product,
                source.boundary,
                source.source_document_sha256,
            )
            coverage = sum(value is not None and str(value).strip() != "" for value in evidence_fields) / len(
                evidence_fields
            )
        return FactorBenchCaseResult(
            case_id=case.case_id,
            tags=case.tags,
            expected_identity=case.expected_identity,
            observed_identity=_identity(recommendation),
            expected_status=case.expected_status,
            observed_status=recommendation.status.value,
            expected_top_ids=case.expected_top_ids,
            observed_top_ids=top_ids,
            expected_required_choices=case.expected_required_choices,
            observed_required_choices=choices,
            expected_hard_exclusions=case.expected_hard_exclusions,
            observed_trace_stages=trace_stages,
            missing_trace_stages=tuple(stage for stage in case.expected_trace_stages if stage not in trace_stages),
            expected_reason_codes=case.expected_reason_codes,
            observed_reason_codes=tuple(str(code) for code in recommendation.reason_codes),
            evidence_coverage=coverage,
            latency_ms=latency_ms,
            used_external_fixture=case.external_fixture is not None,
        )

    def _git_sha(self) -> str | None:
        try:
            return subprocess.run(
                ["git", "rev-parse", "HEAD"],  # noqa: S607 - repository-controlled executable
                cwd=self.dataset_path.parent,
                check=True, capture_output=True, text=True,
            ).stdout.strip() or None
        except (OSError, subprocess.CalledProcessError):
            return None

    @staticmethod
    def _package_version() -> str:
        try:
            return importlib.metadata.version("carbon-factor-resolver")
        except importlib.metadata.PackageNotFoundError:
            return "unknown"


async def run_factorbench(
    dataset_path: str | Path,
    *,
    fixture_root: str | Path | None = None,
    engine_factory: EngineFactory | None = None,
    baseline: FactorBenchRun | Mapping[str, Any] | None = None,
) -> FactorBenchRun:
    return await FactorBenchRunner(
        dataset_path, fixture_root=fixture_root, engine_factory=engine_factory
    ).run(baseline=baseline)
