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
    return latin | grams


@dataclass(slots=True)
class InMemoryFactorRepository:
    records: list[SourceRecord]
    source_types: tuple[FactorSourceType, ...] | None = None
    anchor: DatabaseVersionAnchor | None = None

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
        attempts: list[LinkAttempt] = []
        if exact:
            attempts.append(LinkAttempt(
                LinkStrategy.EXACT,
                LinkOutcome.MATCHED if len(exact) == 1 else LinkOutcome.CANDIDATE_SET,
                tuple(record.source_id for record in exact),
                "canonical material name matched exactly",
            ))
            attempts.append(LinkAttempt(
                LinkStrategy.SYNONYM, LinkOutcome.SKIPPED, reason="exact link already produced candidates"
            ))
            results = exact
        else:
            attempts.append(LinkAttempt(
                LinkStrategy.EXACT, LinkOutcome.NO_MATCH, reason="no exact canonical-name match"
            ))
            synonym = tuple(
                _with_match_strategy(record, LinkStrategy.SYNONYM)
                for record in eligible
                if (
                    _norm(record.material_name) in aliases
                    or query in _record_aliases(record)
                    or bool(aliases & _record_aliases(record))
                )
            )
            attempts.append(LinkAttempt(
                LinkStrategy.SYNONYM,
                LinkOutcome.NO_MATCH if not synonym else LinkOutcome.MATCHED if len(synonym) == 1 else LinkOutcome.CANDIDATE_SET,
                tuple(record.source_id for record in synonym),
                "matched only declared request or record aliases" if synonym else "no registered synonym match",
            ))
            if synonym:
                results = synonym
            else:
                query_terms = _material_terms(activity.canonical_name)
                related = tuple(
                    _with_match_strategy(record, LinkStrategy.RELATED)
                    for record in eligible
                    if query_terms & _material_terms(record.material_name)
                )
                attempts.append(LinkAttempt(
                    LinkStrategy.RELATED,
                    LinkOutcome.NO_MATCH if not related else LinkOutcome.MATCHED if len(related) == 1 else LinkOutcome.CANDIDATE_SET,
                    tuple(record.source_id for record in related),
                    "bounded material-family term recall for gap analysis" if related else "no related local candidates",
                ))
                results = related
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
        attempts: list[LinkAttempt] = []
        if exact_items:
            matched = self._convert_items(exact_items, anchor, LinkStrategy.EXACT)
            attempts.append(LinkAttempt(
                LinkStrategy.EXACT,
                LinkOutcome.NO_MATCH if not matched else LinkOutcome.MATCHED if len(matched) == 1 else LinkOutcome.CANDIDATE_SET,
                tuple(record.source_id for record in matched),
                "catalogue name or code matched the canonical query exactly" if matched else "exact catalogue rows lacked usable factor data",
            ))
            attempts.append(LinkAttempt(LinkStrategy.SYNONYM, LinkOutcome.SKIPPED, reason="exact link already produced candidates"))
        else:
            attempts.append(LinkAttempt(LinkStrategy.EXACT, LinkOutcome.NO_MATCH, reason="no exact catalogue name or code match"))
            synonym_items = tuple(
                item for item in records
                if isinstance(item, Mapping) and self._synonym_match(item, query, aliases)
            )
            matched = self._convert_items(synonym_items, anchor, LinkStrategy.SYNONYM)
            attempts.append(LinkAttempt(
                LinkStrategy.SYNONYM,
                LinkOutcome.NO_MATCH if not matched else LinkOutcome.MATCHED if len(matched) == 1 else LinkOutcome.CANDIDATE_SET,
                tuple(record.source_id for record in matched),
                "matched only aliases declared by the request or catalogue" if matched else "no registered synonym match",
            ))
            if not matched:
                query_terms = _material_terms(activity.canonical_name)
                related_items = tuple(
                    item for item in records
                    if isinstance(item, Mapping)
                    and query_terms & _material_terms(str(item.get("name") or ""))
                )
                matched = self._convert_items(related_items, anchor, LinkStrategy.RELATED)
                attempts.append(LinkAttempt(
                    LinkStrategy.RELATED,
                    LinkOutcome.NO_MATCH if not matched else LinkOutcome.MATCHED if len(matched) == 1 else LinkOutcome.CANDIDATE_SET,
                    tuple(record.source_id for record in matched),
                    "bounded catalogue material-family term recall" if matched else "no related catalogue candidates",
                ))
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
        metadata = {
            "catalog_version": anchor.catalog_version,
            "database_sha256": anchor.database_sha256 or "",
            "record_category": str(item.get("category") or ""),
            "document_status": str(item.get("document_status") or ""),
            "source_priority": str(item.get("source_priority") or ""),
            "aliases": json.dumps(aliases, ensure_ascii=False) if isinstance(aliases, list) else "",
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
            locator=f"{anchor.locator}#{source_id}",
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
        return tuple(
            item for item in self.evidence
            if item.metadata.get("reference_source_id", reference.source_id) == reference.source_id
            and _norm(item.metadata.get("target_material", target)) == target
        )


@dataclass(slots=True)
class InMemoryGradeSeriesRepository:
    records: list[SourceRecord]

    async def search(
        self, activity: NormalizedActivity, reference: SourceRecord
    ) -> Sequence[SourceRecord]:
        family = _norm(reference.metadata.get("series", reference.metadata.get("family", "")))
        return tuple(
            record for record in self.records
            if record.source_id != reference.source_id
            and (
                (family and _norm(record.metadata.get("series", record.metadata.get("family", ""))) == family)
                or _material_terms(record.material_name) & _material_terms(reference.material_name)
            )
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

    async def save_recommendation(self, recommendation: Recommendation) -> None:
        self.recommendations.setdefault(recommendation.request_id, recommendation)

    async def get_recommendation(self, request_id: str) -> Recommendation | None:
        return self.recommendations.get(request_id)

    async def save_trace(self, trace: ResolutionTrace) -> None:
        # Trace is intentionally mutable and replaceable; it is not a snapshot.
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
