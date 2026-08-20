"""Reference in-memory and null adapters.

The repository adapters are intentionally tiny: replacing them with a port
implementation backed by the future database/API does not change graph logic.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping, Sequence
from urllib.request import urlopen

from .matching import normalize_text
from .material_registry import DEFAULT_MATERIAL_REGISTRY, MaterialSemanticRegistryPort
from .models import (
    ApprovalRecord,
    DatabaseVersionAnchor,
    FactorKind,
    FactorSourceType,
    LinkAttempt,
    LinkOutcome,
    LinkStrategy,
    LockedResolution,
    MaterialCategory,
    MaterialClass,
    MaterialInterpretation,
    NormalizedActivity,
    ParameterEvidence,
    RecallObservation,
    Recommendation,
    ReferenceFlowRecord,
    ResolutionRequest,
    ResolutionTrace,
    RetrievalResult,
    SemanticAssessment,
    SourceRecord,
)


def _norm(value: str | None) -> str:
    return normalize_text(value).value


def _record_aliases(record: SourceRecord) -> set[str]:
    raw = record.metadata.get("aliases", "")
    if not raw:
        return set()
    if isinstance(raw, (list, tuple)):
        parsed = list(raw)
    else:
        try:
            parsed = json.loads(str(raw))
        except json.JSONDecodeError:
            parsed = [part.strip() for part in str(raw).split(",")]
    if not isinstance(parsed, list):
        parsed = [parsed]
    return {_norm(str(value)) for value in parsed if _norm(str(value))}


def _with_match_strategy(record: SourceRecord, strategy: LinkStrategy) -> SourceRecord:
    return replace(record, metadata={**record.metadata, "match_strategy": strategy.value})


def _material_terms(value: str | None) -> set[str]:
    normalized = _norm(value)
    latin = {part for part in normalized.split() if len(part) >= 3}
    cjk = "".join(char for char in normalized if "\u4e00" <= char <= "\u9fff")
    grams = {cjk[index : index + 2] for index in range(max(0, len(cjk) - 1))}
    process_terms = {
        "fused", "electrofused", "sintered", "calcined", "electric", "fusion",
        "电熔", "烧结", "煅烧",
    }
    return (latin | grams) - process_terms


def _related_material(
    activity: NormalizedActivity,
    source_name: str,
    registry: MaterialSemanticRegistryPort,
) -> bool:
    target = activity.material_identity
    observed = registry.resolve(source_name).identity
    if target and target.head_material and observed.head_material:
        if target.head_material == observed.head_material:
            return True
    if target and target.product_form and target.product_form == observed.product_form:
        return True
    return bool(_material_terms(activity.canonical_name) & _material_terms(source_name))


@dataclass(slots=True)
class InMemoryFactorRepository:
    records: list[SourceRecord]
    source_types: tuple[FactorSourceType, ...] | None = None
    anchor: DatabaseVersionAnchor | None = None
    material_registry: MaterialSemanticRegistryPort = DEFAULT_MATERIAL_REGISTRY

    def __post_init__(self) -> None:
        if self.anchor is None:
            payload = "|".join(
                f"{record.source_id}:{record.factor_value}:{record.factor_unit}"
                for record in sorted(self.records, key=lambda item: item.source_id)
            )
            self.anchor = DatabaseVersionAnchor(
                catalog_name="in-memory-factor-catalog",
                catalog_version="test-v1",
                database_sha256=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                locator="memory://factor-catalog",
            )

    async def search(self, activity: NormalizedActivity) -> RetrievalResult:
        allowed = self.source_types
        query = _norm(activity.canonical_name)
        aliases = {_norm(x) for x in activity.aliases if _norm(x)}
        eligible = tuple(
            record for record in self.records
            if allowed is None or record.source_type in allowed
        )
        exact = tuple(
            _with_match_strategy(record, LinkStrategy.EXACT)
            for record in eligible if query and _norm(record.material_name) == query
        )
        exact_ids = {record.source_id for record in exact}
        synonym = tuple(
            _with_match_strategy(record, LinkStrategy.SYNONYM)
            for record in eligible
            if record.source_id not in exact_ids
            and (
                _norm(record.material_name) in aliases
                or query in _record_aliases(record)
                or bool(aliases & _record_aliases(record))
            )
        )
        used_ids = exact_ids | {record.source_id for record in synonym}
        related = tuple(
            _with_match_strategy(record, LinkStrategy.RELATED)
            for record in eligible
            if record.source_id not in used_ids
            and _related_material(activity, record.material_name, self.material_registry)
        )
        attempts = [
            LinkAttempt(
                LinkStrategy.EXACT,
                LinkOutcome.NO_MATCH if not exact else LinkOutcome.MATCHED if len(exact) == 1 else LinkOutcome.CANDIDATE_SET,
                tuple(record.source_id for record in exact),
                "canonical material name matched exactly" if exact else "no exact canonical-name match",
            ),
            LinkAttempt(
                LinkStrategy.SYNONYM,
                LinkOutcome.NO_MATCH if not synonym else LinkOutcome.MATCHED if len(synonym) == 1 else LinkOutcome.CANDIDATE_SET,
                tuple(record.source_id for record in synonym),
                "registered aliases recalled pending exact-record qualification" if synonym else "no registered synonym match",
            ),
            LinkAttempt(
                LinkStrategy.RELATED,
                LinkOutcome.NO_MATCH if not related else LinkOutcome.MATCHED if len(related) == 1 else LinkOutcome.CANDIDATE_SET,
                tuple(record.source_id for record in related),
                "bounded material-family recall pending higher-priority qualification" if related else "no related local candidates",
            ),
        ]
        results = (*exact, *synonym, *related)
        assert self.anchor is not None
        observations = tuple(
            RecallObservation(
                source_id=record.source_id,
                material_name=record.material_name,
                retrieval_strategy=LinkStrategy.RELATED,
                retrieval_basis=("material term overlap",),
                identity_compatibility="unknown",
                factor_kind=record.factor_kind,
                eligible_for_candidate_pool=True,
            )
            for record in results
            if record.metadata.get("match_strategy") == LinkStrategy.RELATED.value
        )
        return RetrievalResult(tuple(results), self.anchor, tuple(attempts), observations)


@dataclass(slots=True)
class InMemoryProxyRepository:
    records: list[SourceRecord]

    async def search(self, activity: NormalizedActivity, material_class: MaterialClass) -> Sequence[SourceRecord]:
        family = _norm(material_class.family or material_class.name)
        class_name = _norm(material_class.name)
        results: list[SourceRecord] = []
        for record in self.records:
            haystack = " ".join(
                [_norm(record.material_name), _norm(record.metadata.get("material_class", "")), _norm(record.metadata.get("family", ""))]
            )
            if class_name in haystack or family in haystack or not family:
                results.append(record)
        return tuple(results)


class NullFactorRepository:
    async def search(self, activity: NormalizedActivity) -> RetrievalResult:
        return RetrievalResult(
            (),
            DatabaseVersionAnchor(
                catalog_name="unconfigured-factor-catalog",
                catalog_version="none",
                database_sha256=None,
                locator="none://factor-catalog",
            ),
            (
                LinkAttempt(LinkStrategy.EXACT, LinkOutcome.NO_MATCH, reason="local factor repository is unconfigured"),
                LinkAttempt(LinkStrategy.SYNONYM, LinkOutcome.NO_MATCH, reason="local factor repository is unconfigured"),
                LinkAttempt(LinkStrategy.RELATED, LinkOutcome.NO_MATCH, reason="local factor repository is unconfigured"),
            ),
        )


@dataclass(slots=True)
class HttpCatalogFactorRepository:
    """Read-only adapter for the formal `/api/v2/factors/catalog` endpoint."""

    endpoint: str = "http://127.0.0.1:5004/api/v2/factors/catalog"
    expected_sha256: str | None = None
    timeout_seconds: float = 10.0
    fetch_json: Callable[[str], Mapping[str, Any]] | None = None
    material_registry: MaterialSemanticRegistryPort = DEFAULT_MATERIAL_REGISTRY

    async def search(self, activity: NormalizedActivity) -> RetrievalResult:
        payload = await asyncio.to_thread(self._fetch)
        database = payload.get("database")
        if not isinstance(database, Mapping):
            raise ValueError("factor catalog response lacks database metadata")
        digest = str(database.get("sha256") or "").strip().lower()
        if self.expected_sha256 and digest != self.expected_sha256.strip().lower():
            raise ValueError("formal factor database SHA-256 does not match the configured anchor")
        anchor = DatabaseVersionAnchor(
            catalog_name=str(database.get("name") or "formal-factor-catalog"),
            catalog_version=str(payload.get("catalog_version") or "unknown"),
            database_sha256=digest or None,
            locator=self.endpoint,
        )
        records = payload.get("records")
        if not isinstance(records, list):
            raise ValueError("factor catalog response lacks records")
        query = _norm(activity.canonical_name)
        aliases = {_norm(alias) for alias in activity.aliases if _norm(alias)}
        exact_items = tuple(
            item for item in records
            if isinstance(item, Mapping) and self._exact_match(item, query)
        )
        exact = self._convert_items(exact_items, anchor, LinkStrategy.EXACT)
        exact_ids = {record.source_id for record in exact}
        synonym_items = tuple(
            item for item in records
            if isinstance(item, Mapping)
            and str(item.get("record_id") or item.get("code") or "").strip() not in exact_ids
            and self._synonym_match(item, query, aliases)
        )
        synonym = self._convert_items(synonym_items, anchor, LinkStrategy.SYNONYM)
        used_ids = exact_ids | {record.source_id for record in synonym}
        related_items = tuple(
            item for item in records
            if isinstance(item, Mapping)
            and str(item.get("record_id") or item.get("code") or "").strip() not in used_ids
            and _related_material(activity, str(item.get("name") or ""), self.material_registry)
        )
        related = self._convert_items(related_items, anchor, LinkStrategy.RELATED)
        matched = (*exact, *synonym, *related)
        attempts = [
            LinkAttempt(
                LinkStrategy.EXACT,
                LinkOutcome.NO_MATCH if not exact else LinkOutcome.MATCHED if len(exact) == 1 else LinkOutcome.CANDIDATE_SET,
                tuple(record.source_id for record in exact),
                "catalogue name or code matched exactly" if exact else "no usable exact catalogue match",
            ),
            LinkAttempt(
                LinkStrategy.SYNONYM,
                LinkOutcome.NO_MATCH if not synonym else LinkOutcome.MATCHED if len(synonym) == 1 else LinkOutcome.CANDIDATE_SET,
                tuple(record.source_id for record in synonym),
                "registered aliases recalled pending exact-record qualification" if synonym else "no registered synonym match",
            ),
            LinkAttempt(
                LinkStrategy.RELATED,
                LinkOutcome.NO_MATCH if not related else LinkOutcome.MATCHED if len(related) == 1 else LinkOutcome.CANDIDATE_SET,
                tuple(record.source_id for record in related),
                "bounded catalogue material-family recall pending higher-priority qualification" if related else "no related catalogue candidates",
            ),
        ]
        observations = tuple(
            RecallObservation(
                source_id=record.source_id,
                material_name=record.material_name,
                retrieval_strategy=LinkStrategy.RELATED,
                retrieval_basis=("product/material term overlap",),
                identity_compatibility="unknown",
                factor_kind=record.factor_kind,
                eligible_for_candidate_pool=True,
            )
            for record in matched
            if record.metadata.get("match_strategy") == LinkStrategy.RELATED.value
        )
        return RetrievalResult(matched, anchor, tuple(attempts), observations)

    def _fetch(self) -> Mapping[str, Any]:
        if self.fetch_json is not None:
            return self.fetch_json(self.endpoint)
        with urlopen(self.endpoint, timeout=self.timeout_seconds) as response:  # nosec B310 - configured local API
            value = json.loads(response.read().decode("utf-8"))
        if not isinstance(value, Mapping):
            raise ValueError("factor catalog response must be a JSON object")
        return value

    @staticmethod
    def _exact_match(item: Mapping[str, Any], query: str) -> bool:
        observed = {_norm(str(item.get("name") or "")), _norm(str(item.get("code") or ""))}
        return bool(query and query in observed)

    @staticmethod
    def _synonym_match(item: Mapping[str, Any], query: str, request_aliases: set[str]) -> bool:
        item_aliases = item.get("aliases") if isinstance(item.get("aliases"), list) else []
        aliases = {_norm(str(alias)) for alias in item_aliases if _norm(str(alias))}
        name = _norm(str(item.get("name") or ""))
        return bool((name and name in request_aliases) or (query and query in aliases) or request_aliases & aliases)

    @classmethod
    def _convert_items(
        cls, items: Sequence[Mapping[str, Any]], anchor: DatabaseVersionAnchor, strategy: LinkStrategy
    ) -> tuple[SourceRecord, ...]:
        converted = (cls._to_source_record(item, anchor) for item in items)
        return tuple(_with_match_strategy(record, strategy) for record in converted if record is not None)

    @staticmethod
    def _to_source_record(
        item: Mapping[str, Any], anchor: DatabaseVersionAnchor
    ) -> SourceRecord | None:
        try:
            value = float(item.get("primary_value"))
        except (TypeError, ValueError):
            return None
        unit = str(item.get("primary_unit") or "").strip()
        if not unit:
            return None
        source_id = str(item.get("record_id") or item.get("code") or "").strip()
        material_name = str(item.get("name") or "").strip()
        if not source_id or not material_name:
            return None
        year_value = item.get("year")
        try:
            year = int(year_value) if year_value not in (None, "") else None
        except (TypeError, ValueError):
            year = None
        raw_kind = str(item.get("factor_kind") or item.get("category") or "other").strip().lower()
        aliases = item.get("aliases")
        catalog_locator = f"{anchor.locator}#{source_id}"
        source_document_locator = str(
            item.get("source_document_locator")
            or item.get("document_url")
            or item.get("source_url")
            or ""
        ).strip() or None
        source_document_sha256 = str(item.get("source_document_sha256") or "").strip().lower() or None
        page = str(item.get("page") or "").strip() or None
        table = str(item.get("table") or "").strip() or None
        row = str(item.get("row") or "").strip() or None
        metadata = {
            "catalog_version": anchor.catalog_version,
            "database_sha256": anchor.database_sha256 or "",
            "record_category": str(item.get("category") or ""),
            "document_status": str(item.get("document_status") or ""),
            "source_priority": str(item.get("source_priority") or ""),
            "aliases": json.dumps(aliases, ensure_ascii=False) if isinstance(aliases, list) else "",
            "catalog_locator": catalog_locator,
            "source_document_locator": source_document_locator or "",
            "source_document_sha256": source_document_sha256 or "",
            "source_document_page": page or "",
            "source_document_table": table or "",
            "source_document_row": row or "",
        }
        kind_aliases = {
            "lifecycle": FactorKind.LIFECYCLE_FACTOR,
            "lifecycle_factor": FactorKind.LIFECYCLE_FACTOR,
            "epd": FactorKind.EPD_INDICATOR,
            "epd_indicator": FactorKind.EPD_INDICATOR,
            "emission_limit": FactorKind.EMISSION_LIMIT,
            "emission-limit": FactorKind.EMISSION_LIMIT,
            "derived_proxy": FactorKind.DERIVED_PROXY_FACTOR,
        }
        factor_kind = kind_aliases.get(raw_kind, FactorKind.OTHER)
        raw_source_type = str(item.get("source_type") or "").strip().lower()
        source_type = {
            "epd": FactorSourceType.EPD,
            "literature": FactorSourceType.LITERATURE,
            "supplier": FactorSourceType.SUPPLIER,
            "external_database": FactorSourceType.EXTERNAL_DATABASE,
        }.get(raw_source_type, FactorSourceType.EPD if factor_kind == FactorKind.EPD_INDICATOR else FactorSourceType.LOCAL_DATABASE)
        boundary_modules = item.get("boundary_modules")
        if isinstance(boundary_modules, str):
            boundary_modules = tuple(part.strip() for part in boundary_modules.split(",") if part.strip())
        elif isinstance(boundary_modules, list):
            boundary_modules = tuple(str(part) for part in boundary_modules)
        else:
            boundary_modules = ()
        return SourceRecord(
            source_id=source_id,
            source_type=source_type,
            provider=str(item.get("source_name") or item.get("source") or anchor.catalog_name),
            locator=source_document_locator or catalog_locator,
            material_name=material_name,
            factor_value=value,
            factor_unit=unit,
            geography=str(item.get("geography") or item.get("location") or "").strip() or None,
            year=year,
            product_form=str(item.get("product_form") or "").strip() or None,
            composition=str(item.get("composition") or "").strip() or None,
            production_process=str(item.get("production_process") or item.get("process") or "").strip() or None,
            boundary=str(item.get("boundary") or "").strip() or None,
            citation=str(item.get("source_citation") or item.get("source") or ""),
            excerpt=str(item.get("notes") or ""),
            metadata=metadata,
            factor_kind=factor_kind,
            indicator=str(item.get("indicator") or "").strip() or None,
            declared_product=str(item.get("declared_product") or "").strip() or None,
            boundary_modules=boundary_modules,
            catalog_locator=catalog_locator,
            source_document_sha256=source_document_sha256,
            page=page,
            table=table,
            row=row,
        )


class NullProxyRepository:
    async def search(self, activity: NormalizedActivity, material_class: MaterialClass) -> Sequence[SourceRecord]:
        return ()


@dataclass(slots=True)
class InMemoryReferenceFlowRepository:
    records: list[ReferenceFlowRecord]

    async def search(self, activity: NormalizedActivity) -> Sequence[ReferenceFlowRecord]:
        target = _norm(activity.canonical_name)
        unit = _norm(activity.original_quantity_unit)
        return tuple(
            record for record in self.records
            if _norm(record.material_name) == target and _norm(record.reference_unit) == unit
        )


@dataclass(slots=True)
class InMemoryProcessParameterRepository:
    evidence: list[ParameterEvidence]

    async def search(
        self, activity: NormalizedActivity, reference: SourceRecord
    ) -> Sequence[ParameterEvidence]:
        target = _norm(activity.canonical_name)
        target_process = _norm(activity.production_process)
        return tuple(
            item for item in self.evidence
            if item.metadata.get("reference_source_id") == reference.source_id
            and _norm(item.metadata.get("target_material") or item.metadata.get("target_material_id")) == target
            and (
                not target_process
                or _norm(item.metadata.get("target_process") or item.metadata.get("target_process_id"))
                == target_process
            )
        )


@dataclass(slots=True)
class InMemoryGradeSeriesRepository:
    records: list[SourceRecord]

    async def search(
        self, activity: NormalizedActivity, reference: SourceRecord
    ) -> Sequence[SourceRecord]:
        series_id = _norm(reference.metadata.get("series_id") or reference.metadata.get("series"))
        if not series_id:
            return ()
        return tuple(
            record for record in self.records
            if record.source_id != reference.source_id
            and _norm(record.metadata.get("series_id") or record.metadata.get("series")) == series_id
        )


class NullReferenceFlowRepository:
    async def search(self, activity: NormalizedActivity) -> Sequence[ReferenceFlowRecord]:
        return ()


class NullProcessParameterRepository:
    async def search(
        self, activity: NormalizedActivity, reference: SourceRecord
    ) -> Sequence[ParameterEvidence]:
        return ()


class NullGradeSeriesRepository:
    async def search(
        self, activity: NormalizedActivity, reference: SourceRecord
    ) -> Sequence[SourceRecord]:
        return ()


class DeterministicMaterialUnderstanding:
    """Offline fallback; replace with an LLM adapter for richer semantics."""

    async def interpret(self, request: ResolutionRequest) -> MaterialInterpretation:
        return MaterialInterpretation(
            canonical_name=_norm(request.material_name),
            aliases=(),
            product_form=request.product_form,
            composition=request.composition,
            production_process=request.production_process,
        )

    async def classify(self, activity: NormalizedActivity) -> MaterialClass:
        # Classification is deliberately only called by the proxy branch.
        name = activity.canonical_name
        composition = _norm(activity.composition)
        process = _norm(activity.production_process)
        if any(token in composition or token in name for token in ("steel", "metal", "aluminium", "aluminum", "copper", "钢", "金属", "铝", "铜")):
            family = "metals"
            category = MaterialCategory.METAL
        elif any(token in composition or token in name for token in ("polymer", "plastic", "resin")):
            family = "polymers"
            category = MaterialCategory.SYNTHETIC_CHEMICAL
        elif any(token in process or token in name for token in ("fused", "sintered", "calcined", "电熔", "烧结", "煅烧")):
            family = "manufactured minerals"
            category = MaterialCategory.MANUFACTURED_MINERAL
        elif any(token in process or token in name for token in ("mining", "quarried", "ore", "矿", "开采")):
            family = "natural minerals"
            category = MaterialCategory.NATURAL_MINERAL
        elif any(token in composition or token in name for token in ("glass", "ceramic", "玻璃", "陶瓷", "硅酸铝")):
            family = "inorganics"
            category = MaterialCategory.MANUFACTURED_MINERAL
        else:
            family = composition or "unknown"
            category = MaterialCategory.UNKNOWN
        return MaterialClass(
            name=name, family=family, category=category,
            rationale="offline deterministic fallback", confidence=0.5,
        )

    async def assess_candidate(
        self,
        activity: NormalizedActivity,
        source: SourceRecord,
        origin: str,
        material_class: MaterialClass | None = None,
    ) -> SemanticAssessment:
        return SemanticAssessment()


class InMemoryResolutionStore:
    def __init__(self) -> None:
        self.recommendations: dict[str, Recommendation] = {}
        self.traces: dict[str, ResolutionTrace] = {}
        self.approvals: dict[tuple[str, str], ApprovalRecord] = {}
        self.locked: dict[str, LockedResolution] = {}
        self._run_lock = asyncio.Lock()

    async def has_resolution_run(self, request_id: str) -> bool:
        return request_id in self.recommendations or request_id in self.traces

    async def save_resolution_run(
        self, recommendation: Recommendation, trace: ResolutionTrace
    ) -> None:
        if recommendation.request_id != trace.request_id:
            raise ValueError("recommendation and trace must belong to the same request")
        async with self._run_lock:
            if await self.has_resolution_run(recommendation.request_id):
                raise ValueError(f"duplicate request_id: {recommendation.request_id}")
            self.recommendations[recommendation.request_id] = recommendation
            self.traces[trace.request_id] = trace

    async def get_recommendation(self, request_id: str) -> Recommendation | None:
        return self.recommendations.get(request_id)

    async def save_trace(self, trace: ResolutionTrace) -> None:
        # Trace is intentionally mutable and replaceable; it is not a snapshot.
        if trace.request_id not in self.recommendations:
            raise ValueError("trace updates require an existing atomic resolution run")
        self.traces[trace.request_id] = trace

    async def get_trace(self, request_id: str) -> ResolutionTrace | None:
        return self.traces.get(request_id)

    async def save_approval(self, approval: ApprovalRecord) -> None:
        if approval.request_id in self.locked:
            raise ValueError("locked resolution cannot be changed")
        self.approvals[(approval.request_id, approval.candidate_id)] = approval

    async def get_approval(self, request_id: str, candidate_id: str) -> ApprovalRecord | None:
        return self.approvals.get((request_id, candidate_id))

    async def save_locked(self, locked: LockedResolution) -> None:
        existing = self.locked.get(locked.request_id)
        if existing is not None and existing != locked:
            raise ValueError("resolution is already locked and immutable")
        self.locked.setdefault(locked.request_id, locked)

    async def get_locked(self, request_id: str) -> LockedResolution | None:
        return self.locked.get(request_id)
